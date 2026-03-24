// web/src/pages/tasks/index.jsx
// 真正的任务中心 — 运行中任务实时卡片 + 历史任务分页表格
import { useState, useEffect, useRef, useCallback } from 'react'
import {
  Card, Table, Tag, Button, Space, Typography, Progress,
  Tooltip, Popconfirm, message, Badge, Select, Empty,
  Statistic, Row, Col,
} from 'antd'
import {
  ReloadOutlined, PlayCircleOutlined, DeleteOutlined,
  ThunderboltOutlined, ClockCircleOutlined, CheckCircleOutlined,
  CloseCircleOutlined, SyncOutlined, ClearOutlined,
} from '@ant-design/icons'
import { tasksApi, p115StrmApi } from '@/apis/index.js'

const { Text, Title } = Typography

// ── 状态配置 ────────────────────────────────────────────────────
const STATUS_CFG = {
  running:   { color: 'processing', icon: <SyncOutlined spin />,        label: '运行中' },
  completed: { color: 'success',    icon: <CheckCircleOutlined />,       label: '已完成' },
  failed:    { color: 'error',      icon: <CloseCircleOutlined />,       label: '失败' },
  pending:   { color: 'default',    icon: <ClockCircleOutlined />,       label: '等待中' },
}

const CATEGORY_LABELS = {
  p115_strm: '115 STRM',
  organize:  '整理分类',
  manual:    '手动',
}

function StatusTag({ status }) {
  const cfg = STATUS_CFG[status] || STATUS_CFG.pending
  return (
    <Badge status={cfg.color} text={
      <Space size={4}>{cfg.icon}<span>{cfg.label}</span></Space>
    } />
  )
}

// ── 运行中任务卡片 ────────────────────────────────────────────────
function RunningTaskCard({ task, onRefresh }) {
  const stats = task.live_stats || {}
  const total = (stats.created || 0) + (stats.skipped || 0) + (stats.errors || 0)
  return (
    <Card
      size="small"
      style={{ marginBottom: 8, borderLeft: '3px solid #1677ff' }}
      title={
        <Space>
          <SyncOutlined spin style={{ color: '#1677ff' }} />
          <Text strong>{task.task_name}</Text>
          <Tag color="blue">{CATEGORY_LABELS[task.task_category] || task.task_category}</Tag>
        </Space>
      }
    >
      <Row gutter={16}>
        <Col span={6}><Statistic title="新增" value={stats.created || 0} valueStyle={{ color: '#52c41a', fontSize: 20 }} /></Col>
        <Col span={6}><Statistic title="跳过" value={stats.skipped || 0} valueStyle={{ fontSize: 20 }} /></Col>
        <Col span={6}><Statistic title="失败" value={stats.errors || 0} valueStyle={{ color: '#ff4d4f', fontSize: 20 }} /></Col>
        <Col span={6}><Statistic title="已处理" value={total} valueStyle={{ fontSize: 20 }} /></Col>
      </Row>
      <Progress percent={0} status="active" strokeColor="#1677ff"
        format={() => stats.stage || '运行中...'} style={{ marginTop: 8 }} />
    </Card>
  )
}

