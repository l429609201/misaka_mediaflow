// internal/middleware/auth.go
// API Key 认证中间件

package middleware

import (
	"net/http"
	"strings"

	"github.com/gin-gonic/gin"
)

// EmbyAuth Emby API Key 认证（从 query 或 header 提取）
func EmbyAuth() gin.HandlerFunc {
	return func(c *gin.Context) {
		// 从 query 参数提取
		apiKey := c.Query("api_key")
		if apiKey == "" {
			apiKey = c.Query("X-Emby-Token")
		}
		// 从 header 提取
		if apiKey == "" {
			apiKey = c.GetHeader("X-Emby-Token")
		}
		if apiKey == "" {
			auth := c.GetHeader("Authorization")
			if strings.Contains(auth, "Token=") {
				parts := strings.SplitN(auth, "Token=", 2)
				if len(parts) == 2 {
					apiKey = strings.Trim(parts[1], "\"")
				}
			}
		}

		if apiKey == "" {
			c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"error": "missing api key"})
			return
		}

		c.Set("api_key", apiKey)
		c.Next()
	}
}

