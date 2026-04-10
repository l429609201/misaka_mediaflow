 // web/src/pages/tasks/index.jsx
 // 任务中心 — Tab1=任务历史 Tab2=工作流
 import { useState, useEffect, useRef, useCallback } from 'react'
 import {
   Card, Table, Tag, Button, Space, Typography, Progress, Tabs,
   Tooltip, Popconfirm, message, Badge, Select, Empty, Input,
   Statistic, Row, Col, Modal, List, Descriptions,
 } from 'antd'
 import {
   ReloadOutlined, DeleteOutlined, StopOutlined,
   ThunderboltOutlined, ClockCircleOutlined, CheckCircleOutlined,
   CloseCircleOutlined, SyncOutlined, ClearOutlined, ScissorOutlined,
   PlusOutlined, PlayCircleOutlined, EditOutlined, ApartmentOutlined,
 } from '@ant-design/icons'
 import { useTranslation } from 'react-i18next'
 import { tasksApi, workflowApi } from '@/apis/index.js'
 
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
 const TaskCenter = () => {
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
     <div>
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

 // ── 工作流 Tab ──────────────────────────────────────────────────────
 const WorkflowTab = () => {
   const { t } = useTranslation()
   const [workflows, setWorkflows] = useState([])
   const [loading, setLoading] = useState(false)
   const [editModal, setEditModal] = useState(false)
   const [editData, setEditData] = useState(null)
   const [executions, setExecutions] = useState([])
   const [nodeTypes, setNodeTypes] = useState([])

   const fetchWorkflows = useCallback(async () => {
     setLoading(true)
     try {
       const { data } = await workflowApi.list()
       setWorkflows(data?.items || [])
     } catch { /* ignore */ }
     finally { setLoading(false) }
   }, [])

   const fetchExecutions = useCallback(async () => {
     try {
       const { data } = await workflowApi.listExecutions({ page: 1, size: 20 })
       setExecutions(data?.items || [])
     } catch { /* ignore */ }
   }, [])

   const fetchNodeTypes = useCallback(async () => {
     try {
       const { data } = await workflowApi.getNodeTypes()
       setNodeTypes(data?.items || [])
     } catch { /* ignore */ }
   }, [])

   useEffect(() => {
     fetchWorkflows()
     fetchExecutions()
     fetchNodeTypes()
   }, [fetchWorkflows, fetchExecutions, fetchNodeTypes])

   const handleCreate = () => {
     setEditData({
       name: t('workflow.newWorkflow', '新工作流'),
       description: '',
       nodes: [
         { id: 'start-1', type: 'default', position: { x: 250, y: 50 },
           data: { type: 'start', label: t('workflow.nodeStart', '开始'), params: {} } },
         { id: 'end-1', type: 'default', position: { x: 250, y: 300 },
           data: { type: 'end', label: t('workflow.nodeEnd', '结束'), params: {} } },
       ],
       edges: [{ id: 'e-start-end', source: 'start-1', target: 'end-1' }],
       enabled: 1,
       cron: '',
     })
     setEditModal(true)
   }

   const handleEdit = (wf) => {
     const data = { ...wf }
     try { data.nodes = typeof data.nodes === 'string' ? JSON.parse(data.nodes) : data.nodes } catch { data.nodes = [] }
     try { data.edges = typeof data.edges === 'string' ? JSON.parse(data.edges) : data.edges } catch { data.edges = [] }
     setEditData(data)
     setEditModal(true)
   }

   const handleSave = async () => {
     if (!editData) return
     try {
       await workflowApi.save(editData)
       message.success(t('common.success'))
       setEditModal(false)
       fetchWorkflows()
     } catch { message.error(t('common.failed')) }
   }

   const handleDelete = async (id) => {
     try {
       await workflowApi.remove(id)
       message.success(t('common.success'))
       fetchWorkflows()
     } catch { message.error(t('common.failed')) }
   }

   const handleExecute = async (id) => {
     try {
       const { data } = await workflowApi.execute(id)
       if (data?.success) {
         message.success(t('workflow.executeStarted', '工作流已启动'))
         setTimeout(fetchExecutions, 1000)
       } else {
         message.warning(data?.message || t('common.failed'))
       }
     } catch { message.error(t('common.failed')) }
   }

   const STATUS_COLORS = {
     running: 'processing', completed: 'success', failed: 'error', cancelled: 'warning',
   }

   return (
     <div>
       {/* 工作流列表 */}
       <Card
         title={<Space><ApartmentOutlined /><span>{t('workflow.title', '工作流')}</span></Space>}
         extra={<Button type="primary" icon={<PlusOutlined />} onClick={handleCreate}>{t('workflow.create', '新建工作流')}</Button>}
         style={{ marginBottom: 16 }} size="small"
       >
         <List
           loading={loading}
           dataSource={workflows}
           locale={{ emptyText: <Empty description={t('workflow.noWorkflows', '暂无工作流，点击右上角新建')} /> }}
           renderItem={wf => (
             <List.Item
               actions={[
                 <Button key="run" type="primary" size="small" icon={<PlayCircleOutlined />}
                   onClick={() => handleExecute(wf.id)}>{t('workflow.run', '执行')}</Button>,
                 <Button key="edit" size="small" icon={<EditOutlined />}
                   onClick={() => handleEdit(wf)}>{t('common.edit')}</Button>,
                 <Popconfirm key="del" title={t('common.confirm')} onConfirm={() => handleDelete(wf.id)}>
                   <Button danger size="small" icon={<DeleteOutlined />} />
                 </Popconfirm>,
               ]}
             >
               <List.Item.Meta
                 avatar={<ApartmentOutlined style={{ fontSize: 24, color: wf.enabled ? '#1677ff' : '#999' }} />}
                 title={<Space>{wf.name}{wf.cron && <Tag color="blue">{wf.cron}</Tag>}{!wf.enabled && <Tag color="default">{t('common.disabled')}</Tag>}</Space>}
                 description={wf.description || t('workflow.noDescription', '无描述')}
               />
             </List.Item>
           )}
         />
       </Card>

       {/* 执行记录 */}
       <Card title={t('workflow.execHistory', '执行记录')} size="small"
         extra={<Button icon={<ReloadOutlined />} size="small" onClick={fetchExecutions}>{t('common.refresh')}</Button>}>
         <Table
           rowKey="id" dataSource={executions} size="small"
           locale={{ emptyText: <Empty description={t('workflow.noExecutions', '暂无执行记录')} /> }}
           pagination={{ pageSize: 10, showSizeChanger: false }}
           columns={[
             { title: t('workflow.colName', '工作流'), dataIndex: 'workflow_name', width: 160 },
             { title: t('workflow.colStatus', '状态'), dataIndex: 'status', width: 100,
               render: v => <Badge status={STATUS_COLORS[v] || 'default'} text={v} /> },
             { title: t('workflow.colTrigger', '触发'), dataIndex: 'triggered_by', width: 80,
               render: v => <Tag>{v}</Tag> },
             { title: t('workflow.colStarted', '开始时间'), dataIndex: 'started_at', width: 160,
               render: v => <Typography.Text type="secondary" style={{ fontSize: 12 }}>{v || '-'}</Typography.Text> },
             { title: t('workflow.colFinished', '完成时间'), dataIndex: 'finished_at', width: 160,
               render: v => <Typography.Text type="secondary" style={{ fontSize: 12 }}>{v || '-'}</Typography.Text> },
             { title: t('workflow.colError', '错误'), dataIndex: 'error_message', ellipsis: true,
               render: v => v ? <Tooltip title={v}><Typography.Text type="danger" ellipsis>{v}</Typography.Text></Tooltip> : '-' },
           ]}
         />
       </Card>

       {/* 工作流编辑弹窗 */}
       <Modal
         title={editData?.id ? t('workflow.editTitle', '编辑工作流') : t('workflow.createTitle', '新建工作流')}
         open={editModal} onCancel={() => setEditModal(false)}
         onOk={handleSave} width={700} destroyOnClose
       >
         {editData && (
           <div>
             <Space direction="vertical" style={{ width: '100%' }} size="middle">
               <div>
                 <Typography.Text strong>{t('workflow.name', '名称')}</Typography.Text>
                 <Input value={editData.name} onChange={e => setEditData({ ...editData, name: e.target.value })}
                   style={{ marginTop: 4 }} />
               </div>
               <div>
                 <Typography.Text strong>{t('workflow.description', '描述')}</Typography.Text>
                 <Input.TextArea value={editData.description}
                   onChange={e => setEditData({ ...editData, description: e.target.value })}
                   style={{ marginTop: 4 }} rows={2} />
               </div>
               <div>
                 <Typography.Text strong>{t('workflow.cron', '定时表达式')}</Typography.Text>
                 <Input value={editData.cron} placeholder="0 3 * * *（留空=手动触发）"
                   onChange={e => setEditData({ ...editData, cron: e.target.value })}
                   style={{ marginTop: 4 }} />
               </div>
               {/* 节点编排 — 简化版列表 */}
               <div>
                 <Typography.Text strong>{t('workflow.nodes', '执行节点')}</Typography.Text>
                 <div style={{ marginTop: 8 }}>
                   {(editData.nodes || []).map((node, idx) => (
                     <Tag key={node.id} color={nodeTypes.find(n => n.type === node.data?.type)?.color || '#999'}
                       closable={!['start', 'end'].includes(node.data?.type)}
                       onClose={() => {
                         const newNodes = editData.nodes.filter((_, i) => i !== idx)
                         const newEdges = editData.edges.filter(e => e.source !== node.id && e.target !== node.id)
                         setEditData({ ...editData, nodes: newNodes, edges: newEdges })
                       }}
                       style={{ marginBottom: 4 }}
                     >
                       {nodeTypes.find(n => n.type === node.data?.type)?.label || node.data?.type || '?'}
                     </Tag>
                   ))}
                 </div>
                 <Select
                   placeholder={t('workflow.addNode', '添加节点')}
                   style={{ width: 200, marginTop: 8 }}
                   onChange={(type) => {
                     const info = nodeTypes.find(n => n.type === type) || {}
                     const newId = `${type}-${Date.now()}`
                     const endNode = editData.nodes.find(n => n.data?.type === 'end')
                     const lastNonEnd = [...editData.nodes].reverse().find(n => n.data?.type !== 'end')
                     const newNode = {
                       id: newId, type: 'default',
                       position: { x: 250, y: (editData.nodes.length) * 80 + 50 },
                       data: { type, label: info.label || type, params: {} },
                     }
                     // 插入到 end 之前
                     const nodes = editData.nodes.filter(n => n.data?.type !== 'end')
                     nodes.push(newNode)
                     if (endNode) nodes.push(endNode)
                     // 重建边
                     const edges = []
                     for (let i = 0; i < nodes.length - 1; i++) {
                       edges.push({ id: `e-${nodes[i].id}-${nodes[i+1].id}`, source: nodes[i].id, target: nodes[i+1].id })
                     }
                     setEditData({ ...editData, nodes, edges })
                   }}
                   value={null}
                 >
                   {nodeTypes.filter(n => !['start', 'end'].includes(n.type)).map(n => (
                     <Select.Option key={n.type} value={n.type}>
                       <Space><span style={{ color: n.color }}>●</span>{n.label}</Space>
                     </Select.Option>
                   ))}
                 </Select>
               </div>
             </Space>
           </div>
         )}
       </Modal>
     </div>
   )
 }

 // ── 主页面（Tabs 容器）──────────────────────────────────────────────
 export const Tasks = () => {
   const { t } = useTranslation()
   return (
     <div style={{ padding: 24 }}>
       <Typography.Title level={4} style={{ marginBottom: 16 }}>{t('tasks.title')}</Typography.Title>
       <Tabs
         defaultActiveKey="tasks"
         items={[
           {
             key: 'tasks',
             label: <Space><UnorderedListOutlined />{t('tasks.tabTasks', '任务中心')}</Space>,
             children: <TaskCenter />,
           },
           {
             key: 'workflow',
             label: <Space><ApartmentOutlined />{t('tasks.tabWorkflow', '工作流')}</Space>,
             children: <WorkflowTab />,
           },
         ]}
       />
     </div>
   )
 }

 export default Tasks

