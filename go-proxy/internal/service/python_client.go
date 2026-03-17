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

// ResolveLink 通过 item_id 解析直链（旧接口，兼容保留）
func (pc *PythonClient) ResolveLink(itemID string, storageID int, apiKey string) (*ResolveResult, error) {
	reqURL := fmt.Sprintf("%s/internal/resolve-link?item_id=%s&storage_id=%d&api_key=%s",
		pc.baseURL, url.QueryEscape(itemID), storageID, url.QueryEscape(apiKey))
	return pc.doGet(reqURL)
}

// ResolveByPickcode 通过 pickcode 调用统一解析接口
func (pc *PythonClient) ResolveByPickcode(pickcode string) (*ResolveResult, error) {
	reqURL := fmt.Sprintf("%s/internal/redirect_url/resolve?pickcode=%s",
		pc.baseURL, url.QueryEscape(pickcode))
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


