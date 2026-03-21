 import { useCallback, useEffect, useState } from 'react'
 import {
   Alert, Badge, Button, Card, Col, Form, Input, Radio, Row, Select,
   Space, Spin, Switch, Table, Tabs, Tag, Tooltip, Typography, message,
 } from 'antd'
 import {
   FontSizeOutlined, ReloadOutlined, SaveOutlined, ScanOutlined,
 } from '@ant-design/icons'
 import { systemApi, subtitleApi } from '@/apis'
 
 const { Text } = Typography
 
 // ─── 工具函数 ─────────────────────────────────────────────────────────────────
 function fmtTtl(sec) {
   if (sec <= 0) return '已过期'
   const h = Math.floor(sec / 3600)
   const m = Math.floor((sec % 3600) / 60)
   const s = sec % 60
   return [h && `${h}h`, m && `${m}m`, `${s}s`].filter(Boolean).join(' ')
 }
 function fmtBytes(b) {
   if (b < 1024) return `${b} B`
   if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KB`
   return `${(b / 1024 / 1024).toFixed(2)} MB`
 }
 
 // ═══════════════════════════════════════════════════════════
 // Tab1：当前配置
 // ═══════════════════════════════════════════════════════════
 const DEFAULTS = {
   font_in_ass_enabled: false,
   subtitle_engine: 'external',
   font_in_ass_url: '',
   embedded_sub_enabled: false,
   embedded_sub_tracks: [],
   embedded_sub_include_movies: false,
 }
 
 const ConfigTab = () => {
   const [form] = Form.useForm()
   const [loading, setLoading] = useState(true)
   const [saving, setSaving] = useState(false)
   const [engine, setEngine] = useState('external')
 
   const fetchConfigs = useCallback(async () => {
     setLoading(true)
     try {
       const { data } = await systemApi.getConfig()
       const items = Array.isArray(data?.items) ? data.items : []
       const map = Object.fromEntries(items.map(item => [item.key, item.value]))
       const eng = map.subtitle_engine || 'external'
       setEngine(eng)
       form.setFieldsValue({
         font_in_ass_enabled: map.font_in_ass_enabled === 'true',
         subtitle_engine: eng,
         font_in_ass_url: map.font_in_ass_url || '',
         embedded_sub_enabled: map.embedded_sub_enabled === 'true',
         embedded_sub_tracks: (() => {
           try {
             const parsed = JSON.parse(map.embedded_sub_tracks || '[]')
             return Array.isArray(parsed) ? parsed : []
           } catch { return [] }
         })(),
         embedded_sub_include_movies: map.embedded_sub_include_movies === 'true',
       })
     } catch (e) {
       message.error('加载配置失败: ' + (e?.message || '未知错误'))
     } finally {
       setLoading(false)
     }
   }, [form])
 
   useEffect(() => { fetchConfigs() }, [fetchConfigs])
 
   const handleSave = async () => {
     let values
     try { values = await form.validateFields() } catch { return }
     setSaving(true)
     try {
       const saveOne = async (key, value) => { await systemApi.setConfig({ key, value }) }
       await saveOne('font_in_ass_enabled', String(!!values.font_in_ass_enabled))
       await saveOne('subtitle_engine', values.subtitle_engine || 'external')
       await saveOne('font_in_ass_url', values.font_in_ass_url || '')
       await saveOne('embedded_sub_enabled', String(!!values.embedded_sub_enabled))
       await saveOne('embedded_sub_tracks', JSON.stringify(values.embedded_sub_tracks || []))
       await saveOne('embedded_sub_include_movies', String(!!values.embedded_sub_include_movies))
       message.success('保存成功')
     } catch (e) {
       message.error('保存失败: ' + (e?.message || '未知错误'))
     } finally {
       setSaving(false)
     }
   }
 
   return (
     <Spin spinning={loading}>
       <Form form={form} layout="vertical" initialValues={DEFAULTS}>
         <Row gutter={[16, 16]}>
           <Col span={24}>
             <Card size="small" title={<><FontSizeOutlined style={{ marginRight: 6 }} />实时字幕字体子集化</>}>
               <Form.Item name="font_in_ass_enabled" label="启用实时字幕子集化" valuePropName="checked">
                 <Switch />
               </Form.Item>
               <Text type="secondary">
                 播放器请求 ASS/SSA/SRT 字幕时实时拦截，将字体子集化后嵌入字幕，使无字体的设备正确显示字幕。
               </Text>
             </Card>
           </Col>
           <Col span={24}>
             <Card size="small" title="子集化引擎">
               <Form.Item name="subtitle_engine" label="使用引擎">
                 <Radio.Group onChange={e => setEngine(e.target.value)}>
                   <Space direction="vertical" style={{ width: '100%' }}>
                     <Radio value="external">
                       <Text strong>外置 fontInAss</Text><br />
                       <Text type="secondary" style={{ fontSize: 12 }}>
                         转发给独立部署的 fontInAss 服务（需额外容器，镜像 riderlty/fontinass:noproxy）
                       </Text>
                     </Radio>
                     <Radio value="builtin">
                       <Text strong>内置引擎</Text><br />
                       <Text type="secondary" style={{ fontSize: 12 }}>
                         使用内置 fonttools 处理，无需外部服务；字体放入挂载目录{' '}
                         <Text code style={{ fontSize: 11 }}>/data/config/fonts</Text>{' '}
                         （在线字体自动下载到 downloads 子目录）
                       </Text>
                     </Radio>
                   </Space>
                 </Radio.Group>
               </Form.Item>
               {engine === 'external' && (
                 <Form.Item name="font_in_ass_url" label="fontInAss 服务地址"
                   rules={[{ required: true, message: '请填写 fontInAss 服务地址' }]}>
                   <Input placeholder="http://fontinass:8011" allowClear />
                 </Form.Item>
               )}
               {engine === 'builtin' && (
                 <Alert type="info" showIcon style={{ marginTop: 8 }} message="字体目录说明"
                   description={
                     <span>
                       将字体文件（.ttf / .otf / .ttc）放入{' '}
                       <Text code>/data/config/fonts</Text>{' '}
                       下（递归扫描，但排除 <Text code>downloads</Text> 子目录）。
                       找不到的字体从 fontInAss 在线字体库自动下载，保存至{' '}
                       <Text code>/data/config/fonts/downloads</Text>。
                     </span>
                   }
                 />
               )}
             </Card>
           </Col>
           <Col span={24}>
             <Card size="small" title="内封字幕提取缓存">
               <Form.Item name="embedded_sub_enabled" label="启用内封字幕提取" valuePropName="checked">
                 <Switch />
               </Form.Item>
               <Form.Item name="embedded_sub_tracks" label="轨道匹配优先级">
                 <Select mode="tags" tokenSeparators={[',']} placeholder="例如 zh, chi, chs, jpn" open={false} />
               </Form.Item>
               <Form.Item name="embedded_sub_include_movies" label="对电影也生效" valuePropName="checked">
                 <Switch />
               </Form.Item>
               <Text type="secondary">
                 默认只对剧集生效。开启后仅在没有外挂字幕时触发，按顺序匹配轨道，未匹配则取第一条。
               </Text>
             </Card>
           </Col>
         </Row>
         <div style={{ marginTop: 16 }}>
           <Button type="primary" icon={<SaveOutlined />} loading={saving} onClick={handleSave}>
             保存配置
           </Button>
         </div>
       </Form>
     </Spin>
   )
 }
 
 // ═══════════════════════════════════════════════════════════
 // Tab2：已缓存字幕列表
 // ═══════════════════════════════════════════════════════════
 const CacheTab = () => {
   const [loading, setLoading] = useState(false)
   const [items, setItems] = useState([])
   const [total, setTotal] = useState(0)
 
   const fetchCache = useCallback(async () => {
     setLoading(true)
     try {
       const { data } = await subtitleApi.listEmbeddedCache()
       setItems(data?.items || [])
       setTotal(data?.total || 0)
     } catch (e) {
       message.error('加载字幕缓存失败: ' + (e?.message || '未知错误'))
     } finally {
       setLoading(false)
     }
   }, [])
 
   useEffect(() => { fetchCache() }, [fetchCache])
 
   const columns = [
     { title: 'Item ID', dataIndex: 'item_id', key: 'item_id', width: 100 },
     {
       title: '语言', dataIndex: 'lang', key: 'lang', width: 80,
       render: v => v ? <Tag color="blue">{v}</Tag> : <Text type="secondary">-</Text>,
     },
     { title: '标题', dataIndex: 'title', key: 'title', ellipsis: true },
     { title: '格式', dataIndex: 'codec', key: 'codec', width: 80,
       render: v => v ? <Tag>{v.toUpperCase()}</Tag> : '-' },
     { title: '大小', dataIndex: 'size', key: 'size', width: 90,
       render: v => fmtBytes(v) },
     { title: '剩余有效期', dataIndex: 'ttl', key: 'ttl', width: 110,
       render: v => <Text type={v < 300 ? 'warning' : 'secondary'}>{fmtTtl(v)}</Text> },
   ]
 
   return (
     <Card size="small"
       title={<>已缓存内封字幕 <Badge count={total} showZero style={{ backgroundColor: '#1677ff', marginLeft: 6 }} /></>}
       extra={<Button size="small" icon={<ReloadOutlined />} onClick={fetchCache} loading={loading}>刷新</Button>}
     >
       {items.length === 0 && !loading
         ? <Alert type="info" showIcon message="当前没有已缓存的内封字幕" description="内封字幕在播放时自动提取并缓存，缓存有效期 6 小时。" />
         : <Table
             size="small"
             loading={loading}
             dataSource={items}
             columns={columns}
             rowKey="item_id"
             pagination={{ pageSize: 20, showTotal: t => `共 ${t} 条` }}
           />
       }
     </Card>
   )
 }
 
 // ═══════════════════════════════════════════════════════════
 // Tab3：字体情况
 // ═══════════════════════════════════════════════════════════
 const FontTab = () => {
   const [loading, setLoading] = useState(false)
   const [scanning, setScanning] = useState(false)
   const [status, setStatus] = useState(null)
 
   const fetchStatus = useCallback(async () => {
     setLoading(true)
     try {
       const { data } = await subtitleApi.getFontStatus()
       setStatus(data)
     } catch (e) {
       message.error('加载字体状态失败: ' + (e?.message || '未知错误'))
     } finally {
       setLoading(false)
     }
   }, [])
 
   useEffect(() => { fetchStatus() }, [fetchStatus])
 
   const handleScan = async () => {
     setScanning(true)
     try {
       const { data } = await subtitleApi.triggerFontScan()
       if (data?.success) {
         message.success(`扫描完成：新增 ${data.inserted ?? 0} 删除 ${data.deleted ?? 0} 未变 ${data.unchanged ?? 0}，耗时 ${data.elapsed ?? 0}s`)
         await fetchStatus()
       } else {
         message.error('扫描失败: ' + (data?.error || '未知错误'))
       }
     } catch (e) {
       message.error('扫描请求失败: ' + (e?.message || '未知错误'))
     } finally {
       setScanning(false)
     }
   }
 
   const fontColumns = [
     { title: '字体族名', key: 'family', render: (_, r) =>
       (r.family_names || []).map(n => <Tag key={n}>{n}</Tag>) },
     { title: '全名', key: 'full', render: (_, r) =>
       (r.full_names || []).slice(0, 2).map(n =>
         <Text key={n} type="secondary" style={{ fontSize: 12, marginRight: 4 }}>{n}</Text>
       )
     },
     { title: '属性', key: 'attr', width: 100,
       render: (_, r) => (
         <Space>
           {r.is_bold && <Tag color="orange">Bold</Tag>}
           {r.is_italic && <Tag color="purple">Italic</Tag>}
           {!r.is_bold && !r.is_italic && <Tag>Regular</Tag>}
         </Space>
       )
     },
     { title: '字重', dataIndex: 'weight', key: 'weight', width: 70 },
     { title: 'Face', dataIndex: 'face_index', key: 'face_index', width: 60 },
     { title: '文件', dataIndex: 'path', key: 'path', ellipsis: true,
       render: v => <Tooltip title={v}><Text code style={{ fontSize: 11 }}>{v.split('/').pop()}</Text></Tooltip> },
     { title: '大小', dataIndex: 'file_size', key: 'file_size', width: 90,
       render: v => fmtBytes(v) },
   ]
 
   return (
     <Spin spinning={loading}>
       <Row gutter={[16, 16]}>
         <Col span={24}>
           <Card size="small"
             title={<><ScanOutlined style={{ marginRight: 6 }} />字体目录状态</>}
             extra={
               <Space>
                 <Button size="small" icon={<ReloadOutlined />} onClick={fetchStatus} loading={loading}>刷新</Button>
                 <Button size="small" type="primary" icon={<ScanOutlined />} onClick={handleScan} loading={scanning}>
                   重新扫描
                 </Button>
               </Space>
             }
           >
             {status && (
               <Row gutter={16}>
                 <Col>
                   <Text type="secondary">字体目录：</Text>
                   <Text code>{status.fonts_root}</Text>
                 </Col>
                 <Col>
                   <Text type="secondary">已索引文件：</Text>
                   <Text strong>{status.file_count}</Text> 个
                 </Col>
                 <Col>
                   <Text type="secondary">Face 总数：</Text>
                   <Text strong>{status.face_count}</Text> 个
                 </Col>
               </Row>
             )}
             {status?.face_count === 0 && (
               <Alert type="warning" showIcon style={{ marginTop: 12 }}
                 message="字体目录为空"
                 description={
                   <span>
                     未扫描到任何字体。请将字体文件（.ttf / .otf / .ttc）放入{' '}
                     <Text code>{status?.fonts_root || '/data/config/fonts'}</Text>{' '}
                     后点击「重新扫描」，或等待下次自动扫描。
                   </span>
                 }
               />
             )}
             {status?.error && (
               <Alert type="error" showIcon style={{ marginTop: 12 }}
                 message="获取字体状态出错" description={status.error} />
             )}
           </Card>
         </Col>
         {status?.face_count > 0 && (
           <Col span={24}>
             <Card size="small" title={`已索引字体列表（共 ${status.face_count} 个 face，最多显示 200 条）`}>
               <Table
                 size="small"
                 dataSource={status?.fonts || []}
                 columns={fontColumns}
                 rowKey={(r, i) => `${r.path}-${r.face_index}-${i}`}
                 pagination={{ pageSize: 20, showTotal: t => `共 ${t} 条` }}
               />
             </Card>
           </Col>
         )}
       </Row>
     </Spin>
   )
 }
 
 // ═══════════════════════════════════════════════════════════
 // 主页面：三 Tab 卡片
 // ═══════════════════════════════════════════════════════════
 export const RealtimeSubtitle = () => {
   const tabItems = [
     { key: 'config',  label: '当前配置',   children: <ConfigTab /> },
     { key: 'cache',   label: '已缓存字幕', children: <CacheTab /> },
     { key: 'fonts',   label: '字体情况',   children: <FontTab /> },
   ]
   return <Tabs items={tabItems} defaultActiveKey="config" />
 }
