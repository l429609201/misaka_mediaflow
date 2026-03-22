// internal/router/router.go
// Gin 路由注册 — 参考 embyreverseproxy / MediaWarp
// 支持 Emby + Jellyfin 双路径拦截 + 115 直链播放

package router

import (
	"fmt"
	"io"
	"net/http"

	"github.com/gin-gonic/gin"

	"github.com/mediaflow/go-proxy/internal/config"
	"github.com/mediaflow/go-proxy/internal/handler"
	"github.com/mediaflow/go-proxy/internal/middleware"
	"github.com/mediaflow/go-proxy/internal/service"
	"github.com/mediaflow/go-proxy/internal/traffic"
)

// Setup 创建并配置 Gin 路由
func Setup(cfg *config.Config) *gin.Engine {
	gin.SetMode(gin.ReleaseMode)
	r := gin.New()
	r.Use(gin.Recovery())
	r.Use(middleware.RequestLogger())

	// UA 过滤
	if cfg.Security.ClientFilterEnabled && len(cfg.Security.UABlacklist) > 0 {
		r.Use(middleware.ClientFilter(cfg.Security.UABlacklist))
	}

	// Python 客户端（共享，所有 handler 统一使用）
	pyClient := service.NewPythonClient(cfg)

	// 处理器（Go 只做转发，缓存由 Python 端管理）
	redirectHandler := handler.NewRedirectHandler(cfg, pyClient)
	proxyHandler := handler.NewProxyHandler(cfg, pyClient)
	wsHandler := handler.NewWSHandler(cfg)
	p115Handler := handler.NewP115PlayHandler(cfg, pyClient)
	subtitleHandler := handler.NewSubtitleHandler(cfg, pyClient)

	// ⭐ 302 请求节流器（防止 Web UI 并行 Range 请求导致 115 CDN 限流）
	throttler := middleware.NewRedirectThrottler()
	itemThrottle := throttler.Throttle(func(c *gin.Context) string {
		return c.Param("itemId")
	})
	pickCodeThrottle := throttler.Throttle(func(c *gin.Context) string {
		return c.Param("pickCode")
	})

	// ===== ⭐ 115 直链播放路由 =====
	// STRM 内容: http://<go_proxy>:8888/p115/play/<pick_code>/<filename>
	r.GET("/p115/play/:pickCode/*filename", pickCodeThrottle, p115Handler.HandlePlay)
	r.HEAD("/p115/play/:pickCode/*filename", pickCodeThrottle, p115Handler.HandlePlay)

	// ===== Emby 拦截路由（需要 API Key 认证）=====
	embyGroup := r.Group("/emby")
	embyGroup.Use(middleware.EmbyAuth())
	{
		// 视频流（同时注册大小写路径，Emby Web 前端用大写 /Videos/）
		for _, prefix := range []string{"/videos", "/Videos"} {
			embyGroup.GET(prefix+"/:itemId/stream", itemThrottle, redirectHandler.HandleVideoStream)
			embyGroup.GET(prefix+"/:itemId/stream.:format", itemThrottle, redirectHandler.HandleVideoStream)
			embyGroup.HEAD(prefix+"/:itemId/stream", itemThrottle, redirectHandler.HandleVideoStream)
			embyGroup.HEAD(prefix+"/:itemId/stream.:format", itemThrottle, redirectHandler.HandleVideoStream)

			// 原始文件
			embyGroup.GET(prefix+"/:itemId/original", itemThrottle, redirectHandler.HandleVideoStream)
			embyGroup.GET(prefix+"/:itemId/original.:format", itemThrottle, redirectHandler.HandleVideoStream)
			embyGroup.HEAD(prefix+"/:itemId/original", itemThrottle, redirectHandler.HandleVideoStream)
			embyGroup.HEAD(prefix+"/:itemId/original.:format", itemThrottle, redirectHandler.HandleVideoStream)

			// ⭐ 字幕路由（ASS/SSA/SRT → 转发 Python 字幕服务；其他格式透传 Emby）
			// 注意：Emby 字幕路径格式为 /Subtitles/:subId/0/Stream.ass，需要用 *rest 匹配多段
			embyGroup.GET(prefix+"/:itemId/Subtitles/:subId/*rest", subtitleHandler.HandleSubtitle)
			embyGroup.GET(prefix+"/:itemId/subtitles/:subId/*rest", subtitleHandler.HandleSubtitle)
		}

		// 音频流
		for _, prefix := range []string{"/audio", "/Audio"} {
			embyGroup.GET(prefix+"/:itemId/stream", itemThrottle, redirectHandler.HandleVideoStream)
			embyGroup.GET(prefix+"/:itemId/stream.:format", itemThrottle, redirectHandler.HandleVideoStream)
			embyGroup.HEAD(prefix+"/:itemId/stream", itemThrottle, redirectHandler.HandleVideoStream)
			embyGroup.HEAD(prefix+"/:itemId/stream.:format", itemThrottle, redirectHandler.HandleVideoStream)
		}

		// 下载
		for _, prefix := range []string{"/items", "/Items"} {
			embyGroup.GET(prefix+"/:itemId/Download", itemThrottle, redirectHandler.HandleVideoStream)
			embyGroup.HEAD(prefix+"/:itemId/Download", itemThrottle, redirectHandler.HandleVideoStream)
		}
	}

	// ===== Jellyfin 兼容路由（去掉 /emby/ 前缀）=====
	jellyGroup := r.Group("")
	jellyGroup.Use(middleware.EmbyAuth())
	{
		// 视频流
		for _, prefix := range []string{"/videos", "/Videos"} {
			jellyGroup.GET(prefix+"/:itemId/stream", itemThrottle, redirectHandler.HandleVideoStream)
			jellyGroup.GET(prefix+"/:itemId/stream.:format", itemThrottle, redirectHandler.HandleVideoStream)
			jellyGroup.HEAD(prefix+"/:itemId/stream", itemThrottle, redirectHandler.HandleVideoStream)
			jellyGroup.HEAD(prefix+"/:itemId/stream.:format", itemThrottle, redirectHandler.HandleVideoStream)

			// 原始文件
			jellyGroup.GET(prefix+"/:itemId/original", itemThrottle, redirectHandler.HandleVideoStream)
			jellyGroup.GET(prefix+"/:itemId/original.:format", itemThrottle, redirectHandler.HandleVideoStream)
			jellyGroup.HEAD(prefix+"/:itemId/original", itemThrottle, redirectHandler.HandleVideoStream)
			jellyGroup.HEAD(prefix+"/:itemId/original.:format", itemThrottle, redirectHandler.HandleVideoStream)

			// ⭐ 字幕路由（同 embyGroup，覆盖无 /emby/ 前缀的请求）
			jellyGroup.GET(prefix+"/:itemId/Subtitles/:subId/*rest", subtitleHandler.HandleSubtitle)
			jellyGroup.GET(prefix+"/:itemId/subtitles/:subId/*rest", subtitleHandler.HandleSubtitle)
		}

		// 音频流
		for _, prefix := range []string{"/audio", "/Audio"} {
			jellyGroup.GET(prefix+"/:itemId/stream", itemThrottle, redirectHandler.HandleVideoStream)
			jellyGroup.GET(prefix+"/:itemId/stream.:format", itemThrottle, redirectHandler.HandleVideoStream)
			jellyGroup.HEAD(prefix+"/:itemId/stream", itemThrottle, redirectHandler.HandleVideoStream)
			jellyGroup.HEAD(prefix+"/:itemId/stream.:format", itemThrottle, redirectHandler.HandleVideoStream)
		}

		// 下载
		for _, prefix := range []string{"/items", "/Items"} {
			jellyGroup.GET(prefix+"/:itemId/Download", itemThrottle, redirectHandler.HandleVideoStream)
			jellyGroup.HEAD(prefix+"/:itemId/Download", itemThrottle, redirectHandler.HandleVideoStream)
		}
	}

	// ===== WebSocket 透传 =====
	r.GET("/embywebsocket", wsHandler.HandleWS)
	r.GET("/socket", wsHandler.HandleWS)

	// ===== 流量统计 API =====
	r.GET("/api/traffic", func(c *gin.Context) {
		c.JSON(http.StatusOK, traffic.Counter.Snapshot())
	})

	// ===== 缓存统计 API（转发到 Python 端）=====
	r.GET("/api/cache/stats", func(c *gin.Context) {
		pyURL := fmt.Sprintf("http://127.0.0.1:%d/internal/cache/stats", cfg.Server.PyPort)
		resp, err := http.Get(pyURL)
		if err != nil {
			c.JSON(http.StatusBadGateway, gin.H{"error": err.Error()})
			return
		}
		defer resp.Body.Close()
		c.Status(resp.StatusCode)
		c.Header("Content-Type", "application/json")
		io.Copy(c.Writer, resp.Body)
	})

	// ===== 其他请求透传到 Emby/Jellyfin =====
	r.NoRoute(proxyHandler.HandleProxy)

	return r
}

