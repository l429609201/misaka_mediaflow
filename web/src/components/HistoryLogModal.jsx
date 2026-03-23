// src/components/HistoryLogModal.jsx — 对标弹幕库 HistoryLogModal
// 卡片行 + marginBottom间距 + Switch级别过滤 + 级别颜色左边框 + 搜索高亮 + 复制

import { useCallback, useEffect, useState, useMemo, useRef } from 'react'
import { Modal, Button, Tooltip, Input, Select, Space, Spin, Switch, Tag, Typography, message } from 'antd'
import {
  CopyOutlined, ReloadOutlined, SearchOutlined,
  VerticalAlignTopOutlined, VerticalAlignBottomOutlined,
} from '@ant-design/icons'
import { useTranslation } from 'react-i18next'
import { systemApi } from '@/apis'
import { useThemeContext } from '@/ThemeProvider'

const { Text } = Typography
const MEMORY_LOG_KEY = '__memory__'
const ALL_LEVELS = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']

const LEVEL_COLOR = {
  dark:  { CRITICAL: '#ff1744', ERROR: '#ff4d4f', WARNING: '#faad14', INFO: '#52c41a', DEBUG: '#1677ff' },
  light: { CRITICAL: '#c62828', ERROR: '#d32f2f', WARNING: '#e65100', INFO: '#2e7d32', DEBUG: '#1565c0' },
}
const LEVEL_BG = {
  dark:  { CRITICAL: 'rgba(255,23,68,0.08)',  ERROR: 'rgba(255,77,79,0.07)',  WARNING: 'rgba(250,173,20,0.07)', INFO: 'rgba(82,196,26,0.05)',  DEBUG: 'rgba(22,119,255,0.05)' },
  light: { CRITICAL: 'rgba(198,40,40,0.06)',  ERROR: 'rgba(211,47,47,0.05)', WARNING: 'rgba(230,81,0,0.06)',   INFO: 'rgba(46,125,50,0.04)',  DEBUG: 'rgba(21,101,192,0.04)' },
}
const getLevelColor = (level, isDark) => ((isDark ? LEVEL_COLOR.dark : LEVEL_COLOR.light)[level]) ?? (isDark ? '#888' : '#666')
const getLevelBg    = (level, isDark) => ((isDark ? LEVEL_BG.dark    : LEVEL_BG.light)[level])    ?? 'transparent'
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
const formatSize = (bytes) => {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export default function HistoryLogModal({ open, onClose }) {
  const { t } = useTranslation()
  const { isDark, colorPrimary } = useThemeContext()

  const [logs, setLogs]           = useState([])
  const [loading, setLoading]     = useState(false)
  const [search, setSearch]       = useState('')
  const [logFiles, setLogFiles]   = useState([])
  const [selectedFile, setSelectedFile] = useState(MEMORY_LOG_KEY)
  // 默认 INFO 及以上开启，DEBUG 关闭
  const [levelOn, setLevelOn]     = useState({ DEBUG: false, INFO: true, WARNING: true, ERROR: true, CRITICAL: true })
  const [hoveredIdx, setHoveredIdx] = useState(null)
  const [messageApi, ctxHolder]   = message.useMessage()
  const topRef    = useRef(null)
  const bottomRef = useRef(null)

  const logBg    = isDark ? '#141414' : '#f5f5f5'
  const cardBg   = isDark ? '#1f1f1f' : '#ffffff'
  const textClr  = isDark ? 'rgba(255,255,255,0.82)' : '#333'
  const labelClr = isDark ? '#888' : '#666'
  const barBg    = isDark ? '#1a1a1a' : '#fafafa'
  const barBorder= isDark ? '#2a2a2a' : '#e8e8e8'

  const fetchLogFiles = () => systemApi.getLogFiles()
    .then(({ data }) => setLogFiles(Array.isArray(data) ? data : [])).catch(() => {})

  const fetchLogs = () => {
    setLoading(true)
    const req = selectedFile === MEMORY_LOG_KEY
      ? systemApi.getMemoryLogs()
      : systemApi.getLogFileContent(selectedFile)
    req.then(({ data }) => setLogs(Array.isArray(data) ? data : (data?.lines ?? data?.data ?? [])))
       .catch(() => messageApi.error(t('tasks.fetchFail', '获取日志失败')))
       .finally(() => setLoading(false))
  }

  useEffect(() => { if (open) { setSelectedFile(MEMORY_LOG_KEY); setSearch(''); fetchLogFiles() } }, [open])
  useEffect(() => { if (open) fetchLogs() }, [open, selectedFile])

  const toggleLevel = (lv) => setLevelOn(prev => ({ ...prev, [lv]: !prev[lv] }))

  const filteredLogs = useMemo(() => {
    const kw = search.toLowerCase()
    return logs.filter(line => levelOn[parseLevel(line)] && (!kw || line.toLowerCase().includes(kw)))
  }, [logs, search, levelOn])

  const copyAll  = () => navigator.clipboard.writeText(filteredLogs.join('\n')).then(() => messageApi.success(t('common.copied', '已复制'))).catch(() => {})
  const copyLine = useCallback((line) => navigator.clipboard.writeText(line).then(() => messageApi.success(t('common.copied', '已复制'))).catch(() => {}), [messageApi, t])

  const fileOptions = [
    { value: MEMORY_LOG_KEY, label: `📋 ${t('tasks.memoryLog', '内存日志')} (${t('tasks.latest', '最新')})` },
    ...logFiles.map(f => ({ value: f.name, label: `📄 ${f.name} (${formatSize(f.size)})` })),
  ]

  return (
    <Modal title={<Space>{t('tasks.historyTitle', '历史日志')}<Tag>{filteredLogs.length} {t('tasks.lines', '行')}</Tag></Space>}
      open={open} onCancel={onClose} footer={null} width={980} centered destroyOnClose
      styles={{ body: { padding: 0 } }}
    >
      {ctxHolder}
      {/* 级别 Switch 工具栏 */}
      <div style={{ padding: '8px 16px', display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', background: barBg, borderBottom: `1px solid ${barBorder}` }}>
        <Text style={{ color: labelClr, fontSize: 12, whiteSpace: 'nowrap', marginRight: 4 }}>{t('tasks.levelFilter', '级别过滤')}：</Text>
        {ALL_LEVELS.map(lv => {
          const clr = getLevelColor(lv, isDark)
          const on  = levelOn[lv]
          return (
            <Space key={lv} size={5} style={{ alignItems: 'center' }}>
              <Switch size="small" checked={on} onChange={() => toggleLevel(lv)} style={on ? { backgroundColor: clr } : {}} />
              <Text style={{ fontSize: 12, fontWeight: on ? 700 : 400, userSelect: 'none', color: on ? clr : (isDark ? '#3a3a3a' : '#ccc'), transition: 'color 0.2s' }}>{lv}</Text>
            </Space>
          )
        })}
      </div>
      {/* 文件选择 + 搜索 + 操作 */}
      <div style={{ padding: '8px 16px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8, background: barBg, borderBottom: `1px solid ${barBorder}` }}>
        <Space wrap>
          <Select size="small" value={selectedFile} onChange={setSelectedFile} style={{ width: 260 }} options={fileOptions} />
          <Input size="small" placeholder={t('tasks.searchPlaceholder', '搜索日志...')}
            prefix={<SearchOutlined style={{ color: colorPrimary }} />}
            value={search} onChange={e => setSearch(e.target.value)} allowClear style={{ width: 200 }} />
        </Space>
        <Space>
          <Tooltip title={t('common.refresh', '刷新')}><Button size="small" icon={<ReloadOutlined />} loading={loading} onClick={fetchLogs} /></Tooltip>
          <Tooltip title={t('logs.scrollToTop', '滚到顶部')}><Button size="small" icon={<VerticalAlignTopOutlined />} onClick={() => topRef.current?.scrollIntoView({ behavior: 'smooth' })} /></Tooltip>
          <Tooltip title={t('tasks.scrollToBottom', '滚到底部')}><Button size="small" icon={<VerticalAlignBottomOutlined />} onClick={() => bottomRef.current?.scrollIntoView({ behavior: 'smooth' })} /></Tooltip>
          <Tooltip title={t('common.copy', '复制全部')}><Button size="small" icon={<CopyOutlined />} onClick={copyAll} /></Tooltip>
        </Space>
      </div>
      {/* 日志内容区 — 弹幕库风格：卡片行 + marginBottom间距 + 级别颜色左边框 */}
      <Spin spinning={loading}>
        <div style={{ height: 500, overflowY: 'auto', background: logBg, padding: '8px',
          fontFamily: "'JetBrains Mono','Fira Code','Consolas',monospace", fontSize: 12, lineHeight: 1.7 }}>
          <div ref={topRef} />
          {filteredLogs.length === 0 && !loading && (
            <div style={{ padding: '24px', textAlign: 'center', color: isDark ? '#555' : '#bbb' }}>{t('tasks.noLogs', '暂无日志')}</div>
          )}
          {filteredLogs.map((line, i) => {
            const level   = parseLevel(line)
            const clr     = getLevelColor(level, isDark)
            const bg      = getLevelBg(level, isDark)
            const isHover = hoveredIdx === i
            return (
              <div key={i}
                onMouseEnter={() => setHoveredIdx(i)} onMouseLeave={() => setHoveredIdx(null)}
                style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between',
                  marginBottom: 4, padding: '5px 8px 5px 10px', borderRadius: 6,
                  background: isHover ? (isDark ? '#252525' : '#ebebeb') : (bg || cardBg),
                  borderLeft: `3px solid ${clr}`,
                  boxShadow: isDark ? 'none' : '0 1px 2px rgba(0,0,0,0.04)',
                  transition: 'background 0.15s', cursor: 'default',
                }}
              >
                <span style={{ color: textClr, whiteSpace: 'pre-wrap', wordBreak: 'break-all', flex: 1 }}>
                  {line.split(new RegExp(`(\\[${level}\\]|\\[WARN\\])`, 'g')).map((part, pi) =>
                    (part === `[${level}]` || part === '[WARN]')
                      ? <span key={pi} style={{ color: clr, fontWeight: 700 }}>{part}</span>
                      : (search ? highlight(part, search, isDark) : part)
                  )}
                </span>
                <Tooltip title={t('common.copy', '复制')}>
                  <Button type="text" size="small" icon={<CopyOutlined />} onClick={() => copyLine(line)}
                    style={{ opacity: isHover ? 1 : 0, transition: 'opacity 0.15s', color: isDark ? '#888' : '#999',
                      flexShrink: 0, marginLeft: 6, padding: '0 4px', height: 20 }} />
                </Tooltip>
              </div>
            )
          })}
          <div ref={bottomRef} />
        </div>
      </Spin>
    </Modal>
  )
}

