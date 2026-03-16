// internal/config/timezone.go
// Go 侧时间管理 — 对齐 Python TimeManager

package config

import (
	"os"
	"time"
)

const TimeFormat = "2006-01-02 15:04:05"

var tz *time.Location

// InitTimezone 初始化时区
func InitTimezone(tzStr string) {
	if tzStr == "" {
		tzStr = os.Getenv("MISAKAMF_TZ")
		if tzStr == "" {
			tzStr = "Asia/Shanghai"
		}
	}

	loc, err := time.LoadLocation(tzStr)
	if err != nil {
		// 回退到 UTC+8
		tz = time.FixedZone("CST", 8*3600)
	} else {
		tz = loc
	}
}

// Now 获取当前时间字符串（TEXT 格式，无时区）
func Now() string {
	if tz == nil {
		InitTimezone("")
	}
	return time.Now().In(tz).Format(TimeFormat)
}

// NowTime 获取当前时间
func NowTime() time.Time {
	if tz == nil {
		InitTimezone("")
	}
	return time.Now().In(tz)
}

// GetTimezone 获取当前时区
func GetTimezone() *time.Location {
	if tz == nil {
		InitTimezone("")
	}
	return tz
}

