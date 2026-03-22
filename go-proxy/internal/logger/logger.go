// internal/logger/logger.go
// 统一日志模块 — 支持 INFO/DEBUG 级别，所有日志带 [GO-PROXY] 前缀

package logger

import (
	"fmt"
	"log"
	"strings"
	"sync"
)

const (
	LevelDebug = iota
	LevelInfo
)

var (
	level     = LevelInfo
	once      sync.Once
	stdLogger *log.Logger
)

func init() {
	stdLogger = log.Default()
	// 去掉 Go 默认的日期/时间前缀，避免与外层日志系统（Python）产生双重时间戳
	stdLogger.SetFlags(0)
}

// SetLevel 设置日志级别: "debug" 或 "info"
func SetLevel(l string) {
	switch strings.ToLower(l) {
	case "debug":
		level = LevelDebug
	default:
		level = LevelInfo
	}
}

// Infof INFO 级别日志（始终输出）
func Infof(format string, args ...interface{}) {
	stdLogger.Printf("[GO-PROXY] "+format, args...)
}

// Debugf DEBUG 级别日志（仅 debug 模式输出）
func Debugf(format string, args ...interface{}) {
	if level <= LevelDebug {
		stdLogger.Printf("[GO-PROXY][DEBUG] "+format, args...)
	}
}

// Info 无格式 INFO 日志
func Info(msg string) {
	stdLogger.Printf("[GO-PROXY] %s", msg)
}

// Debug 无格式 DEBUG 日志
func Debug(msg string) {
	if level <= LevelDebug {
		stdLogger.Printf("[GO-PROXY][DEBUG] %s", msg)
	}
}

// Errorf 错误日志（始终输出）
func Errorf(format string, args ...interface{}) {
	stdLogger.Printf("[GO-PROXY][ERROR] "+format, args...)
}

// IsDebug 是否为 debug 级别
func IsDebug() bool {
	return level <= LevelDebug
}

// Sprintf 格式化字符串（便捷方法）
func Sprintf(format string, args ...interface{}) string {
	return fmt.Sprintf(format, args...)
}

