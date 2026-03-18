// internal/handler/proxy.go
// 透传处理器 — 将请求直接代理到 Emby/Jellyfin（基于 httputil.ReverseProxy）

package handler

import (
	"bytes"
	"compress/gzip"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/http/httputil"
	"net/url"
	"regexp"
	"strconv"
	"strings"

	"github.com/gin-gonic/gin"

	"github.com/mediaflow/go-proxy/internal/config"
	"github.com/mediaflow/go-proxy/internal/service"
)

// ── basehtmlplayer.js patch ──
// 参考 embyExternalUrl emby.js modifyBaseHtmlPlayer 函数：
//   body.replace(/mediaSource\.IsRemote\s*&&\s*"DirectPlay"\s*===\s*playMethod\s*\?\s*null\s*:\s*"anonymous"/g, 'null')
//
// 原始代码: getCrossOriginValue=function(mediaSource,playMethod){return mediaSource.IsRemote&&"DirectPlay"===playMethod?null:"anonymous"}
// 压缩后:   getCrossOriginValue=function(n,t){return n.IsRemote&&"DirectPlay"===t?null:"anonymous"}
// 匹配整个三元表达式，替换为 null → 使 getCrossOriginValue() 始终返回 null
var crossOriginValueRe = regexp.MustCompile(`\w+\.IsRemote\s*&&\s*"DirectPlay"\s*===\s*\w+\s*\?\s*null\s*:\s*"anonymous"`)

// ── plugin.js patch ──
// 参考 embyExternalUrl issue #236 的 sed 命令：
//   sed -i 's/&&(elem\.crossOrigin=initialSubtitleStream)//g' plugin.js
//
// 原始代码: &&(elem.crossOrigin=initialSubtitleStream)
// 压缩后:   &&(t.crossOrigin=n) 或其他变量名
// 移除这段代码 → <video> 元素不再被设置 crossOrigin 属性
var pluginCrossOriginRe = regexp.MustCompile(`&&\(\w+\.crossOrigin=\w+\)`)

// seekThrottleJS 注入到 plugin.js 末尾的 seek 防抖脚本模板。
// %d 会被替换为实际的 MIN_INTERVAL_MS（从后端 api_interval 配置读取）。
const seekThrottleTpl = `
;(function(){
  var DEBOUNCE_MS = 500;
  var MIN_INTERVAL_MS = %d;
  var proto = HTMLMediaElement.prototype;
  var desc = Object.getOwnPropertyDescriptor(proto, 'currentTime');
  if (!desc || !desc.set) return;
  var origSet = desc.set;
  var origGet = desc.get;
  var _timer = null;
  var _lastSeekTime = 0;
  var _pendingTime = null;

  function doSeek(elem, t) {
    var now = Date.now();
    var elapsed = now - _lastSeekTime;
    if (elapsed < MIN_INTERVAL_MS) {
      clearTimeout(_timer);
      _timer = setTimeout(function(){ doSeek(elem, t); }, MIN_INTERVAL_MS - elapsed + 50);
      return;
    }
    _lastSeekTime = now;
    _pendingTime = null;
    origSet.call(elem, t);
  }

  function isInBuffered(elem, t) {
    var buf = elem.buffered;
    for (var i = 0; i < buf.length; i++) {
      if (t >= buf.start(i) && t <= buf.end(i)) return true;
    }
    return false;
  }

  Object.defineProperty(proto, 'currentTime', {
    get: function() {
      if (_pendingTime !== null) return _pendingTime;
      return origGet.call(this);
    },
    set: function(v) {
      if (isInBuffered(this, v)) {
        clearTimeout(_timer);
        _pendingTime = null;
        origSet.call(this, v);
        return;
      }
      _pendingTime = v;
      var self = this;
      clearTimeout(_timer);
      _timer = setTimeout(function(){ doSeek(self, v); }, DEBOUNCE_MS);
    },
    configurable: true
  });
  console.log('[Misaka] seek throttle: debounce=' + DEBOUNCE_MS + 'ms, minInterval=' + MIN_INTERVAL_MS + 'ms');
})();
`

