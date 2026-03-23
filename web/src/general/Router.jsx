// src/general/Router.jsx
// Router config

import { createBrowserRouter, redirect } from 'react-router-dom'
import { RoutePaths } from './RoutePaths'
import { NotFound } from './NotFound'
import { Layout } from './Layout'
import { LayoutLogin } from './LayoutLogin'

import Home from '@/pages/home/index.jsx'
import Login from '@/pages/login/index.jsx'
import Storage from '@/pages/storage/index.jsx'
import Strm from '@/pages/strm/index.jsx'
import Drive115 from '@/pages/drive115/index.jsx'
import Classify from '@/pages/classify/index.jsx'
import { RealtimeSubtitle } from '@/pages/realtime-subtitle/index.jsx'
import P115 from '@/pages/media-proxy/index.jsx'
import SearchSource from '@/pages/search-source/index.jsx'
import Tasks from '@/pages/logs/index.jsx'
import Setting from '@/pages/setting/index.jsx'

// Auth guard — 调 /auth/verify 验证凭证（JWT / IP白名单自动登录）
const authLoader = async () => {
  try {
    const token = localStorage.getItem('token')
    const headers = {}
    if (token) {
      headers['Authorization'] = `Bearer ${token}`
    }
    const resp = await fetch('/api/v1/auth/verify', { headers })
    if (resp.ok) {
      const data = await resp.json()
      if (data.valid) {
        // 白名单自动登录：后端签发了 JWT，前端存储
        if (data.token) {
          localStorage.setItem('token', data.token)
        }
        if (data.username) {
          localStorage.setItem('username', data.username)
        }
        return null
      }
    }
  } catch {
    // 网络错误，fallback
  }

  // verify 失败，清除旧凭证，跳转登录
  localStorage.removeItem('token')
  localStorage.removeItem('username')
  return redirect('/login')
}

export const router = createBrowserRouter(
  [
    {
      // 登录页（无需认证，独立布局）
      path: RoutePaths.LOGIN,
      element: <LayoutLogin />,
      children: [
        { index: true, element: <Login /> },
      ],
    },
    {
      // 管理页面（需要认证，带侧边栏）
      path: '/',
      element: <Layout />,
      loader: authLoader,
      children: [
        { index: true,                          element: <Home /> },
        { path: RoutePaths.STORAGE.slice(1),     element: <Storage /> },
        { path: RoutePaths.STRM.slice(1),              element: <Strm /> },
        { path: RoutePaths.DRIVE115.slice(1),          element: <Drive115 /> },
        { path: RoutePaths.CLASSIFY.slice(1),          element: <Classify /> },
        { path: 'p115', loader: () => redirect(RoutePaths.MEDIA_PROXY) },
        { path: RoutePaths.MEDIA_PROXY.slice(1),       element: <P115 /> },
        { path: RoutePaths.REALTIME_SUBTITLE.slice(1), element: <RealtimeSubtitle /> },
        { path: RoutePaths.SEARCH_SOURCE.slice(1),     element: <SearchSource /> },
        { path: RoutePaths.TASKS.slice(1),             element: <Tasks /> },
        { path: RoutePaths.SETTING.slice(1),           element: <Setting /> },
      ],
    },
    {
      // 404
      path: '*',
      element: <NotFound />,
    },
  ],
  {
    basename: '/web',
  },
)

