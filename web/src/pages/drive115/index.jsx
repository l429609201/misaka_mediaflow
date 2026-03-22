// src/pages/drive115/index.jsx
// 115 网盘 -- 无Tab三列布局:
//   左列: 115网盘账号+高级设置（上）、生活事件监控（下）
//   中列: 整理与路径映射
//   右列: STRM 生成

import { useEffect, useState, useCallback, useRef } from 'react'
import {
  Card, Descriptions, Tag, Button, Input, InputNumber, Modal, message,
  Space, Alert, Row, Col, Spin, Typography, Form, Select, QRCode,
  Avatar, Progress, Divider, Switch, Badge, Tooltip,
} from 'antd'
import {
  CheckCircleOutlined, CloseCircleOutlined, CloudSyncOutlined,
  KeyOutlined, QrcodeOutlined, SaveOutlined,
  MobileOutlined, DesktopOutlined, WechatOutlined, AlipayCircleOutlined,
  NodeIndexOutlined, FolderOpenOutlined, UserOutlined,
  ThunderboltOutlined, SyncOutlined, PlayCircleOutlined,
  PauseCircleOutlined, ClockCircleOutlined, CodeOutlined,
} from '@ant-design/icons'
import { useTranslation } from 'react-i18next'
import { p115Api, storageApi, p115StrmApi, strmApi } from '@/apis'
import DirPickerModal from '@/components/DirPickerModal'
import LocalDirPickerModal from '@/components/LocalDirPickerModal'
import StorageDirPickerModal from '@/components/StorageDirPickerModal'

const { TextArea } = Input
const { Text } = Typography

const DEFAULT_TEMPLATE =
  '{{ base_url }}?pickcode={{ pickcode }}{% if file_name %}&file_name={{ file_name | urlencode }}{% endif %}'

const TEMPLATE_PARAMS = [
  { label: '{{ base_url }}',                 insert: '{{ base_url }}',                 desc: '反代服务根地址' },
  { label: '{{ pickcode }}',                 insert: '{{ pickcode }}',                 desc: '115 pickcode' },
  { label: '{{ file_name }}',                insert: '{{ file_name }}',                desc: '文件名（原始）' },
  { label: 'file_name | urlencode',          insert: '{{ file_name | urlencode }}',    desc: '文件名 URL 编码' },
  { label: '{{ file_path }}',                insert: '{{ file_path }}',                desc: '网盘内文件完整路径' },
  { label: 'file_path | urlencode',          insert: '{{ file_path | urlencode }}',   desc: '网盘路径 URL 编码' },
  { label: '{{ sha1 }}',                     insert: '{{ sha1 }}',                     desc: '文件 SHA1' },
  { label: '{% if file_name %}…{% endif %}', insert: '{% if file_name %}{% endif %}',  desc: '条件块（含文件名时输出）' },
]

const StatTag = ({ value, label, color }) => (
  <Tag color={color} style={{ fontSize: 13, padding: '2px 10px' }}>
    {label}: <b>{value ?? 0}</b>
  </Tag>
)

