// src/i18n.js
// i18next 初始化 — 支持 简体中文 / 繁体中文 / English

import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'

import zhCN from './locales/zh-CN.json'
import zhTW from './locales/zh-TW.json'
import en from './locales/en.json'

// 语言配置映射（icon 对应 iconfont 图标类名）
export const LANGUAGES = [
  { key: 'zh-CN', label: '简体中文', icon: 'icon-jianti',  antdKey: 'zhCN', dayjsKey: 'zh-cn' },
  { key: 'zh-TW', label: '繁體中文', icon: 'icon-fanti',   antdKey: 'zhTW', dayjsKey: 'zh-tw' },
  { key: 'en',    label: 'English',  icon: 'icon-yingwen', antdKey: 'enUS', dayjsKey: 'en'    },
]

// 从 localStorage 读取已保存的语言，默认简体中文
const savedLang = localStorage.getItem('language') || 'zh-CN'

i18n
  .use(initReactI18next)
  .init({
    resources: {
      'zh-CN': { translation: zhCN },
      'zh-TW': { translation: zhTW },
      'en':    { translation: en },
    },
    lng: savedLang,
    fallbackLng: 'zh-CN',
    interpolation: {
      escapeValue: false,
    },
  })

export default i18n

/**
 * 切换语言（持久化到 localStorage）
 */
export function changeLanguage(lang) {
  i18n.changeLanguage(lang)
  localStorage.setItem('language', lang)
}

/**
 * 获取当前语言 key
 */
export function getCurrentLanguage() {
  return i18n.language || 'zh-CN'
}

