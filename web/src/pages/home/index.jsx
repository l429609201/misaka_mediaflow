 // src/pages/home/index.jsx
 // 全景仪表盘 — 实时播放、资源统计、活跃会话
 
 import { useEffect, useState, useRef, useCallback } from 'react'
 import {
   Row, Col, Card, Statistic, Descriptions, Spin, Tag, Badge,
   Space, Typography, Tooltip, Empty,
 } from 'antd'
 import {
   PlayCircleOutlined, VideoCameraOutlined, FileTextOutlined,
   DesktopOutlined, UserOutlined, DatabaseOutlined,
   SyncOutlined, CloudServerOutlined, ApiOutlined,
 } from '@ant-design/icons'
 import ReactECharts from 'echarts-for-react'
 import { useTranslation } from 'react-i18next'
 import { systemApi } from '@/apis'
 
 const { Text, Title } = Typography
 
 // ── 活跃会话卡片 ─────────────────────────────────────────────
 function SessionCard({ session, t }) {
   const np = session.now_playing
   const ps = session.play_state
   const tc = session.transcoding_info
   const title = np
     ? (np.series_name ? `${np.series_name} - ${np.name}` : np.name)
     : session.device_name
 
   return (
     <Card size="small" style={{
       borderLeft: `3px solid ${session.is_playing ? '#52c41a' : '#d9d9d9'}`,
       marginBottom: 8,
     }}>
       <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
         <div>
           <Text strong style={{ fontSize: 13 }}>{title}</Text>
           <div style={{ fontSize: 11, color: '#888', marginTop: 2 }}>
             <Space size={8}>
               <span><UserOutlined /> {session.user_name || '-'}</span>
               <span><DesktopOutlined /> {session.client} / {session.device_name}</span>
               <span><ApiOutlined /> {session.remote_end_point}</span>
             </Space>
           </div>
         </div>
         <div style={{ textAlign: 'right' }}>
           {session.is_playing ? (
             <Badge status="processing" text={
               <Text style={{ fontSize: 11 }}>
                 {ps?.is_paused ? t('dashboard.paused') : t('dashboard.playingStatus')}
                 {ps?.play_method === 'Transcode' && <Tag color="orange" style={{ marginLeft: 4, fontSize: 10 }}>{t('dashboard.transcode')}</Tag>}
                 {ps?.play_method === 'DirectPlay' && <Tag color="green" style={{ marginLeft: 4, fontSize: 10 }}>{t('dashboard.directPlay')}</Tag>}
               </Text>
             } />
           ) : (
             <Badge status="default" text={<Text type="secondary" style={{ fontSize: 11 }}>{t('dashboard.idle')}</Text>} />
           )}
           {tc?.is_transcoding && (
             <div style={{ fontSize: 10, color: '#fa8c16', marginTop: 2 }}>
               {tc.video_codec} → {tc.audio_codec}
             </div>
           )}
         </div>
       </div>
     </Card>
   )
 }
 
 // ── 主页面 ──────────────────────────────────────────────────
 export const Home = () => {
   const { t } = useTranslation()
   const [loading, setLoading] = useState(true)
   const [health, setHealth] = useState({})
   const [dash, setDash] = useState({})
   const pollRef = useRef(null)
 
   const fetchData = useCallback(async () => {
     try {
       const [h, d] = await Promise.all([
         systemApi.health(),
         systemApi.getDashboard().catch(() => ({ data: {} })),
       ])
       setHealth(h.data)
       setDash(d.data || {})
     } finally {
       setLoading(false)
     }
   }, [])
 
   useEffect(() => {
     fetchData()
     pollRef.current = setInterval(fetchData, 10000)
     return () => clearInterval(pollRef.current)
   }, [fetchData])
 
   if (loading) return <Spin size="large" style={{ display: 'block', margin: '120px auto' }} />
 
   const sessions = dash.active_sessions || []
   const playing = sessions.filter(s => s.is_playing)
 
   const stats = [
     { title: t('dashboard.movies'), value: dash.movie_count || 0, icon: <VideoCameraOutlined />, color: '#6366f1' },
     { title: t('dashboard.series'), value: dash.series_count || 0, icon: <PlayCircleOutlined />, color: '#10b981' },
     { title: t('dashboard.episodes'), value: dash.episode_count || 0, icon: <DatabaseOutlined />, color: '#f59e0b' },
     { title: t('dashboard.strmFiles'), value: dash.strm_count || 0, icon: <FileTextOutlined />, color: '#8b5cf6' },
     { title: t('dashboard.playing'), value: playing.length, icon: <SyncOutlined spin={playing.length > 0} />, color: '#ef4444' },
     { title: t('dashboard.activeConn'), value: sessions.length, icon: <CloudServerOutlined />, color: '#06b6d4' },
   ]
 
   // 播放方式饼图
   const playMethodData = (() => {
     const methods = { DirectPlay: 0, DirectStream: 0, Transcode: 0 }
     playing.forEach(s => {
       const m = s.play_state?.play_method || 'Unknown'
       methods[m] = (methods[m] || 0) + 1
     })
     return Object.entries(methods)
       .filter(([, v]) => v > 0)
       .map(([name, value]) => ({ name, value }))
   })()
 
   const pieOption = {
     tooltip: { trigger: 'item' },
     legend: { bottom: 0, textStyle: { fontSize: 11 } },
     series: [{
       type: 'pie', radius: ['40%', '70%'],
       label: { show: false },
       emphasis: { label: { show: true, fontSize: 14, fontWeight: 'bold' } },
       data: playMethodData.length > 0 ? playMethodData : [{ name: t('dashboard.noPlay'), value: 1 }],
       color: ['#52c41a', '#1677ff', '#fa8c16', '#d9d9d9'],
     }],
   }
 
   // 客户端分布饼图
   const clientData = (() => {
     const clients = {}
     sessions.forEach(s => {
       const c = s.client || 'Unknown'
       clients[c] = (clients[c] || 0) + 1
     })
     return Object.entries(clients).map(([name, value]) => ({ name, value }))
   })()
 
   const clientPieOption = {
     tooltip: { trigger: 'item' },
     legend: { bottom: 0, textStyle: { fontSize: 11 } },
     series: [{
       type: 'pie', radius: ['40%', '70%'],
       label: { show: false },
       data: clientData.length > 0 ? clientData : [{ name: t('dashboard.noConn'), value: 1 }],
       color: ['#6366f1', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4'],
     }],
   }
 
   return (
     <div>
       {/* 标题区 */}
       <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 }}>
         <Title level={4} style={{ margin: 0 }}>
           <Space><CloudServerOutlined />{t('dashboard.title')}</Space>
         </Title>
         {dash.server_name && (
           <Text type="secondary" style={{ fontSize: 12 }}>
             {dash.server_name} · {dash.server_version} · {dash.os}
           </Text>
         )}
       </div>
 
       {/* 统计卡片 */}
       <Row gutter={[12, 12]} style={{ marginBottom: 20 }}>
         {stats.map((s) => (
           <Col xs={12} sm={8} lg={4} key={s.title}>
             <Card size="small" hoverable style={{ borderTop: `3px solid ${s.color}` }}>
               <Statistic
                 title={<span style={{ fontSize: 12 }}>{s.title}</span>}
                 value={s.value}
                 prefix={<span style={{ color: s.color }}>{s.icon}</span>}
                 valueStyle={{ fontSize: 24 }}
               />
             </Card>
           </Col>
         ))}
       </Row>
 
       <Row gutter={[16, 16]} style={{ marginBottom: 20 }}>
         {/* 播放方式分布 */}
         <Col xs={24} sm={12} lg={8}>
           <Card title={<Space size={4}><SyncOutlined />{t('dashboard.playMethod')}</Space>} size="small">
             <ReactECharts option={pieOption} style={{ height: 200 }} />
           </Card>
         </Col>
 
         {/* 客户端分布 */}
         <Col xs={24} sm={12} lg={8}>
           <Card title={<Space size={4}><DesktopOutlined />{t('dashboard.clientDist')}</Space>} size="small">
             <ReactECharts option={clientPieOption} style={{ height: 200 }} />
           </Card>
         </Col>
 
         {/* 系统信息 */}
         <Col xs={24} lg={8}>
           <Card title={<Space size={4}><CloudServerOutlined />{t('dashboard.sysInfo')}</Space>} size="small" style={{ height: '100%' }}>
             <Descriptions column={1} size="small" style={{ fontSize: 12 }}>
               <Descriptions.Item label={t('dashboard.version')}>
                 {health.version || '-'} <Tag color="blue">{health.version_tag || ''}</Tag>
               </Descriptions.Item>
               <Descriptions.Item label={t('dashboard.timezone')}>{health.timezone || '-'}</Descriptions.Item>
               <Descriptions.Item label={t('dashboard.time')}>{health.time || '-'}</Descriptions.Item>
               <Descriptions.Item label={t('dashboard.mediaServer')}>
                 {dash.media_server_connected
                   ? <Badge status="success" text={<Text style={{ fontSize: 12 }}>{t('dashboard.connected')}</Text>} />
                   : <Badge status="error" text={<Text style={{ fontSize: 12 }}>{t('dashboard.disconnected')}</Text>} />
                 }
               </Descriptions.Item>
             </Descriptions>
           </Card>
         </Col>
       </Row>
 
       {/* 活跃会话列表 */}
       <Card
         title={<Space><UserOutlined />{t('dashboard.activeSessions')} <Badge count={sessions.length} style={{ backgroundColor: playing.length > 0 ? '#52c41a' : '#d9d9d9' }} /></Space>}
         size="small"
       >
         {sessions.length > 0 ? (
           sessions.map(s => <SessionCard key={s.id} session={s} t={t} />)
         ) : (
           <Empty description={<Text type="secondary">{t('dashboard.noSessions')}</Text>} />
         )}
       </Card>
     </div>
   )
 }
 
 export default Home
