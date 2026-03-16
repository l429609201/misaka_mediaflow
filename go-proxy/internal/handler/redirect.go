// internal/handler/redirect.go
// 302 重定向处理器

package handler

import (
	"crypto/sha256"
	"fmt"
	"io"
	"log"
	"net/http"
	"strings"
	"time"

	"github.com/gin-gonic/gin"

	"github.com/mediaflow/go-proxy/internal/cache"
	"github.com/mediaflow/go-proxy/internal/config"
	"github.com/mediaflow/go-proxy/internal/service"
)

// RedirectHandler 302 重定向处理器
type RedirectHandler struct {
	cache       *cache.Manager
	pyClient    *service.PythonClient
	cfg         *config.Config
	proxyClient *http.Client
}

// NewRedirectHandler 创建 302 处理器
func NewRedirectHandler(cfg *config.Config, cm *cache.Manager, pc *service.PythonClient) *RedirectHandler {
	return &RedirectHandler{
		cache:    cm,
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

// HandleVideoStream 处理视频流请求 — 返回 302 或透传
func (h *RedirectHandler) HandleVideoStream(c *gin.Context) {
	itemID := c.Param("itemId")
	apiKey, _ := c.Get("api_key")
	apiKeyStr, _ := apiKey.(string)

	// 生成缓存键
	cacheKey := makeCacheKey(itemID, "0", apiKeyStr)

	// 1. 查缓存
	if url, ok := h.cache.Get(cacheKey); ok {
		log.Printf("缓存命中: %s → 302", itemID)
		c.Redirect(http.StatusFound, url)
		return
	}

	// 2. 缓存未命中 → 调用 Python 解析
	result, err := h.pyClient.ResolveLink(itemID, 0, apiKeyStr)
	if err != nil || result.URL == "" {
		log.Printf("直链解析失败: %s, err=%v", itemID, err)
		// 回退透传
		h.proxyFallback(c)
		return
	}

	// 3. 写入缓存
	h.cache.Set(cacheKey, result.URL)

	// 4. 302 重定向
	urlSnippet := result.URL
	if len(urlSnippet) > 80 {
		urlSnippet = urlSnippet[:80] + "..."
	}
	log.Printf("302 重定向: %s → %s", itemID, urlSnippet)
	c.Redirect(http.StatusFound, result.URL)
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

	// 复制请求头
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

	// 复制响应头
	for key, values := range resp.Header {
		for _, v := range values {
			c.Header(key, v)
		}
	}

	c.Status(resp.StatusCode)
	io.Copy(c.Writer, resp.Body)
}

// makeCacheKey 生成 SHA256 缓存键
func makeCacheKey(itemID, storageID, apiKey string) string {
	raw := fmt.Sprintf("%s:%s:%s", itemID, storageID, apiKey)
	hash := sha256.Sum256([]byte(raw))
	return fmt.Sprintf("%x", hash)
}

