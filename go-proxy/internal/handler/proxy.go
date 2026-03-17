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
	"regexp"
	"strconv"
	"strings"

	"github.com/gin-gonic/gin"

	"github.com/mediaflow/go-proxy/internal/config"
)

// crossOriginPattern 匹配 plugin.js 中各种形式的 crossOrigin 赋值：
//   - 非压缩: &&(elem.crossOrigin=initialSubtitleStream)
//   - 压缩:   &&(e.crossOrigin=t)  /  &&(a.crossOrigin=n)  等
var crossOriginPattern = regexp.MustCompile(`&&\([a-zA-Z_$][a-zA-Z0-9_$]*\.crossOrigin=[a-zA-Z_$][a-zA-Z0-9_$]*\)`)

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

	// 读取响应体（可能 gzip 压缩）
	isGzip := strings.Contains(resp.Header.Get("Content-Encoding"), "gzip")
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

	// 用正则替换所有 crossOrigin 赋值模式
	original := string(body)
	patched := crossOriginPattern.ReplaceAllString(original, "")

	if original != patched {
		matches := crossOriginPattern.FindAllString(original, -1)
		log.Printf("✅ plugin.js 已 patch: 去除 %d 处 crossOrigin 赋值 %v", len(matches), matches)
	} else {
		log.Printf("⚠️ plugin.js 未找到 crossOrigin 赋值模式 (文件大小=%d bytes)", len(body))
	}

	// 写回响应体
	newBody := []byte(patched)
	if isGzip {
		var buf bytes.Buffer
		gw := gzip.NewWriter(&buf)
		gw.Write(newBody)
		gw.Close()
		newBody = buf.Bytes()
	}

	resp.Body = io.NopCloser(bytes.NewReader(newBody))
	resp.ContentLength = int64(len(newBody))
	resp.Header.Set("Content-Length", strconv.Itoa(len(newBody)))

	// ⭐ 禁止浏览器缓存 patch 后的 plugin.js，确保每次都经过 Go 反代处理
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

