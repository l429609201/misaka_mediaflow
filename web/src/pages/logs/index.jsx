// src/pages/logs/index.jsx
// 日志中心 — 实时日志（SSE）+ 历史文件日志（按级别过滤）

import { useEffect, useState, useRef, useCallback } from 'react'
import {
  Card, Select, Button, Space, Input, Row, Col,
  Typography, Badge, Segmented,
} from 'antd'
import {
  ReloadOutlined, ClearOutlined, PauseOutlined, PlayCircleOutlined,
  FileTextOutlined, ThunderboltOutlined,
} from '@ant-design/icons'
import { useTranslation } from 'react-i18next'
import { systemApi } from '@/apis'
import { useThemeContext } from '@/ThemeProvider'
import LevelSegmented, { LEVEL_SHOW_MAP } from '@/components/LevelSegmented'

const { Text } = Typography

const LEVEL_COLORS = {
  DEBUG: '#888888', INFO: '#1677ff', WARNING: '#fa8c16',
  ERROR: '#ff4d4f', CRITICAL: '#a8071a',
}

/** 从日志行文本解析级别 */
function parseLevel(line) {
  if (line.includes('[CRITICAL]')) return 'CRITICAL'
  if (line.includes('[ERROR]'))    return 'ERROR'
  if (line.includes('[WARNING]') || line.includes('[WARN]')) return 'WARNING'
  if (line.includes('[INFO]'))     return 'INFO'
  if (line.includes('[DEBUG]'))    return 'DEBUG'
  return 'INFO'
}

