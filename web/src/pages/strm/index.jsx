 // src/pages/strm/index.jsx
 // STRM 管理
 
 import { useState, useEffect, useCallback } from 'react'
 import {
   Card, Button, Space, Row, Col, Typography, message, Input,
   Table, Tabs, Tag, Tooltip, Popconfirm, Empty, Badge, Modal
 } from 'antd'
 import {
   ScanOutlined, DeleteOutlined, FileTextOutlined,
   ReloadOutlined, ExperimentOutlined,
   SafetyCertificateOutlined, ClearOutlined, EditOutlined,
   SearchOutlined, SwapOutlined,
 } from '@ant-design/icons'
 import { useTranslation } from 'react-i18next'
 import { p115StrmApi, strmApi } from '@/apis'
 
 const { Text, Title } = Typography
 

 
 // ── 操作卡片组件 ─────────────────────────────────────────────
 function ActionCard({ icon, title, desc, danger, loading, disabled, onClick, confirmTitle }) {
   const btn = (
     <Button
       block
       size="large"
       type={danger ? 'primary' : 'default'}
       danger={danger}
       icon={icon}
       loading={loading}
       disabled={disabled}
       onClick={!confirmTitle ? onClick : undefined}
       style={{ height: 'auto', paddingTop: 12, paddingBottom: 12 }}
     >
       <div style={{ lineHeight: 1.3 }}>
         <div style={{ fontWeight: 600, fontSize: 14 }}>{title}</div>
         <div style={{ fontSize: 11, fontWeight: 400, opacity: 0.75, marginTop: 2 }}>{desc}</div>
       </div>
     </Button>
   )
   if (confirmTitle) {
     return (
       <Popconfirm title={confirmTitle} onConfirm={onClick} okText="确定" cancelText="取消" okButtonProps={{ danger }}>
         {btn}
       </Popconfirm>
     )
   }
   return btn
 }
 
 // ─── 页面主体 ────────────────────────────────────────────────
 export const Strm = () => {
   const { t } = useTranslation()
 
   const [scanLoading,  setScanLoading]  = useState(false)
   const [cleanLoading, setCleanLoading] = useState(false)
   const [scrapeLoading,setScrapeLoading]= useState(false)
 
   const [files,      setFiles]      = useState([])
   const [fileLoading,setFileLoading] = useState(false)
   const [filePagination, setFilePagination] = useState({ current: 1, pageSize: 20, total: 0 })
   const [fileSearch, setFileSearch] = useState('')
   // 编辑弹窗
   const [editOpen, setEditOpen] = useState(false)
   const [editFile, setEditFile] = useState(null)
   const [editContent, setEditContent] = useState('')
   // 批量替换
   const [replaceOpen, setReplaceOpen] = useState(false)
   const [replaceFind, setReplaceFind] = useState('')
   const [replaceWith, setReplaceWith] = useState('')
   const [replaceResult, setReplaceResult] = useState(null)
   const [replaceLoading, setReplaceLoading] = useState(false)

   const fetchFiles = useCallback(async (page = 1, size = 20, search) => {
     setFileLoading(true)
     try {
       const { data } = await strmApi.listFiles({ page, size, search: search ?? fileSearch })
       setFiles(data.items || [])
       setFilePagination({ current: data.page || page, pageSize: data.size || size, total: data.total || 0 })
     } catch {
       message.error(t('common.failed'))
     } finally {
       setFileLoading(false)
     }
   }, [t, fileSearch])
 
   useEffect(() => { fetchFiles() }, [fetchFiles])
 
   const handleScan = async () => {
     setScanLoading(true)
     try {
       const r = await p115StrmApi.scanLocalStrm()
       if (r.data?.error) { message.error(r.data.error); return }
       message.success(r.data?.message || '扫描任务已启动，请在任务中心查看进度')
     } catch { message.error(t('common.failed')) }
     finally { setScanLoading(false) }
   }

   const handleClean = async (dryRun = true) => {
     setCleanLoading(true)
     try {
       const r = await p115StrmApi.cleanInvalidStrm({ dry_run: dryRun })
       if (r.data?.error) { message.error(r.data.error); return }
       if (dryRun) {
         const s = r.data
         message.success(`预计清理：${s.deleted_strm} 个 STRM、${s.deleted_nfo} 个 NFO、${s.deleted_images} 张图片`)
       } else {
         message.success(r.data?.message || '清理任务已启动，请在任务中心查看进度')
       }
     } catch { message.error(t('common.failed')) }
     finally { setCleanLoading(false) }
   }

   const handleRescrape = async () => {
     setScrapeLoading(true)
     try {
       const r = await p115StrmApi.rescrapeNfo()
       if (r.data?.error) { message.error(r.data.error); return }
       message.success(r.data?.message || '补刮削任务已启动，请在任务中心查看进度')
     } catch { message.error(t('common.failed')) }
     finally { setScrapeLoading(false) }
   }

   const [purgeLoading, setPurgeLoading] = useState(false)
   const handlePurge = async () => {
     setPurgeLoading(true)
     try {
       const r = await strmApi.purgeStaleFiles()
       message.success(`已清理 ${r.data?.deleted || 0} 条失效记录（共检查 ${r.data?.total_checked || 0} 条）`)
       fetchFiles()
     } catch { message.error(t('common.failed')) }
     finally { setPurgeLoading(false) }
   }
 
   const fileColumns = [
     { title: 'ID', dataIndex: 'id', width: 60 },
     { title: 'STRM 路径', dataIndex: 'strm_path', ellipsis: true,
       render: (v) => <Tooltip title={v}><Text style={{ fontSize: 12 }}>{v}</Text></Tooltip> },
     { title: '内容', dataIndex: 'strm_content', ellipsis: true,
       render: (v) => <Text type="secondary" style={{ fontSize: 12 }}>{v}</Text> },
     { title: '模式', dataIndex: 'strm_mode', width: 80,
       render: (v) => <Tag>{v || '-'}</Tag> },
     { title: '操作', key: 'action', width: 70, fixed: 'right',
       render: (_, row) => (
         <Button type="text" size="small" icon={<EditOutlined />} onClick={() => {
           setEditFile(row); setEditContent(row.strm_content || ''); setEditOpen(true)
         }} />
       ),
     },
   ]
 
   const tabItems = [
     {
       key: 'tools',
       label: <Space><ScanOutlined />本地工具</Space>,
       children: (
         <div style={{ padding: '16px 0' }}>
           {/* 操作按钮区 */}
           <Row gutter={[12, 12]} style={{ marginBottom: 24 }}>
             <Col xs={24} sm={12} md={6}>
               <ActionCard
                 icon={<ScanOutlined />}
                 title="扫描 STRM"
                 desc="扫描本地 STRM 文件状态并写入数据库"
                 loading={scanLoading}
                 onClick={handleScan}
               />
             </Col>
             <Col xs={24} sm={12} md={6}>
               <ActionCard
                 icon={<ExperimentOutlined />}
                 title="试运行清理"
                 desc="预览将删除的文件，不实际执行"
                 loading={cleanLoading}
                 onClick={() => handleClean(true)}
               />
             </Col>
             <Col xs={24} sm={12} md={6}>
               <ActionCard
                 icon={<ClearOutlined />}
                 title="清理无效 STRM"
                 desc="删除异常 STRM 及关联 NFO/图片"
                 danger
                 loading={cleanLoading}
                 confirmTitle="确定要清理无效 STRM 文件吗？此操作不可撤销"
                 onClick={() => handleClean(false)}
               />
             </Col>
             <Col xs={24} sm={12} md={6}>
               <ActionCard
                 icon={<SafetyCertificateOutlined />}
                 title="补刮削 NFO"
                 desc="自动补全缺失的元数据和图片"
                 loading={scrapeLoading}
                 onClick={handleRescrape}
               />
             </Col>
           </Row>

           {/* 文件数量统计 */}
           {filePagination.total > 0 ? (
             <Card size="small" style={{ background: '#fafafa', marginBottom: 16 }}>
               <Space>
                 <FileTextOutlined />
                 <Text>数据库中共 <Text strong style={{ color: '#6366f1' }}>{filePagination.total}</Text> 个 STRM 文件记录</Text>
                 <Text type="secondary" style={{ fontSize: 12 }}>（点击扫描可更新文件列表）</Text>
               </Space>
             </Card>
           ) : (
             <Empty
               image={<ScanOutlined style={{ fontSize: 48, color: '#d9d9d9' }} />}
               description={<Text type="secondary">暂无文件记录，点击「扫描 STRM」发现本地文件</Text>}
             />
           )}
         </div>
       ),
     },
     {
       key: 'files',
       label: <Space><FileTextOutlined />文件列表<Badge count={filePagination.total} overflowCount={99999} style={{ backgroundColor: '#6366f1' }} /></Space>,
       children: (
         <div style={{ paddingTop: 16 }}>
           <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12, gap: 8, flexWrap: 'wrap' }}>
             <Input.Search placeholder="搜索路径或内容..." allowClear style={{ width: 300 }}
               enterButton={<SearchOutlined />}
               onSearch={(val) => { setFileSearch(val); fetchFiles(1, filePagination.pageSize, val) }} />
             <Space>
               <Button icon={<SwapOutlined />} onClick={() => setReplaceOpen(true)}>批量替换</Button>
               <Popconfirm title="删除本地已不存在的记录？" onConfirm={handlePurge} okText="确定" cancelText="取消">
                 <Button icon={<DeleteOutlined />} danger size="small" loading={purgeLoading}>清理失效</Button>
               </Popconfirm>
               <Button icon={<ReloadOutlined />} size="small" onClick={() => fetchFiles()}>刷新</Button>
             </Space>
           </div>
           <Table rowKey="id" columns={fileColumns} dataSource={files} loading={fileLoading} size="small" scroll={{ x: 800 }}
             pagination={{ ...filePagination, onChange: (p, s) => fetchFiles(p, s), showTotal: (total) => `共 ${total} 条`, showSizeChanger: true }} />
           <Modal title="编辑 STRM 内容" open={editOpen} onCancel={() => setEditOpen(false)} width={640} destroyOnClose
             onOk={async () => {
               if (!editFile) return
               try { await strmApi.updateFileContent(editFile.id, editContent); message.success('已更新'); setEditOpen(false); fetchFiles(filePagination.current, filePagination.pageSize) }
               catch { message.error('更新失败') }
             }}>
             {editFile && (<div>
               <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 8 }}>路径: {editFile.strm_path}</Text>
               <Input.TextArea value={editContent} onChange={e => setEditContent(e.target.value)} rows={4} style={{ fontFamily: 'monospace', fontSize: 13 }} />
             </div>)}
           </Modal>
           <Modal title={<Space><SwapOutlined />批量替换 STRM 内容</Space>} open={replaceOpen}
             onCancel={() => { setReplaceOpen(false); setReplaceResult(null) }} width={560} destroyOnClose
             footer={[
               <Button key="close" onClick={() => { setReplaceOpen(false); setReplaceResult(null) }}>关闭</Button>,
               <Button key="dry" loading={replaceLoading} onClick={async () => {
                 setReplaceLoading(true)
                 try { const { data } = await strmApi.batchReplace(replaceFind, replaceWith, true); setReplaceResult(data) }
                 catch { message.error('失败') } finally { setReplaceLoading(false) }
               }}>试运行</Button>,
               <Popconfirm key="exec" title={`确定替换 ${replaceResult?.matched || '?'} 个文件？`}
                 onConfirm={async () => {
                   setReplaceLoading(true)
                   try { const { data } = await strmApi.batchReplace(replaceFind, replaceWith, false); setReplaceResult(data); message.success(`已替换 ${data?.replaced || 0} 个`); fetchFiles(filePagination.current, filePagination.pageSize) }
                   catch { message.error('失败') } finally { setReplaceLoading(false) }
                 }}>
                 <Button type="primary" danger disabled={!replaceResult || replaceResult.matched === 0} loading={replaceLoading}>执行替换</Button>
               </Popconfirm>,
             ]}>
             <Space direction="vertical" style={{ width: '100%' }} size="middle">
               <div><Text strong>查找内容</Text><Input value={replaceFind} onChange={e => setReplaceFind(e.target.value)} placeholder="http://old-host:5244" style={{ marginTop: 4, fontFamily: 'monospace' }} /></div>
               <div><Text strong>替换为</Text><Input value={replaceWith} onChange={e => setReplaceWith(e.target.value)} placeholder="http://new-host:5244" style={{ marginTop: 4, fontFamily: 'monospace' }} /></div>
               {replaceResult && (<Card size="small" style={{ background: '#fafafa' }}><Row gutter={16}>
                 <Col span={8}><Statistic title="匹配" value={replaceResult.matched || 0} valueStyle={{ color: '#1677ff' }} /></Col>
                 <Col span={8}><Statistic title="已替换" value={replaceResult.replaced || 0} valueStyle={{ color: '#52c41a' }} /></Col>
                 <Col span={8}><Tag color={replaceResult.dry_run ? 'orange' : 'green'} style={{ marginTop: 8 }}>{replaceResult.dry_run ? '试运行' : '已执行'}</Tag></Col>
               </Row></Card>)}
             </Space>
           </Modal>
         </div>
       ),
     },
   ]
 
   return (
     <div style={{ padding: 24 }}>
       <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 }}>
         <Title level={4} style={{ margin: 0 }}>
           <Space><FileTextOutlined />STRM 管理</Space>
         </Title>
         <Button icon={<ReloadOutlined />} onClick={() => fetchFiles()}>
           刷新
         </Button>
       </div>
       <Card bodyStyle={{ paddingTop: 0 }}>
         <Tabs items={tabItems} defaultActiveKey="tools" />
       </Card>
     </div>
   )
 }
 
 export default Strm
