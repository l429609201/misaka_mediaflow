// internal/handler/proxy.go
// 透传处理器 — 将请求直接代理到 Emby/Jellyfin（基于 httputil.ReverseProxy）

package handler

import (
	"bytes"
	"compress/gzip"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httputil"
	"net/url"
	"regexp"
	"strconv"
	"strings"
	"time"

	"github.com/gin-gonic/gin"

	"github.com/mediaflow/go-proxy/internal/config"
	"github.com/mediaflow/go-proxy/internal/logger"
	"github.com/mediaflow/go-proxy/internal/service"
)

// ── basehtmlplayer.js patch ──
// 参考 embyExternalUrl emby.js modifyBaseHtmlPlayer 函数：
//   body.replace(/mediaSource\.IsRemote\s*&&\s*"DirectPlay"\s*===\s*playMethod\s*\?\s*null\s*:\s*"anonymous"/g, 'null')
//
// 原始代码: getCrossOriginValue=function(mediaSource,playMethod){return mediaSource.IsRemote&&"DirectPlay"===playMethod?null:"anonymous"}
// 压缩后:   getCrossOriginValue=function(n,t){return n.IsRemote&&"DirectPlay"===t?null:"anonymous"}
// 匹配整个三元表达式，替换为 null → 使 getCrossOriginValue() 始终返回 null
var crossOriginValueRe = regexp.MustCompile(`\w+\.IsRemote\s*&&\s*"DirectPlay"\s*===\s*\w+\s*\?\s*null\s*:\s*"anonymous"`)

// ── plugin.js patch ──
// 参考 embyExternalUrl issue #236 的 sed 命令：
//   sed -i 's/&&(elem\.crossOrigin=initialSubtitleStream)//g' plugin.js
//
// 原始代码: &&(elem.crossOrigin=initialSubtitleStream)
// 压缩后:   &&(t.crossOrigin=n) 或其他变量名
// 移除这段代码 → <video> 元素不再被设置 crossOrigin 属性
var pluginCrossOriginRe = regexp.MustCompile(`&&\(\w+\.crossOrigin=\w+\)`)

// ── crossOrigin 运行时拦截脚本 ──
// 注入到 Emby HTML 页面的 <head> 中，从根源上阻止任何 JS 设置 crossOrigin 属性
// 三重防御：
//   1. Object.defineProperty 覆写 HTMLMediaElement.prototype.crossOrigin setter → JS 赋值无效
//   2. MutationObserver 监控 DOM → setAttribute("crossorigin",...) 也被拦截
//   3. 拦截 createElement，新建的 video/audio 自动清除 crossorigin
//
// 效果: <video> 永远不会有 crossorigin 属性 → 浏览器以 no-cors 模式请求
//       → 302 到 115 CDN 后不做 CORS 检查 → 播放正常
const crossOriginInterceptScript = `<script>
(function(){
  // [MisakaF] crossOrigin 拦截器 — 确保 302 直链播放不受 CORS 限制
  // 第1层: 覆写 crossOrigin 属性的 setter，使任何 JS 赋值都被忽略
  try {
    Object.defineProperty(HTMLMediaElement.prototype,'crossOrigin',{
      get:function(){return null},
      set:function(){},
      configurable:true
    });
  } catch(e){}

  // 第2层: MutationObserver 监控 DOM 变化，移除通过 setAttribute 设置的 crossorigin
  try {
    var ob=new MutationObserver(function(ms){
      ms.forEach(function(m){
        if(m.type==='attributes'&&m.attributeName==='crossorigin'){
          m.target.removeAttribute('crossorigin');
        }
        if(m.type==='childList'){
          m.addedNodes.forEach(function(n){
            if(n.nodeType===1&&(n.tagName==='VIDEO'||n.tagName==='AUDIO')){
              n.removeAttribute('crossorigin');
            }
          });
        }
      });
    });
    if(document.documentElement){
      ob.observe(document.documentElement,{attributes:true,attributeFilter:['crossorigin'],childList:true,subtree:true});
    } else {
      document.addEventListener('DOMContentLoaded',function(){
        ob.observe(document.documentElement,{attributes:true,attributeFilter:['crossorigin'],childList:true,subtree:true});
      });
    }
  } catch(e){}
})();
</script>`

// ProxyHandler 透传处理器
type ProxyHandler struct {
	cfg          *config.Config
	reverseProxy *httputil.ReverseProxy
	targetURL    *url.URL
	pyClient     *service.PythonClient
}

