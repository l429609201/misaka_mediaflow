// store/index.js
// jotai 全局状态 atoms（与 src 同级，对齐 misaka 项目结构）

import { atom } from 'jotai'
import { atomWithStorage } from 'jotai/utils'

// 当前登录用户
export const userAtom = atom(localStorage.getItem('username') || '')

// Token
export const tokenAtom = atom(localStorage.getItem('token') || '')

// 侧边栏折叠
export const sidebarCollapsedAtom = atom(false)

// 语言设置（持久化到 localStorage）
export const languageAtom = atomWithStorage('language', 'zh-CN')

