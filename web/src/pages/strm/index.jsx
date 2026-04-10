 // src/pages/strm/index.jsx
 // STRM 管理
 
 import { useState, useEffect, useCallback } from 'react'
 import {
   Card, Button, Space, Row, Col, Statistic, Typography, message,
   Table, Tabs, Tag, Tooltip, Progress, Popconfirm, Empty, Badge
 } from 'antd'
 import {
   ScanOutlined, DeleteOutlined, FileTextOutlined,
   CheckCircleOutlined, CloseCircleOutlined, WarningOutlined,
   ReloadOutlined, ExperimentOutlined, FolderOpenOutlined,
   SafetyCertificateOutlined, ClearOutlined,
 } from '@ant-design/icons'
 import { useTranslation } from 'react-i18next'
 import { p115StrmApi, strmApi } from '@/apis'
 
 const { Text, Title } = Typography
 
 // ── 统计卡片组件 ─────────────────────────────────────────────
 function StatCard({ title, value, total, icon, color, desc }) {
   const pct = total > 0 ? Math.round((value / total) * 100) : 0
   return (
     <Card size="small" style={{ borderTop: `3px solid ${color}`, height: '100%' }}>
       <Statistic
         title={<Space size={4}><span style={{ color }}>{icon}</span>{title}</Space>}
         value={value}
         valueStyle={{ color, fontSize: 28 }}
       />
       {total > 0 && (
         <Progress
           percent={pct} size="small" showInfo={false}
           strokeColor={color} trailColor="#f0f0f0"
           style={{ marginTop: 8, marginBottom: 0 }}
         />
       )}
       {desc && <Text type="secondary" style={{ fontSize: 11 }}>{desc}</Text>}
     </Card>
   )
 }
 
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
   const [stats, setStats] = useState(null)
 
   const [files,      setFiles]      = useState([])
   const [fileLoading,setFileLoading] = useState(false)
   const [filePagination, setFilePagination] = useState({ current: 1, pageSize: 20, total: 0 })
 
   const fetchFiles = useCallback(async (page = 1, size = 20) => {
     setFileLoading(true)
     try {
       const { data } = await strmApi.listFiles({ page, size })
       setFiles(data.items || [])
       setFilePagination({ current: data.page || page, pageSize: data.size || size, total: data.total || 0 })
     } catch {
       message.error(t('common.failed'))
     } finally {
       setFileLoading(false)
     }
   }, [t])
 
   useEffect(() => { fetchFiles() }, [fetchFiles])
 
   const handleScan = async () => {
     setScanLoading(true)
     try {
       const r = await p115StrmApi.scanLocalStrm()
       if (r.data?.error) { message.error(r.data.error); return }
       setStats(r.data)
       message.success('扫描完成')
     } catch { message.error(t('common.failed')) }
     finally { setScanLoading(false) }
   }
 
   const handleClean = async (dryRun = true) => {
     setCleanLoading(true)
     try {
       const r = await p115StrmApi.cleanInvalidStrm({ dry_run: dryRun })
       if (r.data?.error) { message.error(r.data.error); return }
       const s = r.data
       const action = dryRun ? '预计清理' : '已清理'
       message.success(`${action}：${s.deleted_strm} 个 STRM、${s.deleted_nfo} 个 NFO、${s.deleted_images} 张图片`)
       if (!dryRun) setTimeout(handleScan, 800)
     } catch { message.error(t('common.failed')) }
     finally { setCleanLoading(false) }
   }
 
   const handleRescrape = async () => {
     setScrapeLoading(true)
     try {
       const r = await p115StrmApi.rescrapeNfo()
       if (r.data?.error) { message.error(r.data.error); return }
       const s = r.data
       message.success(`刮削完成：成功 ${s.scraped} 个，失败 ${s.failed} 个`)
       setTimeout(handleScan, 800)
     } catch { message.error(t('common.failed')) }
     finally { setScrapeLoading(false) }
   }
 
   const fileColumns = [
     { title: 'ID', dataIndex: 'id', width: 60 },
     { title: 'STRM 路径', dataIndex: 'strm_path', ellipsis: true,
       render: (v) => <Tooltip title={v}><Text style={{ fontSize: 12 }}>{v}</Text></Tooltip> },
     { title: '内容', dataIndex: 'strm_content', ellipsis: true,
       render: (v) => <Text type="secondary" style={{ fontSize: 12 }}>{v}</Text> },
     { title: '模式', dataIndex: 'strm_mode', width: 80,
       render: (v) => <Tag>{v || '-'}</Tag> },
     { title: '创建时间', dataIndex: 'created_at', width: 150,
       render: (v) => <Text type="secondary" style={{ fontSize: 12 }}>{v || '-'}</Text> },
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
                 desc="统计本地 STRM 文件状态"
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
                 disabled={!stats}
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
                 disabled={!stats}
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
                 disabled={!stats}
                 onClick={handleRescrape}
               />
             </Col>
           </Row>
 
           {/* 统计结果 */}
           {stats ? (
             <>
               <Row gutter={[12, 12]} style={{ marginBottom: 16 }}>
                 <Col xs={12} sm={6}>
                   <StatCard title="总文件数" value={stats.total || 0} total={stats.total}
                     icon={<FileTextOutlined />} color="#6366f1" desc="已扫描" />
                 </Col>
                 <Col xs={12} sm={6}>
                   <StatCard title="有效" value={stats.valid || 0} total={stats.total}
                     icon={<CheckCircleOutlined />} color="#10b981"
                     desc={`占比 ${stats.total ? Math.round((stats.valid/stats.total)*100) : 0}%`} />
                 </Col>
                 <Col xs={12} sm={6}>
                   <StatCard title="无效" value={stats.invalid || 0} total={stats.total}
                     icon={<CloseCircleOutlined />} color="#ef4444"
                     desc="内容空或异常" />
                 </Col>
                 <Col xs={12} sm={6}>
                   <StatCard title="缺失 NFO" value={stats.missing_nfo || 0} total={stats.total}
                     icon={<WarningOutlined />} color="#f59e0b"
                     desc="可补刮削" />
                 </Col>
               </Row>
               <Card size="small" style={{ background: '#fafafa' }}>
                 <Text type="secondary" style={{ fontSize: 12, marginBottom: 6, display: 'block' }}>
                   <FolderOpenOutlined style={{ marginRight: 4 }} />扫描路径
                 </Text>
                 <Space direction="vertical" size={2} style={{ width: '100%' }}>
                   {(stats.paths || []).map(p => (
                     <Text key={p} code style={{ fontSize: 11 }}>{p}</Text>
                   ))}
                 </Space>
               </Card>
             </>
           ) : (
             <Empty
               image={<ScanOutlined style={{ fontSize: 48, color: '#d9d9d9' }} />}
               imageStyle={{ height: 60 }}
               description={<Text type="secondary">点击「扫描 STRM」获取本地文件状态</Text>}
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
           <Table
             rowKey="id"
             columns={fileColumns}
             dataSource={files}
             loading={fileLoading}
             size="small"
             scroll={{ x: 800 }}
             pagination={{
               ...filePagination,
               onChange: (p, s) => fetchFiles(p, s),
               showTotal: (total) => `共 ${total} 条`,
               showSizeChanger: true,
             }}
           />
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
         <Button icon={<ReloadOutlined />} onClick={() => { handleScan(); fetchFiles() }}>
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
