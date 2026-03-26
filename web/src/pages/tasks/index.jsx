 // web/src/pages/tasks/index.jsx
 // 真正的任务中心 — 运行中任务实时卡片 + 历史任务分页表格
 import { useState, useEffect, useRef, useCallback } from 'react'
 import {
   Card, Table, Tag, Button, Space, Typography, Progress,
   Tooltip, Popconfirm, message, Badge, Select, Empty,
   Statistic, Row, Col,
 } from 'antd'
 import {
   ReloadOutlined, DeleteOutlined, StopOutlined,
   ThunderboltOutlined, ClockCircleOutlined, CheckCircleOutlined,
   CloseCircleOutlined, SyncOutlined, ClearOutlined, ScissorOutlined,
 } from '@ant-design/icons'
 import { useTranslation } from 'react-i18next'
 import { tasksApi } from '@/apis/index.js'
 
 const { Text, Title } = Typography
 
 // ── 状态徽标 ────────────────────────────────────────────────────
 function StatusTag({ status }) {
   const { t } = useTranslation()
   const STATUS_CFG = {
     running:   { color: 'processing', icon: <SyncOutlined spin />,  label: t('tasks.statusRunning')   },
     completed: { color: 'success',    icon: <CheckCircleOutlined />, label: t('tasks.statusCompleted') },
     failed:    { color: 'error',      icon: <CloseCircleOutlined />, label: t('tasks.statusFailed')    },
     pending:   { color: 'default',    icon: <ClockCircleOutlined />, label: t('tasks.statusPending')   },
   }
   const cfg = STATUS_CFG[status] || STATUS_CFG.pending
   return (
     <Badge status={cfg.color} text={
       <Space size={4}>{cfg.icon}<span>{cfg.label}</span></Space>
     } />
   )
 }
 
 // ── 运行中任务卡片 ────────────────────────────────────────────────
 function RunningTaskCard({ task, onCancel }) {
   const { t } = useTranslation()
   const [cancelling, setCancelling] = useState(false)
   const CATEGORY_LABELS = {
     p115_strm: t('tasks.categoryP115Strm'),
     organize:  t('tasks.categoryOrganize'),
     manual:    t('tasks.categoryManual'),
   }
   const stats = task.live_stats || {}
   const total = (stats.created || 0) + (stats.skipped || 0) + (stats.errors || 0)

   const handleCancel = async () => {
     setCancelling(true)
     try {
       await onCancel(task.task_id)
     } finally {
       setCancelling(false)
     }
   }

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
       extra={
         <Popconfirm title="确定要终止该任务吗？" onConfirm={handleCancel} okText="终止" cancelText="取消" okButtonProps={{ danger: true }}>
           <Button danger size="small" icon={<StopOutlined />} loading={cancelling}>终止任务</Button>
         </Popconfirm>
       }
     >
       <Row gutter={16}>
         <Col span={6}><Statistic title={t('tasks.statCreated')}   value={stats.created || 0} valueStyle={{ color: '#52c41a', fontSize: 20 }} /></Col>
         <Col span={6}><Statistic title={t('tasks.statSkipped')}   value={stats.skipped || 0} valueStyle={{ fontSize: 20 }} /></Col>
         <Col span={6}><Statistic title={t('tasks.statFailed')}    value={stats.errors  || 0} valueStyle={{ color: '#ff4d4f', fontSize: 20 }} /></Col>
         <Col span={6}><Statistic title={t('tasks.statProcessed')} value={total}              valueStyle={{ fontSize: 20 }} /></Col>
       </Row>
       <Progress percent={0} status="active" strokeColor="#1677ff"
         format={() => stats.stage || t('tasks.inProgress')} style={{ marginTop: 8 }} />
     </Card>
   )
 }
 
 // ── 主页面 ───────────────────────────────────────────────────────
 export const Tasks = () => {
   const { t } = useTranslation()
   const [tasks,      setTasks]      = useState([])
   const [running,    setRunning]    = useState([])
   const [loading,    setLoading]    = useState(false)
   const [pagination, setPagination] = useState({ current: 1, pageSize: 20, total: 0 })
   const [filterStatus,   setFilterStatus]   = useState('')
   const [filterCategory, setFilterCategory] = useState('')
   const pollRef = useRef(null)
 
   const CATEGORY_LABELS = {
     p115_strm: t('tasks.categoryP115Strm'),
     organize:  t('tasks.categoryOrganize'),
     manual:    t('tasks.categoryManual'),
   }
 
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
     } catch { message.error(t('tasks.fetchFailed')) }
     finally { setLoading(false) }
   }, [filterStatus, filterCategory, t])
 
   // 轮询刷新（运行中任务5s一次）
   useEffect(() => {
     fetchTasks()
     fetchRunning()
     pollRef.current = setInterval(() => { fetchRunning() }, 5000)
     return () => clearInterval(pollRef.current)
   }, [fetchTasks, fetchRunning])

   const handleCancel = async (taskId) => {
     try {
       const { data } = await tasksApi.cancel(taskId)
       data?.success
         ? message.success(data.message || '任务已终止')
         : message.warning(data?.message || '终止失败')
       setTimeout(() => { fetchRunning(); fetchTasks(pagination.current, pagination.pageSize) }, 800)
     } catch { message.error('操作失败') }
   }

   const handleDelete = async (id) => {
     try {
       const { data } = await tasksApi.remove(id)
       data?.success
         ? message.success(t('tasks.deleteSuccess'))
         : message.warning(data?.message || t('tasks.deleteFailed'))
       fetchTasks(pagination.current, pagination.pageSize)
     } catch { message.error(t('tasks.deleteFailed')) }
   }

   const handleForceDelete = async (id) => {
     try {
       const { data } = await tasksApi.forceDelete(id)
       data?.success
         ? message.success(t('tasks.forceDeleteSuccess'))
         : message.warning(data?.message || t('tasks.deleteFailed'))
       setTimeout(() => { fetchRunning(); fetchTasks(pagination.current, pagination.pageSize) }, 600)
     } catch { message.error(t('tasks.deleteFailed')) }
   }

   const handleClear = async () => {
     try {
       const { data } = await tasksApi.clear({ status: 'all' })
       message.success(t('tasks.clearSuccess', { count: data?.deleted || 0 }))
       fetchTasks()
     } catch { message.error(t('tasks.clearFailed')) }
   }
 
   const columns = [
     { title: t('tasks.colTaskName'), dataIndex: 'task_name', key: 'task_name', width: 160,
       render: (v) => <Text strong>{v || t('tasks.unnamed')}</Text> },
     { title: t('tasks.colCategory'), dataIndex: 'task_category', key: 'task_category', width: 100,
       render: (v) => <Tag>{CATEGORY_LABELS[v] || v}</Tag> },
     { title: t('tasks.colStatus'), dataIndex: 'status', key: 'status', width: 110,
       render: (v) => <StatusTag status={v} /> },
     { title: t('tasks.colCreated'), dataIndex: 'created_count', key: 'created_count', width: 80,
       render: (v) => <Text style={{ color: '#52c41a' }}>{v}</Text> },
     { title: t('tasks.colSkipped'), dataIndex: 'skipped_count', key: 'skipped_count', width: 80 },
     { title: t('tasks.colFailed'),  dataIndex: 'error_count',   key: 'error_count',   width: 80,
       render: (v) => v > 0 ? <Text type="danger">{v}</Text> : <Text>{v}</Text> },
     { title: t('tasks.colTrigger'), dataIndex: 'task_type', key: 'task_type', width: 100,
       render: (v) => <Tag color="default">{v}</Tag> },
     { title: t('tasks.colStartedAt'),  dataIndex: 'started_at',  key: 'started_at',  width: 160,
       render: (v) => <Text type="secondary" style={{ fontSize: 12 }}>{v || '-'}</Text> },
     { title: t('tasks.colFinishedAt'), dataIndex: 'finished_at', key: 'finished_at', width: 160,
       render: (v) => <Text type="secondary" style={{ fontSize: 12 }}>{v || '-'}</Text> },
     { title: t('tasks.colError'), dataIndex: 'error_message', key: 'error_message', ellipsis: true,
       render: (v) => v ? <Tooltip title={v}><Text type="danger" ellipsis>{v}</Text></Tooltip> : '-' },
     {
       title: t('tasks.colAction'), key: 'action', width: 130, fixed: 'right',
       render: (_, row) => row.status === 'running' ? (
         <Space size={4}>
           <Popconfirm title={t('tasks.confirmCancel')} onConfirm={() => handleCancel(row.id)} okText={t('tasks.confirmCancelOk')} cancelText={t('common.cancel')} okButtonProps={{ danger: true }}>
             <Button type="primary" danger size="small" icon={<StopOutlined />}>{t('tasks.cancelBtn')}</Button>
           </Popconfirm>
           <Popconfirm
             title={t('tasks.confirmForceDelete')}
             description={t('tasks.confirmForceDeleteDesc')}
             onConfirm={() => handleForceDelete(row.id)}
             okText={t('tasks.confirmForceDeleteOk')}
             cancelText={t('common.cancel')}
             okButtonProps={{ danger: true }}
           >
             <Button type="text" danger size="small" icon={<ScissorOutlined />} title={t('tasks.forceDeleteBtn')} />
           </Popconfirm>
         </Space>
       ) : (
         <Popconfirm title={t('tasks.confirmDelete')} onConfirm={() => handleDelete(row.id)}>
           <Button type="text" danger icon={<DeleteOutlined />} size="small" />
         </Popconfirm>
       ),
     },
   ]
 
   return (
     <div style={{ padding: 24 }}>
       <Title level={4} style={{ marginBottom: 16 }}>{t('tasks.title')}</Title>
 
       {/* 运行中任务卡片区 */}
       {running.length > 0 && (
         <Card
           title={<Space><ThunderboltOutlined style={{ color: '#1677ff' }} /><span>{t('tasks.runningTasks')}</span></Space>}
           style={{ marginBottom: 16 }} size="small"
         >
           {running.map(task => <RunningTaskCard key={task.task_id} task={task} onCancel={handleCancel} />)}
         </Card>
       )}

       {/* 操作栏 */}
       <Card style={{ marginBottom: 12 }} size="small">
         <Space wrap>
           <Select placeholder={t('tasks.filterStatus')} allowClear style={{ width: 120 }}
             value={filterStatus || undefined} onChange={(v) => setFilterStatus(v || '')}>
             <Select.Option value="running">{t('tasks.statusRunning')}</Select.Option>
             <Select.Option value="completed">{t('tasks.statusCompleted')}</Select.Option>
             <Select.Option value="failed">{t('tasks.statusFailed')}</Select.Option>
           </Select>
           <Select placeholder={t('tasks.filterCategory')} allowClear style={{ width: 120 }}
             value={filterCategory || undefined} onChange={(v) => setFilterCategory(v || '')}>
             <Select.Option value="p115_strm">{t('tasks.categoryP115Strm')}</Select.Option>
             <Select.Option value="organize">{t('tasks.categoryOrganize')}</Select.Option>
           </Select>
           <Button icon={<ReloadOutlined />} onClick={() => { fetchTasks(); fetchRunning() }}>
             {t('common.refresh')}
           </Button>
           <Popconfirm title={t('tasks.confirmClear')} onConfirm={handleClear}>
             <Button icon={<ClearOutlined />} danger>{t('tasks.clearHistory')}</Button>
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
           locale={{ emptyText: <Empty description={t('tasks.noData')} /> }}
           pagination={{
             ...pagination,
             showSizeChanger: true,
             showTotal: (total) => t('tasks.showTotal', { total }),
             onChange: (page, size) => fetchTasks(page, size),
           }}
         />
       </Card>
     </div>
   )
 }
 
 export default Tasks

