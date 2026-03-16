// internal/traffic/counter.go
// 全局流量统计 — 原子操作，协程安全

package traffic

import (
	"sync/atomic"
	"time"
)

// Counter 全局流量计数器
var Counter = &Stats{}

// Stats 流量统计
type Stats struct {
	totalUpload   atomic.Int64
	totalDownload atomic.Int64
	// 实时流量：最近一个采样周期的字节数
	lastUpload   atomic.Int64
	lastDownload atomic.Int64
	// 采样窗口内的临时计数
	windowUpload   atomic.Int64
	windowDownload atomic.Int64
}

func init() {
	// 每秒采样一次，把窗口值挪到 last（供前端读取）
	go func() {
		ticker := time.NewTicker(1 * time.Second)
		defer ticker.Stop()
		for range ticker.C {
			Counter.lastUpload.Store(Counter.windowUpload.Swap(0))
			Counter.lastDownload.Store(Counter.windowDownload.Swap(0))
		}
	}()
}

// AddUpload 累加上行字节
func (s *Stats) AddUpload(n int64) {
	s.totalUpload.Add(n)
	s.windowUpload.Add(n)
}

// AddDownload 累加下行字节
func (s *Stats) AddDownload(n int64) {
	s.totalDownload.Add(n)
	s.windowDownload.Add(n)
}

// Snapshot 获取当前快照
func (s *Stats) Snapshot() map[string]int64 {
	return map[string]int64{
		"total_upload":     s.totalUpload.Load(),
		"total_download":   s.totalDownload.Load(),
		"current_upload":   s.lastUpload.Load(),
		"current_download": s.lastDownload.Load(),
	}
}

