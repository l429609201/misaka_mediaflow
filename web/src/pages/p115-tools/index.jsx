// src/pages/p115-tools/index.jsx
// 115 工具页 — 全量STRM / 增量STRM / 生活事件监控 / 整理分类

import { useEffect, useState, useCallback } from 'react'
import {
  Card, Tabs, Form, Input, Button, Space, Alert, message,
  Tag, Statistic, Row, Col, Divider, Switch, InputNumber,
  Table, Typography, Badge, Tooltip,
} from 'antd'
import {
  SyncOutlined, PlayCircleOutlined, PauseCircleOutlined,
  FolderAddOutlined, ThunderboltOutlined, PlusOutlined, DeleteOutlined,
  CheckCircleOutlined, ClockCircleOutlined,
} from '@ant-design/icons'
import { p115StrmApi } from '@/apis'

const { Text } = Typography

// ─────────────────────── 工具函数 ───────────────────────

const tsToStr = (ts) => ts ? new Date(ts * 1000).toLocaleString('zh-CN') : '—'

const StatTag = ({ value, label, color }) => (
  <Tag color={color} style={{ fontSize: 13, padding: '2px 10px' }}>
    {label}: <b>{value ?? 0}</b>
  </Tag>
)

// ─────────────────────── STRM 同步 Tab ───────────────────────

