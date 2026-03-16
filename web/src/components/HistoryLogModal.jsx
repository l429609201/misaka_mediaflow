// src/components/HistoryLogModal.jsx
// 历史日志弹窗 — 对齐弹幕库 HistoryLogModal
// 功能：内存日志/历史文件切换 + 搜索 + 复制 + 刷新

import { useEffect, useState, useMemo, useRef } from 'react'
import { Modal, Button, Tooltip, Input, Select, Space, Spin, Tag, Typography, message } from 'antd'
import {
  CopyOutlined, ReloadOutlined, SearchOutlined,
  VerticalAlignTopOutlined, VerticalAlignBottomOutlined,
} from '@ant-design/icons'
import { useTranslation } from 'react-i18next'
import { systemApi } from '@/apis'
import { useThemeContext } from '@/ThemeProvider'
import { highlightText } from '@/utils/highlightText'

const { Text } = Typography

const MEMORY_LOG_KEY = '__memory__'

const getLevelColor = (line, isDark) => {
  const dark  = { CRITICAL: '#ff1744', ERROR: '#ff4d4f', WARNING: '#faad14', INFO: '#52c41a', DEBUG: '#1677ff' }
  const light = { CRITICAL: '#c62828', ERROR: '#d32f2f', WARNING: '#e65100', INFO: '#2e7d32', DEBUG: '#1565c0' }
  const colors = isDark ? dark : light
  if (line.includes('[CRITICAL]')) return colors.CRITICAL
  if (line.includes('[ERROR]')) return colors.ERROR
  if (line.includes('[WARNING]') || line.includes('[WARN]')) return colors.WARNING
  if (line.includes('[INFO]')) return colors.INFO
  if (line.includes('[DEBUG]')) return colors.DEBUG
  return isDark ? '#d4d4d4' : '#333'
}

const getThemeColors = (isDark) => isDark
  ? { toolbarBg: '#141414', toolbarBorder: '#303030', logBg: '#1e1e1e', emptyColor: '#666' }
  : { toolbarBg: '#fafafa', toolbarBorder: '#e8e8e8', logBg: '#f5f5f5', emptyColor: '#999' }

