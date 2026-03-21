// internal/handler/redirect.go
// 302 重定向处理器 — Go 只做流量转发，缓存由 Python 端统一管理
//
// CORS 解决方案: 在 proxy.go 中通过 HTML 注入运行时脚本，
//   阻止 <video> 被设置 crossorigin 属性，使浏览器以 no-cors 模式请求，
//   302 到 115 CDN 后不做 CORS 检查。

package handler

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"sync"
	"time"

	"github.com/gin-gonic/gin"

	"github.com/mediaflow/go-proxy/internal/config"
	"github.com/mediaflow/go-proxy/internal/logger"
	"github.com/mediaflow/go-proxy/internal/service"
)

// _notifiedItems 记录已发过字幕就绪通知的 item_id，避免重复弹消息
var _notifiedItems sync.Map

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

	// ⭐ 302 成功后，goroutine 预热内封字幕（等待提取完成）
	// 提取完成后向客户端推 Emby 消息，引导用户重新选择字幕
	// 不阻塞 302 响应：goroutine 在后台运行
	go func() {
		// 已通知过则跳过（避免每次 Range 请求都重复弹消息）
		if _, alreadyNotified := _notifiedItems.Load(itemID); alreadyNotified {
			return
		}
		// 查询 item 类型
		_, itemType, err := h.pyClient.CheckStrm(itemID, apiKeyStr)
		if err != nil {
			itemType = ""
		}
		// warmup：触发提取并等待最多 5 秒
		warmed := h.pyClient.WarmupEmbeddedSub(itemID, result.URL, userAgent, itemType, 5*time.Second)
		if warmed == nil || !warmed.Cached {
			// 无内封字幕或提取失败，什么都不做
			return
		}
		// 标记已通知（TTL 靠缓存自然过期，这里只防本次播放重复推）
		_notifiedItems.Store(itemID, true)
		logger.Infof("[subtitle] 内封字幕就绪，item_id=%s lang=%s，通知 Emby 刷新字幕", itemID, warmed.Lang)
		// 通知 Emby 会话刷新：发送 DisplayMessage 让播放器弹提示
		h.notifyEmbeddedSubReady(itemID, warmed.Lang, apiKeyStr)
	}()
}

// notifyEmbeddedSubReady 内封字幕就绪后，通过 Emby API 向所有活跃 session 发送消息
// 提示用户字幕已就绪，下次切换或重新选字幕时生效
func (h *RedirectHandler) notifyEmbeddedSubReady(itemID, lang, apiKey string) {
	embyHost := strings.TrimRight(h.cfg.MediaServer.Host, "/")
	if embyHost == "" || apiKey == "" {
		return
	}

	// 查询所有 Session，找到正在播放 itemID 的会话
	sessURL := fmt.Sprintf("%s/emby/Sessions?api_key=%s", embyHost, apiKey)
	resp, err := (&http.Client{Timeout: 3 * time.Second}).Get(sessURL)
	if err != nil {
		logger.Debugf("[subtitle] 查询 Emby Sessions 失败: %v", err)
		return
	}
	defer resp.Body.Close()
	sessBody, _ := io.ReadAll(resp.Body)

	var sessions []map[string]interface{}
	if err := json.Unmarshal(sessBody, &sessions); err != nil {
		return
	}

	client := &http.Client{Timeout: 3 * time.Second}
	notified := 0
	for _, sess := range sessions {
		// 找正在播放目标 item 的 session
		nowPlaying, _ := sess["NowPlayingItem"].(map[string]interface{})
		if nowPlaying == nil {
			continue
		}
		playingID := fmt.Sprintf("%v", nowPlaying["Id"])
		if playingID != itemID {
			continue
		}
		sessID := fmt.Sprintf("%v", sess["Id"])
		// 发送 DisplayMessage 通知
		msgURL := fmt.Sprintf("%s/emby/Sessions/%s/Message?api_key=%s", embyHost, sessID, apiKey)
		msgBody := fmt.Sprintf(`{"Header":"字幕已就绪","Text":"内封字幕(%s)已提取，请重新点击播放以加载字幕。","TimeoutMs":8000}`, lang)
		req, _ := http.NewRequest(http.MethodPost, msgURL, strings.NewReader(msgBody))
		req.Header.Set("Content-Type", "application/json")
		r, err := client.Do(req)
		if err == nil {
			r.Body.Close()
			notified++
			logger.Infof("[subtitle] ✅ 已通知 session=%s 字幕就绪 lang=%s", sessID, lang)
		}
	}
	if notified == 0 {
		logger.Debugf("[subtitle] 未找到正在播放 item_id=%s 的活跃 session", itemID)
	}
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