const StrmSyncTab = () => {
  const [config, setConfig] = useState({ sync_pairs: [], file_extensions: 'mp4,mkv,avi,ts,iso,mov,m2ts', strm_link_host: '' })
  const [status, setStatus] = useState({})
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [syncPairs, setSyncPairs] = useState([])

  const fetchAll = useCallback(async () => {
    try {
      const [cfgRes, stRes] = await Promise.all([p115StrmApi.getSyncConfig(), p115StrmApi.getSyncStatus()])
      const cfg = cfgRes.data || {}
      setConfig(cfg)
      setSyncPairs(cfg.sync_pairs || [])
      setStatus(stRes.data || {})
    } catch { /* ignore */ }
  }, [])

  useEffect(() => { fetchAll() }, [fetchAll])

  const addPair = () => setSyncPairs(prev => [...prev, { cloud_path: '', strm_path: '' }])
  const removePair = (idx) => setSyncPairs(prev => prev.filter((_, i) => i !== idx))
  const updatePair = (idx, field, val) => setSyncPairs(prev => prev.map((p, i) => i === idx ? { ...p, [field]: val } : p))

  const handleSave = async () => {
    setSaving(true)
    try {
      await p115StrmApi.saveSyncConfig({ ...config, sync_pairs: syncPairs })
      message.success('配置已保存')
    } catch { message.error('保存失败') }
    finally { setSaving(false) }
  }

  const handleFullSync = async () => {
    setLoading(true)
    try {
      const res = await p115StrmApi.fullSync()
      if (res.data?.success) { message.success('全量同步已启动') }
      else { message.warning(res.data?.message || '启动失败') }
      setTimeout(fetchAll, 1500)
    } catch { message.error('请求失败') }
    finally { setLoading(false) }
  }

  const handleIncSync = async () => {
    setLoading(true)
    try {
      const res = await p115StrmApi.incSync()
      if (res.data?.success) { message.success('增量同步已启动') }
      else { message.warning(res.data?.message || '启动失败') }
      setTimeout(fetchAll, 1500)
    } catch { message.error('请求失败') }
    finally { setLoading(false) }
  }

  const isRunning = status.running
  const progress = status.progress || {}
  const lastFull = status.last_full_sync
  const lastInc = status.last_inc_sync
  const fullStats = status.last_full_sync_stats || {}
  const incStats = status.last_inc_sync_stats || {}

  return (
    <Space direction="vertical" style={{ width: '100%' }} size="middle">
      {/* 状态 */}
      <Card size="small" title="运行状态">
        <Row gutter={16}>
          <Col span={12}>
            <Statistic title="上次全量同步" value={tsToStr(lastFull)} />
            <Space size={4} wrap style={{ marginTop: 4 }}>
              <StatTag value={fullStats.created} label="生成" color="green" />
              <StatTag value={fullStats.skipped} label="跳过" color="default" />
              <StatTag value={fullStats.errors} label="失败" color="red" />
            </Space>
          </Col>
          <Col span={12}>
            <Statistic title="上次增量同步" value={tsToStr(lastInc)} />
            <Space size={4} wrap style={{ marginTop: 4 }}>
              <StatTag value={incStats.created} label="生成" color="green" />
              <StatTag value={incStats.skipped} label="跳过" color="default" />
              <StatTag value={incStats.errors} label="失败" color="red" />
            </Space>
          </Col>
        </Row>
        {isRunning && (
          <Alert style={{ marginTop: 12 }} type="info" showIcon
            message={`同步进行中… 已生成 ${progress.created || 0} 个 STRM`}
          />
        )}
      </Card>

      {/* 触发按钮 */}
      <Card size="small">
        <Space>
          <Button type="primary" icon={<ThunderboltOutlined />} loading={loading || isRunning} onClick={handleFullSync}>
            全量生成 STRM
          </Button>
          <Button icon={<SyncOutlined />} loading={loading || isRunning} onClick={handleIncSync}>
            增量生成 STRM
          </Button>
          <Button icon={<SyncOutlined spin={isRunning} />} onClick={fetchAll}>刷新状态</Button>
        </Space>
      </Card>

      {/* 配置 */}
      <Card size="small" title="同步配置">
        <Form layout="vertical">
          <Form.Item label="STRM 链接地址（留空自动检测）">
            <Input
              value={config.strm_link_host}
              placeholder="如 http://192.168.1.10:9906"
              onChange={e => setConfig(c => ({ ...c, strm_link_host: e.target.value }))}
            />
          </Form.Item>
          <Form.Item label="视频文件扩展名（逗号分隔）">
            <Input
              value={config.file_extensions}
              onChange={e => setConfig(c => ({ ...c, file_extensions: e.target.value }))}
            />
          </Form.Item>
          <Divider orientation="left" plain>同步路径对</Divider>
          {syncPairs.map((pair, idx) => (
            <Row gutter={8} key={idx} style={{ marginBottom: 8 }} align="middle">
              <Col flex="1">
                <Input
                  placeholder="115网盘路径（如 /媒体库）"
                  value={pair.cloud_path}
                  onChange={e => updatePair(idx, 'cloud_path', e.target.value)}
                />
              </Col>
              <Col flex="1">
                <Input
                  placeholder="本地STRM输出路径（如 /data/strm）"
                  value={pair.strm_path}
                  onChange={e => updatePair(idx, 'strm_path', e.target.value)}
                />
              </Col>
              <Col>
                <Button danger icon={<DeleteOutlined />} onClick={() => removePair(idx)} />
              </Col>
            </Row>
          ))}
          <Button icon={<PlusOutlined />} onClick={addPair} style={{ marginBottom: 12 }}>添加路径对</Button>
          <br />
          <Button type="primary" icon={<CheckCircleOutlined />} onClick={handleSave} loading={saving}>保存配置</Button>
        </Form>
      </Card>
    </Space>
  )
}

// ─────────────────────── 生活事件监控 Tab ───────────────────────

