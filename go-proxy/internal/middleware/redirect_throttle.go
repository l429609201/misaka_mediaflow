// internal/middleware/redirect_throttle.go
// 302 请求节流器 — 防止 Web UI 播放时短时间内对 115 CDN 发起过多并发请求
//
// 问题: 浏览器 <video> 元素不缓存 302 目标 URL，每次 Range 请求都重走
//       Go Proxy → 302 → 115 CDN，短时间内大量并发导致 115 CDN 限流/拒绝
//
// 方案: 基于 itemID 的令牌桶限流，超出速率的请求排队等待
//       - 令牌桶按 itemID 隔离（不同视频互不影响）
//       - 超过 maxWait 的请求返回 429

package middleware

import (
	"log"
	"net/http"
	"sync"
	"time"

	"github.com/gin-gonic/gin"
)

// ── 配置常量（后续可改为从 config 读取）─────────────────────────────
const (
	// 每秒最多允许的 302 请求数（每个 itemID 独立计数）
	defaultMaxRate = 3
	// 令牌桶容量（允许的突发请求数）
	defaultBurst = 3
	// 超出速率时最大等待时间
	defaultMaxWait = 8 * time.Second
	// 桶的过期清理间隔（长时间不用的桶自动回收）
	bucketExpiry = 5 * time.Minute
	// 清理定时器间隔
	cleanupInterval = 2 * time.Minute
)

// tokenBucket 单个 itemID 的令牌桶
type tokenBucket struct {
	tokens     float64
	maxTokens  float64
	refillRate float64 // 每秒补充的令牌数
	lastRefill time.Time
	lastAccess time.Time
	mu         sync.Mutex
}

func newTokenBucket(maxTokens float64, refillRate float64) *tokenBucket {
	now := time.Now()
	return &tokenBucket{
		tokens:     maxTokens, // 初始满桶
		maxTokens:  maxTokens,
		refillRate: refillRate,
		lastRefill: now,
		lastAccess: now,
	}
}

// tryAcquire 尝试获取一个令牌，返回需要等待的时间
// 如果立即可用返回 0；如果需要等待返回等待时长；如果超过 maxWait 返回 -1
func (b *tokenBucket) tryAcquire(maxWait time.Duration) time.Duration {
	b.mu.Lock()
	defer b.mu.Unlock()

	now := time.Now()
	b.lastAccess = now

	// 补充令牌
	elapsed := now.Sub(b.lastRefill).Seconds()
	b.tokens += elapsed * b.refillRate
	if b.tokens > b.maxTokens {
		b.tokens = b.maxTokens
	}
	b.lastRefill = now

	// 有令牌，立即消耗
	if b.tokens >= 1.0 {
		b.tokens -= 1.0
		return 0
	}

	// 没有令牌，计算等待时间
	deficit := 1.0 - b.tokens
	waitTime := time.Duration(deficit / b.refillRate * float64(time.Second))

	if waitTime > maxWait {
		return -1 // 超过最大等待时间
	}

	// 预扣令牌（允许等待后获取）
	b.tokens -= 1.0
	return waitTime
}

// RedirectThrottler 302 请求节流器
type RedirectThrottler struct {
	buckets sync.Map // map[string]*tokenBucket
	maxRate float64
	burst   float64
	maxWait time.Duration
}

// NewRedirectThrottler 创建节流器
func NewRedirectThrottler() *RedirectThrottler {
	t := &RedirectThrottler{
		maxRate: defaultMaxRate,
		burst:   defaultBurst,
		maxWait: defaultMaxWait,
	}

	// 启动后台清理 goroutine
	go t.cleanupLoop()

	return t
}

// getBucket 获取或创建某个 key 的令牌桶
func (t *RedirectThrottler) getBucket(key string) *tokenBucket {
	if v, ok := t.buckets.Load(key); ok {
		return v.(*tokenBucket)
	}
	bucket := newTokenBucket(t.burst, t.maxRate)
	actual, _ := t.buckets.LoadOrStore(key, bucket)
	return actual.(*tokenBucket)
}

// cleanupLoop 定期清理过期的令牌桶
func (t *RedirectThrottler) cleanupLoop() {
	ticker := time.NewTicker(cleanupInterval)
	defer ticker.Stop()

	for range ticker.C {
		now := time.Now()
		count := 0
		t.buckets.Range(func(key, value interface{}) bool {
			bucket := value.(*tokenBucket)
			bucket.mu.Lock()
			idle := now.Sub(bucket.lastAccess)
			bucket.mu.Unlock()

			if idle > bucketExpiry {
				t.buckets.Delete(key)
				count++
			}
			return true
		})
		if count > 0 {
			log.Printf("[throttle] 清理 %d 个过期令牌桶", count)
		}
	}
}

// Throttle 返回 Gin 中间件函数
// keyExtractor 用于从请求中提取限流 key（通常是 itemID）
func (t *RedirectThrottler) Throttle(keyExtractor func(*gin.Context) string) gin.HandlerFunc {
	return func(c *gin.Context) {
		key := keyExtractor(c)
		if key == "" {
			c.Next()
			return
		}

		bucket := t.getBucket(key)
		waitTime := bucket.tryAcquire(t.maxWait)

		if waitTime < 0 {
			// 超过最大等待时间，返回 429
			log.Printf("[throttle] 请求被限流: key=%s, 超过最大等待 %v", key, t.maxWait)
			c.Header("Retry-After", "2")
			c.JSON(http.StatusTooManyRequests, gin.H{
				"error": "too many requests, please slow down",
			})
			c.Abort()
			return
		}

		if waitTime > 0 {
			log.Printf("[throttle] 请求排队: key=%s, 等待 %v", key, waitTime)
			time.Sleep(waitTime)
		}

		c.Next()
	}
}

