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

// crossOriginValueRe 精确匹配 Emby basehtmlplayer.js 中 getCrossOriginValue 函数的返回值。
// 原始代码: getCrossOriginValue=function(mediaSource,playMethod){return mediaSource.IsRemote&&"DirectPlay"===playMethod?null:"anonymous"}
// 压缩后:   getCrossOriginValue=function(n,t){return n.IsRemote&&"DirectPlay"===t?null:"anonymous"}
// 匹配整个三元表达式，替换为 null — 参考 embyExternalUrl modifyBaseHtmlPlayer
var crossOriginValueRe = regexp.MustCompile(`\w+\.IsRemote\s*&&\s*"DirectPlay"\s*===\s*\w+\s*\?\s*null\s*:\s*"anonymous"`)

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
		// 新版 Emby basehtmlplayer.js 的 getCrossOriginValue 函数：
		// 原始:   getCrossOriginValue=function(mediaSource,playMethod){return mediaSource.IsRemote&&"DirectPlay"===playMethod?null:"anonymous"}
		// 压缩后: getCrossOriginValue=function(n,t){return n.IsRemote&&"DirectPlay"===t?null:"anonymous"}
		// → 用精确正则匹配三元表达式，替换为 null（参考 embyExternalUrl modifyBaseHtmlPlayer）
		hasCrossOriginValue := strings.Contains(original, "getCrossOriginValue")
		matchCount := len(crossOriginValueRe.FindAllString(patched, -1))
		patched = crossOriginValueRe.ReplaceAllString(patched, `null`)
		if matchCount > 0 {
			log.Printf("✅ %s crossOriginValue: 精确匹配 %d 处三元表达式 → null", fileName, matchCount)
		} else if hasCrossOriginValue {
			// 正则没命中但函数存在，说明 Emby 代码格式变了，用宽松匹配兜底
			log.Printf("⚠️ %s crossOriginValue: 精确正则未命中，尝试宽松替换", fileName)
			patched = strings.ReplaceAll(patched, `"anonymous"`, `null`)
			patched = strings.ReplaceAll(patched, `'anonymous'`, `null`)
		}
		log.Printf("%s 原始内容: %d bytes, getCrossOriginValue=%v",
			fileName, len(body), hasCrossOriginValue)
	}
	// 通用：把所有 .crossOrigin 属性名替换掉（安全网，两个文件都可能有直接赋值）
	patchCount := strings.Count(patched, ".crossOrigin")
	patched = strings.ReplaceAll(patched, ".crossOrigin", ".crossOriginDisabled")

	if original != patched {
		log.Printf("✅ %s 已 patch: 替换 %d 处 .crossOrigin → .crossOriginDisabled", fileName, patchCount)
	} else {
		snippet := original
		if len(snippet) > 200 {
			snippet = snippet[:200]
		}
		log.Printf("⚠️ %s 未找到 crossOrigin (大小=%d bytes, 前200字节=%q)", fileName, len(body), snippet)
	}

	// ==================== seek 防抖脚本（只在 plugin.js 中注入） ====================
	// basehtmlplayer.js 不需要注入，只需要一份
	if !isBasePlayer {
		intervalSec := h.pyClient.GetAPIInterval()
		intervalMs := int(intervalSec * 1000)
		seekJS := fmt.Sprintf(seekThrottleTpl, intervalMs)
		patched += seekJS
		log.Printf("✅ %s 已注入 seek 防抖脚本 (minInterval=%dms, 来自 api_interval=%.1fs)", fileName, intervalMs, intervalSec)
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

