// src/components/LiveLogDrawer.jsx
// 实时日志抽屉 — 对齐弹幕库样式
// SSE实时推送 + 日志级别过滤 + 搜索 + 自动滚动 + 复制

import { useEffect, useMemo, useRef, useState } from 'react'
import { Drawer, Button, Tooltip, Switch, Input, Select, Space, Tag, Typography, message } from 'antd'
import { ClearOutlined, VerticalAlignBottomOutlined, SearchOutlined, CopyOutlined } from '@ant-design/icons'
import { useTranslation } from 'react-i18next'
import { useThemeContext } from '@/ThemeProvider'
import { highlightText } from '@/utils/highlightText'

const { Text } = Typography
const MAX_LINES = 1000
const LEVEL_VALUES = { DEBUG: 10, INFO: 20, WARNING: 30, ERROR: 40, CRITICAL: 50 }

const parseLevel = (line) => {
  if (line.includes('[CRITICAL]')) return 'CRITICAL'
  if (line.includes('[ERROR]')) return 'ERROR'
  if (line.includes('[WARNING]') || line.includes('[WARN]')) return 'WARNING'
  if (line.includes('[INFO]')) return 'INFO'
  if (line.includes('[DEBUG]')) return 'DEBUG'
  return 'INFO'
}

const getLevelColor = (level, isDark) => {
  const colors = isDark
    ? { CRITICAL: '#ff1744', ERROR: '#ff4d4f', WARNING: '#faad14', INFO: '#52c41a', DEBUG: '#1677ff' }
    : { CRITICAL: '#c62828', ERROR: '#d32f2f', WARNING: '#e65100', INFO: '#2e7d32', DEBUG: '#1565c0' }
  return colors[level] || (isDark ? '#d4d4d4' : '#333')
}

const getThemeColors = (isDark) => isDark
  ? { logBg: '#1e1e1e', emptyColor: '#666', labelColor: '#aaa' }
  : { logBg: '#f5f5f5', emptyColor: '#999', labelColor: '#666' }

export default function LiveLogDrawer({ open, onClose }) {
  const { t } = useTranslation()
  const { isDark } = useThemeContext()
  const tc = getThemeColors(isDark)
  const [logs, setLogs] = useState([])
  const [connected, setConnected] = useState(false)
  const [autoScroll, setAutoScroll] = useState(true)
  const [logLevel, setLogLevel] = useState('INFO')
  const [searchText, setSearchText] = useState('')
  const containerRef = useRef(null)
  const esRef = useRef(null)
  const [messageApi, ctxHolder] = message.useMessage()

  // SSE 连接（后端连接时自动先推送内存已有日志）
  useEffect(() => {
    if (!open) {
      if (esRef.current) { esRef.current.close(); esRef.current = null; setConnected(false) }
      return
    }
    const token = localStorage.getItem('token') || ''
    const es = new EventSource(`/api/v1/system/logs/stream?token=${encodeURIComponent(token)}`)
    esRef.current = es
    es.onopen = () => setConnected(true)
    es.onmessage = (e) => {
      const msg = e.data?.trim()
      if (!msg || msg === '[connected]') return
      setLogs(prev => {
        const next = [...prev, msg]
        return next.length > MAX_LINES ? next.slice(-MAX_LINES) : next
      })
    }
    es.onerror = () => setConnected(false)
    return () => { es.close(); esRef.current = null; setConnected(false) }
  }, [open])

  // 过滤：级别 + 搜索
  const filteredLogs = useMemo(() => {
    const threshold = LEVEL_VALUES[logLevel] ?? 20
    const kw = searchText.toLowerCase()
    return logs.filter(line => {
      if ((LEVEL_VALUES[parseLevel(line)] ?? 20) < threshold) return false
      if (kw && !line.toLowerCase().includes(kw)) return false
      return true
    })
  }, [logs, logLevel, searchText])

  // 自动滚动
  useEffect(() => {
    if (autoScroll && containerRef.current)
      containerRef.current.scrollTop = containerRef.current.scrollHeight
  }, [filteredLogs, autoScroll])

  const handleCopy = () => {
    const text = filteredLogs.join('\n')
    navigator.clipboard.writeText(text)
      .then(() => messageApi.success(t('common.copied', '已复制'))).catch(() => {})
  }

  return (
    <Drawer
      title={
        <Space>
          {t('logs.liveTitle', '实时日志')}
          {connected
            ? <Tag color="success">{t('logs.connected', '已连接')}</Tag>
            : <Tag color="error">{t('logs.disconnected', '未连接')}</Tag>}
          <Text type="secondary" style={{ fontSize: 12 }}>{filteredLogs.length} / {logs.length}</Text>
        </Space>
      }
      placement="right"
      width={780}
      open={open}
      onClose={onClose}
      destroyOnClose
    >
      {ctxHolder}
      {/* 工具栏 */}
      <div style={{
        marginBottom: 12, display: 'flex', alignItems: 'center',
        justifyContent: 'space-between', flexWrap: 'wrap', gap: 8,
      }}>
        <Space wrap>
          <Select size="small" value={logLevel} onChange={setLogLevel} style={{ width: 110 }}
            options={[
              { value: 'DEBUG',   label: <span style={{ color: getLevelColor('DEBUG', isDark) }}>DEBUG</span> },
              { value: 'INFO',    label: <span style={{ color: getLevelColor('INFO', isDark) }}>INFO</span> },
              { value: 'WARNING', label: <span style={{ color: getLevelColor('WARNING', isDark) }}>WARNING</span> },
              { value: 'ERROR',   label: <span style={{ color: getLevelColor('ERROR', isDark) }}>ERROR</span> },
            ]}
          />
          <Input size="small" placeholder={t('logs.searchPlaceholder', '搜索日志...')}
            prefix={<SearchOutlined />} value={searchText}
            onChange={e => setSearchText(e.target.value)} allowClear style={{ width: 180 }}
          />
        </Space>
        <Space>
          <Text style={{ color: tc.labelColor, fontSize: 12 }}>{t('logs.autoScroll', '自动滚动')}</Text>
          <Switch size="small" checked={autoScroll} onChange={setAutoScroll} />
          <Tooltip title={t('logs.scrollToBottom', '滚到底部')}>
            <Button size="small" icon={<VerticalAlignBottomOutlined />}
              onClick={() => containerRef.current && (containerRef.current.scrollTop = containerRef.current.scrollHeight)} />
          </Tooltip>
          <Tooltip title={t('common.copy', '复制')}>
            <Button size="small" icon={<CopyOutlined />} onClick={handleCopy} />
          </Tooltip>
          <Tooltip title={t('logs.clear', '清空')}>
            <Button size="small" icon={<ClearOutlined />} onClick={() => setLogs([])} />
          </Tooltip>
        </Space>
      </div>
      {/* 日志内容 */}
      <div ref={containerRef} style={{
        height: 'calc(100% - 50px)', overflow: 'auto', background: tc.logBg,
        borderRadius: 6, padding: '12px 16px',
        fontFamily: "'JetBrains Mono','Fira Code','Consolas',monospace", fontSize: 12, lineHeight: 1.7,
      }}>
        {filteredLogs.length === 0 && (
          <Text style={{ color: tc.emptyColor }}>{t('logs.waitingLogs', '等待日志...')}</Text>
        )}
        {filteredLogs.map((line, i) => (
          <div key={i} style={{ color: getLevelColor(parseLevel(line), isDark), whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
            {searchText ? highlightText(line, searchText, isDark) : line}
          </div>
        ))}
      </div>
    </Drawer>
  )
}