export const Tasks = () => {
  const { t } = useTranslation()
  const { isDark } = useThemeContext()

  // ── 模式：realtime=实时SSE, file=历史文件
  const [mode, setMode]   = useState('realtime')

  // ── 三档级别滑动选择器（默认 INFO）
  const [levelSlider, setLevelSlider] = useState('INFO')

  // ── 关键字搜索
  const [keyword, setKeyword] = useState('')

  // ── 实时模式
  const [lines, setLines]           = useState([])
  const [paused, setPaused]         = useState(false)
  const [connected, setConnected]   = useState(false)
  const pausedRef = useRef(false)
  const esRef     = useRef(null)
  const bottomRef = useRef(null)
  const linesRef  = useRef([])
  const autoScroll = useRef(true)
  // 是否曾经成功连接过（用于区分首次连接 vs 重连，重连时自动清空日志）
  const wasConnectedRef = useRef(false)

  // ── 文件模式
  const [fileList, setFileList]       = useState([])
  const [selFile, setSelFile]         = useState('')
  const [fileLines, setFileLines]     = useState([])
  const [fileLoading, setFileLoading] = useState(false)
  const [tailCount, setTailCount]     = useState(500)

  // ── 实时 SSE 连接
  const connectSSE = useCallback(() => {
    if (esRef.current) { esRef.current.close() }
    const token = localStorage.getItem('token') || ''
    const url = `/api/v1/system/logs/stream?token=${encodeURIComponent(token)}`
    const es = new EventSource(url)
    esRef.current = es
    es.onopen = () => {
      setConnected(true)
      if (wasConnectedRef.current) {
        // 曾经成功连接过，再次 onopen → 服务重启 / 断线重连，自动清空旧日志
        linesRef.current = []
        setLines([])
      }
      wasConnectedRef.current = true
    }
    es.onerror = () => setConnected(false)
    es.onmessage = (e) => {
      if (pausedRef.current) return
      const text = e.data?.trim()
      if (!text) return
      linesRef.current = [text, ...linesRef.current].slice(0, 1000)
      setLines([...linesRef.current])
      if (autoScroll.current && bottomRef.current) {
        bottomRef.current.scrollIntoView({ behavior: 'smooth' })
      }
    }
    return es
  }, [])

  useEffect(() => {
    if (mode === 'realtime') {
      wasConnectedRef.current = false   // 切换到实时模式时重置，首次进入不触发清空
      connectSSE()
      return () => { esRef.current?.close(); setConnected(false) }
    }
  }, [mode, connectSSE])

  // ── 历史文件模式
  const fetchFileList = useCallback(async () => {
    try {
      const { data } = await systemApi.getLogFiles()
      const files = data?.files || []
      setFileList(files)
      if (files.length && !selFile) setSelFile(files[0].filename)
    } catch { /* ignore */ }
  }, [selFile])

  const fetchFileContent = useCallback(async () => {
    if (!selFile) return
    setFileLoading(true)
    try {
      const { data } = await systemApi.getLogFileContent(selFile, tailCount)
      setFileLines((data?.lines || []).slice().reverse())  // 最新在下方
    } catch { /* ignore */ }
    finally { setFileLoading(false) }
  }, [selFile, tailCount])

  useEffect(() => { if (mode === 'file') fetchFileList() }, [mode])
  useEffect(() => { if (mode === 'file' && selFile) fetchFileContent() }, [mode, selFile, tailCount])

  // ── 前端过滤
  const getFilteredLines = (rawLines) => rawLines.filter(line => {
    const enabled = LEVEL_SHOW_MAP[levelSlider]
    if (!enabled.has(parseLevel(line))) return false
    if (keyword && !line.toLowerCase().includes(keyword.toLowerCase())) return false
    return true
  })

  const displayLines = getFilteredLines(mode === 'realtime' ? lines : fileLines)

  return (
    <Card
      title={
        <Space>
          <span>日志中心</span>
          {mode === 'realtime' && (
            <Badge
              status={connected ? 'processing' : 'error'}
              text={connected ? '已连接' : '未连接'}
            />
          )}
        </Space>
      }
      extra={
        <Space>
          {/* 模式切换 — 滑动开关 */}
          <Segmented
            value={mode}
            onChange={setMode}
            size="small"
            options={[
              {
                value: 'realtime',
                label: (
                  <Space size={4}>
                    <ThunderboltOutlined />
                    实时
                  </Space>
                ),
              },
              {
                value: 'file',
                label: (
                  <Space size={4}>
                    <FileTextOutlined />
                    历史
                  </Space>
                ),
              },
            ]}
          />

          {/* 级别过滤 — 三档滑动选择器 */}
          <LevelSegmented value={levelSlider} onChange={setLevelSlider} isDark={isDark} />

          {/* 关键字搜索 */}
          <Input
            value={keyword}
            onChange={e => setKeyword(e.target.value)}
            placeholder="关键字过滤"
            allowClear
            style={{ width: 150 }}
            size="small"
          />

          {/* 文件模式专属控件 */}
          {mode === 'file' && (
            <>
              <Select
                value={selFile}
                onChange={setSelFile}
                options={fileList.map(f => ({ value: f.filename, label: f.filename }))}
                style={{ width: 200 }}
                size="small"
                placeholder="选择日志文件"
              />
              <Select
                value={tailCount}
                onChange={setTailCount}
                size="small"
                style={{ width: 100 }}
                options={[
                  { value: 200,  label: '最后200行' },
                  { value: 500,  label: '最后500行' },
                  { value: 1000, label: '最后1000行' },
                  { value: 2000, label: '最后2000行' },
                ]}
              />
              <Button size="small" icon={<ReloadOutlined />} onClick={fetchFileContent} loading={fileLoading}>刷新</Button>
            </>
          )}

          {/* 实时模式专属控件 */}
          {mode === 'realtime' && (
            <>
              <Button size="small"
                icon={paused ? <PlayCircleOutlined /> : <PauseOutlined />}
                onClick={() => { pausedRef.current = !paused; setPaused(!paused) }}
              >{paused ? '继续' : '暂停'}</Button>
              <Button size="small" icon={<ClearOutlined />}
                onClick={() => { linesRef.current = []; setLines([]) }}>清空</Button>
              <Button size="small" icon={<ReloadOutlined />} onClick={connectSSE}>重连</Button>
            </>
          )}
        </Space>
      }
    >
      {/* 统计栏 */}
      <Row style={{ marginBottom: 6 }}>
        <Col>
          <Text type="secondary" style={{ fontSize: 12 }}>
            显示 {displayLines.length} 条
            {`（级别 ≥ ${levelSlider}）`}
            {keyword ? `（含「${keyword}」）` : ''}
            {mode === 'file'
              ? ' ｜ 历史文件为后台写入的完整 DEBUG 日志'
              : ' ｜ 实时日志最多保留 1000 条'}
          </Text>
        </Col>
      </Row>

      {/* 日志内容区 */}
      <div
        style={{
          height: 580, overflowY: 'auto', background: '#fafafa',
          border: '1px solid #f0f0f0', borderRadius: 6,
          padding: '6px 10px',
        }}
        onScroll={e => {
          const el = e.target
          autoScroll.current = el.scrollTop + el.clientHeight >= el.scrollHeight - 30
        }}
      >
        {displayLines.length === 0
          ? <Text type="secondary" style={{ fontSize: 12 }}>
              {paused ? '（已暂停，点击「继续」恢复）' : '暂无匹配日志'}
            </Text>
          : displayLines.map((line, i) => {
              const level = parseLevel(line)
              const color = LEVEL_COLORS[level] || '#555'
              return (
                <div key={i} style={{
                  fontFamily: 'monospace', fontSize: 12, lineHeight: '1.6',
                  padding: '1px 0', borderBottom: '1px solid #f0f0f0',
                  color, wordBreak: 'break-all', whiteSpace: 'pre-wrap',
                }}>
                  {line}
                </div>
              )
            })
        }
        <div ref={bottomRef} />
      </div>
    </Card>
  )
}


export default Tasks
