// internal/handler/redirect.go
// 302 重定向处理器 — Go 只做流量转发，缓存由 Python 端统一管理

package handler

import (
	"io"
	"log"
	"net/http"
	"strings"
	"time"

	"github.com/gin-gonic/gin"

	"github.com/mediaflow/go-proxy/internal/config"
	"github.com/mediaflow/go-proxy/internal/service"
)

// RedirectHandler 302 重定向处理器
type RedirectHandler struct {
	pyClient    *service.PythonClient
	cfg         *config.Config
	proxyClient *http.Client
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
	}
}

// HandleVideoStream 处理视频流请求 — 调 Python 获取直链 → 302
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
	log.Printf("302 重定向: %s → %s (source=%s)", itemID, urlSnippet, result.Source)
	c.Redirect(http.StatusFound, result.URL)
}

// HandleResolveURL 返回 JSON 直链（供前端 JS 直链直出使用）
// 前端 JS hook video.src 后，通过此 API 获取 CDN 直链，
// 直接设为 video.src，避免每次 Range 请求都走 302。
func (h *RedirectHandler) HandleResolveURL(c *gin.Context) {
	itemID := c.Param("itemId")
	apiKey, _ := c.Get("api_key")
	apiKeyStr, _ := apiKey.(string)

	userID := c.Query("UserId")
	if userID == "" {
		userID = c.Query("userId")
	}

	userAgent := c.GetHeader("User-Agent")
	result, err := h.pyClient.ResolveLink(itemID, 0, apiKeyStr, userID, userAgent)
	if err != nil || result.URL == "" {
		log.Printf("[directurl] 直链解析失败: %s, err=%v", itemID, err)
		c.JSON(http.StatusOK, gin.H{"url": "", "error": "resolve failed"})
		return
	}

	log.Printf("[directurl] 直链直出: %s (source=%s)", itemID, result.Source)
	c.JSON(http.StatusOK, gin.H{"url": result.URL})
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

