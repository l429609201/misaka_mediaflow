// internal/cache/redis.go
// L2 Redis 缓存

package cache

import (
	"context"
	"fmt"
	"time"

	"github.com/redis/go-redis/v9"

	"github.com/mediaflow/go-proxy/internal/config"
)

// RedisCache L2 Redis 缓存
type RedisCache struct {
	client    *redis.Client
	keyPrefix string
	defaultTTL time.Duration
}

// NewRedisCache 创建 Redis 缓存
func NewRedisCache(cfg config.RedisConfig, ttl time.Duration) *RedisCache {
	client := redis.NewClient(&redis.Options{
		Addr:     fmt.Sprintf("%s:%d", cfg.Host, cfg.Port),
		Password: cfg.Password,
		DB:       cfg.DB,
	})
	return &RedisCache{
		client:     client,
		keyPrefix:  cfg.KeyPrefix,
		defaultTTL: ttl,
	}
}

// Get 获取缓存
func (rc *RedisCache) Get(ctx context.Context, key string) (string, bool) {
	val, err := rc.client.Get(ctx, rc.keyPrefix+key).Result()
	if err != nil {
		return "", false
	}
	return val, true
}

// Set 设置缓存
func (rc *RedisCache) Set(ctx context.Context, key, value string, ttl ...time.Duration) error {
	duration := rc.defaultTTL
	if len(ttl) > 0 {
		duration = ttl[0]
	}
	return rc.client.Set(ctx, rc.keyPrefix+key, value, duration).Err()
}

// Delete 删除缓存
func (rc *RedisCache) Delete(ctx context.Context, key string) error {
	return rc.client.Del(ctx, rc.keyPrefix+key).Err()
}

// Close 关闭连接
func (rc *RedisCache) Close() error {
	return rc.client.Close()
}

// Ping 测试连接
func (rc *RedisCache) Ping(ctx context.Context) error {
	return rc.client.Ping(ctx).Err()
}