// directUrlTpl 注入到 plugin.js 末尾的"直链直出"脚本。
// 非侵入式：不 hook video.src setter（避免破坏 Emby 的同步播放流程），
// 而是用 MutationObserver 观察 <video>/<audio> 的 src 变化。
//
// 工作流程（不打断 Emby 正常播放）：
//   1. Emby 正常设置 video.src → 302 → CDN → 播放正常启动
//   2. MutationObserver 检测到 src 变化 → 后台 fetch directurl API 获取 CDN 直链
//   3. 直链到手后：保存播放位置 → 替换 src 为 CDN URL → 恢复位置 → 继续播放
//   4. 替换后：后续 Range 请求全部直连 CDN（复用 Keep-Alive），不再走 302
//   5. 如果 fetch 失败：什么都不做，原来的 302 播放继续
const directUrlTpl = `
;(function(){
  var TAG = '[Misaka]';
  // 匹配 /emby/videos/{id}/stream 或 /Videos/{id}/stream（含可选后缀）
  var streamRe = /\/(?:emby\/)?(?:videos|Videos|audio|Audio)\/(\d+)\/(?:stream|original)(?:\.\w+)?/;

  function toResolveUrl(src) {
    try {
      var u = new URL(src, location.origin);
      u.pathname = u.pathname.replace(/\/(stream|original)(\.\w+)?$/, '/directurl');
      return u.toString();
    } catch(e) { return ''; }
  }

  function tryReplace(elem) {
    var src = elem.getAttribute('src') || elem.src || '';
    if (!src || !streamRe.test(src)) return;
    if (elem._mskId) return;  // 已处理过

    var m = streamRe.exec(src);
    var itemId = m ? m[1] : '?';
    elem._mskId = itemId;

    var resolveUrl = toResolveUrl(src);
    if (!resolveUrl) return;

    console.log(TAG + ' 直链解析: itemId=' + itemId);

    fetch(resolveUrl)
      .then(function(r) { return r.json(); })
      .then(function(data) {
        if (!data || !data.url) {
          console.warn(TAG + ' 直链为空, 保持302: itemId=' + itemId);
          return;
        }
        // 保存播放状态
        var pos = elem.currentTime || 0;
        var wasPlaying = !elem.paused;
        console.log(TAG + ' 直链直出 ✓ itemId=' + itemId + ' pos=' + pos.toFixed(1) + 's');

        // 标记跳过 observer 对本次 src 变更的监听
        elem._mskSwap = true;
        elem.src = data.url;

        // 恢复播放位置
        elem.addEventListener('loadedmetadata', function onMeta() {
          elem.removeEventListener('loadedmetadata', onMeta);
          if (pos > 0.5) elem.currentTime = pos;
          if (wasPlaying) elem.play().catch(function(){});
        });
        // 兜底：如果 loadedmetadata 不触发（已有 metadata），直接恢复
        if (elem.readyState >= 1) {
          if (pos > 0.5) elem.currentTime = pos;
          if (wasPlaying) elem.play().catch(function(){});
        }
      })
      .catch(function(err) {
        console.warn(TAG + ' 直链异常, 保持302: ' + err);
      });
  }

  // 观察 DOM：video/audio 元素新增或 src 属性变更
  var observer = new MutationObserver(function(mutations) {
    for (var i = 0; i < mutations.length; i++) {
      var m = mutations[i];
      if (m.type === 'childList') {
        for (var j = 0; j < m.addedNodes.length; j++) {
          var n = m.addedNodes[j];
          if (n.nodeType !== 1) continue;
          if (n.tagName === 'VIDEO' || n.tagName === 'AUDIO') tryReplace(n);
          var subs = n.querySelectorAll ? n.querySelectorAll('video,audio') : [];
          for (var k = 0; k < subs.length; k++) tryReplace(subs[k]);
        }
      }
      if (m.type === 'attributes' && m.attributeName === 'src') {
        var el = m.target;
        if (el._mskSwap) { el._mskSwap = false; continue; }  // 跳过自己触发的
        el._mskId = null;  // 新 src，重新处理
        if (el.tagName === 'VIDEO' || el.tagName === 'AUDIO') tryReplace(el);
      }
    }
  });

  observer.observe(document.documentElement, {
    childList: true, subtree: true,
    attributes: true, attributeFilter: ['src']
  });

  console.log(TAG + ' 直链直出: MutationObserver 已启用');
})();
`

// ProxyHandler 透传处理器
type ProxyHandler struct {
	cfg          *config.Config
	reverseProxy *httputil.ReverseProxy
	targetURL    *url.URL
	pyClient     *service.PythonClient
}

