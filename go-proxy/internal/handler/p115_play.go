// internal/handler/p115_play.go
// 115 直链播放处理器 — /p115/play/:pickCode/*filename

package handler

import (
	"fmt"
	"log"
	"net/http"
	"strings"

	"github.com/gin-gonic/gin"

	"github.com/mediaflow/go-proxy/internal/cache"
	"github.com/mediaflow/go-proxy/internal/config"
	"github.com/mediaflow/go-proxy/internal/service"
)

// P115PlayHandler 115 直链播放处理器
type P115PlayHandler struct {
	cache    *cache.Manager
	cfg      *config.Config
	pyClient *service.PythonClient
}

// NewP115PlayHandler 创建 115 Play 处理器
func NewP115PlayHandler(cfg *config.Config, cm *cache.Manager, pc *service.PythonClient) *P115PlayHandler {
	return &P115PlayHandler{
		cache:    cm,
		cfg:      cfg,
		pyClient: pc,
	}
}

// HandlePlay 处理 /p115/play/:pickCode/*filename
// STRM 文件内容: http://<go_proxy>:8888/p115/play/<pick_code>/<filename>
// Go 收到后 → 查缓存 → 未命中调 Python 统一解析接口 → 302 重定向到 115 CDN 直链
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

	// 2. 缓存未命中 → 调用 Python 统一解析接口（通过 pickcode）
	result, err := h.pyClient.ResolveByPickcode(pickCode)
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
	log.Printf("[115] 302 重定向: %s → %s (source=%s)", pickCode, urlSnippet, result.Source)
	c.Redirect(http.StatusFound, result.URL)
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