// NewProxyHandler 创建透传处理器
func NewProxyHandler(cfg *config.Config, pyClient *service.PythonClient) *ProxyHandler {
	target, err := url.Parse(cfg.MediaServer.Host)
	if err != nil {
		logger.Errorf("MediaServer.Host 解析失败: %v", err)
		panic("MediaServer.Host 解析失败")
	}

	rp := httputil.NewSingleHostReverseProxy(target)

	// 自定义 Director：修正 Host 头，确保 Emby 能正确响应
	originalDirector := rp.Director
	rp.Director = func(req *http.Request) {
		// ⭐ 保存原始认证头（originalDirector 可能丢失这些头）
		origEmbyToken := req.Header.Get("X-Emby-Token")
		origEmbyAuth := req.Header.Get("X-Emby-Authorization")
		origAuth := req.Header.Get("Authorization")

		originalDirector(req)
		req.Host = target.Host

		// ⭐ 恢复认证头（ModifyResponse 需要从 resp.Request 中提取 apiKey）
		if origEmbyToken != "" {
			req.Header.Set("X-Emby-Token", origEmbyToken)
		}
		if origEmbyAuth != "" {
			req.Header.Set("X-Emby-Authorization", origEmbyAuth)
		}
		if origAuth != "" {
			req.Header.Set("Authorization", origAuth)
		}

		// ⭐ 对需要 patch 的响应，去掉 Accept-Encoding
		// 让 Emby 返回未压缩的响应，确保 ModifyResponse 能读取和修改
		// 否则浏览器发 Accept-Encoding: br,gzip → Emby 返回 Brotli → Go 无法解压
		//
		// 判断条件：路径匹配（不依赖 Accept 头，因为 Accept 头可能不存在或不准确）
		needsPatch := isHtmlPlayerJS(req.URL.Path) ||
			strings.HasSuffix(req.URL.Path, "/PlaybackInfo") ||
			req.URL.Path == "/" || req.URL.Path == "" ||
			strings.HasPrefix(req.URL.Path, "/web/") || req.URL.Path == "/web" ||
			strings.HasSuffix(req.URL.Path, ".html") || strings.HasSuffix(req.URL.Path, ".htm")
		if needsPatch {
			req.Header.Del("Accept-Encoding")
		}
	}

	// 错误处理
	rp.ErrorHandler = func(w http.ResponseWriter, r *http.Request, err error) {
		logger.Infof("反代透传失败: %s %s -> %s, err=%v", r.Method, r.URL.Path, target.String(), err)
		w.WriteHeader(http.StatusBadGateway)
		w.Write([]byte(`{"error":"proxy request failed"}`))
	}

	// ⭐ 修改响应（三层防御 + PlaybackInfo 强制 DirectPlay）：
	//   1. JS 源码 patch: 替换 basehtmlplayer.js / plugin.js 中的 crossOrigin 逻辑
	//   2. HTML 注入: 在页面 <head> 中注入运行时拦截脚本，从根源阻止 crossOrigin 被设置
	//   3. PlaybackInfo: 对 STRM 文件强制 DirectPlay，阻止 Emby 走 HLS 转码

	h := &ProxyHandler{
		cfg:          cfg,
		reverseProxy: rp,
		targetURL:    target,
		pyClient:     pyClient,
	}
	rp.ModifyResponse = h.modifyResponse

	return h
}

// modifyResponse 统一拦截 Emby 响应，根据路径分发到不同的 patch 逻辑
func (h *ProxyHandler) modifyResponse(resp *http.Response) error {
	path := resp.Request.URL.Path
	ct := resp.Header.Get("Content-Type")
	encoding := resp.Header.Get("Content-Encoding")

	// ⭐ 对所有 text/html 和 JS 请求打日志，方便排查
	if strings.Contains(ct, "text/html") || isHtmlPlayerJS(path) || strings.HasSuffix(path, "/PlaybackInfo") {
		logger.Infof("[ModifyResponse] path=%s status=%d Content-Type=%q Content-Encoding=%q", path, resp.StatusCode, ct, encoding)
	}

	// PlaybackInfo → 强制 DirectPlay（阻止 STRM 文件被转码）
	if strings.HasSuffix(path, "/PlaybackInfo") {
		return h.patchPlaybackInfo(resp)
	}

	// htmlvideoplayer JS → crossOrigin patch（第1层防御：源码级替换）
	if isHtmlPlayerJS(path) {
		logger.Infof("[ModifyResponse] ✅ 拦截 HtmlPlayerJS: %s", path)
		return h.patchHtmlPlayerJS(resp)
	}

	// HTML 页面 → 注入 crossOrigin 运行时拦截脚本（第2层防御：运行时兜底）
	if strings.Contains(ct, "text/html") && resp.StatusCode == http.StatusOK {
		logger.Infof("[ModifyResponse] ✅ 拦截 HTML 页面: %s", path)
		return h.patchHtmlPage(resp)
	}

	return nil
}

