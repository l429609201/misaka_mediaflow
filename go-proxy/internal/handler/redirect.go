// internal/handler/redirect.go
// 302 重定向处理器 — Go 只做流量转发，缓存由 Python 端统一管理
//
// CORS 解决方案: 在 proxy.go 中通过 HTML 注入运行时脚本，
//   阻止 <video> 被设置 crossorigin 属性，使浏览器以 no-cors 模式请求，
//   302 到 115 CDN 后不做 CORS 检查。

package handler

import (
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"

	"github.com/gin-gonic/gin"

	"github.com/mediaflow/go-proxy/internal/config"
	"github.com/mediaflow/go-proxy/internal/logger"
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
		logger.Infof("直链解析失败: %s, err=%v", itemID, err)
		h.proxyFallback(c)
		return
	}

	urlSnippet := result.URL
	if len(urlSnippet) > 80 {
		urlSnippet = urlSnippet[:80] + "..."
	}
	logger.Infof("302 重定向: %s → %s (source=%s)", itemID, urlSnippet, result.Source)

	// 让浏览器缓存此 302，后续 Range 请求直接跳转到 CDN，不再回 go-proxy
	age := redirectCacheDefaultSec
	if result.ExpiresIn > 0 && result.ExpiresIn < redirectCacheMaxSec {
		age = result.ExpiresIn
	}
	c.Header("Cache-Control", fmt.Sprintf("public, max-age=%d", age))

	// ⭐ 如果客户端通过 HTTPS 访问，将 CDN 链接也升级为 HTTPS
	// 避免 Mixed Content 问题：HTTPS 页面中加载 HTTP 资源会被浏览器阻止
	cdnURL := result.URL
	if (c.Request.TLS != nil || c.GetHeader("X-Forwarded-Proto") == "https") &&
		strings.HasPrefix(cdnURL, "http://") {
		cdnURL = "https://" + cdnURL[7:]
		logger.Infof("302 升级 HTTPS: %s → https://...", itemID)
	}

	c.Redirect(http.StatusFound, cdnURL)
}

// proxyFallback 透传到 Emby
func (h *RedirectHandler) proxyFallback(c *gin.Context) {
	targetURL := strings.TrimRight(h.cfg.MediaServer.Host, "/") + c.Request.URL.String()

	req, err := http.NewRequestWithContext(c.Request.Context(), c.Request.Method, targetURL, c.Request.Body)
	if err != nil {
		logger.Infof("proxyFallback 创建请求失败: %v", err)
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
		logger.Infof("proxyFallback 请求失败: %v", err)
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

