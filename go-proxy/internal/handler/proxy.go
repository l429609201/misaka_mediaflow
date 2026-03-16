// internal/handler/proxy.go
// 透传处理器 — 将请求直接代理到 Emby/Jellyfin（基于 httputil.ReverseProxy）

package handler

import (
	"log"
	"net/http"
	"net/http/httputil"
	"net/url"

	"github.com/gin-gonic/gin"

	"github.com/mediaflow/go-proxy/internal/config"
)

// ProxyHandler 透传处理器
type ProxyHandler struct {
	cfg          *config.Config
	reverseProxy *httputil.ReverseProxy
	targetURL    *url.URL
}

// NewProxyHandler 创建透传处理器
func NewProxyHandler(cfg *config.Config) *ProxyHandler {
	target, err := url.Parse(cfg.MediaServer.Host)
	if err != nil {
		log.Fatalf("MediaServer.Host 解析失败: %v", err)
	}

	rp := httputil.NewSingleHostReverseProxy(target)

	// 自定义 Director：修正 Host 头，确保 Emby 能正确响应
	originalDirector := rp.Director
	rp.Director = func(req *http.Request) {
		originalDirector(req)
		req.Host = target.Host
	}

	// 错误处理
	rp.ErrorHandler = func(w http.ResponseWriter, r *http.Request, err error) {
		log.Printf("反代透传失败: %s %s -> %s, err=%v", r.Method, r.URL.Path, target.String(), err)
		w.WriteHeader(http.StatusBadGateway)
		w.Write([]byte(`{"error":"proxy request failed"}`))
	}

	return &ProxyHandler{
		cfg:          cfg,
		reverseProxy: rp,
		targetURL:    target,
	}
}

// HandleProxy 透传请求到 Emby/Jellyfin
func (h *ProxyHandler) HandleProxy(c *gin.Context) {
	h.reverseProxy.ServeHTTP(c.Writer, c.Request)
}