// isHtmlPageRequest 判断请求是否可能返回 HTML 页面（用于 Director 中提前去除 Accept-Encoding）
// Emby Web UI 的主要 HTML 入口：
//   - / (根路径)
//   - /web/ 或 /web/index.html
//   - 不含文件扩展名的路径（SPA 路由）
func isHtmlPageRequest(req *http.Request) bool {
	path := req.URL.Path
	accept := req.Header.Get("Accept")

	// 浏览器请求 HTML 页面时，Accept 头包含 text/html
	if !strings.Contains(accept, "text/html") {
		return false
	}

	// 根路径
	if path == "/" || path == "" {
		logger.Infof("[isHtmlPageRequest] ✅ 匹配根路径: path=%q", path)
		return true
	}

	// /web/ 相关路径
	if strings.HasPrefix(path, "/web/") || path == "/web" {
		logger.Infof("[isHtmlPageRequest] ✅ 匹配 /web/ 路径: path=%q", path)
		return true
	}

	// 排除明确的 API / 静态资源路径
	if strings.HasPrefix(path, "/emby/") || strings.HasPrefix(path, "/Items/") {
		return false
	}

	// 不含扩展名的路径（可能是 SPA 路由，Emby 会返回 HTML）
	lastSlash := strings.LastIndex(path, "/")
	lastPart := path
	if lastSlash >= 0 {
		lastPart = path[lastSlash:]
	}
	if !strings.Contains(lastPart, ".") {
		logger.Infof("[isHtmlPageRequest] ✅ 匹配无扩展名路径(SPA): path=%q", path)
		return true
	}

	// .html 文件
	if strings.HasSuffix(path, ".html") || strings.HasSuffix(path, ".htm") {
		logger.Infof("[isHtmlPageRequest] ✅ 匹配 .html 文件: path=%q", path)
		return true
	}

	return false
}

