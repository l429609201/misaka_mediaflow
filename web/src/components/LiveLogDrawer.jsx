// src/components/LiveLogDrawer.jsx — 对标弹幕库 RealtimeLogModal
// 卡片行 + marginBottom间距 + 级别Switch(颜色联动主题色) + 左边框 + 搜索高亮 + 单行复制

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Button, Drawer, Input, Space, Switch, Tag, Tooltip, Typography, message, Segmented } from 'antd'
import { ClearOutlined, CopyOutlined, SearchOutlined, VerticalAlignBottomOutlined } from '@ant-design/icons'
import { useTranslation } from 'react-i18next'
import { useThemeContext } from '@/ThemeProvider'

const { Text } = Typography
const MAX_LINES = 1000

// 三档滑动选择器：选中档位 = 显示该级别及以上
const LEVEL_SLIDER_OPTIONS = ['DEBUG', 'INFO', 'WARNING']
const LEVEL_SHOW_MAP = {
  DEBUG:   new Set(['DEBUG', 'INFO', 'WARNING']),
  INFO:    new Set(['INFO', 'WARNING']),
  WARNING: new Set(['WARNING']),
}

const LEVEL_COLOR = {
  dark:  { CRITICAL: '#ff1744', ERROR: '#ff4d4f', WARNING: '#faad14', INFO: '#52c41a', DEBUG: '#1677ff' },
  light: { CRITICAL: '#c62828', ERROR: '#d32f2f', WARNING: '#e65100', INFO: '#2e7d32', DEBUG: '#1565c0' },
}
const LEVEL_BG = {
  dark:  { CRITICAL: 'rgba(255,23,68,0.08)',  ERROR: 'rgba(255,77,79,0.07)',  WARNING: 'rgba(250,173,20,0.07)', INFO: 'rgba(82,196,26,0.05)',  DEBUG: 'rgba(22,119,255,0.05)' },
  light: { CRITICAL: 'rgba(198,40,40,0.06)',  ERROR: 'rgba(211,47,47,0.05)', WARNING: 'rgba(230,81,0,0.06)',   INFO: 'rgba(46,125,50,0.04)',  DEBUG: 'rgba(21,101,192,0.04)' },
}

const getLevelColor = (level, isDark) =>
  ((isDark ? LEVEL_COLOR.dark : LEVEL_COLOR.light)[level]) ?? (isDark ? '#888' : '#666')
const getLevelBg = (level, isDark) =>
  ((isDark ? LEVEL_BG.dark : LEVEL_BG.light)[level]) ?? 'transparent'

const parseLevel = (line) => {
  if (line.includes('[CRITICAL]')) return 'CRITICAL'
  if (line.includes('[ERROR]'))    return 'ERROR'
  if (line.includes('[WARNING]') || line.includes('[WARN]')) return 'WARNING'
  if (line.includes('[INFO]'))     return 'INFO'
  if (line.includes('[DEBUG]'))    return 'DEBUG'
  return 'INFO'
}

const highlight = (text, kw, isDark) => {
  if (!kw) return text
  const esc = kw.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  return text.split(new RegExp(`(${esc})`, 'gi')).map((p, i) =>
    p.toLowerCase() === kw.toLowerCase()
      ? <mark key={i} style={{ background: isDark ? '#b5861a' : '#ffe58f', color: 'inherit', borderRadius: 2, padding: '0 1px' }}>{p}</mark>
      : p
  )
}

