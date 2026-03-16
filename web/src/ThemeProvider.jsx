// src/ThemeProvider.jsx
// Ant Design 主题 + i18n locale + 暗色模式 联动 Provider

import { useMemo, createContext, useContext } from 'react'
import { ConfigProvider, theme as antTheme } from 'antd'
import { useTranslation } from 'react-i18next'
import { useTheme } from '@/hooks/useTheme'
import dayjs from 'dayjs'
import 'dayjs/locale/zh-cn'
import 'dayjs/locale/zh-tw'
import 'dayjs/locale/en'

// Ant Design 语言包
import zhCN from 'antd/locale/zh_CN'
import zhTW from 'antd/locale/zh_TW'
import enUS from 'antd/locale/en_US'

// 映射表
const antdLocaleMap = { 'zh-CN': zhCN, 'zh-TW': zhTW, en: enUS }
const dayjsLocaleMap = { 'zh-CN': 'zh-cn', 'zh-TW': 'zh-tw', en: 'en' }

// 暴露主题 Context 给全局使用
const ThemeContext = createContext(null)
export const useThemeContext = () => useContext(ThemeContext)

export const ThemeProvider = ({ children }) => {
  const { i18n } = useTranslation()
  const lang = i18n.language || 'zh-CN'
  const themeState = useTheme()
  const { isDark, colorPrimary } = themeState

  // 响应式切换 Ant Design locale
  const antdLocale = useMemo(() => antdLocaleMap[lang] || zhCN, [lang])

  // 同步切换 dayjs locale
  useMemo(() => {
    dayjs.locale(dayjsLocaleMap[lang] || 'zh-cn')
  }, [lang])

  const themeConfig = useMemo(() => ({
    algorithm: isDark ? antTheme.darkAlgorithm : antTheme.defaultAlgorithm,
    token: {
      colorPrimary,
      borderRadius: 8,
    },
  }), [isDark, colorPrimary])

  return (
    <ThemeContext.Provider value={themeState}>
      <ConfigProvider locale={antdLocale} theme={themeConfig}>
        {children}
      </ConfigProvider>
    </ThemeContext.Provider>
  )
}