// patchHtmlPage 在 Emby HTML 页面中注入 crossOrigin 运行时拦截脚本。
// 这是第2层防御（兜底）：即使 JS 源码 patch（第1层）未匹配到，
// 运行时拦截也能确保 <video> 不被设置 crossorigin 属性。
//
// 工作原理：
//   - 在 </head> 前注入 <script>，比 Emby 自身 JS 更早执行
//   - 覆写 HTMLMediaElement.prototype.crossOrigin 的 setter → JS 赋值无效
//   - MutationObserver 监控 DOM → setAttribute 也被拦截
//   - 效果: <video> 永远不会有 crossorigin 属性
//   - 浏览器以 no-cors 模式请求 → 302 到 115 CDN 后不做 CORS 检查
func (h *ProxyHandler) patchHtmlPage(resp *http.Response) error {
	path := resp.Request.URL.Path
	encoding := resp.Header.Get("Content-Encoding")
	logger.Infof("[HTML注入] 开始处理: path=%s, Content-Encoding=%q, Status=%d", path, encoding, resp.StatusCode)

	// 如果是 Brotli 等不支持的编码，跳过（应该不会出现，因为 Director 已删 Accept-Encoding）
	if encoding != "" && !strings.Contains(encoding, "gzip") {
		logger.Infof("⚠️ [HTML注入] 不支持的编码 %q，跳过注入 (path=%s)", encoding, path)
		return nil
	}

	// 读取响应体（处理 gzip）
	isGzip := strings.Contains(encoding, "gzip")
	var bodyReader io.Reader = resp.Body
	if isGzip {
		gr, err := gzip.NewReader(resp.Body)
		if err != nil {
			logger.Infof("❌ [HTML注入] gzip 解压失败: %v (path=%s)", err, path)
			return nil
		}
		defer gr.Close()
		bodyReader = gr
	}

	body, err := io.ReadAll(bodyReader)
	resp.Body.Close()
	if err != nil {
		logger.Infof("❌ [HTML注入] 读取 body 失败: %v (path=%s)", err, path)
		return nil
	}

	html := string(body)
	logger.Infof("[HTML注入] body 读取成功: %d bytes, 包含</head>=%v (path=%s)",
		len(body), strings.Contains(html, "</head>"), path)

	// 避免重复注入（如果已经有我们的标识就跳过）
	if strings.Contains(html, "[MisakaF] crossOrigin") {
		logger.Infof("[HTML注入] 已有注入标识，跳过 (path=%s)", path)
		resp.Body = io.NopCloser(bytes.NewReader(body))
		return nil
	}

	// 在 </head> 前注入拦截脚本（尽早执行，在 Emby JS 之前）
	injected := false
	if idx := strings.Index(html, "</head>"); idx >= 0 {
		html = html[:idx] + crossOriginInterceptScript + html[idx:]
		injected = true
	} else if idx := strings.Index(html, "<head>"); idx >= 0 {
		// 备选：在 <head> 后注入
		insertAt := idx + len("<head>")
		html = html[:insertAt] + crossOriginInterceptScript + html[insertAt:]
		injected = true
	}

	if !injected {
		// 片段 HTML（如对话框、面板等）没有 <head> 标签是正常的，静默跳过
		resp.Body = io.NopCloser(bytes.NewReader(body))
		return nil
	}

	logger.Infof("✅ [HTML注入] 成功! path=%s, 原始=%d bytes, 注入后=%d bytes", path, len(body), len(html))

	// 写回响应
	newBody := []byte(html)
	resp.Body = io.NopCloser(bytes.NewReader(newBody))
	resp.ContentLength = int64(len(newBody))
	resp.Header.Set("Content-Length", strconv.Itoa(len(newBody)))
	resp.Header.Del("Content-Encoding")

	// 禁止浏览器缓存此 HTML（确保每次都拿到注入后的版本）
	resp.Header.Set("Cache-Control", "no-cache, no-store, must-revalidate")
	resp.Header.Set("Pragma", "no-cache")
	resp.Header.Set("Expires", "0")
	resp.Header.Del("ETag")
	resp.Header.Del("Last-Modified")

	return nil
}

// isHtmlPlayerJS 判断是否为 Emby htmlvideoplayer 的 JS 文件
// 需要 patch 的文件：
//   - plugin.js（旧版 Emby，路径含 htmlvideoplayer/plugin.js）
//   - basehtmlplayer.js（新版 Emby，路径含 htmlvideoplayer/basehtmlplayer.js）
func isHtmlPlayerJS(path string) bool {
	return strings.Contains(path, "htmlvideoplayer/plugin.js") ||
		strings.Contains(path, "htmlvideoplayer/basehtmlplayer.js")
}

