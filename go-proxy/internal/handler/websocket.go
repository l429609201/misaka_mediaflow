// internal/handler/websocket.go
// WebSocket 透传 — 参考 embyreverseproxy

package handler

import (
	"net/http"
	"net/url"
	"strings"

	"github.com/gin-gonic/gin"
	"github.com/gorilla/websocket"

	"github.com/mediaflow/go-proxy/internal/config"
	"github.com/mediaflow/go-proxy/internal/logger"
)

var upgrader = websocket.Upgrader{
	CheckOrigin: func(r *http.Request) bool { return true },
}

// WSHandler WebSocket 透传处理器
type WSHandler struct {
	cfg *config.Config
}

// NewWSHandler 创建 WS 处理器
func NewWSHandler(cfg *config.Config) *WSHandler {
	return &WSHandler{cfg: cfg}
}

// HandleWS WebSocket 透传
func (h *WSHandler) HandleWS(c *gin.Context) {
	// 连接客户端
	clientConn, err := upgrader.Upgrade(c.Writer, c.Request, nil)
	if err != nil {
		logger.Infof("WS 升级失败: %v", err)
		return
	}
	defer clientConn.Close()

	// 构建目标 URL
	targetHost := strings.TrimPrefix(h.cfg.MediaServer.Host, "http://")
	targetHost = strings.TrimPrefix(targetHost, "https://")
	targetURL := url.URL{
		Scheme:   "ws",
		Host:     targetHost,
		Path:     c.Request.URL.Path,
		RawQuery: c.Request.URL.RawQuery,
	}

	// 连接目标
	serverConn, _, err := websocket.DefaultDialer.Dial(targetURL.String(), nil)
	if err != nil {
		logger.Infof("WS 目标连接失败: %v", err)
		return
	}
	defer serverConn.Close()

	// 双向透传
	done := make(chan struct{})

	go func() {
		defer close(done)
		for {
			msgType, msg, err := serverConn.ReadMessage()
			if err != nil {
				return
			}
			if err := clientConn.WriteMessage(msgType, msg); err != nil {
				return
			}
		}
	}()

	for {
		msgType, msg, err := clientConn.ReadMessage()
		if err != nil {
			return
		}
		if err := serverConn.WriteMessage(msgType, msg); err != nil {
			return
		}
	}
}

