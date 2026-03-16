// src/apis/fetch.js
// axios 实例封装（对齐 misaka 项目 apis/fetch.js 模式）

import axios from 'axios'

const api = axios.create({
  baseURL: '/api/v1',
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' },
})

// 请求拦截器 — 自动附加 Token
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// 响应拦截器 — 401 跳转登录（排除 verify 接口避免死循环）
api.interceptors.response.use(
  (response) => response,
  (error) => {
    const url = error.config?.url || ''
    if (error.response?.status === 401 && !url.includes('/auth/verify')) {
      localStorage.removeItem('token')
      localStorage.removeItem('username')
      window.location.href = '/web/login'
    }
    return Promise.reject(error)
  },
)

export default api

