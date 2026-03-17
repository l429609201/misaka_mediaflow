// internal/handler/proxy.go
// 透传处理器 — 将请求直接代理到 Emby/Jellyfin（基于 httputil.ReverseProxy）

package handler

import (
	"bytes"
	"compress/gzip"
	"io"
	"log"
	"net/http"
	"net/http/httputil"
	"net/url"
	"strconv"
	"strings"

	"github.com/gin-gonic/gin"

	"github.com/mediaflow/go-proxy/internal/config"
)

// seekThrottleJS 注入到 plugin.js 末尾的 seek 防抖脚本。
// 拦截 HTMLMediaElement.prototype.currentTime setter，快速拖拽时只在用户松手后
// 执行一次真正的 seek，防止瞬间并发大量 Range 请求导致 115 CDN 返回 403。
const seekThrottleJS = `
;(function(){
  /* ===== Misaka MediaFlow Seek Throttle ===== */
  var DEBOUNCE_MS = 500;       /* 松手后等待 ms 再 seek */
  var MIN_INTERVAL_MS = 2000;  /* 两次真实 seek 最小间隔 */
  var proto = HTMLMediaElement.prototype;
  var desc = Object.getOwnPropertyDescriptor(proto, 'currentTime');
  if (!desc || !desc.set) return;
  var origSet = desc.set;
  var origGet = desc.get;
  var _timer = null;
  var _lastSeekTime = 0;
  var _pendingTime = null;
  var _isSeeking = false;

  function doSeek(elem, t) {
    var now = Date.now();
    var elapsed = now - _lastSeekTime;
    if (elapsed < MIN_INTERVAL_MS) {
      /* 距上次 seek 太近，延迟执行 */
      clearTimeout(_timer);
      _timer = setTimeout(function(){ doSeek(elem, t); }, MIN_INTERVAL_MS - elapsed + 50);
      return;
    }
    _lastSeekTime = now;
    _pendingTime = null;
    _isSeeking = false;
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
      /* 拖拽中返回目标时间，让进度条 UI 跟手 */
      if (_pendingTime !== null) return _pendingTime;
      return origGet.call(this);
    },
    set: function(v) {
      /* 在已缓冲范围内，直接 seek（不产生网络请求） */
      if (isInBuffered(this, v)) {
        clearTimeout(_timer);
        _pendingTime = null;
        _isSeeking = false;
        origSet.call(this, v);
        return;
      }
      /* 超出缓冲区：防抖 */
      _pendingTime = v;
      _isSeeking = true;
      var self = this;
      clearTimeout(_timer);
      _timer = setTimeout(function(){ doSeek(self, v); }, DEBOUNCE_MS);
    },
    configurable: true
  });
  console.log('[Misaka] seek throttle active: debounce=' + DEBOUNCE_MS + 'ms, minInterval=' + MIN_INTERVAL_MS + 'ms');
})();
`

// ProxyHandler 透传处理器
type ProxyHandler struct {
	cfg          *config.Config
	reverseProxy *httputil.ReverseProxy
	targetURL    *url.URL
}

// NewProxyHandler 创建透传处理器
func NewProxyHandler(cfg *config.Config) *ProxyHandler {
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

		// ⭐ 对 htmlvideoplayer/plugin.js 请求，去掉 Accept-Encoding
		// 让 Go Transport 自动用 gzip 并自动解压，确保 ModifyResponse 收到纯文本
		// 否则浏览器发 Accept-Encoding: br,gzip → Emby 返回 Brotli → 我们无法解压替换
		if strings.Contains(req.URL.Path, "htmlvideoplayer/plugin.js") {
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
	// 解决 Web 浏览器 302 重定向到 115 CDN 时的 CORS 跨域问题
	// 参考: https://github.com/bpking1/embyExternalUrl/issues/236
	rp.ModifyResponse = patchPluginJS

	return &ProxyHandler{
		cfg:          cfg,
		reverseProxy: rp,
		targetURL:    target,
	}
}

// patchPluginJS 拦截 Emby htmlvideoplayer/plugin.js 响应，
// 用正则去除 .crossOrigin 赋值（兼容压缩/非压缩变量名）。
// 115 CDN 不返回 Access-Control-Allow-Origin 头，浏览器带 crossorigin="anonymous"
// 的 <video> 元素在 302 重定向后会被 CORS 策略阻止。
func patchPluginJS(resp *http.Response) error {
	// 只处理 htmlvideoplayer/plugin.js
	path := resp.Request.URL.Path
	if !strings.Contains(path, "htmlvideoplayer/plugin.js") {
		return nil
	}

	// 只处理成功响应
	if resp.StatusCode != http.StatusOK {
		return nil
	}

	encoding := resp.Header.Get("Content-Encoding")
	log.Printf("plugin.js 响应: status=%d, Content-Encoding=%q, Content-Length=%d",
		resp.StatusCode, encoding, resp.ContentLength)

	// 读取响应体
	// Director 已去掉 Accept-Encoding，Transport 会自动解压 gzip
	// 但以防万一也处理手动 gzip 的情况
	isGzip := strings.Contains(encoding, "gzip")
	var bodyReader io.Reader = resp.Body
	if isGzip {
		gr, err := gzip.NewReader(resp.Body)
		if err != nil {
			log.Printf("plugin.js gzip 解压失败: %v", err)
			return nil
		}
		defer gr.Close()
		bodyReader = gr
	}

	body, err := io.ReadAll(bodyReader)
	resp.Body.Close()
	if err != nil {
		log.Printf("plugin.js 读取失败: %v", err)
		return nil
	}

	log.Printf("plugin.js 原始内容: %d bytes, 包含 .crossOrigin=%v",
		len(body), strings.Contains(string(body), ".crossOrigin"))

	// ⭐ 核心：把所有 .crossOrigin 替换成 .crossOriginDisabled
	// 同时覆盖旧版 &&(elem.crossOrigin=xxx) 和新版 getCrossOriginValue() 模式
	original := string(body)
	patchCount := strings.Count(original, ".crossOrigin")
	patched := strings.ReplaceAll(original, ".crossOrigin", ".crossOriginDisabled")

	if original != patched {
		log.Printf("✅ plugin.js 已 patch: 替换 %d 处 .crossOrigin → .crossOriginDisabled", patchCount)
	} else {
		snippet := string(body)
		if len(snippet) > 200 {
			snippet = snippet[:200]
		}
		log.Printf("⚠️ plugin.js 未找到 crossOrigin (大小=%d bytes, 前200字节=%q)", len(body), snippet)
	}

	// ⭐ 追加 seek 防抖脚本，防止拖拽进度条产生大量 Range 请求导致 115 CDN 403
	patched += seekThrottleJS
	log.Printf("✅ plugin.js 已注入 seek 防抖脚本")

	// 写回响应体（不压缩，浏览器可以接受纯文本）
	newBody := []byte(patched)
	resp.Body = io.NopCloser(bytes.NewReader(newBody))
	resp.ContentLength = int64(len(newBody))
	resp.Header.Set("Content-Length", strconv.Itoa(len(newBody)))
	resp.Header.Del("Content-Encoding") // 确保无压缩头

	// 禁止浏览器缓存
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

