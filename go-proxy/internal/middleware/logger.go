// internal/middleware/logger.go
// 请求日志中间件 + 流量统计

package middleware

import (
	"log"
	"time"

	"github.com/gin-gonic/gin"

	"github.com/mediaflow/go-proxy/internal/config"
	"github.com/mediaflow/go-proxy/internal/traffic"
)

// RequestLogger 请求日志 + 流量统计
func RequestLogger() gin.HandlerFunc {
	return func(c *gin.Context) {
		start := time.Now()
		path := c.Request.URL.Path

		c.Next()

		latency := time.Since(start)
		status := c.Writer.Status()

		// 上行 = 请求体大小（Content-Length 或实际读取）
		reqSize := c.Request.ContentLength
		if reqSize < 0 {
			reqSize = 0
		}
		// 下行 = 响应体大小
		respSize := int64(c.Writer.Size())
		if respSize < 0 {
			respSize = 0
		}

		traffic.Counter.AddUpload(reqSize)
		traffic.Counter.AddDownload(respSize)

		log.Printf("[%s] %d %s %s %v ↑%d ↓%d",
			config.Now(), status, c.Request.Method, path, latency, reqSize, respSize)
	}
}

