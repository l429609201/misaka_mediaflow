// src/ThemeProvider.jsx
// Ant Design 主题 + i18n locale + 暗色模式 联动 Provider
// 对标弹幕库：根据主色动态派生全套 CSS 变量 + AntD token/components 双套配置

import { useEffect, useMemo, createContext, useContext } from 'react'
import { ConfigProvider, theme as antTheme } from 'antd'
import { useTranslation } from 'react-i18next'
import { useTheme } from '@/hooks/useTheme'
import dayjs from 'dayjs'
import 'dayjs/locale/zh-cn'
import 'dayjs/locale/zh-tw'
import 'dayjs/locale/en'

import zhCN from 'antd/locale/zh_CN'
import zhTW from 'antd/locale/zh_TW'
import enUS from 'antd/locale/en_US'

const antdLocaleMap = { 'zh-CN': zhCN, 'zh-TW': zhTW, en: enUS }
const dayjsLocaleMap = { 'zh-CN': 'zh-cn', 'zh-TW': 'zh-tw', en: 'en' }

// ── 颜色工具函数（对标弹幕库 ThemeProvider）──────────────────────────────
function hexToRgb(hex) {
  const h = hex.replace('#', '')
  return { r: parseInt(h.slice(0, 2), 16), g: parseInt(h.slice(2, 4), 16), b: parseInt(h.slice(4, 6), 16) }
}
function rgbToHex(r, g, b) {
  return '#' + [r, g, b].map(x => Math.round(Math.max(0, Math.min(255, x))).toString(16).padStart(2, '0')).join('')
}
function mixColors(c1, c2, ratio) {
  const a = hexToRgb(c1), b = hexToRgb(c2)
  return rgbToHex(a.r * ratio + b.r * (1 - ratio), a.g * ratio + b.g * (1 - ratio), a.b * ratio + b.b * (1 - ratio))
}
function darkenColor(hex, amount) {
  const { r, g, b } = hexToRgb(hex)
  return rgbToHex(r * (1 - amount), g * (1 - amount), b * (1 - amount))
}
function hexToRgba(hex, alpha) {
  const { r, g, b } = hexToRgb(hex)
  return `rgba(${r}, ${g}, ${b}, ${alpha})`
}

// 根据主色生成一整套派生色（对标弹幕库 generateThemeColors）
function generateThemeColors(primary) {
  const hover  = darkenColor(primary, 0.1)
  const active = darkenColor(primary, 0.2)
  return {
    primary, hover, active,
    // 亮色模式派生
    lightBorder:    mixColors(primary, '#FFFFFF', 0.15),
    lightBorderSec: mixColors(primary, '#FFFFFF', 0.10),
    lightHoverBg:   mixColors(primary, '#FFFFFF', 0.06),
    lightBgBase:    mixColors(primary, '#FFFFFF', 0.03),
    lightShadow:    hexToRgba(primary, 0.15),
    // 暗色模式派生
    darkBorder:     mixColors(primary, '#000000', 0.30),
    darkBorderSec:  mixColors(primary, '#000000', 0.20),
    darkHoverBg:    hexToRgba(primary, 0.12),
    darkBgBase:     hexToRgba(primary, 0.05),
    darkShadow:     hexToRgba(primary, 0.25),
  }
}

const ThemeContext = createContext(null)
export const useThemeContext = () => useContext(ThemeContext)

