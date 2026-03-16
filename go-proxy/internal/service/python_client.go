// internal/service/python_client.go
// Python 内部 API 客户端 — Go 缓存未命中时调用

package service

import (
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"time"

	"github.com/mediaflow/go-proxy/internal/config"
)

// ResolveResult Python resolve-link 返回结果
type ResolveResult struct {
	URL       string `json:"url"`
	ExpiresIn int    `json:"expires_in"`
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

// ResolveLink 调用 Python 解析直链
func (pc *PythonClient) ResolveLink(itemID string, storageID int, apiKey string) (*ResolveResult, error) {
	url := fmt.Sprintf("%s/internal/resolve-link?item_id=%s&storage_id=%d&api_key=%s",
		pc.baseURL, itemID, storageID, apiKey)

	resp, err := pc.client.Get(url)
	if err != nil {
		log.Printf("调用 Python resolve-link 失败: %v", err)
		return nil, err
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, err
	}

	var result ResolveResult
	if err := json.Unmarshal(body, &result); err != nil {
		return nil, err
	}

	return &result, nil
}

