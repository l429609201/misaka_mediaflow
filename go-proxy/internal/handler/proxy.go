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
	"strconv"
	"strings"

	"github.com/gin-gonic/gin"

	"github.com/mediaflow/go-proxy/internal/config"
	"github.com/mediaflow/go-proxy/internal/service"
)

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
	// + 注入 seek 防抖脚本（防止 115 CDN 403）
	// 参考: https://github.com/bpking1/embyExternalUrl/issues/236

	h := &ProxyHandler{
		cfg:          cfg,
		reverseProxy: rp,
		targetURL:    target,
		pyClient:     pyClient,
	}
	rp.ModifyResponse = h.patchPluginJS

	return h
}

// patchPluginJS 拦截 Emby htmlvideoplayer/plugin.js 响应，
// 1) 把 .crossOrigin 替换掉（解决 115 CDN CORS 问题）
// 2) 追加 seek 防抖脚本（防止拖拽产生大量 Range 请求导致 403）
// MIN_INTERVAL_MS 通过内部 API 从 Python 端 api_interval 配置读取。
func (h *ProxyHandler) patchPluginJS(resp *http.Response) error {
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
	// 从 Python 内部 API 读取 api_interval 配置
	intervalSec := h.pyClient.GetAPIInterval()
	intervalMs := int(intervalSec * 1000)
	seekJS := fmt.Sprintf(seekThrottleTpl, intervalMs)
	patched += seekJS
	log.Printf("✅ plugin.js 已注入 seek 防抖脚本 (minInterval=%dms, 来自 api_interval=%.1fs)", intervalMs, intervalSec)

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