// patchHtmlPlayerJS 统一拦截 Emby htmlvideoplayer 的 JS 响应，
// 去除 crossOrigin 设置。
//
// 解决两类 CORS 问题（115 CDN 不返回 Access-Control-Allow-Origin）：
//   - 旧版 Emby plugin.js: &&(elem.crossOrigin=xxx) 直接赋值
//   - 新版 Emby basehtmlplayer.js: getCrossOriginValue() 返回 "anonymous"
//
// 参考:
//   - https://github.com/bpking1/embyExternalUrl/issues/236
//   - https://github.com/chen3861229/embyExternalUrl/issues/64
func (h *ProxyHandler) patchHtmlPlayerJS(resp *http.Response) error {
	path := resp.Request.URL.Path

	if resp.StatusCode != http.StatusOK {
		return nil
	}

	// 判断是哪个文件
	isBasePlayer := strings.Contains(path, "basehtmlplayer.js")
	fileName := "plugin.js"
	if isBasePlayer {
		fileName = "basehtmlplayer.js"
	}

	encoding := resp.Header.Get("Content-Encoding")
	logger.Infof("%s 响应: status=%d, Content-Encoding=%q, Content-Length=%d",
		fileName, resp.StatusCode, encoding, resp.ContentLength)

	// 读取响应体（处理 gzip）
	isGzip := strings.Contains(encoding, "gzip")
	var bodyReader io.Reader = resp.Body
	if isGzip {
		gr, err := gzip.NewReader(resp.Body)
		if err != nil {
			logger.Infof("%s gzip 解压失败: %v", fileName, err)
			return nil
		}
		defer gr.Close()
		bodyReader = gr
	}

	body, err := io.ReadAll(bodyReader)
	resp.Body.Close()
	if err != nil {
		logger.Infof("%s 读取失败: %v", fileName, err)
		return nil
	}

	original := string(body)
	patched := original

	// ==================== crossOrigin patch ====================
	if isBasePlayer {
		// ── basehtmlplayer.js: 参考 embyExternalUrl modifyBaseHtmlPlayer ──
		// 精确正则匹配 getCrossOriginValue 中的三元表达式，替换为 null
		// 效果: getCrossOriginValue() 始终返回 null → <video> 不设置 crossorigin 属性
		matchCount := len(crossOriginValueRe.FindAllString(patched, -1))
		patched = crossOriginValueRe.ReplaceAllString(patched, `null`)
		if matchCount > 0 {
			logger.Infof("✅ %s: 精确匹配 %d 处 getCrossOriginValue 三元表达式 → null", fileName, matchCount)
		} else {
			// 正则没命中，可能 Emby 代码格式变了，用宽松匹配兜底
			hasCrossOriginValue := strings.Contains(original, "getCrossOriginValue")
			if hasCrossOriginValue {
				logger.Infof("⚠️ %s: getCrossOriginValue 函数存在但精确正则未命中，尝试宽松替换 \"anonymous\" → null", fileName)
				patched = strings.ReplaceAll(patched, `"anonymous"`, `null`)
				patched = strings.ReplaceAll(patched, `'anonymous'`, `null`)
			} else {
				logger.Infof("⚠️ %s: 未找到 getCrossOriginValue 函数 (大小=%d bytes)", fileName, len(body))
			}
		}
	} else {
		// ── plugin.js: 参考 embyExternalUrl issue #236 ──
		// sed -i 's/&&(elem\.crossOrigin=initialSubtitleStream)//g' plugin.js
		// 精确正则移除 &&(xxx.crossOrigin=yyy) 赋值语句
		// 效果: <video> 元素不再被赋值 crossOrigin 属性
		matchCount := len(pluginCrossOriginRe.FindAllString(patched, -1))
		patched = pluginCrossOriginRe.ReplaceAllString(patched, ``)
		if matchCount > 0 {
			logger.Infof("✅ %s: 移除 %d 处 &&(*.crossOrigin=*) 赋值（参考 issue #236）", fileName, matchCount)
		} else {
			// 兜底：如果精确正则未命中，尝试替换属性名
			hasCrossOrigin := strings.Contains(original, ".crossOrigin")
			if hasCrossOrigin {
				crossOriginCount := strings.Count(patched, ".crossOrigin")
				patched = strings.ReplaceAll(patched, ".crossOrigin", ".crossOriginDisabled")
				logger.Infof("⚠️ %s: &&(*.crossOrigin=*) 精确正则未命中，兜底替换 %d 处 .crossOrigin → .crossOriginDisabled", fileName, crossOriginCount)
			} else {
				logger.Infof("⚠️ %s: 未找到 crossOrigin 相关代码 (大小=%d bytes)", fileName, len(body))
			}
		}
	}

	if original != patched {
		logger.Infof("✅ %s crossOrigin patch 完成 (原始=%d bytes, patch后=%d bytes)", fileName, len(original), len(patched))
	}

	// ==================== 写回响应 ====================
	newBody := []byte(patched)
	resp.Body = io.NopCloser(bytes.NewReader(newBody))
	resp.ContentLength = int64(len(newBody))
	resp.Header.Set("Content-Length", strconv.Itoa(len(newBody)))
	resp.Header.Del("Content-Encoding")

	// 禁止浏览器缓存（确保每次都拿到 patch 后的版本）
	resp.Header.Set("Cache-Control", "no-cache, no-store, must-revalidate")
	resp.Header.Set("Pragma", "no-cache")
	resp.Header.Set("Expires", "0")
	resp.Header.Del("ETag")
	resp.Header.Del("Last-Modified")

	return nil
}

// HandleProxy 透传请求到 Emby/Jellyfin
func (h *ProxyHandler) HandleProxy(c *gin.Context) {
	h.reverseProxy.ServeHTTP(c.Writer, c.Request)
}

