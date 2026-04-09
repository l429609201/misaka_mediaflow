 // web/src/pages/drive115-account/index.jsx
 // 115 账号管理 — 账号信息 + Cookie登录 + 高级设置 + 路径映射
 // 从原 drive115/index.jsx 左列 + 中列拆分而来，全部 i18n
 
 import { useCallback, useEffect, useRef, useState } from 'react'
 import {
   Alert, Avatar, Button, Card, Col, Descriptions, Divider,
   Form, Input, InputNumber, Modal, Progress, Row, Select,
   Space, Spin, Tag, Typography, message, theme,
 } from 'antd'
 import {
   AlipayCircleOutlined, CheckCircleOutlined, CloseCircleOutlined,
   CloudSyncOutlined, DesktopOutlined, FolderOpenOutlined,
   KeyOutlined, MobileOutlined, NodeIndexOutlined,
   QrcodeOutlined, SaveOutlined, UserOutlined, WechatOutlined,
 } from '@ant-design/icons'
 import { useTranslation } from 'react-i18next'
 import { p115Api, storageApi } from '@/apis'
 import DirPickerModal from '@/components/DirPickerModal'
 import LocalDirPickerModal from '@/components/LocalDirPickerModal'
 import StorageDirPickerModal from '@/components/StorageDirPickerModal'
 
 const { TextArea } = Input
 const { Text, Title } = Typography
 
 export const Drive115Account = () => {
   const { t } = useTranslation()
   const { token } = theme.useToken()
 
   const [status,  setStatus]  = useState({})
   const [loading, setLoading] = useState(true)
   const [account, setAccount] = useState({})
 
   const [cookieModal,  setCookieModal]  = useState(false)
   const [cookieValue,  setCookieValue]  = useState('')
   const [cookieSaving, setCookieSaving] = useState(false)
 
   const [qrModal,  setQrModal]  = useState(false)
   const [qrData,   setQrData]   = useState(null)
   const [qrStatus, setQrStatus] = useState('idle')
   const [qrApp,    setQrApp]    = useState('alipaymini')
   const pollRef = useRef(null)
 
   const [settingsSaving, setSettingsSaving] = useState(false)
   const [settingsForm] = Form.useForm()
 
   const [mappingLoading,       setMappingLoading]       = useState(true)
   const [mappingSaving,        setMappingSaving]        = useState(false)
   const [mappingForm]                                   = Form.useForm()
   const [dirPickerOpen,        setDirPickerOpen]        = useState(false)
   const [dirPickerTarget,      setDirPickerTarget]      = useState(null)
   const [localDirPickerOpen,   setLocalDirPickerOpen]   = useState(false)
   const [localDirPickerTarget, setLocalDirPickerTarget] = useState(null)
   const [storageSources,       setStorageSources]       = useState([])
   const [localMediaSource,     setLocalMediaSource]     = useState('local')
   const [storageDirPickerOpen, setStorageDirPickerOpen] = useState(false)
 
   // ── 数据加载 ────────────────────────────────────────────────────────────
   const fetchStatus = useCallback(async () => {
     try { const { data } = await p115Api.status(); setStatus(data) }
     finally { setLoading(false) }
   }, [])
   const fetchAccount = useCallback(async () => {
     try { const { data } = await p115Api.getAccount(); setAccount(data) }
     catch { /* ignore */ }
   }, [])
   const fetchPathMapping = useCallback(async () => {
     try {
       const { data } = await p115Api.getPathMapping()
       mappingForm.setFieldsValue(data)
       if (data.local_media_source) setLocalMediaSource(data.local_media_source)
     } catch { /* ignore */ } finally { setMappingLoading(false) }
   }, [mappingForm])
   const fetchStorageSources = useCallback(async () => {
     try {
       const { data } = await storageApi.list()
       setStorageSources(Array.isArray(data) ? data : (data?.items || []))
     } catch { /* ignore */ }
   }, [])
   const fetchSettings = useCallback(async () => {
     try { const { data } = await p115Api.getSettings(); settingsForm.setFieldsValue(data) }
     catch { /* ignore */ }
   }, [settingsForm])
 
   useEffect(() => {
     fetchStatus(); fetchAccount(); fetchPathMapping()
     fetchSettings(); fetchStorageSources()
   }, [fetchStatus, fetchAccount, fetchPathMapping, fetchSettings, fetchStorageSources])
 
   // ── Cookie 操作 ─────────────────────────────────────────────────────────
   const handleSetCookie = async () => {
     if (!cookieValue.trim()) return
     setCookieSaving(true)
     try {
       const { data } = await p115Api.setCookie(cookieValue)
       if (data.valid) {
         message.success(t('p115.cookieSet'))
         setCookieModal(false); setCookieValue('')
         fetchStatus(); fetchAccount()
       } else { message.warning(t('p115.cookieNotSet')) }
     } catch { message.error(t('common.failed')) }
     finally { setCookieSaving(false) }
   }
 
   // ── 扫码登录 ─────────────────────────────────────────────────────────────
   const stopPolling = useCallback(() => {
     if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
   }, [])
   const handleOpenQr = async () => {
     stopPolling()
     setQrModal(true); setQrStatus('loading'); setQrData(null)
     try {
       const { data } = await p115Api.qrcodeStart(qrApp)
       setQrData(data); setQrStatus('waiting')
       pollRef.current = setInterval(async () => {
         try {
           const { data: poll } = await p115Api.qrcodePoll({
             uid: data.uid, time: data.time, sign: data.sign, app: qrApp,
           })
           const s = poll.status
           if (s === 'scanned') { setQrStatus('scanned') }
           else if (s === 'success') {
             stopPolling(); setQrStatus('success')
             message.success(t('p115.qrSuccess'))
             setTimeout(() => { setQrModal(false); fetchStatus(); fetchAccount() }, 1500)
           } else if (s === 'expired') { stopPolling(); setQrStatus('expired') }
           else if (['canceled','failed','error'].includes(s)) { stopPolling(); setQrStatus('failed') }
         } catch (err) { console.warn('[qr poll error]', err) }
       }, 2000)
     } catch { setQrStatus('failed') }
   }
   const handleCloseQr = () => { stopPolling(); setQrModal(false) }
 
   // ── 高级设置 ─────────────────────────────────────────────────────────────
   const handleSaveSettings = async () => {
     setSettingsSaving(true)
     try {
       const values = await settingsForm.validateFields()
       await p115Api.saveSettings(values)
       message.success(t('common.success'))
     } catch { message.error(t('common.failed')) }
     finally { setSettingsSaving(false) }
   }
 
   // ── 路径映射 ─────────────────────────────────────────────────────────────
   const handleSavePathMapping = async () => {
     setMappingSaving(true)
     try {
       const values = await mappingForm.validateFields()
       values.local_media_source = localMediaSource
       await p115Api.savePathMapping(values)
       message.success(t('common.success')); fetchPathMapping()
     } catch { message.error(t('common.failed')) }
     finally { setMappingSaving(false) }
   }
   const openDirPicker      = (f) => { setDirPickerTarget(f);      setDirPickerOpen(true) }
   const openLocalDirPicker = (f) => { setLocalDirPickerTarget(f); setLocalDirPickerOpen(true) }
   const handleDirSelected      = (p) => { if (dirPickerTarget)      mappingForm.setFieldValue(dirPickerTarget, p) }
   const handleLocalDirSelected = (p) => { if (localDirPickerTarget) mappingForm.setFieldValue(localDirPickerTarget, p) }
 
   const formatSize = (bytes) => {
     if (!bytes) return '0 B'
     const units = ['B','KB','MB','GB','TB','PB']
     const i = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1)
     return (bytes / Math.pow(1024, i)).toFixed(1) + ' ' + units[i]
   }
   const spacePercent = account.space_total
     ? Math.round((account.space_used / account.space_total) * 100) : 0
 
   const qrStatusHint = {
     idle: '', loading: t('p115.qrLoading'), waiting: t('p115.qrWaiting'),
     scanned: t('p115.qrScanned'), success: t('p115.qrSuccess'),
     expired: t('p115.qrExpired'), failed: t('p115.qrFailed'),
   }
   const APP_OPTIONS = [
     { value: 'alipaymini', label: t('p115.appAlipay'),     icon: <AlipayCircleOutlined /> },
     { value: 'wechatmini', label: t('p115.appWechat'),     icon: <WechatOutlined /> },
     { value: 'android',    label: t('p115.appAndroid'),    icon: <MobileOutlined /> },
     { value: '115android', label: t('p115.app115Android'), icon: <MobileOutlined /> },
     { value: 'ios',        label: t('p115.appIos'),        icon: <MobileOutlined /> },
     { value: '115ios',     label: t('p115.app115Ios'),     icon: <MobileOutlined /> },
     { value: 'web',        label: t('p115.appWeb'),        icon: <DesktopOutlined /> },
     { value: 'tv',         label: t('p115.appTv'),         icon: <DesktopOutlined /> },
     { value: 'qandroid',   label: t('p115.appQandroid'),   icon: <MobileOutlined /> },
     { value: '115ipad',    label: t('p115.app115Ipad'),    icon: <MobileOutlined /> },
   ]
 
   if (!status.enabled && !loading) {
     return (
       <div style={{ padding: 24 }}>
         <Alert type="warning" message={t('p115.notEnabled')} description={t('p115.enableHint')} showIcon />
       </div>
     )
   }
 
   return (
     <div style={{ padding: 24 }}>
       <Title level={4} style={{ marginBottom: 16 }}>
         <Space><CloudSyncOutlined />{t('menu.drive115Account')}</Space>
       </Title>
       <Row gutter={[24, 24]}>
 
         {/* 左列：账号信息 + 高级设置 */}
         <Col xs={24} lg={12}>
           <Spin spinning={loading}>
             <Card
               title={<Space><CloudSyncOutlined />{t('p115.tabDrive')}</Space>}
               extra={
                 <Space>
                   {!loading && (status.cookie
                     ? <Tag color="success">{t('p115.connected')}</Tag>
                     : <Tag color="error">{t('p115.disconnected')}</Tag>)}
                   <Button type="primary" icon={<SaveOutlined />} loading={settingsSaving} onClick={handleSaveSettings}>
                     {t('common.save')}
                   </Button>
                 </Space>
               }
             >
               {account.logged_in && (
                 <>
                   <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12 }}>
                     <Avatar size={48} src={account.avatar} icon={!account.avatar && <UserOutlined />} />
                     <div style={{ flex: 1 }}>
                       <Space>
                         <Text strong style={{ fontSize: 16 }}>{account.user_name}</Text>
                         {account.vip_name && <Tag color={account.vip_color || 'gold'}>{account.vip_name}</Tag>}
                       </Space>
                       <div style={{ marginTop: 4 }}>
                         <Progress percent={spacePercent} size="small"
                           format={() => `${formatSize(account.space_used)} / ${formatSize(account.space_total)}`}
                           strokeColor={spacePercent > 90 ? '#ff4d4f' : spacePercent > 70 ? '#faad14' : undefined}
                         />
                       </div>
                     </div>
                   </div>
                   <Divider style={{ margin: '8px 0 16px' }} />
                 </>
               )}
               <Descriptions column={1} bordered size="small" style={{ marginBottom: 16 }}>
                 <Descriptions.Item label={t('p115.cookieStatus')}>
                   <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', width: '100%' }}>
                     {status.cookie
                       ? <Tag icon={<CheckCircleOutlined />} color="success">{t('p115.cookieSet')}</Tag>
                       : <Tag icon={<CloseCircleOutlined />} color="error">{t('p115.cookieNotSet')}</Tag>}
                     <Space size="small">
                       <Button size="small" icon={<KeyOutlined />} onClick={() => setCookieModal(true)}>{t('p115.setCookie')}</Button>
                       <Button size="small" icon={<QrcodeOutlined />} onClick={handleOpenQr}>{t('p115.scanLogin')}</Button>
                     </Space>
                   </div>
                 </Descriptions.Item>
                 <Descriptions.Item label={t('p115.openapiStatus')}>
                   {status.openapi
                     ? <Tag icon={<CheckCircleOutlined />} color="success">{t('p115.openapiSet')}</Tag>
                     : <Tag icon={<CloseCircleOutlined />} color="warning">{t('p115.openapiNotSet')}</Tag>}
                 </Descriptions.Item>
                 <Descriptions.Item label={t('p115.rateBlocked')}>
                   {status.rate_blocked ? <Tag color="error">Blocked</Tag> : <Tag color="success">OK</Tag>}
                 </Descriptions.Item>
                 <Descriptions.Item label={t('p115.cacheSize')}>{status.cache_size ?? 0}</Descriptions.Item>
               </Descriptions>
               <Form form={settingsForm} layout="vertical" size="small"
                 initialValues={{ api_interval: 1, api_concurrent: 3, file_extensions: 'mp4,mkv,avi,ts,iso,mov,m2ts', fscache_ttl_hours: 24 }}
               >
                 <Row gutter={16}>
                   <Col span={12}>
                     <Form.Item name="api_interval" label={t('p115.apiInterval')} tooltip={t('p115.apiIntervalHint')}>
                       <InputNumber min={0.1} step={0.5} style={{ width: '100%' }} addonAfter={t('p115.seconds')} />
                     </Form.Item>
                   </Col>
                   <Col span={12}>
                     <Form.Item name="api_concurrent" label={t('p115.apiConcurrent')} tooltip={t('p115.apiConcurrentHint')}>
                       <InputNumber min={1} max={10} style={{ width: '100%' }} />
                     </Form.Item>
                   </Col>
                 </Row>
                 <Form.Item name="file_extensions" label={t('p115.fileExtensions')} tooltip={t('p115.fileExtensionsHint')}>
                   <Input placeholder="mp4,mkv,avi,ts,iso,mov,m2ts" />
                 </Form.Item>
                 <Form.Item name="strm_link_host" label="base_url"
                   tooltip={t('p115.strmLinkHostHint')}>
                   <Input placeholder="http://192.168.1.10:9906" allowClear />
                 </Form.Item>
                 <Form.Item name="fscache_ttl_hours" label={t('p115.advancedSettings')}
                   tooltip="全量同步(skip模式)目录树缓存有效期，0=禁用">
                   <InputNumber min={0} max={168} step={1} style={{ width: '100%' }} addonAfter="h" />
                 </Form.Item>
               </Form>
             </Card>
           </Spin>
         </Col>
 
         {/* 右列：路径映射 */}
         <Col xs={24} lg={12}>
           <Spin spinning={mappingLoading}>
             <Card
               title={<Space><NodeIndexOutlined />{t('p115.pathMappingTitle')}</Space>}
               extra={
                 <Button type="primary" icon={<SaveOutlined />} loading={mappingSaving} onClick={handleSavePathMapping}>
                   {t('common.save')}
                 </Button>
               }
             >
               <Alert type="info" showIcon style={{ marginBottom: 16 }} message={t('p115.pathMappingHint')} />
               <Form form={mappingForm} layout="vertical" size="small"
                 initialValues={{ media_prefix: '', cloud_prefix: '', strm_prefix: '', local_media_prefix: '', organize_source: '', organize_unrecognized: '' }}
               >
                 <Form.Item name="cloud_prefix" label={t('p115.cloudPrefix')} tooltip={t('p115.cloudPrefixHint')}>
                   <Input placeholder="/media" addonAfter={
                     <Button type="link" size="small" icon={<FolderOpenOutlined />}
                       onClick={() => openDirPicker('cloud_prefix')} style={{ padding: 0, height: 'auto' }}>
                       {t('p115.selectDir')}
                     </Button>} />
                 </Form.Item>
                 <Form.Item name="organize_source" label={t('p115.organizeSource')} tooltip={t('p115.organizeSourceHint')}>
                   <Input placeholder="/pending" addonAfter={
                     <Button type="link" size="small" icon={<FolderOpenOutlined />}
                       onClick={() => openDirPicker('organize_source')} style={{ padding: 0, height: 'auto' }}>
                       {t('p115.selectDir')}
                     </Button>} />
                 </Form.Item>
                 <Form.Item name="organize_unrecognized" label={t('p115.organizeUnrecognized')} tooltip={t('p115.organizeUnrecognizedHint')}>
                   <Input placeholder="/unrecognized" addonAfter={
                     <Button type="link" size="small" icon={<FolderOpenOutlined />}
                       onClick={() => openDirPicker('organize_unrecognized')} style={{ padding: 0, height: 'auto' }}>
                       {t('p115.selectDir')}
                     </Button>} />
                 </Form.Item>
                 <Form.Item name="media_prefix" label={t('p115.mediaPrefix')} tooltip={t('p115.mediaPrefixHint')}>
                   <Input placeholder="/media/movies" />
                 </Form.Item>
                 <Form.Item name="strm_prefix" label={t('p115.strmPrefix')} tooltip={t('p115.strmPrefixHint')}>
                   <Input placeholder="/config/strm/movies" addonAfter={
                     <Button type="link" size="small" icon={<FolderOpenOutlined />}
                       onClick={() => openLocalDirPicker('strm_prefix')} style={{ padding: 0, height: 'auto' }}>
                       {t('p115.selectDir')}
                     </Button>} />
                 </Form.Item>
                 <Form.Item name="local_media_prefix" label={t('p115.localMediaPrefix')} tooltip={t('p115.localMediaPrefixHint')}>
                   <Input placeholder="/cd2/115open"
                     addonBefore={
                       <Select value={localMediaSource} onChange={setLocalMediaSource} style={{ width: 120 }}
                         options={[
                           { value: 'local', label: t('p115.localMediaSourceLocal') },
                           ...storageSources.filter(s => s.is_active).map(s => ({ value: String(s.id), label: s.name })),
                           { value: 'storage_dir', label: t('p115.localMediaSourceStorage') },
                         ]} />
                     }
                     addonAfter={
                       localMediaSource === 'storage_dir'
                         ? <Button type="link" size="small" icon={<FolderOpenOutlined />}
                             onClick={() => setStorageDirPickerOpen(true)} style={{ padding: 0, height: 'auto' }}>
                             {t('p115.selectDir')}
                           </Button>
                         : localMediaSource === 'local'
                           ? <Button type="link" size="small" icon={<FolderOpenOutlined />}
                               onClick={() => openLocalDirPicker('local_media_prefix')} style={{ padding: 0, height: 'auto' }}>
                               {t('p115.selectDir')}
                             </Button>
                           : null
                     }
                   />
                 </Form.Item>
               </Form>
             </Card>
           </Spin>
         </Col>
 
       </Row>
 
       {/* Cookie 弹窗 */}
       <Modal title={t('p115.setCookie')} open={cookieModal}
         onCancel={() => setCookieModal(false)} onOk={handleSetCookie} confirmLoading={cookieSaving}>
         <TextArea rows={4} value={cookieValue}
           onChange={e => setCookieValue(e.target.value)} placeholder={t('p115.cookiePlaceholder')} />
       </Modal>
 
       {/* 扫码弹窗 */}
       <Modal title={t('p115.scanLogin')} open={qrModal} onCancel={handleCloseQr} footer={null} width={420}>
         <div style={{ marginBottom: 12 }}>
           <Text type="secondary">{t('p115.selectAppType')}</Text>
           <Select value={qrApp} onChange={v => setQrApp(v)} style={{ width: '100%', marginTop: 8 }}
             options={APP_OPTIONS.map(o => ({ value: o.value, label: <Space>{o.icon}{o.label}</Space> }))}
           />
         </div>
         <div style={{ textAlign: 'center', padding: '16px 0' }}>
           {qrStatus === 'loading' && <Spin tip={t('p115.qrLoading')} />}
           {(qrStatus === 'waiting' || qrStatus === 'scanned') && qrData?.qrcode_content && (
             <div style={{ position: 'relative', display: 'inline-block' }}>
               <img src={qrData.qrcode_content} alt="QR Code"
                 style={{ width: 200, height: 200, filter: qrStatus === 'scanned' ? 'brightness(0.45)' : 'none', borderRadius: 8, display: 'block' }}
               />
               {qrStatus === 'scanned' && (
                 <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 8 }}>
                   <CheckCircleOutlined style={{ fontSize: 48, color: '#52c41a' }} />
                   <span style={{ color: '#fff', fontWeight: 600, fontSize: 13 }}>{t('p115.qrScanned')}</span>
                 </div>
               )}
             </div>
           )}
           {qrStatus === 'success' && <Alert type="success" message={t('p115.qrSuccess')} showIcon />}
           {qrStatus === 'expired' && <Space direction="vertical"><Alert type="warning" message={t('p115.qrExpired')} showIcon /><Button onClick={handleOpenQr}>{t('p115.qrRetry')}</Button></Space>}
           {qrStatus === 'failed'  && <Space direction="vertical"><Alert type="error"   message={t('p115.qrFailed')}  showIcon /><Button onClick={handleOpenQr}>{t('p115.qrRetry')}</Button></Space>}
         </div>
         <div style={{ textAlign: 'center' }}><Text type="secondary">{qrStatusHint[qrStatus]}</Text></div>
       </Modal>
 
       <DirPickerModal open={dirPickerOpen} onClose={() => setDirPickerOpen(false)} onSelect={handleDirSelected} />
       <LocalDirPickerModal open={localDirPickerOpen} onClose={() => setLocalDirPickerOpen(false)} onSelect={handleLocalDirSelected} />
       <StorageDirPickerModal
         open={storageDirPickerOpen} onClose={() => setStorageDirPickerOpen(false)}
         storageId={localMediaSource !== 'local' ? Number(localMediaSource) : null}
         onSelect={p => mappingForm.setFieldValue('local_media_prefix', p)}
       />
     </div>
   )
 }
 
 export default Drive115Account