const formatSize = (bytes) => {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export default function HistoryLogModal({ open, onClose }) {
  const { t } = useTranslation()
  const { isDark } = useThemeContext()
  const tc = getThemeColors(isDark)
  const [logs, setLogs] = useState([])
  const [loading, setLoading] = useState(false)
  const [search, setSearch] = useState('')
  const [logFiles, setLogFiles] = useState([])
  const [selectedFile, setSelectedFile] = useState(MEMORY_LOG_KEY)
  const [messageApi, ctxHolder] = message.useMessage()
  const topRef = useRef(null)
  const bottomRef = useRef(null)

  // 加载日志文件列表
  const fetchLogFiles = () => {
    systemApi.getLogFiles()
      .then(({ data }) => setLogFiles(Array.isArray(data) ? data : []))
      .catch(() => {})
  }

  // 加载日志内容
  const fetchLogs = () => {
    setLoading(true)
    if (selectedFile === MEMORY_LOG_KEY) {
      systemApi.getMemoryLogs()
        .then(({ data }) => {
          const arr = Array.isArray(data) ? data : (data?.lines ?? data?.data ?? [])
          setLogs(arr)
        })
        .catch(() => messageApi.error(t('logs.fetchFail', '获取日志失败')))
        .finally(() => setLoading(false))
    } else {
      systemApi.getLogFileContent(selectedFile)
        .then(({ data }) => {
          const arr = Array.isArray(data) ? data : (data?.lines ?? data?.data ?? [])
          setLogs(arr)
        })
        .catch(() => messageApi.error(t('logs.fetchFileFail', '获取日志文件失败')))
        .finally(() => setLoading(false))
    }
  }

  useEffect(() => {
    if (open) {
      setSelectedFile(MEMORY_LOG_KEY)
      setSearch('')
      fetchLogFiles()
    }
  }, [open])

  useEffect(() => {
    if (open) fetchLogs()
  }, [open, selectedFile])

  // 搜索过滤
  const filteredLogs = useMemo(() => {
    if (!search) return logs
    const kw = search.toLowerCase()
    return logs.filter(line => line.toLowerCase().includes(kw))
  }, [logs, search])

  const handleCopy = () => {
    const text = filteredLogs.join('\n')
    navigator.clipboard.writeText(text)
      .then(() => messageApi.success(t('common.copied', '已复制'))).catch(() => {})
  }

  // 构建文件选择选项
  const fileOptions = [
    { value: MEMORY_LOG_KEY, label: t('logs.memoryLog', '📋 内存日志 (最新)') },
    ...logFiles.map(f => ({
      value: f.name,
      label: `📄 ${f.name} (${formatSize(f.size)})`,
    }))
  ]

  return (
    <Modal
      title={
        <Space>
          {t('logs.historyTitle', '历史日志')}
          <Tag>{filteredLogs.length} {t('logs.lines', '行')}</Tag>
        </Space>
      }
      open={open} onCancel={onClose} footer={null}
      width={960} centered destroyOnClose
      styles={{ body: { padding: 0 } }}
    >
      {ctxHolder}
      {/* 工具栏 */}
      <div style={{
        padding: '8px 16px', display: 'flex', alignItems: 'center',
        justifyContent: 'space-between', flexWrap: 'wrap', gap: 8,
        borderBottom: `1px solid ${tc.toolbarBorder}`, background: tc.toolbarBg,
      }}>
        <Space wrap>
          <Select
            size="small"
            value={selectedFile}
            onChange={setSelectedFile}
            style={{ width: 260 }}
            options={fileOptions}
          />
          <Input
            size="small"
            placeholder={t('logs.searchPlaceholder', '搜索日志...')}
            prefix={<SearchOutlined />}
            value={search}
            onChange={e => setSearch(e.target.value)}
            allowClear
            style={{ width: 200 }}
          />
        </Space>
        <Space>
          <Tooltip title={t('common.refresh', '刷新')}>
            <Button size="small" icon={<ReloadOutlined />} loading={loading} onClick={fetchLogs} />
          </Tooltip>
          <Tooltip title={t('logs.scrollToTop', '滚到顶部')}>
            <Button size="small" icon={<VerticalAlignTopOutlined />}
              onClick={() => topRef.current?.scrollIntoView({ behavior: 'smooth' })} />
          </Tooltip>
          <Tooltip title={t('logs.scrollToBottom', '滚到底部')}>
            <Button size="small" icon={<VerticalAlignBottomOutlined />}
              onClick={() => bottomRef.current?.scrollIntoView({ behavior: 'smooth' })} />
          </Tooltip>
          <Tooltip title={t('common.copy', '复制')}>
            <Button size="small" icon={<CopyOutlined />} onClick={handleCopy} />
          </Tooltip>
        </Space>
      </div>
      {/* 日志内容 */}
      <Spin spinning={loading}>
        <div style={{
          height: 500, overflow: 'auto', background: tc.logBg, padding: '12px 16px',
          fontFamily: "'JetBrains Mono','Fira Code','Consolas',monospace", fontSize: 12, lineHeight: 1.7,
        }}>
          <div ref={topRef} />
          {filteredLogs.length === 0 && !loading && (
            <Text style={{ color: tc.emptyColor }}>{t('logs.noLogs', '暂无日志')}</Text>
          )}
          {filteredLogs.map((line, i) => (
            <div key={i} style={{ color: getLevelColor(line, isDark), whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
              {search ? highlightText(line, search, isDark) : line}
            </div>
          ))}
          <div ref={bottomRef} />
        </div>
      </Spin>
    </Modal>
  )
}