// extractAPIKey 从请求中提取 Emby/Jellyfin API Key（Token）
// 支持多种认证方式（按优先级）：
//  1. X-Emby-Token header（最常用）
//  2. X-Emby-Authorization header: MediaBrowser Client="...", Token="xxx"
//  3. Authorization header: Bearer xxx 或 MediaBrowser Token="xxx"
//  4. api_key query 参数
//  5. X-Emby-Token query 参数
func extractAPIKey(req *http.Request) string {
	// 1. X-Emby-Token header
	if token := req.Header.Get("X-Emby-Token"); token != "" {
		return token
	}

	// 2. X-Emby-Authorization header
	if auth := req.Header.Get("X-Emby-Authorization"); auth != "" {
		if token := extractTokenFromMediaBrowser(auth); token != "" {
			return token
		}
	}

	// 3. Authorization header
	if auth := req.Header.Get("Authorization"); auth != "" {
		if strings.HasPrefix(auth, "Bearer ") {
			return strings.TrimPrefix(auth, "Bearer ")
		}
		if token := extractTokenFromMediaBrowser(auth); token != "" {
			return token
		}
	}

	// 4. api_key query 参数
	if apiKey := req.URL.Query().Get("api_key"); apiKey != "" {
		return apiKey
	}

	// 5. X-Emby-Token query 参数
	if token := req.URL.Query().Get("X-Emby-Token"); token != "" {
		return token
	}

	return ""
}

// extractTokenFromMediaBrowser 从 MediaBrowser 格式的认证字符串中提取 Token
// 格式: MediaBrowser Client="...", Device="...", DeviceId="...", Version="...", Token="xxx"
func extractTokenFromMediaBrowser(auth string) string {
	idx := strings.Index(auth, `Token="`)
	if idx == -1 {
		return ""
	}
	tokenStart := idx + 7 // len(`Token="`)
	rest := auth[tokenStart:]
	tokenEnd := strings.Index(rest, `"`)
	if tokenEnd == -1 {
		return ""
	}
	return rest[:tokenEnd]
}

// itemIdFromPath 从 PlaybackInfo URL 路径中提取 itemId
// 路径格式: /emby/Items/44998/PlaybackInfo 或 /Items/44998/PlaybackInfo
// [^/]+ 兼容纯数字 ID 和 GUID 格式
var playbackInfoRe = regexp.MustCompile(`/Items/([^/]+)/PlaybackInfo`)

func itemIdFromPath(path string) string {
	m := playbackInfoRe.FindStringSubmatch(path)
	if len(m) >= 2 {
		return m[1]
	}
	return ""
}

