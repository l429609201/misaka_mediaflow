// internal/cache/memory.go
// L1 内存缓存 — LRU + TTL

package cache

import (
	"sync"
	"time"
)

type cacheEntry struct {
	value     string
	expiresAt time.Time
}

// MemoryCache L1 内存缓存
type MemoryCache struct {
	mu       sync.RWMutex
	items    map[string]cacheEntry
	maxSize  int
	defaultTTL time.Duration
}

// NewMemoryCache 创建内存缓存
func NewMemoryCache(maxSize int, ttl time.Duration) *MemoryCache {
	mc := &MemoryCache{
		items:      make(map[string]cacheEntry, maxSize),
		maxSize:    maxSize,
		defaultTTL: ttl,
	}
	// 定期清理过期条目
	go mc.cleanup()
	return mc
}

// Get 获取缓存
func (mc *MemoryCache) Get(key string) (string, bool) {
	mc.mu.RLock()
	defer mc.mu.RUnlock()

	entry, ok := mc.items[key]
	if !ok {
		return "", false
	}
	if time.Now().After(entry.expiresAt) {
		return "", false
	}
	return entry.value, true
}

// Set 设置缓存
func (mc *MemoryCache) Set(key, value string, ttl ...time.Duration) {
	mc.mu.Lock()
	defer mc.mu.Unlock()

	duration := mc.defaultTTL
	if len(ttl) > 0 {
		duration = ttl[0]
	}

	// 简单淘汰：超过 maxSize 时清空
	if len(mc.items) >= mc.maxSize {
		mc.evict()
	}

	mc.items[key] = cacheEntry{
		value:     value,
		expiresAt: time.Now().Add(duration),
	}
}

// Delete 删除缓存
func (mc *MemoryCache) Delete(key string) {
	mc.mu.Lock()
	defer mc.mu.Unlock()
	delete(mc.items, key)
}

// Clear 清空缓存
func (mc *MemoryCache) Clear() {
	mc.mu.Lock()
	defer mc.mu.Unlock()
	mc.items = make(map[string]cacheEntry, mc.maxSize)
}

// Size 缓存条目数
func (mc *MemoryCache) Size() int {
	mc.mu.RLock()
	defer mc.mu.RUnlock()
	return len(mc.items)
}

// evict 淘汰过期条目 (需要在已持有锁时调用)
func (mc *MemoryCache) evict() {
	now := time.Now()
	for key, entry := range mc.items {
		if now.After(entry.expiresAt) {
			delete(mc.items, key)
		}
	}
}

// cleanup 定期清理
func (mc *MemoryCache) cleanup() {
	ticker := time.NewTicker(time.Minute)
	for range ticker.C {
		mc.mu.Lock()
		mc.evict()
		mc.mu.Unlock()
	}
}