export default function LiveLogDrawer({ open, onClose }) {
  const { t } = useTranslation()
  const { isDark, colorPrimary } = useThemeContext()

  const [logs, setLogs]             = useState([])
  const [connected, setConnected]   = useState(false)
  const [autoScroll, setAutoScroll] = useState(true)
  const [searchText, setSearchText] = useState('')
  // 三档滑动选择器，默认 INFO
  const [levelSlider, setLevelSlider] = useState('INFO')
  const [hoveredIdx, setHoveredIdx] = useState(null)
  const containerRef = useRef(null)
  const esRef        = useRef(null)
  const [messageApi, ctxHolder] = message.useMessage()

  const logBg    = isDark ? '#141414' : '#f5f5f5'
  const cardBg   = isDark ? '#1f1f1f' : '#ffffff'
  const textClr  = isDark ? 'rgba(255,255,255,0.82)' : '#333'
  const labelClr = isDark ? '#888' : '#666'

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

  // 过滤：三档选择器 + 关键词搜索
  const filteredLogs = useMemo(() => {
    const kw = searchText.toLowerCase()
    const enabled = LEVEL_SHOW_MAP[levelSlider]
    return logs.filter(line => enabled.has(parseLevel(line)) && (!kw || line.toLowerCase().includes(kw)))
  }, [logs, levelSlider, searchText])

  // 自动滚动到底部
  useEffect(() => {
    if (autoScroll && containerRef.current)
      containerRef.current.scrollTop = containerRef.current.scrollHeight
  }, [filteredLogs, autoScroll])

  const copyAll  = () => navigator.clipboard.writeText(filteredLogs.join('\n'))
    .then(() => messageApi.success(t('common.copied', '已复制'))).catch(() => {})
  const copyLine = useCallback((line) => navigator.clipboard.writeText(line)
    .then(() => messageApi.success(t('common.copied', '已复制'))).catch(() => {}), [messageApi, t])

  return (
    <Drawer
      title={
        <Space>
          {t('tasks.liveTitle', '实时日志')}
          {connected
            ? <Tag color="success">{t('p115.connected', '已连接')}</Tag>
            : <Tag color="error">{t('p115.disconnected', '未连接')}</Tag>}
          <Text type="secondary" style={{ fontSize: 12 }}>{filteredLogs.length} / {logs.length}</Text>
        </Space>
      }
      placement="right" width={860} open={open} onClose={onClose} destroyOnClose
    >
      {ctxHolder}

      {/* 级别 Segmented 工具栏 — 三档左右拨动选择器 */}
      <div style={{
        marginBottom: 10, display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap',
        padding: '8px 12px', borderRadius: 8,
        background: isDark ? '#1a1a1a' : '#fafafa',
        border: `1px solid ${isDark ? '#2a2a2a' : '#e8e8e8'}`,
      }}>
        <Text style={{ color: labelClr, fontSize: 12, whiteSpace: 'nowrap', marginRight: 4 }}>
          {t('tasks.levelFilter', '级别过滤')}：
        </Text>
        <Segmented
          size="small"
          value={levelSlider}
          onChange={setLevelSlider}
          options={LEVEL_SLIDER_OPTIONS.map(lv => ({ value: lv, label: lv }))}
        />
      </div>

      {/* 搜索 + 操作按钮行 */}
      <div style={{ marginBottom: 10, display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 }}>
        <Input size="small" placeholder={t('tasks.searchPlaceholder', '搜索日志...')}
          prefix={<SearchOutlined style={{ color: colorPrimary }} />}
          value={searchText} onChange={e => setSearchText(e.target.value)} allowClear style={{ width: 220 }} />
        <Space>
          <Text style={{ color: labelClr, fontSize: 12 }}>{t('tasks.autoScroll', '自动滚动')}</Text>
          <Switch size="small" checked={autoScroll} onChange={setAutoScroll}
            style={autoScroll ? { backgroundColor: colorPrimary } : {}} />
          <Tooltip title={t('tasks.scrollToBottom', '滚到底部')}>
            <Button size="small" icon={<VerticalAlignBottomOutlined />}
              onClick={() => containerRef.current && (containerRef.current.scrollTop = containerRef.current.scrollHeight)} />
          </Tooltip>
          <Tooltip title={t('common.copy', '复制全部')}>
            <Button size="small" icon={<CopyOutlined />} onClick={copyAll} />
          </Tooltip>
          <Tooltip title={t('tasks.clear', '清空')}>
            <Button size="small" icon={<ClearOutlined />} onClick={() => setLogs([])} />
          </Tooltip>
        </Space>
      </div>

      {/* 日志内容区 — 弹幕库风格：每条独立卡片 + marginBottom间距 + 级别颜色左边框 */}
      <div ref={containerRef} style={{
        height: 'calc(100% - 130px)', overflowY: 'auto',
        background: logBg, borderRadius: 8, padding: '8px',
        fontFamily: "'JetBrains Mono','Fira Code','Consolas',monospace",
        fontSize: 12, lineHeight: 1.7,
      }}>
        {filteredLogs.length === 0 && (
          <div style={{ padding: '24px', textAlign: 'center', color: isDark ? '#555' : '#bbb' }}>
            {t('tasks.waitingLogs', '等待日志...')}
          </div>
        )}
        {filteredLogs.map((line, i) => {
          const level   = parseLevel(line)
          const clr     = getLevelColor(level, isDark)
          const bg      = getLevelBg(level, isDark)
          const isHover = hoveredIdx === i
          return (
            <div key={i}
              onMouseEnter={() => setHoveredIdx(i)}
              onMouseLeave={() => setHoveredIdx(null)}
              style={{
                display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between',
                marginBottom: 4,
                padding: '5px 8px 5px 10px',
                borderRadius: 6,
                background: isHover ? (isDark ? '#252525' : '#ebebeb') : (bg || cardBg),
                borderLeft: `3px solid ${clr}`,
                boxShadow: isDark ? 'none' : '0 1px 2px rgba(0,0,0,0.04)',
                transition: 'background 0.15s',
                cursor: 'default',
              }}
            >
              <span style={{ color: textClr, whiteSpace: 'pre-wrap', wordBreak: 'break-all', flex: 1 }}>
                {line.split(new RegExp(`(\\[${level}\\]|\\[WARN\\])`, 'g')).map((part, pi) =>
                  (part === `[${level}]` || part === '[WARN]')
                    ? <span key={pi} style={{ color: clr, fontWeight: 700 }}>{part}</span>
                    : (searchText ? highlight(part, searchText, isDark) : part)
                )}
              </span>
              <Tooltip title={t('common.copy', '复制')}>
                <Button type="text" size="small" icon={<CopyOutlined />}
                  onClick={() => copyLine(line)}
                  style={{ opacity: isHover ? 1 : 0, transition: 'opacity 0.15s',
                    color: isDark ? '#888' : '#999', flexShrink: 0, marginLeft: 6, padding: '0 4px', height: 20 }} />
              </Tooltip>
            </div>
          )
        })}
      </div>
    </Drawer>
  )
}

