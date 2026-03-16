// internal/handler/p115_play.go
// 115 直链播放处理器 — /p115/play/:pickCode/*filename

package handler

import (
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"strings"
	"time"

	"github.com/gin-gonic/gin"

	"github.com/mediaflow/go-proxy/internal/cache"
	"github.com/mediaflow/go-proxy/internal/config"
)

// P115PlayHandler 115 直链播放处理器
type P115PlayHandler struct {
	cache    *cache.Manager
	cfg      *config.Config
	pyClient *http.Client
}

// p115ResolveResult Python /internal/p115/download-url 返回结果
type p115ResolveResult struct {
	URL       string `json:"url"`
	ExpiresIn int    `json:"expires_in"`
	FileName  string `json:"file_name"`
	Error     string `json:"error"`
}

// NewP115PlayHandler 创建 115 Play 处理器
func NewP115PlayHandler(cfg *config.Config, cm *cache.Manager) *P115PlayHandler {
	return &P115PlayHandler{
		cache: cm,
		cfg:   cfg,
		pyClient: &http.Client{
			Timeout: 30 * time.Second,
		},
	}
}

// HandlePlay 处理 /p115/play/:pickCode/*filename
// STRM 文件内容: http://<go_proxy>:8888/p115/play/<pick_code>/<filename>
// Go 收到后 → 查缓存 → 未命中调 Python → 302 重定向到 115 CDN 直链
func (h *P115PlayHandler) HandlePlay(c *gin.Context) {
	pickCode := c.Param("pickCode")
	if pickCode == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "missing pick_code"})
		return
	}

	// 提取 UA 类型用于缓存分组（不同客户端可能需要不同直链）
	uaCategory := classifyUA(c.GetHeader("User-Agent"))

	// 生成缓存键: p115:<pickCode>:<uaCategory>
	cacheKey := fmt.Sprintf("p115:%s:%s", pickCode, uaCategory)

	// 1. 查缓存
	if url, ok := h.cache.Get(cacheKey); ok {
		log.Printf("[115] 缓存命中: %s → 302", pickCode)
		c.Redirect(http.StatusFound, url)
		return
	}

	// 2. 缓存未命中 → 调用 Python /internal/p115/download-url
	result, err := h.resolveP115Link(pickCode)
	if err != nil || result.URL == "" {
		errMsg := ""
		if err != nil {
			errMsg = err.Error()
		} else if result != nil {
			errMsg = result.Error
		}
		log.Printf("[115] 直链解析失败: pickCode=%s, err=%s", pickCode, errMsg)
		c.JSON(http.StatusBadGateway, gin.H{"error": "failed to resolve 115 download url"})
		return
	}

	// 3. 写入缓存
	h.cache.Set(cacheKey, result.URL)

	// 4. 302 重定向到 115 CDN
	urlSnippet := result.URL
	if len(urlSnippet) > 80 {
		urlSnippet = urlSnippet[:80] + "..."
	}
	log.Printf("[115] 302 重定向: %s → %s", pickCode, urlSnippet)
	c.Redirect(http.StatusFound, result.URL)
}

// resolveP115Link 调用 Python 内部 API 获取 115 直链
func (h *P115PlayHandler) resolveP115Link(pickCode string) (*p115ResolveResult, error) {
	url := fmt.Sprintf("http://127.0.0.1:%d/internal/p115/download-url?pick_code=%s",
		h.cfg.Server.PyPort, pickCode)

	resp, err := h.pyClient.Get(url)
	if err != nil {
		return nil, fmt.Errorf("调用 Python p115 API 失败: %w", err)
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("读取响应失败: %w", err)
	}

	var result p115ResolveResult
	if err := json.Unmarshal(body, &result); err != nil {
		return nil, fmt.Errorf("解析响应失败: %w", err)
	}

	return &result, nil
}

// classifyUA 根据 User-Agent 分类（部分 115 CDN 对不同客户端返回不同链接）
func classifyUA(ua string) string {
	ua = strings.ToLower(ua)
	switch {
	case strings.Contains(ua, "infuse"):
		return "infuse"
	case strings.Contains(ua, "emby"):
		return "emby"
	case strings.Contains(ua, "jellyfin"):
		return "jellyfin"
	case strings.Contains(ua, "vlc"):
		return "vlc"
	case strings.Contains(ua, "mpv"):
		return "mpv"
	default:
		return "default"
	}
}