// ── 主页面 ───────────────────────────────────────────────────────
export const Tasks = () => {
  const [tasks,      setTasks]      = useState([])
  const [running,    setRunning]    = useState([])
  const [loading,    setLoading]    = useState(false)
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20, total: 0 })
  const [filterStatus,   setFilterStatus]   = useState('')
  const [filterCategory, setFilterCategory] = useState('')
  const [triggering, setTriggering] = useState({ full: false, inc: false })
  const pollRef = useRef(null)

  const fetchRunning = useCallback(async () => {
    try {
      const { data } = await tasksApi.running()
      setRunning(data?.items || [])
    } catch { /* ignore */ }
  }, [])

  const fetchTasks = useCallback(async (page = 1, size = 20) => {
    setLoading(true)
    try {
      const params = { page, size }
      if (filterStatus)   params.status   = filterStatus
      if (filterCategory) params.category = filterCategory
      const { data } = await tasksApi.list(params)
      setTasks(data?.items || [])
      setPagination(p => ({ ...p, current: data?.page || 1, total: data?.total || 0, pageSize: size }))
    } catch { message.error('获取任务列表失败') }
    finally { setLoading(false) }
  }, [filterStatus, filterCategory])

  // 启动轮询（运行中任务5s刷一次）
  useEffect(() => {
    fetchTasks()
    fetchRunning()
    pollRef.current = setInterval(() => { fetchRunning() }, 5000)
    return () => clearInterval(pollRef.current)
  }, [fetchTasks, fetchRunning])

  const triggerSync = async (type) => {
    setTriggering(t => ({ ...t, [type]: true }))
    try {
      const fn = type === 'full' ? p115StrmApi.fullSync : p115StrmApi.incSync
      const { data } = await fn()
      data?.success ? message.success(data.message) : message.warning(data?.message || '启动失败')
      setTimeout(() => { fetchRunning(); fetchTasks() }, 1500)
    } catch { message.error('操作失败') }
    finally { setTriggering(t => ({ ...t, [type]: false })) }
  }

  const handleDelete = async (id) => {
    try {
      const { data } = await tasksApi.remove(id)
      data?.success ? message.success('已删除') : message.warning(data?.message || '删除失败')
      fetchTasks(pagination.current, pagination.pageSize)
    } catch { message.error('删除失败') }
  }

  const handleClear = async () => {
    try {
      const { data } = await tasksApi.clear({ status: 'all' })
      message.success(`已清除 ${data?.deleted || 0} 条记录`)
      fetchTasks()
    } catch { message.error('清除失败') }
  }

  const columns = [
    { title: '任务名称', dataIndex: 'task_name', key: 'task_name', width: 160,
      render: (v) => <Text strong>{v || '未命名'}</Text> },
    { title: '分类', dataIndex: 'task_category', key: 'task_category', width: 100,
      render: (v) => <Tag>{CATEGORY_LABELS[v] || v}</Tag> },
    { title: '状态', dataIndex: 'status', key: 'status', width: 100,
      render: (v) => <StatusTag status={v} /> },
    { title: '新增', dataIndex: 'created_count', key: 'created_count', width: 80,
      render: (v) => <Text style={{ color: '#52c41a' }}>{v}</Text> },
    { title: '跳过', dataIndex: 'skipped_count', key: 'skipped_count', width: 80 },
    { title: '失败', dataIndex: 'error_count', key: 'error_count', width: 80,
      render: (v) => v > 0 ? <Text type="danger">{v}</Text> : <Text>{v}</Text> },
    { title: '触发方式', dataIndex: 'task_type', key: 'task_type', width: 100,
      render: (v) => <Tag color="default">{v}</Tag> },
    { title: '开始时间', dataIndex: 'started_at', key: 'started_at', width: 160,
      render: (v) => <Text type="secondary" style={{ fontSize: 12 }}>{v || '-'}</Text> },
    { title: '完成时间', dataIndex: 'finished_at', key: 'finished_at', width: 160,
      render: (v) => <Text type="secondary" style={{ fontSize: 12 }}>{v || '-'}</Text> },
    { title: '错误信息', dataIndex: 'error_message', key: 'error_message', ellipsis: true,
      render: (v) => v ? <Tooltip title={v}><Text type="danger" ellipsis>{v}</Text></Tooltip> : '-' },
    {
      title: '操作', key: 'action', width: 80, fixed: 'right',
      render: (_, row) => (
        <Popconfirm title="确认删除此任务记录？" onConfirm={() => handleDelete(row.id)}>
          <Button type="text" danger icon={<DeleteOutlined />} size="small"
            disabled={row.status === 'running'} />
        </Popconfirm>
      ),
    },
  ]

  return (
    <div style={{ padding: 24 }}>
      <Title level={4} style={{ marginBottom: 16 }}>任务中心</Title>

      {/* 运行中任务 */}
      {running.length > 0 && (
        <Card title={<Space><ThunderboltOutlined style={{ color: '#1677ff' }} /><span>运行中任务</span></Space>}
          style={{ marginBottom: 16 }} size="small">
          {running.map(t => <RunningTaskCard key={t.task_id} task={t} />)}
        </Card>
      )}

      {/* 操作栏 */}
      <Card style={{ marginBottom: 12 }} size="small">
        <Space wrap>
          <Button type="primary" icon={<PlayCircleOutlined />}
            loading={triggering.full} onClick={() => triggerSync('full')}>
            触发全量同步
          </Button>
          <Button icon={<PlayCircleOutlined />}
            loading={triggering.inc} onClick={() => triggerSync('inc')}>
            触发增量同步
          </Button>
          <Select placeholder="状态筛选" allowClear style={{ width: 120 }}
            value={filterStatus || undefined} onChange={(v) => setFilterStatus(v || '')}>
            <Select.Option value="running">运行中</Select.Option>
            <Select.Option value="completed">已完成</Select.Option>
            <Select.Option value="failed">失败</Select.Option>
          </Select>
          <Select placeholder="分类筛选" allowClear style={{ width: 120 }}
            value={filterCategory || undefined} onChange={(v) => setFilterCategory(v || '')}>
            <Select.Option value="p115_strm">115 STRM</Select.Option>
            <Select.Option value="organize">整理分类</Select.Option>
          </Select>
          <Button icon={<ReloadOutlined />} onClick={() => { fetchTasks(); fetchRunning() }}>刷新</Button>
          <Popconfirm title="确认清除所有已完成/失败的任务记录？" onConfirm={handleClear}>
            <Button icon={<ClearOutlined />} danger>清除历史</Button>
          </Popconfirm>
        </Space>
      </Card>

      {/* 历史任务表格 */}
      <Card size="small">
        <Table
          rowKey="id"
          columns={columns}
          dataSource={tasks}
          loading={loading}
          scroll={{ x: 1200 }}
          locale={{ emptyText: <Empty description="暂无任务记录" /> }}
          pagination={{
            ...pagination,
            showSizeChanger: true,
            showTotal: (t) => `共 ${t} 条`,
            onChange: (page, size) => fetchTasks(page, size),
          }}
        />
      </Card>
    </div>
  )
}

export default Tasks