// NewProxyHandler 创建透传处理器
func NewProxyHandler(cfg *config.Config, pyClient *service.PythonClient) *ProxyHandler {
	target, err := url.Parse(cfg.MediaServer.Host)
	if err != nil {
		log.Fatalf("MediaServer.Host 解析失败: %v", err)
	}

	rp := httputil.NewSingleHostReverseProxy(target)

	// 自定义 Director：修正 Host 头，确保 Emby 能正确响应
	originalDirector := rp.Director
	rp.Director = func(req *http.Request) {
		originalDirector(req)
		req.Host = target.Host

		// ⭐ 对 htmlvideoplayer JS 请求，去掉 Accept-Encoding
		// 让 Go Transport 自动用 gzip 并自动解压，确保 ModifyResponse 收到纯文本
		// 否则浏览器发 Accept-Encoding: br,gzip → Emby 返回 Brotli → 我们无法解压替换
		// 需要同时处理 plugin.js（旧版 Emby）和 basehtmlplayer.js（新版 Emby）
		if isHtmlPlayerJS(req.URL.Path) {
			req.Header.Del("Accept-Encoding")
		}
	}

	// 错误处理
	rp.ErrorHandler = func(w http.ResponseWriter, r *http.Request, err error) {
		log.Printf("反代透传失败: %s %s -> %s, err=%v", r.Method, r.URL.Path, target.String(), err)
		w.WriteHeader(http.StatusBadGateway)
		w.Write([]byte(`{"error":"proxy request failed"}`))
	}

	// ⭐ 修改响应：自动去除 Emby htmlvideoplayer 的 crossOrigin 设置
	// + 注入 seek 防抖脚本（防止 115 CDN 403）
	// 参考: https://github.com/bpking1/embyExternalUrl/issues/236

	h := &ProxyHandler{
		cfg:          cfg,
		reverseProxy: rp,
		targetURL:    target,
		pyClient:     pyClient,
	}
	rp.ModifyResponse = h.patchHtmlPlayerJS

	return h
}

// isHtmlPlayerJS 判断是否为 Emby htmlvideoplayer 的 JS 文件
// 需要 patch 的文件：
//   - plugin.js（旧版 Emby，路径含 htmlvideoplayer/plugin.js）
//   - basehtmlplayer.js（新版 Emby，路径含 htmlvideoplayer/basehtmlplayer.js）
func isHtmlPlayerJS(path string) bool {
	return strings.Contains(path, "htmlvideoplayer/plugin.js") ||
		strings.Contains(path, "htmlvideoplayer/basehtmlplayer.js")
}