// patchPlaybackInfo 拦截 PlaybackInfo API 响应，对 STRM 文件强制 DirectPlay。
// 参考 embyExternalUrl emby.js transferPlaybackInfo + modifyDirectPlaySupports
//
// 问题: Emby 对浏览器不支持的编码（如 HEVC/x265）返回 SupportsDirectPlay=false，
//
//	导致前端走 HLS 转码（/videos/:id/hls1/），302 重定向完全无法生效。
//
// 方案: 调用 Python 内部接口 /internal/emby/check-strm 判断是否为 STRM 文件，
//
//	Python 用数据库中保存的 user_id 拼接正确的 Emby 查询路径，
//	确认是 STRM 后强制 DirectPlay → 触发 302 → CDN 直链。
//	非 STRM 文件保持 Emby 原始行为。
func (h *ProxyHandler) patchPlaybackInfo(resp *http.Response) error {
	if resp.StatusCode != http.StatusOK {
		return nil
	}

	path := resp.Request.URL.Path
	itemID := itemIdFromPath(path)
	if itemID == "" {
		logger.Infof(" [PlaybackInfo] 无法从路径提取 itemId: path=%s", path)
		return nil
	}

	// 从原始请求中提取 API Key，透传给 Python 作为优先 token
	apiKey := extractAPIKey(resp.Request)
	logger.Infof("[PlaybackInfo] itemId=%s apiKey长度=%d", itemID, len(apiKey))

	// 调 Python 内部接口判断是否 STRM，Python 自己用保存的 user_id 拼路径
	isStrm, _, err := h.pyClient.CheckStrm(itemID, apiKey)
	if err != nil {
		logger.Infof(" [PlaybackInfo] CheckStrm 调用失败: %v，跳过 patch", err)
		return nil
	}
	if !isStrm {
		logger.Infof("[PlaybackInfo] itemId=%s 非 STRM 文件，保持原始行为", itemID)
		return nil
	}
	logger.Infof("[PlaybackInfo] itemId=%s 确认为 STRM 文件，开始强制 DirectPlay", itemID)


	// ---- 以下只对 STRM 文件执行 ----

	// 读取响应体（处理 gzip）
	encoding := resp.Header.Get("Content-Encoding")
	isGzip := strings.Contains(encoding, "gzip")
	var bodyReader io.Reader = resp.Body
	if isGzip {
		gr, err := gzip.NewReader(resp.Body)
		if err != nil {
			return nil
		}
		defer gr.Close()
		bodyReader = gr
	}

	body, err := io.ReadAll(bodyReader)
	resp.Body.Close()
	if err != nil {
		return nil
	}

	// 解析 JSON
	var data map[string]interface{}
	if err := json.Unmarshal(body, &data); err != nil {
		resp.Body = io.NopCloser(bytes.NewReader(body))
		return nil
	}

	// 获取 MediaSources 数组
	mediaSources, ok := data["MediaSources"].([]interface{})
	if !ok || len(mediaSources) == 0 {
		resp.Body = io.NopCloser(bytes.NewReader(body))
		return nil
	}

	// 已确认是 STRM 文件，对所有 MediaSource 强制 DirectPlay
	for _, ms := range mediaSources {
		source, ok := ms.(map[string]interface{})
		if !ok {
			continue
		}
		source["SupportsDirectPlay"] = true
		source["SupportsDirectStream"] = true
		source["SupportsTranscoding"] = false
		delete(source, "TranscodingUrl")
		delete(source, "TranscodingContainer")
		delete(source, "TranscodingSubProtocol")
	}

	// ── 记录并修正现有外挂字幕 DeliveryUrl ──────────────────────────────────
	// Emby 外挂字幕（IsExternal=true）的 DeliveryUrl 必须经过 Go 反代才能被子集化路由拦截。
	// DeliveryUrl 通常是相对路径（/emby/Videos/{id}/Subtitles/{subIdx}/0/Stream.ass），
	// 只要播放器通过 Go 反代访问，就会自然命中 subtitle 路由。
	// 这里打印日志以便诊断字幕 URL 是否正确。
	subtitleCount := 0
	for _, ms := range mediaSources {
		source, ok := ms.(map[string]interface{})
		if !ok {
			continue
		}
		streams, _ := source["MediaStreams"].([]interface{})
		for _, s := range streams {
			sm, ok2 := s.(map[string]interface{})
			if !ok2 {
				continue
			}
			if smType, _ := sm["Type"].(string); smType != "Subtitle" {
				continue
			}
			isExternal, _ := sm["IsExternal"].(bool)
			deliveryUrl, _ := sm["DeliveryUrl"].(string)
			codec, _ := sm["Codec"].(string)
			lang, _ := sm["Language"].(string)
			idx, _ := sm["Index"].(float64)
			if isExternal && deliveryUrl != "" {
				subtitleCount++
				logger.Infof("[PlaybackInfo] 外挂字幕 index=%.0f codec=%s lang=%s DeliveryUrl=%s",
					idx, codec, lang, deliveryUrl)
			}
		}
	}
	if subtitleCount == 0 {
		logger.Infof("[PlaybackInfo] itemId=%s 无外挂字幕轨道（外置字幕文件未扫描或视频无字幕）", itemID)
	}

	// ── 注入内封字幕到 MediaStreams ──────────────────────────────────────────
	// 查询 Python 是否有该 item 的内封字幕缓存，有则注入为外挂字幕条目，
	// 这样 Emby 界面字幕列表里就能显示并让用户选择
	subInfo := h.pyClient.GetEmbeddedSubInfo(itemID)
	if subInfo == nil {
		// 缓存未命中 → 同步预热：先拿 CDN 直链，再触发字幕提取等待最多 4s
		// 这样第一次播放就能把字幕注入进 PlaybackInfo，播放器当次就能看到字幕
		userAgent := resp.Request.Header.Get("User-Agent")
		userID := resp.Request.URL.Query().Get("UserId")
		if userID == "" {
			userID = resp.Request.URL.Query().Get("userId")
		}
		logger.Infof("[PlaybackInfo] itemId=%s 无字幕缓存，尝试同步预热内封字幕...", itemID)
		result, resolveErr := h.pyClient.ResolveLink(itemID, 0, apiKey, userID, userAgent)
		if resolveErr == nil && result != nil && result.URL != "" {
			subInfo = h.pyClient.WarmupEmbeddedSub(itemID, result.URL, userAgent, "", 4*time.Second)
			if subInfo != nil {
				logger.Infof("[PlaybackInfo] itemId=%s 预热成功，本次 PlaybackInfo 将注入字幕 lang=%s codec=%s",
					itemID, subInfo.Lang, subInfo.Codec)
			} else {
				logger.Infof("[PlaybackInfo] itemId=%s 预热超时或无内封字幕，跳过注入", itemID)
			}
		} else {
			logger.Infof("[PlaybackInfo] itemId=%s ResolveLink 失败(%v)，跳过字幕预热", itemID, resolveErr)
		}
	}

	if subInfo != nil {
		langDisplay := subInfo.Lang
		if langDisplay == "" {
			langDisplay = "und"
		}
		titleDisplay := subInfo.Title
		if titleDisplay == "" {
			titleDisplay = "内封字幕 (" + langDisplay + ")"
		}

		// 根据实际 codec 决定扩展名
		streamExt := "srt"
		embyCodec := "subrip"
		switch strings.ToLower(subInfo.Codec) {
		case "ass", "ssa":
			streamExt = "ass"
			embyCodec = "ass"
		}

		deliveryURL := fmt.Sprintf("/emby/Videos/%s/Subtitles/embedded/0/Stream.%s", itemID, streamExt)

		// 注入到每个 MediaSource 的 MediaStreams（与 Emby 外挂字幕字段完全对齐）
		// SubtitleLocationType="External" 是播放器判断"可请求外挂字幕"的关键字段
		for _, ms := range mediaSources {
			source, ok := ms.(map[string]interface{})
			if !ok {
				continue
			}
			existingStreams, _ := source["MediaStreams"].([]interface{})

			// 避免重复注入
			alreadyInjected := false
			for _, s := range existingStreams {
				sm, ok2 := s.(map[string]interface{})
				if !ok2 {
					continue
				}
				if url, _ := sm["DeliveryUrl"].(string); strings.Contains(url, "/Subtitles/embedded/") {
					alreadyInjected = true
					break
				}
			}
			if alreadyInjected {
				continue
			}

			// 计算 Index
			maxIdx := 0
			for _, s := range existingStreams {
				sm, ok2 := s.(map[string]interface{})
				if !ok2 {
					continue
				}
				if idx, ok3 := sm["Index"].(float64); ok3 && int(idx) > maxIdx {
					maxIdx = int(idx)
				}
			}

			injectedStream := map[string]interface{}{
				"Codec":                  embyCodec,
				"Type":                   "Subtitle",
				"IsExternal":             true,
				"IsTextSubtitleStream":   true,
				"IsForced":               false,
				"IsDefault":              false,
				"Language":               langDisplay,
				"DisplayTitle":           titleDisplay + " [内封]",
				"Title":                  titleDisplay,
				"DeliveryMethod":         "External",
				"DeliveryUrl":            deliveryURL,
				"IsExternalUrl":          false,
				"SupportsExternalStream": true,
				"SubtitleLocationType":   "External",
				"Index":                  maxIdx + 1,
			}
			source["MediaStreams"] = append(existingStreams, injectedStream)
			// 同时删除之前错误注入的 ExternalSubtitles（如果有）
			delete(source, "ExternalSubtitles")
			logger.Infof("[PlaybackInfo] 注入内封字幕: item_id=%s codec=%s ext=%s lang=%s DeliveryUrl=%s",
				itemID, embyCodec, streamExt, langDisplay, deliveryURL)
			break // 只注入第一个 MediaSource
		}
	}

	// 重新序列化
	newBody, err := json.Marshal(data)
	if err != nil {
		resp.Body = io.NopCloser(bytes.NewReader(body))
		return nil
	}

	logger.Infof(" PlaybackInfo: STRM(itemId=%s) 强制 DirectPlay (MediaSources=%d 个)", itemID, len(mediaSources))

	resp.Body = io.NopCloser(bytes.NewReader(newBody))
	resp.ContentLength = int64(len(newBody))
	resp.Header.Set("Content-Length", strconv.Itoa(len(newBody)))
	resp.Header.Del("Content-Encoding")

	return nil
}