const MonitorTab = () => {
  const [config, setConfig] = useState({ enabled: false, poll_interval: 30, auto_inc_sync: true })
  const [status, setStatus] = useState({})
  const [saving, setSaving] = useState(false)

  const fetchAll = useCallback(async () => {
    try {
      const [cfgRes, stRes] = await Promise.all([p115StrmApi.getMonitorConfig(), p115StrmApi.getMonitorStatus()])
      setConfig(cfgRes.data || {})
      setStatus(stRes.data || {})
    } catch { /* ignore */ }
  }, [])

  useEffect(() => { fetchAll() }, [fetchAll])

  const handleSave = async () => {
    setSaving(true)
    try {
      await p115StrmApi.saveMonitorConfig(config)
      message.success('配置已保存')
    } catch { message.error('保存失败') }
    finally { setSaving(false) }
  }

  const handleToggle = async () => {
    try {
      if (status.running) {
        await p115StrmApi.stopMonitor()
        message.success('监控已停止')
      } else {
        await p115StrmApi.startMonitor()
        message.success('监控已启动')
      }
      setTimeout(fetchAll, 800)
    } catch { message.error('操作失败') }
  }

  const recentEvents = status.recent_events || []
  const evTypeMap = { 0: '上传', 1: '新建目录', 2: '删除', 4: '重命名', 5: '移动' }

  const eventCols = [
    { title: '事件类型', dataIndex: 'type', key: 'type', width: 100, render: v => evTypeMap[v] || v },
    { title: '文件名', dataIndex: 'file_name', key: 'file_name', ellipsis: true },
    { title: '时间', dataIndex: 'time', key: 'time', width: 180, render: v => tsToStr(v) },
  ]

  return (
    <Space direction="vertical" style={{ width: '100%' }} size="middle">
      <Card size="small" title="监控状态">
        <Row gutter={16} align="middle">
          <Col>
            <Badge status={status.running ? 'processing' : 'default'} text={status.running ? '运行中' : '未运行'} />
          </Col>
          <Col>
            <Text type="secondary">上次事件: {tsToStr(status.last_event_time)}</Text>
          </Col>
          <Col>
            <Button
              type={status.running ? 'default' : 'primary'}
              icon={status.running ? <PauseCircleOutlined /> : <PlayCircleOutlined />}
              onClick={handleToggle}
            >
              {status.running ? '停止监控' : '启动监控'}
            </Button>
          </Col>
          <Col>
            <Button icon={<SyncOutlined />} onClick={fetchAll}>刷新</Button>
          </Col>
        </Row>
      </Card>

      <Card size="small" title="监控配置">
        <Form layout="vertical">
          <Form.Item label="轮询间隔（秒）">
            <InputNumber
              min={10} max={3600}
              value={config.poll_interval}
              onChange={v => setConfig(c => ({ ...c, poll_interval: v }))}
            />
          </Form.Item>
          <Form.Item label="检测到新文件时自动触发增量同步">
            <Switch
              checked={config.auto_inc_sync}
              onChange={v => setConfig(c => ({ ...c, auto_inc_sync: v }))}
            />
          </Form.Item>
          <Button type="primary" icon={<CheckCircleOutlined />} onClick={handleSave} loading={saving}>保存配置</Button>
        </Form>
      </Card>

      <Card size="small" title={`最近事件（${recentEvents.length} 条）`}>
        <Table
          dataSource={recentEvents}
          columns={eventCols}
          rowKey={(r, i) => i}
          size="small"
          pagination={{ pageSize: 10, size: 'small' }}
          locale={{ emptyText: '暂无事件' }}
        />
      </Card>
    </Space>
  )
}

// ─────────────────────── 整理分类 Tab ───────────────────────

