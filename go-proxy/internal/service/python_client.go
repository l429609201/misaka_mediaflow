// internal/service/python_client.go
// Python 内部 API 客户端 — Go 缓存未命中时调用

package service

import (
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/url"
	"time"

	"github.com/mediaflow/go-proxy/internal/config"
)

// ResolveResult Python resolve 返回结果（通用）
type ResolveResult struct {
	URL       string `json:"url"`
	ExpiresIn int    `json:"expires_in"`
	Source    string `json:"source"`
	Error     string `json:"error"`
}

// PythonClient Python 内部 API 客户端
type PythonClient struct {
	baseURL string
	client  *http.Client
}

// NewPythonClient 创建 Python 客户端
func NewPythonClient(cfg *config.Config) *PythonClient {
	return &PythonClient{
		baseURL: fmt.Sprintf("http://127.0.0.1:%d", cfg.Server.PyPort),
		client: &http.Client{
			Timeout: 30 * time.Second,
		},
	}
}

// BaseURL 返回 Python 内部 API 基础地址（供其他 handler 拼接路径使用）
func (pc *PythonClient) BaseURL() string {
	return pc.baseURL
}

// ResolveLink 通过 item_id 解析直链
func (pc *PythonClient) ResolveLink(itemID string, storageID int, apiKey string, userID string, userAgent string) (*ResolveResult, error) {
	q := url.Values{}
	q.Set("item_id", itemID)
	q.Set("storage_id", fmt.Sprintf("%d", storageID))
	if apiKey != "" {
		q.Set("api_key", apiKey)
	}
	if userID != "" {
		q.Set("user_id", userID)
	}
	if userAgent != "" {
		q.Set("user_agent", userAgent)
	}
	reqURL := fmt.Sprintf("%s/internal/resolve-link?%s", pc.baseURL, q.Encode())
	return pc.doGet(reqURL)
}

// ResolveByPickcode 通过 pickcode 调用统一解析接口
func (pc *PythonClient) ResolveByPickcode(pickcode string, userAgent string) (*ResolveResult, error) {
	q := url.Values{}
	q.Set("pickcode", pickcode)
	if userAgent != "" {
		q.Set("user_agent", userAgent)
	}
	reqURL := fmt.Sprintf("%s/internal/redirect_url/resolve?%s", pc.baseURL, q.Encode())
	return pc.doGet(reqURL)
}

// ResolveByPath 通过路径调用统一解析接口
func (pc *PythonClient) ResolveByPath(filePath string, storageID int) (*ResolveResult, error) {
	reqURL := fmt.Sprintf("%s/internal/redirect_url/resolve?path=%s&storage_id=%d",
		pc.baseURL, url.QueryEscape(filePath), storageID)
	return pc.doGet(reqURL)
}

// ResolveByURL 通过 HTTP URL 调用统一解析接口
func (pc *PythonClient) ResolveByURL(rawURL string) (*ResolveResult, error) {
	reqURL := fmt.Sprintf("%s/internal/redirect_url/resolve?url=%s",
		pc.baseURL, url.QueryEscape(rawURL))
	return pc.doGet(reqURL)
}

// ResolveAny 通用统一解析入口（透传所有参数）
func (pc *PythonClient) ResolveAny(params map[string]string) (*ResolveResult, error) {
	q := url.Values{}
	for k, v := range params {
		if v != "" {
			q.Set(k, v)
		}
	}
	reqURL := fmt.Sprintf("%s/internal/redirect_url/resolve?%s", pc.baseURL, q.Encode())
	return pc.doGet(reqURL)
}

// doGet 内部通用 GET 请求
func (pc *PythonClient) doGet(reqURL string) (*ResolveResult, error) {
	resp, err := pc.client.Get(reqURL)
	if err != nil {
		log.Printf("[go] Python API 请求失败: %v url=%s", err, reqURL)
		return nil, err
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, err
	}

	var result ResolveResult
	if err := json.Unmarshal(body, &result); err != nil {
		return nil, fmt.Errorf("解析响应失败: %w body=%s", err, string(body))
	}
	return &result, nil
}

// CheckStrmResult Python check-strm 返回结果
type CheckStrmResult struct {
	IsStrm   bool   `json:"is_strm"`
	ItemType string `json:"item_type"` // Movie / Episode / Series / 空(配置不完整时)
}

// CheckStrm 调用 Python 内部接口，判断 itemId 对应的 Emby 条目是否为 STRM 文件。
// Python 端会自动使用数据库中保存的 user_id / host / api_key 拼接正确查询路径。
// apiKey 为 Go 从 PlaybackInfo 请求里提取的 token，Python 优先用此值，兜底用数据库值。
// 返回 (isStrm, itemType, error)，itemType 如 "Movie" / "Episode"
func (pc *PythonClient) CheckStrm(itemID, apiKey string) (bool, string, error) {
	q := url.Values{}
	q.Set("item_id", itemID)
	if apiKey != "" {
		q.Set("api_key", apiKey)
	}
	reqURL := fmt.Sprintf("%s/internal/emby/check-strm?%s", pc.baseURL, q.Encode())

	resp, err := pc.client.Get(reqURL)
	if err != nil {
		log.Printf("[go] CheckStrm 请求失败: %v url=%s", err, reqURL)
		return false, "", err
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return false, "", err
	}

	var result CheckStrmResult
	if err := json.Unmarshal(body, &result); err != nil {
		return false, "", fmt.Errorf("CheckStrm 解析响应失败: %w body=%s", err, string(body))
	}
	return result.IsStrm, result.ItemType, nil
}

// GetAPIInterval 从 Python 获取 115 的 API 请求间隔（秒）
func (pc *PythonClient) GetAPIInterval() float64 {
	reqURL := fmt.Sprintf("%s/internal/p115/api-interval", pc.baseURL)
	resp, err := pc.client.Get(reqURL)
	if err != nil {
		return 1.0 // 默认 1 秒
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return 1.0
	}

	var result struct {
		APIInterval float64 `json:"api_interval"`
	}
	if err := json.Unmarshal(body, &result); err != nil || result.APIInterval <= 0 {
		return 1.0
	}
	return result.APIInterval
}


