// internal/cache/manager.go
// 双层缓存管理器 — L1 内存 + L2 Redis

package cache

import (
	"context"
	"log"
	"time"

	"github.com/mediaflow/go-proxy/internal/config"
)

const (
	defaultMemTTL   = 5 * time.Minute
	defaultRedisTTL = 15 * time.Minute
)

// Manager 双层缓存管理器
type Manager struct {
	Memory *MemoryCache
	Redis  *RedisCache
}

// NewManager 创建缓存管理器
func NewManager(redisCfg config.RedisConfig, memSize int) *Manager {
	if memSize <= 0 {
		memSize = 10000
	}
	m := &Manager{
		Memory: NewMemoryCache(memSize, defaultMemTTL),
		Redis:  NewRedisCache(redisCfg, defaultRedisTTL),
	}

	// 测试 Redis 连接
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if err := m.Redis.Ping(ctx); err != nil {
		log.Printf("Redis 连接失败（将仅使用内存缓存）: %v", err)
	} else {
		log.Println("Redis 连接成功")
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
		// 回填 L1
		m.Memory.Set(key, val)
		return val, true
	}
	return "", false
}

// Set 写入双层缓存
func (m *Manager) Set(key, value string) {
	m.Memory.Set(key, value)
	ctx := context.Background()
	_ = m.Redis.Set(ctx, key, value)
}

// Delete 删除双层缓存
func (m *Manager) Delete(key string) {
	m.Memory.Delete(key)
	ctx := context.Background()
	_ = m.Redis.Delete(ctx, key)
}

// Close 关闭缓存
func (m *Manager) Close() {
	if m.Redis != nil {
		_ = m.Redis.Close()
	}
}

