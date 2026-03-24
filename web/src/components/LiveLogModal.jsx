// src/components/LiveLogModal.jsx
// 实时日志弹窗 — 样式对齐 HistoryLogModal（卡片行+左侧彩色竖条）

import { useEffect, useMemo, useRef, useState } from 'react'
import { Modal, Button, Tooltip, Switch, Input, Space, Tag, Typography, message, Segmented } from 'antd'
import { ClearOutlined, VerticalAlignBottomOutlined, SearchOutlined, CopyOutlined } from '@ant-design/icons'
import { useTranslation } from 'react-i18next'
import { useThemeContext } from '@/ThemeProvider'

const { Text } = Typography
const MAX_LINES = 1000

// 三档滑动选择器：选中档位 = 显示该级别及以上
// DEBUG → DEBUG+INFO+WARNING   INFO → INFO+WARNING   WARNING → 仅WARNING
const LEVEL_SLIDER_OPTIONS = ['DEBUG', 'INFO', 'WARNING']
const LEVEL_SHOW_MAP = {
  DEBUG:   new Set(['DEBUG', 'INFO', 'WARNING']),
  INFO:    new Set(['INFO', 'WARNING']),
  WARNING: new Set(['WARNING']),
}

// 与 HistoryLogModal 完全一致的颜色表
const LEVEL_COLOR = {
  dark:  { CRITICAL: '#ff1744', ERROR: '#ff4d4f', WARNING: '#faad14', INFO: '#52c41a', DEBUG: '#1677ff' },
  light: { CRITICAL: '#c62828', ERROR: '#d32f2f', WARNING: '#e65100', INFO: '#2e7d32', DEBUG: '#1565c0' },
}
const LEVEL_BG = {
  dark:  { CRITICAL: 'rgba(255,23,68,0.08)',  ERROR: 'rgba(255,77,79,0.07)',  WARNING: 'rgba(250,173,20,0.07)', INFO: 'rgba(82,196,26,0.05)',  DEBUG: 'rgba(22,119,255,0.05)' },
  light: { CRITICAL: 'rgba(198,40,40,0.06)',  ERROR: 'rgba(211,47,47,0.05)', WARNING: 'rgba(230,81,0,0.06)',   INFO: 'rgba(46,125,50,0.04)',  DEBUG: 'rgba(21,101,192,0.04)' },
}
const getLevelColor = (level, isDark) => (isDark ? LEVEL_COLOR.dark : LEVEL_COLOR.light)[level] ?? (isDark ? '#888' : '#666')
const getLevelBg    = (level, isDark) => (isDark ? LEVEL_BG.dark    : LEVEL_BG.light)[level]    ?? 'transparent'

const parseLevel = (line) => {
  if (line.includes('[CRITICAL]') || line.includes('CRITICAL')) return 'CRITICAL'
  if (line.includes('[ERROR]')    || line.includes('ERROR'))    return 'ERROR'
  if (line.includes('[WARNING]')  || line.includes('WARNING'))  return 'WARNING'
  if (line.includes('[INFO]')     || line.includes('INFO'))     return 'INFO'
  if (line.includes('[DEBUG]')    || line.includes('DEBUG'))    return 'DEBUG'
  return 'INFO'
}

