// internal/handler/redirect.go
// 302 重定向处理器 — Go 只做流量转发，缓存由 Python 端统一管理
//
// ⭐ CORS 解决方案:
//   Web 浏览器 → 流式反代（go-proxy 代请求 CDN → 流式返回，同源无 CORS）
//   原生客户端 → 302 重定向（直连 CDN，高性能）
//
// 原因: 115 CDN 不返回 Access-Control-Allow-Origin 头，
//       浏览器以 CORS 模式请求 302 目标时会被拦截。
//       参考 embyExternalUrl 的做法：对 Web 走代理，对客户端走 302。

package handler

import (
	"fmt"
	"io"
	"log"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/gin-gonic/gin"

	"github.com/mediaflow/go-proxy/internal/config"
	"github.com/mediaflow/go-proxy/internal/service"
)

const (
	// 302 缓存上限（秒）：即使 CDN 直链有效期更长，浏览器也最多缓存这么久
	redirectCacheMaxSec     = 600
	// 当 Python 端未返回 expires_in 时的默认缓存时长
	redirectCacheDefaultSec = 300
)

// RedirectHandler 302 重定向处理器
type RedirectHandler struct {
	pyClient    *service.PythonClient
	cfg         *config.Config
	proxyClient *http.Client  // 用于 proxyFallback（不跟随重定向）
	streamClient *http.Client // 用于 streamProxy（流式反代到 CDN）
}

// NewRedirectHandler 创建 302 处理器
func NewRedirectHandler(cfg *config.Config, pc *service.PythonClient) *RedirectHandler {
	return &RedirectHandler{
		pyClient: pc,
		cfg:      cfg,
		proxyClient: &http.Client{
			Timeout: time.Duration(cfg.Proxy.ConnectTimeout) * time.Second,
			CheckRedirect: func(req *http.Request, via []*http.Request) error {
				return http.ErrUseLastResponse
			},
		},
		// streamClient: 流式反代专用，不设全局 Timeout（流媒体可能长连接），
		// 不跟随重定向（CDN URL 已经是最终地址）
		streamClient: &http.Client{
			Timeout: 0, // 不设超时，由客户端断开控制
			CheckRedirect: func(req *http.Request, via []*http.Request) error {
				return http.ErrUseLastResponse
			},
		},
	}
}

// isWebBrowser 检测请求是否来自 Web 浏览器
// 浏览器会自动设置 Sec-Fetch-Mode 头（cors / navigate / no-cors / same-origin），
// 原生客户端（Emby App、Infuse、mpv 等）不会发送此头。
// 同时检查 Origin 头作为备用判断。
func isWebBrowser(c *gin.Context) bool {
	// ① Sec-Fetch-Mode 是最可靠的判断依据
	// 浏览器 <video> 加载视频时发 "no-cors" 或 "cors"
	// fetch() / XHR 发 "cors"
	// 页面导航发 "navigate"
	// 只有浏览器会发这个头
	if sfm := c.GetHeader("Sec-Fetch-Mode"); sfm != "" {
		return true
	}

	// ② Origin 头：跨域请求时浏览器自动附带
	if origin := c.GetHeader("Origin"); origin != "" {
		return true
	}

	// ③ Sec-Fetch-Site：另一个浏览器专有头
	if sfs := c.GetHeader("Sec-Fetch-Site"); sfs != "" {
		return true
	}

	return false
}

// HandleVideoStream 处理视频流请求 — 调 Python 获取直链 → 302 或流式反代
func (h *RedirectHandler) HandleVideoStream(c *gin.Context) {
	itemID := c.Param("itemId")
	apiKey, _ := c.Get("api_key")
	apiKeyStr, _ := apiKey.(string)

	userID := c.Query("UserId")
	if userID == "" {
		userID = c.Query("userId")
	}

	// 调用 Python 解析（Python 端已含缓存层：内存 L1 + DB/Redis L2）
	userAgent := c.GetHeader("User-Agent")
	result, err := h.pyClient.ResolveLink(itemID, 0, apiKeyStr, userID, userAgent)
	if err != nil || result.URL == "" {
		log.Printf("直链解析失败: %s, err=%v", itemID, err)
		h.proxyFallback(c)
		return
	}

	urlSnippet := result.URL
	if len(urlSnippet) > 80 {
		urlSnippet = urlSnippet[:80] + "..."
	}

	// ⭐ CORS 策略分流：Web 浏览器 → 流式反代，原生客户端 → 302
	if isWebBrowser(c) {
		log.Printf("🌐 Web 浏览器请求，走流式反代: %s → %s (source=%s)", itemID, urlSnippet, result.Source)
		h.streamProxy(c, result.URL)
		return
	}

	log.Printf("📱 客户端请求，走 302 重定向: %s → %s (source=%s)", itemID, urlSnippet, result.Source)

	// 让客户端缓存此 302，后续 Range 请求直接跳转到 CDN，不再回 go-proxy
	age := redirectCacheDefaultSec
	if result.ExpiresIn > 0 && result.ExpiresIn < redirectCacheMaxSec {
		age = result.ExpiresIn
	}
	c.Header("Cache-Control", fmt.Sprintf("public, max-age=%d", age))
	c.Redirect(http.StatusFound, result.URL)
}

