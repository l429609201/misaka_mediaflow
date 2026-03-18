// internal/config/config.go
// Go 反代配置 — 只保留 Go 自身需要的配置项
// 缓存相关配置已移至 Python 端（MISAKAMF_CACHE__ 环境变量由 Python 读取）

package config

import (
	"os"
	"strconv"

	"gopkg.in/yaml.v3"
)

// Config 全局配置（Go 反代只需要转发相关配置）
type Config struct {
	Server      ServerConfig      `yaml:"server"`
	Timezone    string            `yaml:"timezone"`
	LogLevel    string            `yaml:"log_level"` // debug / info（默认 info）
	Proxy       ProxyConfig       `yaml:"proxy"`
	MediaServer MediaServerConfig `yaml:"media_server"`
	Security    SecurityConfig    `yaml:"security"`
}

type ServerConfig struct {
	Host   string `yaml:"host"`
	GoPort int    `yaml:"go_port"`
	PyPort int    `yaml:"py_port"`
}

type ProxyConfig struct {
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

	configPath := envStr("MISAKAMF_CONFIG_PATH", "/data/config/config.yaml")
	data, err := os.ReadFile(configPath)
	if err == nil {
		if err := yaml.Unmarshal(data, cfg); err != nil {
			return nil, err
		}
	}

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
		LogLevel: "info",
		Proxy: ProxyConfig{
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
	if v := os.Getenv("TZ"); v != "" {
		cfg.Timezone = v
	}
	if v := os.Getenv("MISAKAMF_TZ"); v != "" {
		cfg.Timezone = v
	}
	if v := os.Getenv("MISAKAMF_TIMEZONE"); v != "" {
		cfg.Timezone = v
	}
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
	if v := os.Getenv("MISAKAMF_MEDIA_SERVER__TYPE"); v != "" {
		cfg.MediaServer.Type = v
	}
	if v := os.Getenv("MISAKAMF_MEDIA_SERVER__HOST"); v != "" {
		cfg.MediaServer.Host = v
	}
	if v := os.Getenv("MISAKAMF_MEDIA_SERVER__API_KEY"); v != "" {
		cfg.MediaServer.APIKey = v
	}
	if v := os.Getenv("MISAKAMF_SECURITY__API_TOKEN"); v != "" {
		cfg.Security.APIToken = v
	}
	if v := os.Getenv("MISAKAMF_LOG_LEVEL"); v != "" {
		cfg.LogLevel = v
	}
}

func envStr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

