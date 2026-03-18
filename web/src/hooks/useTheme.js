// src/hooks/useTheme.js
// 主题管理 hook — 暗色/亮色模式 + 主题色
import { useState, useEffect, useCallback } from 'react'

const THEME_KEY = 'theme_mode'
const COLOR_KEY = 'theme_color'

const PRESET_COLORS = [
  { key: 'blue',    color: '#1677ff', label: '蓝色' },
  { key: 'purple',  color: '#6366f1', label: '靛紫' },
  { key: 'pink',    color: '#ff6b9b', label: '粉色' },
  { key: 'green',   color: '#52c41a', label: '绿色' },
  { key: 'orange',  color: '#fa8c16', label: '橙色' },
  { key: 'red',     color: '#f5222d', label: '红色' },
  { key: 'cyan',    color: '#13c2c2', label: '青色' },
  { key: 'volcano', color: '#fa541c', label: '火山' },
]

export function useTheme() {
  const [mode, setMode] = useState(() => localStorage.getItem(THEME_KEY) || 'light')
  const [colorPrimary, setColorPrimary] = useState(() => localStorage.getItem(COLOR_KEY) || '#1677ff')

  useEffect(() => {
    localStorage.setItem(THEME_KEY, mode)
    // body 添加 class 供 CSS 适配
    document.documentElement.setAttribute('data-theme', mode)
  }, [mode])

  useEffect(() => {
    localStorage.setItem(COLOR_KEY, colorPrimary)
  }, [colorPrimary])

  const toggleMode = useCallback(() => {
    setMode(prev => prev === 'light' ? 'dark' : 'light')
  }, [])

  const isDark = mode === 'dark'

  return { mode, isDark, toggleMode, colorPrimary, setColorPrimary, PRESET_COLORS }
}