// streamProxy 流式反代：go-proxy 代替浏览器请求 CDN，然后流式返回
// 解决 115 CDN 不返回 CORS 头导致浏览器跨域失败的问题
func (h *RedirectHandler) streamProxy(c *gin.Context, cdnURL string) {
	// 构造到 CDN 的请求
	req, err := http.NewRequestWithContext(c.Request.Context(), c.Request.Method, cdnURL, nil)
	if err != nil {
		log.Printf("streamProxy 创建请求失败: %v", err)
		c.JSON(http.StatusBadGateway, gin.H{"error": "failed to create stream request"})
		return
	}

	// 传递关键请求头（Range 支持断点续传）
	if rangeHeader := c.GetHeader("Range"); rangeHeader != "" {
		req.Header.Set("Range", rangeHeader)
	}
	if ifRange := c.GetHeader("If-Range"); ifRange != "" {
		req.Header.Set("If-Range", ifRange)
	}

	// User-Agent: 115 CDN 可能校验 UA，使用合理的 UA
	// 注意不能用浏览器的 UA（115 可能拒绝），使用通用下载工具 UA
	req.Header.Set("User-Agent", "Mozilla/5.0")

	// 请求 CDN
	resp, err := h.streamClient.Do(req)
	if err != nil {
		log.Printf("streamProxy CDN 请求失败: %v", err)
		c.JSON(http.StatusBadGateway, gin.H{"error": "CDN request failed"})
		return
	}
	defer resp.Body.Close()

	// 转发关键响应头
	streamHeaders := []string{
		"Content-Type",
		"Content-Length",
		"Content-Range",
		"Accept-Ranges",
		"ETag",
		"Last-Modified",
		"Content-Disposition",
	}
	for _, header := range streamHeaders {
		if v := resp.Header.Get(header); v != "" {
			c.Header(header, v)
		}
	}

	// 禁止浏览器缓存流式响应（每次都走 go-proxy，确保 CDN URL 有效）
	c.Header("Cache-Control", "no-cache, no-store, must-revalidate")

	// 写入状态码（200 或 206 Partial Content）
	c.Status(resp.StatusCode)

	// 流式传输
	written, err := io.Copy(c.Writer, resp.Body)
	if err != nil {
		// 客户端断开连接是正常现象（seek、切集等），不算错误
		if !isClientDisconnect(err) {
			log.Printf("streamProxy 传输中断: %v (已传输 %s)", err, formatBytes(written))
		}
	}
}

// isClientDisconnect 判断是否是客户端主动断开连接
func isClientDisconnect(err error) bool {
	if err == nil {
		return false
	}
	errMsg := err.Error()
	return strings.Contains(errMsg, "broken pipe") ||
		strings.Contains(errMsg, "connection reset") ||
		strings.Contains(errMsg, "client disconnected") ||
		strings.Contains(errMsg, "context canceled") ||
		strings.Contains(errMsg, "request canceled")
}

// formatBytes 格式化字节数为可读字符串
func formatBytes(bytes int64) string {
	const (
		KB = 1024
		MB = KB * 1024
		GB = MB * 1024
	)
	switch {
	case bytes >= GB:
		return strconv.FormatFloat(float64(bytes)/float64(GB), 'f', 2, 64) + " GB"
	case bytes >= MB:
		return strconv.FormatFloat(float64(bytes)/float64(MB), 'f', 2, 64) + " MB"
	case bytes >= KB:
		return strconv.FormatFloat(float64(bytes)/float64(KB), 'f', 2, 64) + " KB"
	default:
		return strconv.FormatInt(bytes, 10) + " B"
	}
}

// proxyFallback 透传到 Emby
func (h *RedirectHandler) proxyFallback(c *gin.Context) {
	targetURL := strings.TrimRight(h.cfg.MediaServer.Host, "/") + c.Request.URL.String()

	req, err := http.NewRequestWithContext(c.Request.Context(), c.Request.Method, targetURL, c.Request.Body)
	if err != nil {
		log.Printf("proxyFallback 创建请求失败: %v", err)
		c.JSON(http.StatusBadGateway, gin.H{"error": "failed to create proxy request"})
		return
	}

	for key, values := range c.Request.Header {
		for _, v := range values {
			req.Header.Add(key, v)
		}
	}

	resp, err := h.proxyClient.Do(req)
	if err != nil {
		log.Printf("proxyFallback 请求失败: %v", err)
		c.JSON(http.StatusBadGateway, gin.H{"error": "proxy request failed"})
		return
	}
	defer resp.Body.Close()

	for key, values := range resp.Header {
		for _, v := range values {
			c.Header(key, v)
		}
	}

	c.Status(resp.StatusCode)
	io.Copy(c.Writer, resp.Body)
}

