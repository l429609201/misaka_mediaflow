// src/components/LiveLogDrawer.jsx
// 实时日志抽屉 — 对标弹幕库 Logs.jsx 样式
// SSE实时推送 + 左色条卡片行 + 多开关级别过滤 + 搜索 + 自动滚动 + 单行复制

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Button, Drawer, Input, Space, Switch, Tag, Tooltip, Typography, message } from 'antd'
import { ClearOutlined, CopyOutlined, SearchOutlined, VerticalAlignBottomOutlined } from '@ant-design/icons'
import { useTranslation } from 'react-i18next'
import { useThemeContext } from '@/ThemeProvider'

const { Text } = Typography
const MAX_LINES = 1000
const ALL_LEVELS = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']

// 左边框 / 级别文字颜色（亮/暗双套）
const LEVEL_BORDER = {
  dark:  { CRITICAL: '#ff1744', ERROR: '#ff4d4f', WARNING: '#faad14', INFO: '#52c41a', DEBUG: '#1677ff' },
  light: { CRITICAL: '#c62828', ERROR: '#d32f2f', WARNING: '#e65100', INFO: '#2e7d32', DEBUG: '#1565c0' },
}
// 行背景底色（极淡色调，级别可视化）
const LEVEL_ROW_BG = {
  dark:  { CRITICAL: 'rgba(255,23,68,0.08)',  ERROR: 'rgba(255,77,79,0.07)',  WARNING: 'rgba(250,173,20,0.07)', INFO: 'rgba(82,196,26,0.05)',  DEBUG: 'rgba(22,119,255,0.05)' },
  light: { CRITICAL: 'rgba(198,40,40,0.06)',  ERROR: 'rgba(211,47,47,0.05)', WARNING: 'rgba(230,81,0,0.06)',   INFO: 'rgba(46,125,50,0.04)',  DEBUG: 'rgba(21,101,192,0.04)' },
}

const getBorderColor = (level, isDark) =>
  ((isDark ? LEVEL_BORDER.dark : LEVEL_BORDER.light)[level]) ?? (isDark ? '#555' : '#bbb')
const getRowBg = (level, isDark) =>
  ((isDark ? LEVEL_ROW_BG.dark : LEVEL_ROW_BG.light)[level]) ?? 'transparent'

const parseLevel = (line) => {
  if (line.includes('[CRITICAL]')) return 'CRITICAL'
  if (line.includes('[ERROR]'))    return 'ERROR'
  if (line.includes('[WARNING]') || line.includes('[WARN]')) return 'WARNING'
  if (line.includes('[INFO]'))     return 'INFO'
  if (line.includes('[DEBUG]'))    return 'DEBUG'
  return 'INFO'
}

// 搜索关键词高亮（纯 inline style，不依赖 Tailwind）
const highlight = (text, kw, isDark) => {
  if (!kw) return text
  const escaped = kw.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const parts = text.split(new RegExp(`(${escaped})`, 'gi'))
  return parts.map((p, i) =>
    p.toLowerCase() === kw.toLowerCase()
      ? <mark key={i} style={{ background: isDark ? '#b5861a' : '#ffe58f', color: 'inherit', borderRadius: 2, padding: '0 1px' }}>{p}</mark>
      : p
  )
}

