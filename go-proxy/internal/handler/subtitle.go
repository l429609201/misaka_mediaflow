// internal/handler/subtitle.go
// 字幕处理器
//
// 职责：
//   1. 接到 /emby/videos/:itemId/Subtitles/:subId/:rest 的 GET 请求
//   2. 判断是 ASS/SSA/SRT 字幕请求 → 调 Python /internal/subtitle/proxy 处理
//      Python 端决定：转发给 fontInAss（已启用）或返回 action=passthrough
//   3. 若 passthrough 或非文本字幕格式 → 直接透传到 Emby
//   4. 302 成功后的字幕触发：在 redirect.go 里负责，此处只做字幕路由

package handler

import (
	"encoding/json"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"

	"github.com/gin-gonic/gin"

	"github.com/mediaflow/go-proxy/internal/config"
	"github.com/mediaflow/go-proxy/internal/logger"
	"github.com/mediaflow/go-proxy/internal/service"
)

// subtitleHTTPClient 字幕请求专用 HTTP 客户端（含超时，避免播放器卡住）
var subtitleHTTPClient = &http.Client{Timeout: 30 * time.Second}

// 需要子集化处理的字幕扩展名（ASS/SSA/SRT）
var subsettableExts = map[string]bool{
	"ass": true,
	"ssa": true,
	"srt": true,
	"vtt": false, // 明确列出但不处理，避免歧义
}

// SubtitleHandler 字幕路由处理器
type SubtitleHandler struct {
	cfg      *config.Config
	pyClient *service.PythonClient
	proxyH   *ProxyHandler
	pyBase   string // Python 内部 API 基础地址
}

// NewSubtitleHandler 创建字幕处理器
func NewSubtitleHandler(cfg *config.Config, pc *service.PythonClient) *SubtitleHandler {
	return &SubtitleHandler{
		cfg:      cfg,
		pyClient: pc,
		proxyH:   NewProxyHandler(cfg, pc),
		pyBase:   pc.BaseURL(),
	}
}

// HandleSubtitle 处理字幕请求
// 路由：/emby/videos/:itemId/Subtitles/:subId/*rest
// 示例：/emby/videos/123/Subtitles/1/0/Stream.ass  → rest="/0/Stream.ass"
func (h *SubtitleHandler) HandleSubtitle(c *gin.Context) {
	itemId := c.Param("itemId")
	subId := c.Param("subId")
	rest := strings.TrimPrefix(c.Param("rest"), "/") // Gin 通配符带前导 /，去掉

	// 判断是否需要子集化的字幕格式
	needsProcessing := false
	restLower := strings.ToLower(rest)
	for ext := range subsettableExts {
		if strings.HasSuffix(restLower, "."+ext) || strings.Contains(restLower, "stream."+ext) {
			needsProcessing = true
			break
		}
	}

	logger.Infof("[subtitle] 字幕请求命中路由: itemId=%s subId=%s rest=%s needsProcessing=%v",
		itemId, subId, rest, needsProcessing)

	if !needsProcessing {
		// 非 ASS/SSA/SRT 格式（如 VTT）→ 直接透传 Emby
		logger.Infof("[subtitle] 非文字字幕格式，直接透传: itemId=%s rest=%s", itemId, rest)
		h.proxyH.HandleProxy(c)
		return
	}

	// ── 构造原始请求路径，转发给 Python 字幕服务判断 ──────────────────────────
	originalPath := c.Request.URL.Path
	queryString := c.Request.URL.RawQuery

	pyBase := strings.TrimRight(h.pyBase, "/")
	pyURL := pyBase + "/internal/subtitle/proxy"

	params := url.Values{}
	params.Set("path", originalPath)
	params.Set("item_id", itemId)
	params.Set("sub_id", subId)
	if queryString != "" {
		params.Set("qs", queryString)
	}
	pyURL += "?" + params.Encode()

	logger.Infof("[subtitle] 调用 Python 字幕服务: url=%s", pyURL)

	req, err := http.NewRequestWithContext(c.Request.Context(), http.MethodGet, pyURL, nil)
	if err != nil {
		logger.Infof("[subtitle] 构造 Python 请求失败: %v，降级透传", err)
		h.proxyH.HandleProxy(c)
		return
	}
	// 透传 Authorization / Cookie 头给 Python（Python 再透传给 fontInAss）
	for _, hdr := range []string{"Authorization", "Cookie", "X-Emby-Token", "X-Emby-Authorization"} {
		if v := c.GetHeader(hdr); v != "" {
			req.Header.Set(hdr, v)
		}
	}

	resp, err := subtitleHTTPClient.Do(req)
	if err != nil {
		logger.Infof("[subtitle] Python 字幕服务请求失败: %v，降级透传", err)
		h.proxyH.HandleProxy(c)
		return
	}
	defer resp.Body.Close()

	bodyBytes, readErr := io.ReadAll(resp.Body)
	if readErr != nil {
		logger.Infof("[subtitle] 读取 Python 响应失败: %v，降级透传", readErr)
		h.proxyH.HandleProxy(c)
		return
	}

	// ── 判断 Python 响应类型 ──────────────────────────────────────────────────
	// 先尝试 JSON 解析，判断是否是 {action: passthrough} 指令
	ct := resp.Header.Get("Content-Type")
	logger.Infof("[subtitle] Python 响应: status=%d Content-Type=%s size=%d bytes itemId=%s",
		resp.StatusCode, ct, len(bodyBytes), itemId)

	if strings.Contains(ct, "application/json") {
		// Python 明确返回 JSON → 解析 action 字段
		var pyResp struct {
			Action string `json:"action"`
		}
		if err2 := json.Unmarshal(bodyBytes, &pyResp); err2 == nil && pyResp.Action == "passthrough" {
			logger.Infof("[subtitle] Python 指示透传 Emby: itemId=%s", itemId)
			h.proxyH.HandleProxy(c)
			return
		}
		// JSON 但不是 passthrough 指令 → 异常，降级透传
		logger.Infof("[subtitle] Python 返回未知 JSON，降级透传: itemId=%s body=%s", itemId, string(bodyBytes[:min(len(bodyBytes), 200)]))
		h.proxyH.HandleProxy(c)
		return
	}

	if resp.StatusCode != http.StatusOK {
		// 非 200 且非 JSON → 异常，降级透传
		logger.Infof("[subtitle] Python 返回异常 status=%d，降级透传: itemId=%s", resp.StatusCode, itemId)
		h.proxyH.HandleProxy(c)
		return
	}

	// status=200 且非 JSON → 字幕内容，直接返回给播放器（子集化已在 Python 端完成）
	logger.Infof("[subtitle] 返回子集化字幕: itemId=%s subId=%s size=%d bytes", itemId, subId, len(bodyBytes))
	for k, vals := range resp.Header {
		kl := strings.ToLower(k)
		if kl == "content-type" || kl == "content-disposition" {
			for _, v := range vals {
				c.Header(k, v)
			}
		}
	}
	c.Header("X-Subtitle-Source", resp.Header.Get("X-Subtitle-Source"))
	c.Header("Cache-Control", "no-cache")
	c.Status(resp.StatusCode)
	c.Writer.Write(bodyBytes) //nolint:errcheck
}

// min 辅助函数（Go 1.21 之前无内置 min）
func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}

