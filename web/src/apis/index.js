// src/apis/index.js
// API 方法集中导出（对齐 misaka 项目 apis/index.js 模式）

import api from './fetch'

// ==================== Auth ====================
export const authApi = {
  login: (username, password) => api.post('/auth/login', { username, password }),
  verify: () => api.get('/auth/verify'),
  changePassword: (old_password, new_password) =>
    api.post('/auth/change-password', { old_password, new_password }),
  me: () => api.get('/auth/me'),
  getApiToken: () => api.get('/auth/api-token'),
}

// ==================== System ====================
export const systemApi = {
  health: () => api.get('/system/health'),
  getConfig: () => api.get('/system/config'),
  setConfig: (payload) => api.post('/system/config', payload),
  getDashboard: () => api.get('/system/dashboard'),
  getLogs: (params) => api.get('/system/logs', { params }),
  getProxyConfig: () => api.get('/system/proxy-config'),
  updateProxyConfig: (payload) => api.post('/system/proxy-config', payload),
  getIpWhitelist: () => api.get('/system/ip-whitelist'),
  updateIpWhitelist: (items) => api.post('/system/ip-whitelist', { items }),
  // 媒体库
  getMediaServer: () => api.get('/system/media-server'),
  updateMediaServer: (payload) => api.post('/system/media-server', payload),
  testMediaServer: (payload) => api.post('/system/media-server/test', payload),
  getMediaServerUsers: (payload) => api.post('/system/media-server/users', payload),
  getMediaLibraries: () => api.get('/system/media-server/libraries'),
  getSelectedLibraries: () => api.get('/system/media-server/selected-libraries'),
  saveSelectedLibraries: (library_ids) => api.post('/system/media-server/selected-libraries', { library_ids }),
  // Go 反代进程
  getGoProxyStatus: () => api.get('/system/go-proxy/status'),
  startGoProxy: () => api.post('/system/go-proxy/start'),
  stopGoProxy: () => api.post('/system/go-proxy/stop'),
  getGoProxyTraffic: () => api.get('/system/go-proxy/traffic'),
  // 日志（对齐弹幕库）
  getMemoryLogs: () => api.get('/system/logs/memory'),
  getLogFiles: () => api.get('/system/logs/files'),
  getLogFileContent: (filename, tail = 500) =>
    api.get(`/system/logs/files/${encodeURIComponent(filename)}`, { params: { tail } }),
}

// ==================== Storage ====================
export const storageApi = {
  meta: () => api.get('/storage/meta'),
  list: (params) => api.get('/storage', { params }),
  create: (payload) => api.post('/storage', payload),
  update: (id, payload) => api.put(`/storage/${id}`, payload),
  remove: (id) => api.delete(`/storage/${id}`),
  test: (id) => api.post(`/storage/${id}/test`),
  space: (id) => api.get(`/storage/${id}/space`),
  browseTree: (id, path = '/') => api.get(`/storage/${id}/tree`, { params: { path } }),
}

// ==================== Path Mapping ====================
export const mappingApi = {
  list: (params) => api.get('/storage/mappings', { params }),
  create: (payload) => api.post('/storage/mappings', payload),
  update: (id, payload) => api.put(`/storage/mappings/${id}`, payload),
  toggle: (id) => api.patch(`/storage/mappings/${id}/toggle`),
  remove: (id) => api.delete(`/storage/mappings/${id}`),
}

// ==================== STRM ====================
export const strmApi = {
  listTasks: (params) => api.get('/strm/tasks', { params }),
  createTask: (task_type) => api.post('/strm/tasks', null, { params: { task_type } }),
  getTask: (id) => api.get(`/strm/tasks/${id}`),
  listFiles: (params) => api.get('/strm/files', { params }),
}

// ==================== 115 ====================
export const p115Api = {
  status: () => api.get('/p115/status'),
  getAccount: () => api.get('/p115/account'),
  setCookie: (cookie) => api.post('/p115/auth/cookie', { cookie }),
  getQrcodeApps: () => api.get('/p115/auth/qrcode/apps'),
  qrcodeStart: (app = 'web') => api.post('/p115/auth/qrcode/start', { app }),
  qrcodePoll: (payload) => api.post('/p115/auth/qrcode/poll', payload),
  browseFiles: (params) => api.get('/p115/files', { params }),
  browseDirTree: (cid = '0') => api.get('/p115/dir-tree', { params: { cid } }),
  syncDir: (payload) => api.post('/p115/sync', payload),
  getDownloadUrl: (pick_code) => api.get('/p115/download-url', { params: { pick_code } }),
  organize: (file_ids) => api.post('/p115/organize', { file_ids }),
  // 路径映射
  getPathMapping: () => api.get('/p115/path-mapping'),
  savePathMapping: (payload) => api.post('/p115/path-mapping', payload),
  // 高级设置
  getSettings: () => api.get('/p115/settings'),
  saveSettings: (payload) => api.post('/p115/settings', payload),
}