export default function LiveLogDrawer({ open, onClose }) {
  const { t } = useTranslation()
  const { isDark } = useThemeContext()

  const [logs, setLogs]             = useState([])
  const [connected, setConnected]   = useState(false)
  const [autoScroll, setAutoScroll] = useState(true)
  const [searchText, setSearchText] = useState('')
  const [levelOn, setLevelOn]       = useState({ DEBUG: false, INFO: true, WARNING: true, ERROR: true, CRITICAL: true })
  const [hoveredIdx, setHoveredIdx] = useState(null)
  const containerRef = useRef(null)
  const esRef        = useRef(null)
  const [messageApi, ctxHolder] = message.useMessage()

  // 主题色
  const logBg      = isDark ? '#141414' : '#f9f9f9'
  const labelClr   = isDark ? '#888'    : '#666'
  const textClr    = isDark ? 'rgba(255,255,255,0.82)' : '#333'
  const hoverRowBg = isDark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.025)'

  // SSE 连接
  useEffect(() => {
    if (!open) {
      esRef.current?.close(); esRef.current = null; setConnected(false)
      return
    }
    const token = localStorage.getItem('token') || ''
    const es = new EventSource(`/api/v1/system/logs/stream?token=${encodeURIComponent(token)}`)
    esRef.current = es
    es.onopen    = () => setConnected(true)
    es.onerror   = () => setConnected(false)
    es.onmessage = (e) => {
      const msg = e.data?.trim()
      if (!msg || msg === '[connected]') return
      setLogs(prev => { const next = [...prev, msg]; return next.length > MAX_LINES ? next.slice(-MAX_LINES) : next })
    }
    return () => { es.close(); esRef.current = null; setConnected(false) }
  }, [open])

  // 过滤：级别开关 + 关键词搜索
  const filteredLogs = useMemo(() => {
    const kw = searchText.toLowerCase()
    return logs.filter(line => levelOn[parseLevel(line)] && (!kw || line.toLowerCase().includes(kw)))
  }, [logs, levelOn, searchText])

  // 自动滚动到底部
  useEffect(() => {
    if (autoScroll && containerRef.current)
      containerRef.current.scrollTop = containerRef.current.scrollHeight
  }, [filteredLogs, autoScroll])

  const toggleLevel = (lv) => setLevelOn(prev => ({ ...prev, [lv]: !prev[lv] }))
  const copyAll  = () => navigator.clipboard.writeText(filteredLogs.join('\n'))
    .then(() => messageApi.success(t('common.copied', '已复制'))).catch(() => {})
  const copyLine = useCallback((line) => navigator.clipboard.writeText(line)
    .then(() => messageApi.success(t('common.copied', '已复制'))).catch(() => {}), [messageApi, t])

  return (
    <Drawer
      title={
        <Space>
          {t('logs.liveTitle', '实时日志')}
          {connected
            ? <Tag color="success">{t('p115.connected', '已连接')}</Tag>
            : <Tag color="error">{t('p115.disconnected', '未连接')}</Tag>}
          <Text type="secondary" style={{ fontSize: 12 }}>{filteredLogs.length} / {logs.length}</Text>
        </Space>
      }
      placement="right" width={860} open={open} onClose={onClose} destroyOnClose
    >
      {ctxHolder}

      {/* 工具栏第一行：各级别独立开关 */}
      <div style={{ marginBottom: 8, display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <Text style={{ color: labelClr, fontSize: 12, whiteSpace: 'nowrap' }}>{t('logs.levelFilter', '日志级别')}：</Text>
        {ALL_LEVELS.map(lv => {
          const clr = getBorderColor(lv, isDark)
          return (
            <Space key={lv} size={4} style={{ alignItems: 'center' }}>
              <Switch
                size="small" checked={levelOn[lv]} onChange={() => toggleLevel(lv)}
                style={levelOn[lv] ? { backgroundColor: clr } : {}}
              />
              <Text style={{
                fontSize: 12, fontWeight: levelOn[lv] ? 700 : 400, userSelect: 'none',
                color: levelOn[lv] ? clr : (isDark ? '#444' : '#ccc'),
              }}>
                {lv}
              </Text>
            </Space>
          )
        })}
      </div>

      {/* 工具栏第二行：搜索 + 操作按钮 */}
      <div style={{ marginBottom: 10, display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 }}>
        <Input
          size="small" placeholder={t('logs.searchPlaceholder', '搜索日志...')}
          prefix={<SearchOutlined />} value={searchText}
          onChange={e => setSearchText(e.target.value)} allowClear style={{ width: 220 }}
        />
        <Space>
          <Text style={{ color: labelClr, fontSize: 12 }}>{t('logs.autoScroll', '自动滚动')}</Text>
          <Switch size="small" checked={autoScroll} onChange={setAutoScroll} />
          <Tooltip title={t('logs.scrollToBottom', '滚到底部')}>
            <Button size="small" icon={<VerticalAlignBottomOutlined />}
              onClick={() => containerRef.current && (containerRef.current.scrollTop = containerRef.current.scrollHeight)} />
          </Tooltip>
          <Tooltip title={t('common.copy', '复制全部')}>
            <Button size="small" icon={<CopyOutlined />} onClick={copyAll} />
          </Tooltip>
          <Tooltip title={t('logs.clear', '清空')}>
            <Button size="small" icon={<ClearOutlined />} onClick={() => setLogs([])} />
          </Tooltip>
        </Space>
      </div>

      {/* 日志内容区 — 弹幕库风格：左色条 + 行背景 + hover显示复制 */}
      <div ref={containerRef} style={{
        height: 'calc(100% - 108px)', overflowY: 'auto',
        background: logBg, borderRadius: 8, padding: '6px 0',
        fontFamily: "'JetBrains Mono','Fira Code','Consolas',monospace",
        fontSize: 12, lineHeight: 1.75,
      }}>
        {filteredLogs.length === 0 && (
          <div style={{ padding: '16px 20px', color: isDark ? '#555' : '#bbb' }}>
            {t('logs.waitingLogs', '等待日志...')}
          </div>
        )}
        {filteredLogs.map((line, i) => {
          const level  = parseLevel(line)
          const border = getBorderColor(level, isDark)
          const rowBg  = hoveredIdx === i ? hoverRowBg : getRowBg(level, isDark)
          return (
            <div
              key={i}
              onMouseEnter={() => setHoveredIdx(i)}
              onMouseLeave={() => setHoveredIdx(null)}
              style={{
                display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between',
                padding: '3px 12px',
                background: rowBg,
                borderLeft: `4px solid ${border}`,
                transition: 'background 0.15s',
                cursor: 'default',
              }}
            >
              {/* 日志文字：级别标签单独着色，搜索词高亮 */}
              <span style={{ color: textClr, whiteSpace: 'pre-wrap', wordBreak: 'break-all', flex: 1, lineHeight: 1.75 }}>
                {line.split(new RegExp(`(\\[${level}\\]|\\[WARN\\])`, 'g')).map((part, pi) =>
                  (part === `[${level}]` || part === '[WARN]')
                    ? <span key={pi} style={{ color: border, fontWeight: 700 }}>{part}</span>
                    : (searchText ? highlight(part, searchText, isDark) : part)
                )}
              </span>
              {/* 单行复制按钮：hover 才显示 */}
              <Tooltip title={t('common.copy', '复制')}>
                <Button
                  type="text" size="small" icon={<CopyOutlined />}
                  onClick={() => copyLine(line)}
                  style={{
                    opacity: hoveredIdx === i ? 1 : 0,
                    transition: 'opacity 0.15s',
                    color: isDark ? '#888' : '#999',
                    flexShrink: 0, marginLeft: 8, padding: '0 4px', height: 20,
                  }}
                />
              </Tooltip>
            </div>
          )
        })}
      </div>
    </Drawer>
  )
}

