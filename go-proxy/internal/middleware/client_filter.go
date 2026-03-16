// internal/middleware/client_filter.go
// 客户端 UA 过滤中间件

package middleware

import (
	"net/http"
	"strings"

	"github.com/gin-gonic/gin"
)

// ClientFilter UA 黑名单过滤
func ClientFilter(blacklist []string) gin.HandlerFunc {
	return func(c *gin.Context) {
		if len(blacklist) == 0 {
			c.Next()
			return
		}

		ua := strings.ToLower(c.GetHeader("User-Agent"))
		for _, keyword := range blacklist {
			if strings.Contains(ua, strings.ToLower(keyword)) {
				c.AbortWithStatusJSON(http.StatusForbidden, gin.H{
					"error": "client blocked",
				})
				return
			}
		}
		c.Next()
	}
}

