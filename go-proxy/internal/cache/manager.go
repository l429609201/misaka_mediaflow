// internal/cache/manager.go
// 双层缓存管理器 — L1 内存 + L2 Redis
// 115 直链缓存核心：利用 Python 返回的 expires_in 设置精确 TTL

package cache

import (
	"context"
	"log"
	"time"

	"github.com/mediaflow/go-proxy/internal/config"
)

// Manager 双层缓存管理器
type Manager struct {
	Memory     *MemoryCache
	Redis      *RedisCache
	defaultTTL time.Duration // 来自配置的默认 TTL
}

// NewManager 创建缓存管理器
func NewManager(redisCfg config.RedisConfig, cacheTTL int, memSize int) *Manager {
	if memSize <= 0 {
		memSize = 10000
	}
	if cacheTTL <= 0 {
		cacheTTL = 900 // 默认 15 分钟
	}

	ttl := time.Duration(cacheTTL) * time.Second

	m := &Manager{
		Memory:     NewMemoryCache(memSize, ttl),
		Redis:      NewRedisCache(redisCfg, ttl),
		defaultTTL: ttl,
	}

	// 测试 Redis 连接
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if err := m.Redis.Ping(ctx); err != nil {
		log.Printf("Redis 连接失败（将仅使用内存缓存）: %v", err)
	} else {
		log.Printf("Redis 连接成功，缓存 TTL=%v", ttl)
	}

	return m
}

// Get 双层查找: L1 → L2
func (m *Manager) Get(key string) (string, bool) {
	// L1
	if val, ok := m.Memory.Get(key); ok {
		return val, true
	}
	// L2
	ctx := context.Background()
	if val, ok := m.Redis.Get(ctx, key); ok {
		// 回填 L1（用较短 TTL 避免过期链接留在内存）
		m.Memory.Set(key, val)
		return val, true
	}
	return "", false
}

// Set 使用默认 TTL 写入双层缓存
func (m *Manager) Set(key, value string) {
	m.SetWithTTL(key, value, m.defaultTTL)
}

// SetWithTTL 使用自定义 TTL 写入双层缓存
func (m *Manager) SetWithTTL(key, value string, ttl time.Duration) {
	m.Memory.Set(key, value, ttl)
	ctx := context.Background()
	_ = m.Redis.Set(ctx, key, value, ttl)
}

// SetWithExpiry 根据直链有效期（秒）设置缓存，预留 60 秒安全余量
// 如果 expiresIn <= 0，使用默认 TTL
func (m *Manager) SetWithExpiry(key, value string, expiresIn int) time.Duration {
	var ttl time.Duration

	if expiresIn > 60 {
		// 直链有效期减去 60 秒安全余量，避免拿到即将过期的链接
		ttl = time.Duration(expiresIn-60) * time.Second
		// 不超过默认 TTL
		if ttl > m.defaultTTL {
			ttl = m.defaultTTL
		}
	} else {
		ttl = m.defaultTTL
	}

	m.SetWithTTL(key, value, ttl)
	return ttl
}

// Delete 删除双层缓存
func (m *Manager) Delete(key string) {
	m.Memory.Delete(key)
	ctx := context.Background()
	_ = m.Redis.Delete(ctx, key)
}

// Stats 缓存统计
func (m *Manager) Stats() map[string]interface{} {
	return map[string]interface{}{
		"memory_size": m.Memory.Size(),
		"default_ttl": m.defaultTTL.String(),
	}
}

// Close 关闭缓存
func (m *Manager) Close() {
	if m.Redis != nil {
		_ = m.Redis.Close()
	}
}