export const Drive115 = () => {
  const { t } = useTranslation()

  const [status,  setStatus]  = useState({})
  const [loading, setLoading] = useState(true)
  const [account, setAccount] = useState({})

  const [cookieModal,  setCookieModal]  = useState(false)
  const [cookieValue,  setCookieValue]  = useState('')
  const [cookieSaving, setCookieSaving] = useState(false)

  const [qrModal,  setQrModal]  = useState(false)
  const [qrData,   setQrData]   = useState(null)
  const [qrStatus, setQrStatus] = useState('idle')
  const [qrApp,    setQrApp]    = useState('web')
  const pollRef = useRef(null)

  const [settingsLoading, setSettingsLoading] = useState(true)
  const [settingsSaving,  setSettingsSaving]  = useState(false)
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

  const [strmStatus,  setStrmStatus]  = useState({})
  const [strmSyncing, setStrmSyncing] = useState(false)

  const [monitorCfg,    setMonitorCfg]    = useState({ poll_interval: 30, auto_inc_sync: true, monitor_dir: '', strm_dir: '', use_custom_dir: false })
  const [monitorStatus, setMonitorStatus] = useState({})
  const [monitorSaving, setMonitorSaving] = useState(false)

  // 监控目录 / STRM目录 选择器
  const [monitorDirPickerOpen, setMonitorDirPickerOpen] = useState(false)
  const [strmDirPickerOpen,    setStrmDirPickerOpen]    = useState(false)

  // STRM URL 模板
  const [urlTemplate,    setUrlTemplate]    = useState('')
  const [templateSaving, setTemplateSaving] = useState(false)
  const templateRef = useRef(null)

  // ----------------------------------------------------------------
  //  数据加载
  // ----------------------------------------------------------------
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
    catch { /* ignore */ } finally { setSettingsLoading(false) }
  }, [settingsForm])

  const fetchStrmAll = useCallback(async () => {
    try {
      const [cfgRes, stRes] = await Promise.all([
        p115StrmApi.getSyncConfig(),
        p115StrmApi.getSyncStatus(),
      ])
      setStrmStatus(stRes.data || {})
      const cfg = cfgRes.data || {}
      if (cfg.sync_pairs?.length) {
        const pair = cfg.sync_pairs[0]
        if (!mappingForm.getFieldValue('cloud_prefix') && pair.cloud_path)
          mappingForm.setFieldValue('cloud_prefix', pair.cloud_path)
        if (!mappingForm.getFieldValue('strm_prefix') && pair.strm_path)
          mappingForm.setFieldValue('strm_prefix', pair.strm_path)
      }
    } catch { /* ignore */ }
  }, [mappingForm])

  const MONITOR_CFG_DEFAULTS = {
    poll_interval:  30,
    auto_inc_sync:  true,
    monitor_dir:    '',
    strm_dir:       '',
    use_custom_dir: false,
  }

  const fetchMonitorAll = useCallback(async () => {
    try {
      const [cfgRes, stRes] = await Promise.all([
        p115StrmApi.getMonitorConfig(),
        p115StrmApi.getMonitorStatus(),
      ])
      // 用默认值兜底，防止后端缺字段导致 state 出现 undefined
      setMonitorCfg(prev => ({ ...MONITOR_CFG_DEFAULTS, ...prev, ...(cfgRes.data || {}) }))
      setMonitorStatus(stRes.data || {})
    } catch { /* ignore */ }
  }, [])

  const fetchUrlTemplate = useCallback(async () => {
    try {
      const { data } = await strmApi.getUrlTemplate()
      setUrlTemplate(data.template || DEFAULT_TEMPLATE)
    } catch { setUrlTemplate(DEFAULT_TEMPLATE) }
  }, [])

  useEffect(() => {
    fetchStatus(); fetchAccount(); fetchPathMapping()
    fetchSettings(); fetchStorageSources()
    fetchStrmAll(); fetchMonitorAll(); fetchUrlTemplate()
  }, [fetchStatus, fetchAccount, fetchPathMapping, fetchSettings,
      fetchStorageSources, fetchStrmAll, fetchMonitorAll, fetchUrlTemplate])

  useEffect(() => {
    if (status.cookie && !monitorStatus.running) {
      p115StrmApi.startMonitor().catch(() => {})
      setTimeout(fetchMonitorAll, 1000)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status.cookie])

  // ----------------------------------------------------------------
  //  Cookie
  // ----------------------------------------------------------------
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

  // ----------------------------------------------------------------
  //  扫码
  // ----------------------------------------------------------------
  const stopPolling = useCallback(() => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
  }, [])

  const handleOpenQr = async () => {
    setQrModal(true); setQrStatus('loading'); setQrData(null)
    try {
      const { data } = await p115Api.qrcodeStart(qrApp)
      setQrData(data); setQrStatus('waiting')
      pollRef.current = setInterval(async () => {
        try {
          const { data: poll } = await p115Api.qrcodePoll({
            uid: data.uid, time: data.time, sign: data.sign, app: qrApp,
          })
          if (poll.status === 'scanned') setQrStatus('scanned')
          else if (poll.status === 'success') {
            setQrStatus('success'); stopPolling()
            message.success(t('p115.qrSuccess'))
            setTimeout(() => { setQrModal(false); fetchStatus(); fetchAccount() }, 1000)
          } else if (poll.status === 'expired') { setQrStatus('expired'); stopPolling() }
          else if (poll.status === 'canceled')  { setQrStatus('failed');  stopPolling() }
        } catch { /* ignore */ }
      }, 2000)
    } catch { setQrStatus('failed') }
  }
  const handleCloseQr = () => { stopPolling(); setQrModal(false) }

  // ----------------------------------------------------------------
  //  操作
  // ----------------------------------------------------------------
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

  const handleSaveSettings = async () => {
    setSettingsSaving(true)
    try {
      const values = await settingsForm.validateFields()
      await p115Api.saveSettings(values)
      message.success(t('common.success'))
    } catch { message.error(t('common.failed')) }
    finally { setSettingsSaving(false) }
  }

  const openDirPicker          = (f) => { setDirPickerTarget(f);      setDirPickerOpen(true) }
  const openLocalDirPicker     = (f) => { setLocalDirPickerTarget(f); setLocalDirPickerOpen(true) }
  const handleDirSelected      = (p) => { if (dirPickerTarget)      mappingForm.setFieldValue(dirPickerTarget, p) }
  const handleLocalDirSelected = (p) => { if (localDirPickerTarget) mappingForm.setFieldValue(localDirPickerTarget, p) }

  const handleFullSync = async () => {
    setStrmSyncing(true)
    try {
      const cloudPath = mappingForm.getFieldValue('cloud_prefix') || ''
      const strmPath  = mappingForm.getFieldValue('strm_prefix')  || ''
      const r = await p115StrmApi.fullSync(
        cloudPath && strmPath ? { cloud_path: cloudPath, strm_path: strmPath } : undefined
      )
      r.data?.success
        ? message.success(t('p115.syncStarted'))
        : message.warning(r.data?.message || t('p115.syncStartFailed'))
      setTimeout(fetchStrmAll, 1500)
    } catch { message.error(t('common.failed')) }
    finally { setStrmSyncing(false) }
  }

  const handleIncSync = async () => {
    setStrmSyncing(true)
    try {
      const cloudPath = mappingForm.getFieldValue('cloud_prefix') || ''
      const strmPath  = mappingForm.getFieldValue('strm_prefix')  || ''
      const r = await p115StrmApi.incSync(
        cloudPath && strmPath ? { cloud_path: cloudPath, strm_path: strmPath } : undefined
      )
      r.data?.success
        ? message.success(t('p115.syncStarted'))
        : message.warning(r.data?.message || t('p115.syncStartFailed'))
      setTimeout(fetchStrmAll, 1500)
    } catch { message.error(t('common.failed')) }
    finally { setStrmSyncing(false) }
  }

  const handleMonitorSave = async () => {
    setMonitorSaving(true)
    try {
      // use_custom_dir=false 时不传目录字段，避免覆盖后端已有值
      const payload = { ...monitorCfg }
      if (!monitorCfg.use_custom_dir) {
        delete payload.monitor_dir
        delete payload.strm_dir
      }
      await p115StrmApi.saveMonitorConfig(payload)
      message.success(t('p115.configSaved'))
    }
    catch { message.error(t('p115.saveFailed')) }
    finally { setMonitorSaving(false) }
  }

  const handleMonitorToggle = async () => {
    try {
      if (monitorStatus.running) {
        await p115StrmApi.stopMonitor()
        message.success(t('p115.monitorStopped2'))
      } else {
        await p115StrmApi.startMonitor()
        message.success(t('p115.monitorStarted'))
      }
      setTimeout(fetchMonitorAll, 800)
    } catch { message.error(t('p115.operateFailed')) }
  }

  // STRM URL 模板
  const insertAtCursor = (snippet) => {
    const el = templateRef.current
    if (!el) { setUrlTemplate(s => s + snippet); return }
    const start = el.selectionStart ?? urlTemplate.length
    const end   = el.selectionEnd   ?? urlTemplate.length
    const next  = urlTemplate.slice(0, start) + snippet + urlTemplate.slice(end)
    setUrlTemplate(next)
    requestAnimationFrame(() => {
      el.focus()
      el.setSelectionRange(start + snippet.length, start + snippet.length)
    })
  }

  const handleSaveTemplate = async () => {
    setTemplateSaving(true)
    try { await strmApi.saveUrlTemplate(urlTemplate); message.success('模板已保存') }
    catch { message.error('保存失败') }
    finally { setTemplateSaving(false) }
  }

  // ----------------------------------------------------------------
  //  未启用
  // ----------------------------------------------------------------
  if (!status.enabled && !loading) {
    return (
      <div style={{ padding: 24 }}>
        <Alert type="warning" message={t('p115.notEnabled')} description={t('p115.enableHint')} showIcon />
      </div>
    )
  }

  // ----------------------------------------------------------------
  //  常量
  // ----------------------------------------------------------------
  const qrStatusHint = {
    idle: '', loading: t('p115.qrLoading'), waiting: t('p115.qrWaiting'),
    scanned: t('p115.qrScanned'), success: t('p115.qrSuccess'),
    expired: t('p115.qrExpired'), failed: t('p115.qrFailed'),
  }
  const APP_OPTIONS = [
    { value: 'web',        label: t('p115.appWeb'),        icon: <DesktopOutlined /> },
    { value: 'android',    label: t('p115.appAndroid'),    icon: <MobileOutlined /> },
    { value: 'ios',        label: t('p115.appIos'),        icon: <MobileOutlined /> },
    { value: 'alipaymini', label: t('p115.appAlipay'),     icon: <AlipayCircleOutlined /> },
    { value: 'wechatmini', label: t('p115.appWechat'),     icon: <WechatOutlined /> },
    { value: 'tv',         label: t('p115.appTv'),         icon: <DesktopOutlined /> },
    { value: 'qandroid',   label: t('p115.appQandroid'),   icon: <MobileOutlined /> },
    { value: '115android', label: t('p115.app115Android'), icon: <MobileOutlined /> },
    { value: '115ios',     label: t('p115.app115Ios'),     icon: <MobileOutlined /> },
    { value: '115ipad',    label: t('p115.app115Ipad'),    icon: <MobileOutlined /> },
  ]
  const formatSize = (bytes) => {
    if (!bytes) return '0 B'
    const units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB', 'EB']
    const i = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1)
    return (bytes / Math.pow(1024, i)).toFixed(1) + ' ' + units[i]
  }
  const spacePercent = account.space_total
    ? Math.round((account.space_used / account.space_total) * 100) : 0
  const strmProgress = strmStatus.progress || {}
  const fullStats    = strmStatus.last_full_sync_stats || {}
  const incStats     = strmStatus.last_inc_sync_stats  || {}

  // ================================================================
  //  主渲染
  // ================================================================
  return (
    <div style={{ padding: 24 }}>
      <Row gutter={[24, 24]}>

        {/* == 左列：115网盘（上）+ 监控状态（下）== */}
        <Col xs={24} lg={8}>
          <Row gutter={[0, 24]}>

            {/* 115网盘账号 + 高级设置 */}
            <Col span={24}>
              <Spin spinning={loading || settingsLoading}>
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
                    initialValues={{ api_interval: 1, api_concurrent: 3, file_extensions: 'mp4,mkv,avi,ts,iso,mov,m2ts' }}
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
                  </Form>
                </Card>
              </Spin>
            </Col>

            {/* 生活事件监控 */}
            <Col span={24}>
              <Card
                title={<Space><ClockCircleOutlined />生活事件监控</Space>}
                extra={<Button icon={<SyncOutlined />} size="small" onClick={fetchMonitorAll}>{t('common.refresh')}</Button>}
              >
                <div style={{ marginBottom: 16 }}>
                  <Badge
                    status={monitorStatus.running ? 'processing' : 'default'}
                    text={<Text strong>{monitorStatus.running ? t('p115.monitorRunning') : t('p115.monitorStopped')}</Text>}
                  />
                </div>
                <div style={{ marginBottom: 12 }}>
                  <Text type="secondary">{t('p115.lastEvent')}: </Text>
                  <Text>
                    {monitorStatus.last_event_time
                      ? new Date(monitorStatus.last_event_time * 1000).toLocaleString()
                      : '—'}
                  </Text>
                </div>
                <div style={{ marginBottom: 16 }}>
                  <Button
                    type={monitorStatus.running ? 'default' : 'primary'}
                    icon={monitorStatus.running ? <PauseCircleOutlined /> : <PlayCircleOutlined />}
                    onClick={handleMonitorToggle} block
                  >
                    {monitorStatus.running ? t('p115.stopMonitor') : t('p115.startMonitor')}
                  </Button>
                </div>
                <Divider style={{ margin: '0 0 16px' }} />
                <Form layout="vertical" size="small">
                  {/* 全局 / 自定义 目录开关 */}
                  <Form.Item style={{ marginBottom: 12 }}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                      background: monitorCfg.use_custom_dir ? '#f6ffed' : '#f5f5f5',
                      border: `1px solid ${monitorCfg.use_custom_dir ? '#b7eb8f' : '#d9d9d9'}`,
                      borderRadius: 8, padding: '8px 14px', transition: 'all .25s' }}>
                      <div>
                        <Text strong style={{ fontSize: 13 }}>
                          {monitorCfg.use_custom_dir ? '自定义目录' : '使用全局配置'}
                        </Text>
                        <div style={{ fontSize: 11, color: '#888', marginTop: 2 }}>
                          {monitorCfg.use_custom_dir
                            ? '使用下方目录，覆盖全局路径映射'
                            : '沿用「整理与路径映射」中的云盘/STRM路径'}
                        </div>
                      </div>
                      <Switch
                        checkedChildren="自定义"
                        unCheckedChildren="全局"
                        checked={monitorCfg.use_custom_dir}
                        onChange={v => setMonitorCfg(c => ({ ...c, use_custom_dir: v }))}
                      />
                    </div>
                  </Form.Item>
                  <Form.Item label="监控目录" tooltip="生活事件监控扫描的115网盘目录">
                    <Input
                      placeholder={monitorCfg.use_custom_dir ? '/待整理' : '（使用全局云盘根目录）'}
                      disabled={!monitorCfg.use_custom_dir}
                      value={monitorCfg.monitor_dir || ''}
                      onChange={e => setMonitorCfg(c => ({ ...c, monitor_dir: e.target.value }))}
                      addonAfter={
                        <Button type="link" size="small" icon={<FolderOpenOutlined />}
                          disabled={!monitorCfg.use_custom_dir}
                          onClick={() => monitorCfg.use_custom_dir && setMonitorDirPickerOpen(true)}
                          style={{ padding: 0, height: 'auto' }}>
                          选择
                        </Button>
                      }
                    />
                  </Form.Item>
                  <Form.Item label="STRM目录" tooltip="监控到新文件后生成 STRM 的本地目录">
                    <Input
                      placeholder={monitorCfg.use_custom_dir ? '/config/strm' : '（使用全局STRM根目录）'}
                      disabled={!monitorCfg.use_custom_dir}
                      value={monitorCfg.strm_dir || ''}
                      onChange={e => setMonitorCfg(c => ({ ...c, strm_dir: e.target.value }))}
                      addonAfter={
                        <Button type="link" size="small" icon={<FolderOpenOutlined />}
                          disabled={!monitorCfg.use_custom_dir}
                          onClick={() => monitorCfg.use_custom_dir && setStrmDirPickerOpen(true)}
                          style={{ padding: 0, height: 'auto' }}>
                          选择
                        </Button>
                      }
                    />
                  </Form.Item>
                  <Form.Item label={t('p115.pollInterval')}>
                    <InputNumber min={10} max={3600} value={monitorCfg.poll_interval}
                      style={{ width: '100%' }} addonAfter={t('p115.seconds')}
                      onChange={v => setMonitorCfg(c => ({ ...c, poll_interval: v }))} />
                  </Form.Item>
                  <Form.Item label={t('p115.autoIncSync')}>
                    <Switch checked={monitorCfg.auto_inc_sync}
                      onChange={v => setMonitorCfg(c => ({ ...c, auto_inc_sync: v }))} />
                  </Form.Item>
                  <Button type="primary" icon={<CheckCircleOutlined />}
                    onClick={handleMonitorSave} loading={monitorSaving} block>
                    {t('common.save')}
                  </Button>
                </Form>
                {(monitorStatus.recent_events || []).length > 0 && (
                  <>
                    <Divider style={{ margin: '16px 0 8px' }} />
                    <div style={{ fontSize: 12, color: '#888', marginBottom: 6 }}>
                      {t('p115.recentEvents', { count: (monitorStatus.recent_events || []).length })}
                    </div>
                    <div style={{ maxHeight: 160, overflowY: 'auto', fontSize: 12 }}>
                      {[...(monitorStatus.recent_events || [])].reverse().map((ev, i) => (
                        <div key={i} style={{ padding: '3px 0', borderBottom: '1px solid #f0f0f0', display: 'flex', gap: 8 }}>
                          <Tag color="blue" style={{ fontSize: 11, padding: '0 4px', margin: 0 }}>
                            {t(`p115.evType${ev.type}`) || ev.type}
                          </Tag>
                          <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            {ev.file_name}
                          </span>
                          <span style={{ color: '#aaa', flexShrink: 0 }}>
                            {new Date(ev.time * 1000).toLocaleTimeString()}
                          </span>
                        </div>
                      ))}
                    </div>
                  </>
                )}
              </Card>
            </Col>

          </Row>
        </Col>

        {/* == 中列：整理与路径映射 == */}
        <Col xs={24} lg={8}>
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

        {/* == 右列：STRM 生成 == */}
        <Col xs={24} lg={8}>
          <Card
            title={<Space><i className="iconfont icon-wenjianshengcheng" />{t('p115.strmGeneration')}</Space>}
            extra={
              <Button icon={<SyncOutlined spin={strmStatus.running} />} size="small" onClick={fetchStrmAll}>
                {t('p115.refreshStatus')}
              </Button>
            }
          >
            <Alert type="info" showIcon style={{ marginBottom: 16 }} message={t('p115.strmPathFromMapping')} />
            <Form layout="vertical" size="small">
              <Form.Item label={t('p115.cloudPrefix')}>
                <Input disabled value={mappingForm.getFieldValue('cloud_prefix') || '—'} />
              </Form.Item>
              <Form.Item label={t('p115.strmPrefix')}>
                <Input disabled value={mappingForm.getFieldValue('strm_prefix') || '—'} />
              </Form.Item>
            </Form>
            <Divider style={{ margin: '12px 0' }} />

            <div style={{ fontSize: 12, color: '#888', marginBottom: 2 }}>{t('p115.lastFullSync')}</div>
            <div style={{ fontWeight: 600, marginBottom: 6 }}>
              {strmStatus.last_full_sync
                ? new Date(strmStatus.last_full_sync * 1000).toLocaleString() : '—'}
            </div>
            <Space size={4} wrap style={{ marginBottom: 10 }}>
              <StatTag value={fullStats.created} label={t('p115.statGenerated')} color="green" />
              <StatTag value={fullStats.skipped} label={t('p115.statSkipped')}   color="default" />
              <StatTag value={fullStats.errors}  label={t('p115.statFailed')}    color="red" />
            </Space>
            {strmStatus.running && (
              <Alert style={{ marginBottom: 10 }} type="info" showIcon
                message={t('p115.syncInProgress', { count: strmProgress.created || 0 })} />
            )}
            <Button type="primary" icon={<ThunderboltOutlined />} block style={{ marginBottom: 12 }}
              loading={strmSyncing || strmStatus.running} onClick={handleFullSync}>
              {t('p115.fullSync')}
            </Button>

            <Divider style={{ margin: '0 0 12px' }} />

            <div style={{ fontSize: 12, color: '#888', marginBottom: 2 }}>{t('p115.lastIncSync')}</div>
            <div style={{ fontWeight: 600, marginBottom: 6 }}>
              {strmStatus.last_inc_sync
                ? new Date(strmStatus.last_inc_sync * 1000).toLocaleString() : '—'}
            </div>
            <Space size={4} wrap style={{ marginBottom: 10 }}>
              <StatTag value={incStats.created} label={t('p115.statGenerated')} color="green" />
              <StatTag value={incStats.skipped} label={t('p115.statSkipped')}   color="default" />
              <StatTag value={incStats.errors}  label={t('p115.statFailed')}    color="red" />
            </Space>
            <Button icon={<SyncOutlined />} block
              loading={strmSyncing || strmStatus.running} onClick={handleIncSync}>
              {t('p115.incSync')}
            </Button>

            <Divider style={{ margin: '12px 0' }} />

            {/* STRM URL 模板 */}
            <Alert type="info" showIcon style={{ marginBottom: 12 }}
              message="使用 Jinja2 语法拼接 STRM 文件内容。点击下方参数按钮可将其插入至光标所在位置。" />
            <div style={{ marginBottom: 10 }}>
              <Text type="secondary" style={{ display: 'block', marginBottom: 6, fontSize: 12 }}>
                <CodeOutlined style={{ marginRight: 4 }} />可选参数（点击插入）
              </Text>
              <Space wrap size={[6, 6]}>
                {TEMPLATE_PARAMS.map(p => (
                  <Tooltip key={p.label} title={p.desc}>
                    <Button size="small" onClick={() => insertAtCursor(p.insert)}>{p.label}</Button>
                  </Tooltip>
                ))}
              </Space>
            </div>
            <textarea
              ref={templateRef}
              value={urlTemplate}
              onChange={e => setUrlTemplate(e.target.value)}
              rows={4}
              spellCheck={false}
              style={{
                width: '100%', padding: '8px 12px', fontFamily: 'monospace', fontSize: 12,
                border: '1px solid #d9d9d9', borderRadius: 6, resize: 'vertical',
                outline: 'none', lineHeight: 1.6, boxSizing: 'border-box',
                background: 'var(--ant-color-bg-container, #fff)',
                color: 'var(--ant-color-text, #000)',
              }}
            />
            <Space style={{ marginTop: 10 }}>
              <Button type="primary" icon={<SaveOutlined />} loading={templateSaving} onClick={handleSaveTemplate}>
                保存模板
              </Button>
              <Button onClick={() => setUrlTemplate(DEFAULT_TEMPLATE)}>恢复默认</Button>
            </Space>
          </Card>
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
          {qrStatus === 'waiting' && qrData?.qrcode_content && <QRCode value={qrData.qrcode_content} size={200} />}
          {qrStatus === 'scanned' && <Alert type="info"    message={t('p115.qrScanned')} showIcon />}
          {qrStatus === 'success' && <Alert type="success" message={t('p115.qrSuccess')} showIcon />}
          {qrStatus === 'expired' && <Space direction="vertical"><Alert type="warning" message={t('p115.qrExpired')} showIcon /><Button onClick={handleOpenQr}>{t('p115.qrRetry')}</Button></Space>}
          {qrStatus === 'failed'  && <Space direction="vertical"><Alert type="error"   message={t('p115.qrFailed')}  showIcon /><Button onClick={handleOpenQr}>{t('p115.qrRetry')}</Button></Space>}
        </div>
        <div style={{ textAlign: 'center' }}><Text type="secondary">{qrStatusHint[qrStatus]}</Text></div>
      </Modal>

      {/* 目录选择器 */}
      <DirPickerModal open={dirPickerOpen} onClose={() => setDirPickerOpen(false)} onSelect={handleDirSelected} />
      <LocalDirPickerModal open={localDirPickerOpen} onClose={() => setLocalDirPickerOpen(false)} onSelect={handleLocalDirSelected} />
      <StorageDirPickerModal
        open={storageDirPickerOpen} onClose={() => setStorageDirPickerOpen(false)}
        storageId={localMediaSource !== 'local' ? Number(localMediaSource) : null}
        onSelect={p => mappingForm.setFieldValue('local_media_prefix', p)}
      />
      {/* 监控目录选择器（115网盘目录） */}
      <DirPickerModal
        open={monitorDirPickerOpen} onClose={() => setMonitorDirPickerOpen(false)}
        onSelect={p => { setMonitorCfg(c => ({ ...c, monitor_dir: p })); setMonitorDirPickerOpen(false) }}
      />
      {/* STRM目录选择器（本地目录） */}
      <LocalDirPickerModal
        open={strmDirPickerOpen} onClose={() => setStrmDirPickerOpen(false)}
        onSelect={p => { setMonitorCfg(c => ({ ...c, strm_dir: p })); setStrmDirPickerOpen(false) }}
      />
    </div>
  )
}

export default Drive115

