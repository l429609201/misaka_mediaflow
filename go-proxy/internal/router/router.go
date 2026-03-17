// internal/router/router.go
// Gin 路由注册 — 参考 embyreverseproxy / MediaWarp
// 支持 Emby + Jellyfin 双路径拦截 + 115 直链播放

package router

import (
	"net/http"

	"github.com/gin-gonic/gin"

	"github.com/mediaflow/go-proxy/internal/cache"
	"github.com/mediaflow/go-proxy/internal/config"
	"github.com/mediaflow/go-proxy/internal/handler"
	"github.com/mediaflow/go-proxy/internal/middleware"
	"github.com/mediaflow/go-proxy/internal/service"
	"github.com/mediaflow/go-proxy/internal/traffic"
)

// Setup 创建并配置 Gin 路由
func Setup(cfg *config.Config, cm *cache.Manager) *gin.Engine {
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

	// 处理器
	redirectHandler := handler.NewRedirectHandler(cfg, cm, pyClient)
	proxyHandler := handler.NewProxyHandler(cfg, pyClient)
	wsHandler := handler.NewWSHandler(cfg)
	p115Handler := handler.NewP115PlayHandler(cfg, cm, pyClient) // ⭐ 传入共享 pyClient

	// ===== ⭐ 115 直链播放路由 =====
	// STRM 内容: http://<go_proxy>:8888/p115/play/<pick_code>/<filename>
	r.GET("/p115/play/:pickCode/*filename", p115Handler.HandlePlay)
	r.HEAD("/p115/play/:pickCode/*filename", p115Handler.HandlePlay)

	// ===== Emby 拦截路由（需要 API Key 认证）=====
	embyGroup := r.Group("/emby")
	embyGroup.Use(middleware.EmbyAuth())
	{
		// 视频流（同时注册大小写路径，Emby Web 前端用大写 /Videos/）
		for _, prefix := range []string{"/videos", "/Videos"} {
			embyGroup.GET(prefix+"/:itemId/stream", redirectHandler.HandleVideoStream)
			embyGroup.GET(prefix+"/:itemId/stream.:format", redirectHandler.HandleVideoStream)
			embyGroup.HEAD(prefix+"/:itemId/stream", redirectHandler.HandleVideoStream)
			embyGroup.HEAD(prefix+"/:itemId/stream.:format", redirectHandler.HandleVideoStream)

			// 原始文件
			embyGroup.GET(prefix+"/:itemId/original", redirectHandler.HandleVideoStream)
			embyGroup.GET(prefix+"/:itemId/original.:format", redirectHandler.HandleVideoStream)
			embyGroup.HEAD(prefix+"/:itemId/original", redirectHandler.HandleVideoStream)
			embyGroup.HEAD(prefix+"/:itemId/original.:format", redirectHandler.HandleVideoStream)
		}

		// 音频流
		for _, prefix := range []string{"/audio", "/Audio"} {
			embyGroup.GET(prefix+"/:itemId/stream", redirectHandler.HandleVideoStream)
			embyGroup.GET(prefix+"/:itemId/stream.:format", redirectHandler.HandleVideoStream)
			embyGroup.HEAD(prefix+"/:itemId/stream", redirectHandler.HandleVideoStream)
			embyGroup.HEAD(prefix+"/:itemId/stream.:format", redirectHandler.HandleVideoStream)
		}

		// 下载
		for _, prefix := range []string{"/items", "/Items"} {
			embyGroup.GET(prefix+"/:itemId/Download", redirectHandler.HandleVideoStream)
			embyGroup.HEAD(prefix+"/:itemId/Download", redirectHandler.HandleVideoStream)
		}
	}

	// ===== Jellyfin 兼容路由（去掉 /emby/ 前缀）=====
	jellyGroup := r.Group("")
	jellyGroup.Use(middleware.EmbyAuth())
	{
		// 视频流
		for _, prefix := range []string{"/videos", "/Videos"} {
			jellyGroup.GET(prefix+"/:itemId/stream", redirectHandler.HandleVideoStream)
			jellyGroup.GET(prefix+"/:itemId/stream.:format", redirectHandler.HandleVideoStream)
			jellyGroup.HEAD(prefix+"/:itemId/stream", redirectHandler.HandleVideoStream)
			jellyGroup.HEAD(prefix+"/:itemId/stream.:format", redirectHandler.HandleVideoStream)

			// 原始文件
			jellyGroup.GET(prefix+"/:itemId/original", redirectHandler.HandleVideoStream)
			jellyGroup.GET(prefix+"/:itemId/original.:format", redirectHandler.HandleVideoStream)
			jellyGroup.HEAD(prefix+"/:itemId/original", redirectHandler.HandleVideoStream)
			jellyGroup.HEAD(prefix+"/:itemId/original.:format", redirectHandler.HandleVideoStream)
		}

		// 音频流
		for _, prefix := range []string{"/audio", "/Audio"} {
			jellyGroup.GET(prefix+"/:itemId/stream", redirectHandler.HandleVideoStream)
			jellyGroup.GET(prefix+"/:itemId/stream.:format", redirectHandler.HandleVideoStream)
			jellyGroup.HEAD(prefix+"/:itemId/stream", redirectHandler.HandleVideoStream)
			jellyGroup.HEAD(prefix+"/:itemId/stream.:format", redirectHandler.HandleVideoStream)
		}

		// 下载
		for _, prefix := range []string{"/items", "/Items"} {
			jellyGroup.GET(prefix+"/:itemId/Download", redirectHandler.HandleVideoStream)
			jellyGroup.HEAD(prefix+"/:itemId/Download", redirectHandler.HandleVideoStream)
		}
	}

	// ===== WebSocket 透传 =====
	r.GET("/embywebsocket", wsHandler.HandleWS)
	r.GET("/socket", wsHandler.HandleWS)

	// ===== 流量统计 API =====
	r.GET("/api/traffic", func(c *gin.Context) {
		c.JSON(http.StatusOK, traffic.Counter.Snapshot())
	})

	// ===== 其他请求透传到 Emby/Jellyfin =====
	r.NoRoute(proxyHandler.HandleProxy)

	return r
}

