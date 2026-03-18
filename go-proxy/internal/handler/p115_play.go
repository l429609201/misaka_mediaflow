// internal/handler/p115_play.go
// 115 直链播放处理器 — Go 只做流量转发，缓存由 Python 端统一管理

package handler

import (
	"fmt"
	"log"
	"net/http"

	"github.com/gin-gonic/gin"

	"github.com/mediaflow/go-proxy/internal/config"
	"github.com/mediaflow/go-proxy/internal/service"
)

// P115PlayHandler 115 直链播放处理器
type P115PlayHandler struct {
	cfg      *config.Config
	pyClient *service.PythonClient
}

// NewP115PlayHandler 创建 115 Play 处理器
func NewP115PlayHandler(cfg *config.Config, pc *service.PythonClient) *P115PlayHandler {
	return &P115PlayHandler{
		cfg:      cfg,
		pyClient: pc,
	}
}

// HandlePlay 处理 /p115/play/:pickCode/*filename
// Go 收到后 → 调 Python（Python 内含缓存）→ 302 重定向到 115 CDN 直链
func (h *P115PlayHandler) HandlePlay(c *gin.Context) {
	pickCode := c.Param("pickCode")
	if pickCode == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "missing pick_code"})
		return
	}

	// 调 Python 获取直链（Python 端已含缓存层）
	userAgent := c.GetHeader("User-Agent")
	result, err := h.pyClient.ResolveByPickcode(pickCode, userAgent)
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

	urlSnippet := result.URL
	if len(urlSnippet) > 80 {
		urlSnippet = urlSnippet[:80] + "..."
	}
	log.Printf("[115] 302 重定向: %s → %s (source=%s)", pickCode, urlSnippet, result.Source)

	age := redirectCacheDefaultSec
	if result.ExpiresIn > 0 && result.ExpiresIn < redirectCacheMaxSec {
		age = result.ExpiresIn
	}
	c.Header("Cache-Control", fmt.Sprintf("public, max-age=%d", age))
	c.Redirect(http.StatusFound, result.URL)
}