const OrganizeTab = () => {
  const [config, setConfig] = useState({
    source_paths: [],
    target_root: '',
    dry_run: false,
    categories: { 电影: '电影', 剧集: '剧集', 动漫: '动漫', 纪录片: '纪录片', 综艺: '综艺' },
  })
  const [status, setStatus] = useState({})
  const [saving, setSaving] = useState(false)
  const [running, setRunning] = useState(false)
  const [sourcePaths, setSourcePaths] = useState([])

  const fetchAll = useCallback(async () => {
    try {
      const [cfgRes, stRes] = await Promise.all([p115StrmApi.getOrganizeConfig(), p115StrmApi.getOrganizeStatus()])
      const cfg = cfgRes.data || {}
      setConfig(cfg)
      setSourcePaths(cfg.source_paths || [])
      setStatus(stRes.data || {})
    } catch { /* ignore */ }
  }, [])

  useEffect(() => { fetchAll() }, [fetchAll])

  const handleSave = async () => {
    setSaving(true)
    try {
      await p115StrmApi.saveOrganizeConfig({ ...config, source_paths: sourcePaths })
      message.success('配置已保存')
    } catch { message.error('保存失败') }
    finally { setSaving(false) }
  }

  const handleRun = async () => {
    setRunning(true)
    try {
      const res = await p115StrmApi.runOrganize()
      if (res.data?.success) { message.success('整理任务已启动') }
      else { message.warning(res.data?.message || '启动失败') }
      setTimeout(fetchAll, 1500)
    } catch { message.error('请求失败') }
    finally { setRunning(false) }
  }

  const st = status || {}
  const lastStats = st.last_organize_stats || {}

  return (
    <Space direction="vertical" style={{ width: '100%' }} size="middle">
      <Card size="small" title="整理状态">
        <Row gutter={16}>
          <Col>
            <Statistic title="上次整理" value={tsToStr(st.last_organize)} />
          </Col>
          <Col>
            <Space size={4} wrap style={{ marginTop: 20 }}>
              <StatTag value={lastStats.moved} label="已移动" color="green" />
              <StatTag value={lastStats.skipped} label="跳过" color="default" />
              <StatTag value={lastStats.errors} label="失败" color="red" />
            </Space>
          </Col>
        </Row>
        {st.running && <Alert style={{ marginTop: 8 }} type="info" showIcon message="整理进行中…" />}
      </Card>

      <Card size="small">
        <Space>
          <Button type="primary" icon={<FolderAddOutlined />} loading={running || st.running} onClick={handleRun}>
            开始整理
          </Button>
          <Button icon={<SyncOutlined />} onClick={fetchAll}>刷新状态</Button>
        </Space>
      </Card>

      <Card size="small" title="整理配置">
        <Alert
          style={{ marginBottom: 12 }}
          type="info" showIcon
          message="整理功能会将源目录中的文件按分类规则移动到目标目录。开启「试运行」可预览效果而不实际移动。"
        />
        <Form layout="vertical">
          <Form.Item label="目标根目录（115网盘路径，如 /整理后）">
            <Input
              value={config.target_root}
              placeholder="/整理后"
              onChange={e => setConfig(c => ({ ...c, target_root: e.target.value }))}
            />
          </Form.Item>
          <Form.Item label="试运行（只记录日志，不实际移动）">
            <Switch checked={config.dry_run} onChange={v => setConfig(c => ({ ...c, dry_run: v }))} />
          </Form.Item>
          <Divider orientation="left" plain>源目录</Divider>
          {sourcePaths.map((p, idx) => (
            <Row gutter={8} key={idx} style={{ marginBottom: 8 }} align="middle">
              <Col flex="1">
                <Input
                  placeholder="115网盘路径（如 /待整理）"
                  value={p}
                  onChange={e => setSourcePaths(prev => prev.map((v, i) => i === idx ? e.target.value : v))}
                />
              </Col>
              <Col>
                <Button danger icon={<DeleteOutlined />} onClick={() => setSourcePaths(prev => prev.filter((_, i) => i !== idx))} />
              </Col>
            </Row>
          ))}
          <Button icon={<PlusOutlined />} onClick={() => setSourcePaths(prev => [...prev, ''])} style={{ marginBottom: 12 }}>
            添加源目录
          </Button>
          <br />
          <Divider orientation="left" plain>分类规则（分类名 → 目标子目录）</Divider>
          {Object.entries(config.categories || {}).map(([cat, sub]) => (
            <Row gutter={8} key={cat} style={{ marginBottom: 8 }} align="middle">
              <Col span={6}><Tag color="blue">{cat}</Tag></Col>
              <Col flex="1">
                <Input
                  value={sub}
                  onChange={e => setConfig(c => ({ ...c, categories: { ...c.categories, [cat]: e.target.value } }))}
                />
              </Col>
            </Row>
          ))}
          <br />
          <Button type="primary" icon={<CheckCircleOutlined />} onClick={handleSave} loading={saving}>保存配置</Button>
        </Form>
      </Card>
    </Space>
  )
}

// ─────────────────────── 主页面 ───────────────────────

const tabItems = [
  {
    key: 'strm',
    label: (
      <span><ThunderboltOutlined /> STRM 生成</span>
    ),
    children: <StrmSyncTab />,
  },
  {
    key: 'monitor',
    label: (
      <span><ClockCircleOutlined /> 生活事件监控</span>
    ),
    children: <MonitorTab />,
  },
  {
    key: 'organize',
    label: (
      <span><FolderAddOutlined /> 整理分类</span>
    ),
    children: <OrganizeTab />,
  },
]

export const P115Tools = () => {
  return (
    <div>
      <Card
        title={<><ThunderboltOutlined style={{ marginRight: 8 }} />115 工具</>}
        style={{ marginBottom: 0 }}
      >
        <Tabs defaultActiveKey="strm" items={tabItems} destroyInactiveTabPane={false} />
      </Card>
    </div>
  )
}

export default P115Tools