// patchHtmlPlayerJS 统一拦截 Emby htmlvideoplayer 的 JS 响应，
// 去除 crossOrigin 设置 + 注入 seek 防抖脚本。
//
// 解决两类 CORS 问题（115 CDN 不返回 Access-Control-Allow-Origin）：
//   - 旧版 Emby plugin.js: &&(elem.crossOrigin=xxx) 直接赋值
//   - 新版 Emby basehtmlplayer.js: getCrossOriginValue() 返回 "anonymous"
//
// 参考:
//   - https://github.com/bpking1/embyExternalUrl/issues/236
//   - https://github.com/chen3861229/embyExternalUrl/issues/64
func (h *ProxyHandler) patchHtmlPlayerJS(resp *http.Response) error {
	path := resp.Request.URL.Path
	if !isHtmlPlayerJS(path) {
		return nil
	}

	if resp.StatusCode != http.StatusOK {
		return nil
	}

	// 判断是哪个文件
	isBasePlayer := strings.Contains(path, "basehtmlplayer.js")
	fileName := "plugin.js"
	if isBasePlayer {
		fileName = "basehtmlplayer.js"
	}

	encoding := resp.Header.Get("Content-Encoding")
	log.Printf("%s 响应: status=%d, Content-Encoding=%q, Content-Length=%d",
		fileName, resp.StatusCode, encoding, resp.ContentLength)

	// 读取响应体（处理 gzip）
	isGzip := strings.Contains(encoding, "gzip")
	var bodyReader io.Reader = resp.Body
	if isGzip {
		gr, err := gzip.NewReader(resp.Body)
		if err != nil {
			log.Printf("%s gzip 解压失败: %v", fileName, err)
			return nil
		}
		defer gr.Close()
		bodyReader = gr
	}

	body, err := io.ReadAll(bodyReader)
	resp.Body.Close()
	if err != nil {
		log.Printf("%s 读取失败: %v", fileName, err)
		return nil
	}

	original := string(body)
	patched := original

	// ==================== crossOrigin patch ====================
	if isBasePlayer {
		// ── basehtmlplayer.js: 参考 embyExternalUrl modifyBaseHtmlPlayer ──
		// 精确正则匹配 getCrossOriginValue 中的三元表达式，替换为 null
		// 效果: getCrossOriginValue() 始终返回 null → <video> 不设置 crossorigin 属性
		matchCount := len(crossOriginValueRe.FindAllString(patched, -1))
		patched = crossOriginValueRe.ReplaceAllString(patched, `null`)
		if matchCount > 0 {
			log.Printf("✅ %s: 精确匹配 %d 处 getCrossOriginValue 三元表达式 → null", fileName, matchCount)
		} else {
			// 正则没命中，可能 Emby 代码格式变了，用宽松匹配兜底
			hasCrossOriginValue := strings.Contains(original, "getCrossOriginValue")
			if hasCrossOriginValue {
				log.Printf("⚠️ %s: getCrossOriginValue 函数存在但精确正则未命中，尝试宽松替换 \"anonymous\" → null", fileName)
				patched = strings.ReplaceAll(patched, `"anonymous"`, `null`)
				patched = strings.ReplaceAll(patched, `'anonymous'`, `null`)
			} else {
				log.Printf("⚠️ %s: 未找到 getCrossOriginValue 函数 (大小=%d bytes)", fileName, len(body))
			}
		}
	} else {
		// ── plugin.js: 参考 embyExternalUrl issue #236 ──
		// sed -i 's/&&(elem\.crossOrigin=initialSubtitleStream)//g' plugin.js
		// 精确正则移除 &&(xxx.crossOrigin=yyy) 赋值语句
		// 效果: <video> 元素不再被赋值 crossOrigin 属性
		matchCount := len(pluginCrossOriginRe.FindAllString(patched, -1))
		patched = pluginCrossOriginRe.ReplaceAllString(patched, ``)
		if matchCount > 0 {
			log.Printf("✅ %s: 移除 %d 处 &&(*.crossOrigin=*) 赋值（参考 issue #236）", fileName, matchCount)
		} else {
			// 兜底：如果精确正则未命中，尝试替换属性名
			hasCrossOrigin := strings.Contains(original, ".crossOrigin")
			if hasCrossOrigin {
				crossOriginCount := strings.Count(patched, ".crossOrigin")
				patched = strings.ReplaceAll(patched, ".crossOrigin", ".crossOriginDisabled")
				log.Printf("⚠️ %s: &&(*.crossOrigin=*) 精确正则未命中，兜底替换 %d 处 .crossOrigin → .crossOriginDisabled", fileName, crossOriginCount)
			} else {
				log.Printf("⚠️ %s: 未找到 crossOrigin 相关代码 (大小=%d bytes)", fileName, len(body))
			}
		}
	}

	if original != patched {
		log.Printf("✅ %s crossOrigin patch 完成 (原始=%d bytes, patch后=%d bytes)", fileName, len(original), len(patched))
	}

	// ==================== seek 防抖 + 直链直出脚本（只在 plugin.js 中注入） ====================
	// basehtmlplayer.js 不需要注入，只需要一份
	if !isBasePlayer {
		intervalSec := h.pyClient.GetAPIInterval()
		intervalMs := int(intervalSec * 1000)
		seekJS := fmt.Sprintf(seekThrottleTpl, intervalMs)
		patched += seekJS
		log.Printf("✅ %s 已注入 seek 防抖脚本 (minInterval=%dms, 来自 api_interval=%.1fs)", fileName, intervalMs, intervalSec)

		// ⭐ 直链直出：hook video.src，让浏览器直连 CDN 而非每次走 302
		patched += directUrlTpl
		log.Printf("✅ %s 已注入直链直出脚本 (video.src hook)", fileName)
	}

	// ==================== 写回响应 ====================
	newBody := []byte(patched)
	resp.Body = io.NopCloser(bytes.NewReader(newBody))
	resp.ContentLength = int64(len(newBody))
	resp.Header.Set("Content-Length", strconv.Itoa(len(newBody)))
	resp.Header.Del("Content-Encoding")

	// 禁止浏览器缓存（确保每次都拿到 patch 后的版本）
	resp.Header.Set("Cache-Control", "no-cache, no-store, must-revalidate")
	resp.Header.Set("Pragma", "no-cache")
	resp.Header.Set("Expires", "0")
	resp.Header.Del("ETag")
	resp.Header.Del("Last-Modified")

	return nil
}

// HandleProxy 透传请求到 Emby/Jellyfin
func (h *ProxyHandler) HandleProxy(c *gin.Context) {
	h.reverseProxy.ServeHTTP(c.Writer, c.Request)
}