// 高亮搜索关键字
const highlightSearch = (text, keyword, isDark) => {
  if (!keyword) return <span>{text}</span>
  const parts = text.split(new RegExp(`(${keyword.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi'))
  return (
    <>
      {parts.map((p, i) =>
        p.toLowerCase() === keyword.toLowerCase()
          ? <mark key={i} style={{ background: isDark ? '#faad1440' : '#fff566', borderRadius: 2, padding: '0 1px' }}>{p}</mark>
          : p
      )}
    </>
  )
}

// 单条日志行（对齐 HistoryLogModal 的 LogRow）
const LogRow = ({ line, search, isDark }) => {
  const [hovered, setHovered] = useState(false)
  const level = parseLevel(line)
  const color = getLevelColor(level, isDark)
  const bg    = getLevelBg(level, isDark)
  const border = isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)'

  return (
    <div
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        display: 'flex', alignItems: 'flex-start', gap: 0,
        borderLeft: `3px solid ${color}`,
        background: hovered ? (isDark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.03)') : bg,
        borderBottom: `1px solid ${border}`,
        borderRadius: 4, marginBottom: 4, padding: '5px 10px 5px 10px',
        transition: 'background 0.15s',
        minHeight: 28,
      }}
    >
      {/* 级别标签 */}
      <Tag
        color={color}
        style={{ flexShrink: 0, fontSize: 10, lineHeight: '16px', padding: '0 4px', marginRight: 8, marginTop: 1, border: 'none' }}
      >
        {level}
      </Tag>

      {/* 日志内容 */}
      <Text style={{ fontFamily: 'monospace', fontSize: 12, flex: 1, wordBreak: 'break-all', color: isDark ? '#d4d4d4' : '#222', whiteSpace: 'pre-wrap' }}>
        {highlightSearch(line, search, isDark)}
      </Text>

      {/* hover 时显示复制按钮 */}
      {hovered && (
        <Tooltip title="复制">
          <Button
            type="text" size="small" icon={<CopyOutlined />}
            style={{ flexShrink: 0, color: isDark ? '#888' : '#aaa', marginLeft: 4 }}
            onClick={() => { navigator.clipboard.writeText(line); message.success('已复制') }}
          />
        </Tooltip>
      )}
    </div>
  )
}


export default function LiveLogModal({ open, onClose }) {
  const { t } = useTranslation()
  const { isDark } = useThemeContext()
  const [logs, setLogs] = useState([])
  const [connected, setConnected] = useState(false)
  const [autoScroll, setAutoScroll] = useState(true)
  // 三档滑动选择器，默认 INFO（显示 INFO + WARNING）
  const [levelSlider, setLevelSlider] = useState('INFO')
  const [searchText, setSearchText] = useState('')
  const containerRef = useRef(null)
  const esRef = useRef(null)

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

  // 自动滚动
  useEffect(() => {
    if (autoScroll && containerRef.current)
      containerRef.current.scrollTop = containerRef.current.scrollHeight
  }, [logs, autoScroll])

  // 过滤：根据三档选择器 + 关键词
  const enabledLevels = LEVEL_SHOW_MAP[levelSlider]
  const filtered = useMemo(() => {
    const kw = searchText.trim().toLowerCase()
    return logs.filter(line => {
      const lv = parseLevel(line)
      if (!enabledLevels.has(lv)) return false
      if (kw && !line.toLowerCase().includes(kw)) return false
      return true
    })
  }, [logs, levelSlider, searchText])

  const bg = isDark ? '#141414' : '#fafafa'
  const borderColor = isDark ? '#303030' : '#e8e8e8'

  return (
    <Modal
      open={open} onCancel={onClose} footer={null} destroyOnClose
      width={860} styles={{ body: { padding: 0 } }}
      title={
        <Space>
          <span>{t('tasks.liveTitle')}</span>
          <Tag color={connected ? 'success' : 'default'}>{connected ? t('tasks.connected') : t('tasks.disconnected')}</Tag>
          <Tag>{filtered.length}/{logs.length}</Tag>
        </Space>
      }
    >
      {/* 工具栏 */}
      <div style={{ padding: '8px 16px', borderBottom: `1px solid ${borderColor}`, display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 10, background: bg }}>
        {/* 级别过滤 — 三档左右拨动选择器 */}
        <Text type="secondary" style={{ fontSize: 12, whiteSpace: 'nowrap', marginRight: 2 }}>级别过滤：</Text>
        <Segmented
          size="small"
          value={levelSlider}
          onChange={setLevelSlider}
          options={LEVEL_SLIDER_OPTIONS.map(lv => ({
            value: lv,
            label: lv,
          }))}
        />
        <Input
          size="small" placeholder="搜索…" prefix={<SearchOutlined />} allowClear
          value={searchText} onChange={e => setSearchText(e.target.value)}
          style={{ width: 160, marginLeft: 4 }}
        />
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 6, alignItems: 'center' }}>
          <Switch size="small" checked={autoScroll} onChange={setAutoScroll}
            checkedChildren={<VerticalAlignBottomOutlined />} unCheckedChildren={<VerticalAlignBottomOutlined />} />
          <Text type="secondary" style={{ fontSize: 12 }}>{t('tasks.autoScroll')}</Text>
          <Tooltip title={t('common.clear')}>
            <Button size="small" icon={<ClearOutlined />} onClick={() => setLogs([])} />
          </Tooltip>
        </div>
      </div>

      {/* 日志内容区 — 卡片行样式 */}
      <div
        ref={containerRef}
        style={{ height: 480, overflowY: 'auto', padding: '8px 12px', background: bg }}
      >
        {filtered.length === 0
          ? <Text type="secondary" style={{ display: 'block', textAlign: 'center', marginTop: 40 }}>{t('tasks.waitingLogs')}</Text>
          : filtered.map((line, i) => <LogRow key={i} line={line} search={searchText} isDark={isDark} />)
        }
      </div>
    </Modal>
  )
}
