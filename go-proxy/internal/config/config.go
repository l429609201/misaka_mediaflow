// internal/config/config.go
// 配置加载 — 读取 config.yaml 或环境变量

package config

import (
	"os"
	"strconv"

	"gopkg.in/yaml.v3"
)

// Config 全局配置
type Config struct {
	Server      ServerConfig      `yaml:"server"`
	Timezone    string            `yaml:"timezone"`
	Redis       RedisConfig       `yaml:"redis"`
	Proxy       ProxyConfig       `yaml:"proxy"`
	MediaServer MediaServerConfig `yaml:"media_server"`
	Security    SecurityConfig    `yaml:"security"`
}

type ServerConfig struct {
	Host   string `yaml:"host"`
	GoPort int    `yaml:"go_port"`
	PyPort int    `yaml:"py_port"`
}

type RedisConfig struct {
	Host      string `yaml:"host"`
	Port      int    `yaml:"port"`
	DB        int    `yaml:"db"`
	Password  string `yaml:"password"`
	KeyPrefix string `yaml:"key_prefix"`
}

type ProxyConfig struct {
	CacheTTL       int `yaml:"cache_ttl"`
	MemCacheSize   int `yaml:"mem_cache_size"`
	ConnectTimeout int `yaml:"connect_timeout"`
	WSPingInterval int `yaml:"ws_ping_interval"`
}

type MediaServerConfig struct {
	Type   string `yaml:"type"`
	Host   string `yaml:"host"`
	APIKey string `yaml:"api_key"`
}

type SecurityConfig struct {
	APIToken            string   `yaml:"api_token"`
	ClientFilterEnabled bool     `yaml:"client_filter_enabled"`
	UABlacklist         []string `yaml:"ua_blacklist"`
}

// Load 加载配置
func Load() (*Config, error) {
	cfg := defaultConfig()

	// 从 YAML 文件读取
	configPath := envStr("MISAKAMF_CONFIG_PATH", "/data/config/config.yaml")
	data, err := os.ReadFile(configPath)
	if err == nil {
		if err := yaml.Unmarshal(data, cfg); err != nil {
			return nil, err
		}
	}

	// 环境变量覆盖
	applyEnvOverrides(cfg)

	return cfg, nil
}

func defaultConfig() *Config {
	return &Config{
		Server: ServerConfig{
			Host:   "0.0.0.0",
			GoPort: 9906,
			PyPort: 7789,
		},
		Timezone: "Asia/Shanghai",
		Redis: RedisConfig{
			Host:      "127.0.0.1",
			Port:      6379,
			DB:        0,
			KeyPrefix: "mmf:",
		},
		Proxy: ProxyConfig{
			CacheTTL:       900,
			MemCacheSize:   10000,
			ConnectTimeout: 10,
			WSPingInterval: 30,
		},
		MediaServer: MediaServerConfig{
			Type: "emby",
			Host: "http://127.0.0.1:8096",
		},
	}
}

func applyEnvOverrides(cfg *Config) {
	// 环境变量使用 MISAKAMF_ 前缀 + 双下划线分隔层级
	// 例如: MISAKAMF_SERVER__GO_PORT=9906
	if v := os.Getenv("MISAKAMF_TZ"); v != "" {
		cfg.Timezone = v
	}
	if v := os.Getenv("MISAKAMF_TIMEZONE"); v != "" {
		cfg.Timezone = v
	}
	// server
	if v := os.Getenv("MISAKAMF_SERVER__HOST"); v != "" {
		cfg.Server.Host = v
	}
	if v := os.Getenv("MISAKAMF_SERVER__GO_PORT"); v != "" {
		if port, err := strconv.Atoi(v); err == nil {
			cfg.Server.GoPort = port
		}
	}
	if v := os.Getenv("MISAKAMF_SERVER__PORT"); v != "" {
		if port, err := strconv.Atoi(v); err == nil {
			cfg.Server.PyPort = port
		}
	}
	// redis
	if v := os.Getenv("MISAKAMF_REDIS__HOST"); v != "" {
		cfg.Redis.Host = v
	}
	if v := os.Getenv("MISAKAMF_REDIS__PORT"); v != "" {
		if port, err := strconv.Atoi(v); err == nil {
			cfg.Redis.Port = port
		}
	}
	if v := os.Getenv("MISAKAMF_REDIS__PASSWORD"); v != "" {
		cfg.Redis.Password = v
	}
	if v := os.Getenv("MISAKAMF_REDIS__DB"); v != "" {
		if db, err := strconv.Atoi(v); err == nil {
			cfg.Redis.DB = db
		}
	}
	// media_server
	if v := os.Getenv("MISAKAMF_MEDIA_SERVER__TYPE"); v != "" {
		cfg.MediaServer.Type = v
	}
	if v := os.Getenv("MISAKAMF_MEDIA_SERVER__HOST"); v != "" {
		cfg.MediaServer.Host = v
	}
	if v := os.Getenv("MISAKAMF_MEDIA_SERVER__API_KEY"); v != "" {
		cfg.MediaServer.APIKey = v
	}
	// security
	if v := os.Getenv("MISAKAMF_SECURITY__API_TOKEN"); v != "" {
		cfg.Security.APIToken = v
	}
	// proxy
	if v := os.Getenv("MISAKAMF_PROXY__CACHE_TTL"); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			cfg.Proxy.CacheTTL = n
		}
	}
	if v := os.Getenv("MISAKAMF_PROXY__MEM_CACHE_SIZE"); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			cfg.Proxy.MemCacheSize = n
		}
	}
}

func envStr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