export const ThemeProvider = ({ children }) => {
  const { i18n } = useTranslation()
  const lang = i18n.language || 'zh-CN'
  const themeState = useTheme()
  const { isDark, colorPrimary } = themeState

  const antdLocale = useMemo(() => antdLocaleMap[lang] || zhCN, [lang])
  useMemo(() => { dayjs.locale(dayjsLocaleMap[lang] || 'zh-cn') }, [lang])

  // 每次主色或亮/暗切换时，把派生色写入 :root CSS 变量（弹幕库同款做法）
  useEffect(() => {
    const c = generateThemeColors(colorPrimary)
    const root = document.documentElement
    if (isDark) {
      root.style.setProperty('--color-bg',      '#141414')
      root.style.setProperty('--color-card',    '#1f1f1f')
      root.style.setProperty('--color-header',  '#1f1f1f')
      root.style.setProperty('--color-hover',   '#2a2a2a')
      root.style.setProperty('--color-text',    'rgba(255,255,255,0.85)')
      root.style.setProperty('--color-border',  c.darkBorder)
      root.style.setProperty('--color-border-sec', c.darkBorderSec)
      root.style.setProperty('--color-hover-bg',   c.darkHoverBg)
      root.style.setProperty('--color-shadow',     c.darkShadow)
    } else {
      root.style.setProperty('--color-bg',      c.lightBgBase || '#f5f7fa')
      root.style.setProperty('--color-card',    '#ffffff')
      root.style.setProperty('--color-header',  '#ffffff')
      root.style.setProperty('--color-hover',   c.lightHoverBg)
      root.style.setProperty('--color-text',    '#333333')
      root.style.setProperty('--color-border',  c.lightBorder)
      root.style.setProperty('--color-border-sec', c.lightBorderSec)
      root.style.setProperty('--color-hover-bg',   c.lightHoverBg)
      root.style.setProperty('--color-shadow',     c.lightShadow)
    }
    root.style.setProperty('--color-primary',      colorPrimary)
    root.style.setProperty('--color-primary-hover', c.hover)
    root.style.setProperty('--color-primary-active', c.active)
  }, [isDark, colorPrimary])

  const themeConfig = useMemo(() => {
    const c = generateThemeColors(colorPrimary)
    if (isDark) {
      return {
        algorithm: antTheme.darkAlgorithm,
        token: {
          colorPrimary,
          colorBgBase: '#141414',
          colorBgContainer: '#1f1f1f',
          colorBgElevated: '#2a2a2a',
          colorBorder: c.darkBorder,
          colorBorderSecondary: c.darkBorderSec,
          borderRadius: 8,
        },
        components: {
          Layout:  { siderBg: '#1f1f1f', headerBg: '#1f1f1f', bodyBg: '#141414' },
          Menu:    { darkItemBg: '#1f1f1f', darkSubMenuItemBg: '#1f1f1f', itemBg: '#1f1f1f' },
          Card:    { colorBgContainer: '#1f1f1f' },
          Table:   { colorBgContainer: '#1f1f1f', headerBg: '#262626' },
          Modal:   { contentBg: '#1f1f1f', headerBg: '#1f1f1f' },
          Drawer:  { colorBgElevated: '#1f1f1f' },
          Select:  { colorBgContainer: '#1f1f1f' },
          Input:   { colorBgContainer: '#1f1f1f' },
        },
      }
    }
    return {
      algorithm: antTheme.defaultAlgorithm,
      token: {
        colorPrimary,
        colorBgBase: '#ffffff',
        colorBgContainer: '#ffffff',
        colorBgLayout: c.lightBgBase || '#f5f7fa',
        colorBorder: c.lightBorder,
        colorBorderSecondary: c.lightBorderSec,
        borderRadius: 8,
      },
      components: {
        Layout:  { siderBg: '#ffffff', headerBg: '#ffffff', bodyBg: c.lightBgBase || '#f5f7fa' },
        Menu:    { itemBg: '#ffffff', subMenuItemBg: '#ffffff' },
        Card:    { colorBgContainer: '#ffffff' },
        Table:   { colorBgContainer: '#ffffff', headerBg: '#fafafa' },
        Modal:   { contentBg: '#ffffff', headerBg: '#ffffff' },
        Drawer:  { colorBgElevated: '#ffffff' },
        Select:  { colorBgContainer: '#ffffff' },
        Input:   { colorBgContainer: '#ffffff' },
      },
    }
  }, [isDark, colorPrimary])

  return (
    <ThemeContext.Provider value={themeState}>
      <ConfigProvider locale={antdLocale} theme={themeConfig}>
        {children}
      </ConfigProvider>
    </ThemeContext.Provider>
  )
}

