// cmd/proxy/main.go
// Misaka MediaFlow Go 反代服务入口

package main

import (
	"flag"
	"fmt"
	"log"
	"os"
	"os/signal"
	"syscall"

	"github.com/mediaflow/go-proxy/internal/cache"
	"github.com/mediaflow/go-proxy/internal/config"
	"github.com/mediaflow/go-proxy/internal/router"
)

// 版本号 — 通过 ldflags 注入: go build -ldflags "-X main.Version=1.0.0"
var Version = "dev"

func main() {
	// 解析命令行参数
	port := flag.Int("port", 0, "监听端口 (覆盖配置文件)")
	embyHost := flag.String("emby-host", "", "Emby/Jellyfin 地址 (如 http://192.168.1.100:8096)")
	embyAPIKey := flag.String("emby-apikey", "", "Emby/Jellyfin API Key")
	flag.Parse()

	log.Printf("Misaka MediaFlow Go Proxy %s 启动中...\n", Version)

	// 1. 加载配置 (YAML + 环境变量)
	cfg, err := config.Load()
	if err != nil {
		log.Fatalf("配置加载失败: %v", err)
	}

	// 命令行参数优先级最高，覆盖配置
	if *port > 0 {
		cfg.Server.GoPort = *port
	}
	if *embyHost != "" {
		cfg.MediaServer.Host = *embyHost
	}
	if *embyAPIKey != "" {
		cfg.MediaServer.APIKey = *embyAPIKey
	}

	// 2. 初始化时区
	config.InitTimezone(cfg.Timezone)
	log.Printf("时区: %s", cfg.Timezone)
	log.Printf("Emby 后端: %s", cfg.MediaServer.Host)

	// 3. 初始化缓存（TTL 来自配置 proxy.cache_ttl）
	cacheManager := cache.NewManager(cfg.Redis, cfg.Proxy.CacheTTL, cfg.Proxy.MemCacheSize)
	defer cacheManager.Close()

	// 4. 启动 HTTP 服务
	r := router.Setup(cfg, cacheManager)

	addr := fmt.Sprintf("%s:%d", cfg.Server.Host, cfg.Server.GoPort)
	log.Printf("Go 反代监听: %s", addr)

	go func() {
		if err := r.Run(addr); err != nil {
			log.Fatalf("HTTP 服务启动失败: %v", err)
		}
	}()

	// 5. 优雅关闭
	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	<-quit
	log.Println("Go 反代已停止")
}

