// src/pages/drive115/index.jsx
// 115 网盘 — Tab布局:
//   Tab1: 115网盘（左：账号信息+高级设置，右：生活事件监控）
//   Tab2: 整理&路径（左：路径映射，右：整理分类；下方：STRM生成三列卡片）

import { useEffect, useState, useRef, useCallback } from 'react'
import {
  Card, Descriptions, Tag, Button, Input, InputNumber, Modal, message,
  Space, Alert, Row, Col, Spin, Typography, Form, Select, QRCode,
  Avatar, Progress, Divider, Tabs, Switch, Badge,
} from 'antd'
import {
  CheckCircleOutlined, CloseCircleOutlined, CloudSyncOutlined,
  KeyOutlined, QrcodeOutlined, SaveOutlined,
  MobileOutlined, DesktopOutlined, WechatOutlined, AlipayCircleOutlined,
  NodeIndexOutlined, FolderOpenOutlined, UserOutlined,
  ThunderboltOutlined, SyncOutlined, PlayCircleOutlined,
  PauseCircleOutlined, FolderAddOutlined, PlusOutlined, DeleteOutlined,
  ClockCircleOutlined,
} from '@ant-design/icons'
import { useTranslation } from 'react-i18next'
import { p115Api, storageApi, p115StrmApi } from '@/apis'
import DirPickerModal from '@/components/DirPickerModal'
import LocalDirPickerModal from '@/components/LocalDirPickerModal'
import StorageDirPickerModal from '@/components/StorageDirPickerModal'

const { TextArea } = Input
const { Text } = Typography

const getDefaultStrmHost = () => {
  if (typeof window === 'undefined' || !window.location) return ''
  return window.location.origin || ''
}
const tsToStr = (ts) => ts ? new Date(ts * 1000).toLocaleString('zh-CN') : '—'
const StatTag = ({ value, label, color }) => (
  <Tag color={color} style={{ fontSize: 13, padding: '2px 10px' }}>
    {label}: <b>{value ?? 0}</b>
  </Tag>
)

export const Drive115 = () => {
  const { t } = useTranslation()

  // ── 115 状态 / 账号 ──────────────────────────────────────────────────
  const [status,  setStatus]  = useState({})
  const [loading, setLoading] = useState(true)
  const [account, setAccount] = useState({})

  // ── Cookie 弹窗 ───────────────────────────────────────────────────────
  const [cookieModal,  setCookieModal]  = useState(false)
  const [cookieValue,  setCookieValue]  = useState('')
  const [cookieSaving, setCookieSaving] = useState(false)

  // ── 扫码弹窗 ──────────────────────────────────────────────────────────
  const [qrModal,  setQrModal]  = useState(false)
  const [qrData,   setQrData]   = useState(null)
  const [qrStatus, setQrStatus] = useState('idle')
  const [qrApp,    setQrApp]    = useState('web')
  const pollRef = useRef(null)

  // ── 高级设置 ──────────────────────────────────────────────────────────
  const [settingsLoading, setSettingsLoading] = useState(true)
  const [settingsSaving,  setSettingsSaving]  = useState(false)
  const [settingsForm] = Form.useForm()

  // ── 路径映射 ──────────────────────────────────────────────────────────
  const [mappingLoading, setMappingLoading] = useState(true)
  const [mappingSaving,  setMappingSaving]  = useState(false)
  const [mappingForm] = Form.useForm()
  const [dirPickerOpen,        setDirPickerOpen]        = useState(false)
  const [dirPickerTarget,      setDirPickerTarget]      = useState(null)
  const [localDirPickerOpen,   setLocalDirPickerOpen]   = useState(false)
  const [localDirPickerTarget, setLocalDirPickerTarget] = useState(null)
  const [storageSources,       setStorageSources]       = useState([])
  const [localMediaSource,     setLocalMediaSource]     = useState('local')
  const [storageDirPickerOpen, setStorageDirPickerOpen] = useState(false)
  const defaultStrmHost = getDefaultStrmHost()

  // ── STRM 同步 ─────────────────────────────────────────────────────────
  const [strmConfig,    setStrmConfig]    = useState({ sync_pairs: [], file_extensions: 'mp4,mkv,avi,ts,iso,mov,m2ts', strm_link_host: '' })
  const [strmStatus,    setStrmStatus]    = useState({})
  const [syncPairs,     setSyncPairs]     = useState([])
  const [strmSyncing,   setStrmSyncing]   = useState(false)
  const [strmCfgSaving, setStrmCfgSaving] = useState(false)

  // ── 生活事件监控 ──────────────────────────────────────────────────────
  const [monitorCfg,    setMonitorCfg]    = useState({ poll_interval: 30, auto_inc_sync: true })
  const [monitorStatus, setMonitorStatus] = useState({})
  const [monitorSaving, setMonitorSaving] = useState(false)

  // ── 整理分类 ──────────────────────────────────────────────────────────
  const [orgCfg,     setOrgCfg]     = useState({
    source_paths: [], target_root: '', dry_run: false,
    categories: { 电影: '电影', 剧集: '剧集', 动漫: '动漫', 纪录片: '纪录片', 综艺: '综艺' },
  })
  const [orgStatus,  setOrgStatus]  = useState({})
  const [orgPaths,   setOrgPaths]   = useState([])
  const [orgSaving,  setOrgSaving]  = useState(false)
  const [orgRunning, setOrgRunning] = useState(false)

  // ===================================================================
  //                          数据加载
  // ===================================================================

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
    try { const { data } = await storageApi.list(); setStorageSources(Array.isArray(data) ? data : (data?.items || [])) }
    catch { /* ignore */ }
  }, [])
  const fetchSettings = useCallback(async () => {
    try { const { data } = await p115Api.getSettings(); settingsForm.setFieldsValue(data) }
    catch { /* ignore */ } finally { setSettingsLoading(false) }
  }, [settingsForm])
  const fetchStrmAll = useCallback(async () => {
    try {
      const [cfgRes, stRes] = await Promise.all([p115StrmApi.getSyncConfig(), p115StrmApi.getSyncStatus()])
      const cfg = cfgRes.data || {}
      setStrmConfig(cfg); setSyncPairs(cfg.sync_pairs || []); setStrmStatus(stRes.data || {})
    } catch { /* ignore */ }
  }, [])
  const fetchMonitorAll = useCallback(async () => {
    try {
      const [cfgRes, stRes] = await Promise.all([p115StrmApi.getMonitorConfig(), p115StrmApi.getMonitorStatus()])
      setMonitorCfg(cfgRes.data || {}); setMonitorStatus(stRes.data || {})
    } catch { /* ignore */ }
  }, [])
  const fetchOrganizeAll = useCallback(async () => {
    try {
      const [cfgRes, stRes] = await Promise.all([p115StrmApi.getOrganizeConfig(), p115StrmApi.getOrganizeStatus()])
      const cfg = cfgRes.data || {}
      setOrgCfg(cfg); setOrgPaths(cfg.source_paths || []); setOrgStatus(stRes.data || {})
    } catch { /* ignore */ }
  }, [])

  useEffect(() => {
    fetchStatus(); fetchAccount(); fetchPathMapping()
    fetchSettings(); fetchStorageSources()
    fetchStrmAll(); fetchMonitorAll(); fetchOrganizeAll()
  }, [fetchStatus, fetchAccount, fetchPathMapping, fetchSettings,
      fetchStorageSources, fetchStrmAll, fetchMonitorAll, fetchOrganizeAll])

  // Cookie 就绪时自动启动生活事件监控
  useEffect(() => {
    if (status.cookie && !monitorStatus.running) {
      p115StrmApi.startMonitor().catch(() => {})
      setTimeout(fetchMonitorAll, 1000)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status.cookie])

  // ===================================================================
  //                          Cookie 逻辑
  // ===================================================================

  const handleSetCookie = async () => {
    if (!cookieValue.trim()) return
    setCookieSaving(true)
    try {
      const { data } = await p115Api.setCookie(cookieValue)
      if (data.valid) {
        message.success(t('p115.cookieSet'))
        setCookieModal(false)
        setCookieValue('')
        fetchStatus()
        fetchAccount()
      } else {
        message.warning(t('p115.cookieNotSet'))
      }
    } catch { message.error(t('common.failed')) }
    finally { setCookieSaving(false) }
  }

  // ===================================================================
  //                          扫码逻辑
  // ===================================================================

  const stopPolling = useCallback(() => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
  }, [])

  const handleOpenQr = async () => {
    setQrModal(true)
    setQrStatus('loading')
    setQrData(null)
    try {
      const { data } = await p115Api.qrcodeStart(qrApp)
      setQrData(data)
      setQrStatus('waiting')
      pollRef.current = setInterval(async () => {
        try {
          const { data: poll } = await p115Api.qrcodePoll({
            uid: data.uid, time: data.time, sign: data.sign, app: qrApp,
          })
          if (poll.status === 'scanned') setQrStatus('scanned')
          else if (poll.status === 'success') {
            setQrStatus('success')
            stopPolling()
            message.success(t('p115.qrSuccess'))
            setTimeout(() => { setQrModal(false); fetchStatus(); fetchAccount() }, 1000)
          } else if (poll.status === 'expired') {
            setQrStatus('expired')
            stopPolling()
          } else if (poll.status === 'canceled') {
            setQrStatus('failed')
            stopPolling()
          }
        } catch { /* ignore */ }
      }, 2000)
    } catch {
      setQrStatus('failed')
    }
  }

  const handleCloseQr = () => { stopPolling(); setQrModal(false) }

  // ===================================================================
  //                    新增：STRM / 监控 / 整理 操作
  // ===================================================================

  const handleSavePathMapping = async () => {
    setMappingSaving(true)
    try {
      const values = await mappingForm.validateFields()
      values.local_media_source = localMediaSource
      await p115Api.savePathMapping(values)
      message.success(t('common.success'))
      fetchPathMapping()
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

  // 目录选择器
  const openDirPicker        = (f) => { setDirPickerTarget(f);      setDirPickerOpen(true) }
  const openLocalDirPicker   = (f) => { setLocalDirPickerTarget(f); setLocalDirPickerOpen(true) }
  const handleDirSelected      = (p) => { if (dirPickerTarget)      mappingForm.setFieldValue(dirPickerTarget, p) }
  const handleLocalDirSelected = (p) => { if (localDirPickerTarget) mappingForm.setFieldValue(localDirPickerTarget, p) }

  // STRM
  const handleStrmSaveCfg = async () => {
    setStrmCfgSaving(true)
    try {
      const cloudPath = mappingForm.getFieldValue('cloud_prefix') || ''
      const strmPath  = mappingForm.getFieldValue('strm_prefix') || ''
      const pairs = cloudPath && strmPath ? [{ cloud_path: cloudPath, strm_path: strmPath }] : syncPairs
      await p115StrmApi.saveSyncConfig({ ...strmConfig, sync_pairs: pairs })
      message.success(t('p115.configSaved'))
    }
    catch { message.error(t('p115.saveFailed')) } finally { setStrmCfgSaving(false) }
  }
  const handleFullSync = async () => {
    setStrmSyncing(true)
    try {
      const cloudPath = mappingForm.getFieldValue('cloud_prefix') || ''
      const strmPath  = mappingForm.getFieldValue('strm_prefix') || ''
      const r = await p115StrmApi.fullSync(cloudPath && strmPath ? { cloud_path: cloudPath, strm_path: strmPath } : undefined)
      r.data?.success ? message.success(t('p115.syncStarted')) : message.warning(r.data?.message || t('p115.syncStartFailed'))
      setTimeout(fetchStrmAll, 1500)
    } catch { message.error(t('common.failed')) } finally { setStrmSyncing(false) }
  }
  const handleIncSync = async () => {
    setStrmSyncing(true)
    try {
      const cloudPath = mappingForm.getFieldValue('cloud_prefix') || ''
      const strmPath  = mappingForm.getFieldValue('strm_prefix') || ''
      const r = await p115StrmApi.incSync(cloudPath && strmPath ? { cloud_path: cloudPath, strm_path: strmPath } : undefined)
      r.data?.success ? message.success(t('p115.syncStarted')) : message.warning(r.data?.message || t('p115.syncStartFailed'))
      setTimeout(fetchStrmAll, 1500)
    } catch { message.error(t('common.failed')) } finally { setStrmSyncing(false) }
  }

  // 监控
  const handleMonitorSave = async () => {
    setMonitorSaving(true)
    try { await p115StrmApi.saveMonitorConfig(monitorCfg); message.success(t('p115.configSaved')) }
    catch { message.error(t('p115.saveFailed')) } finally { setMonitorSaving(false) }
  }
  const handleMonitorToggle = async () => {
    try {
      if (monitorStatus.running) { await p115StrmApi.stopMonitor(); message.success(t('p115.monitorStopped2')) }
      else { await p115StrmApi.startMonitor(); message.success(t('p115.monitorStarted')) }
      setTimeout(fetchMonitorAll, 800)
    } catch { message.error(t('p115.operateFailed')) }
  }

  // 整理
  const handleOrgSave = async () => {
    setOrgSaving(true)
    try { await p115StrmApi.saveOrganizeConfig({ ...orgCfg, source_paths: orgPaths }); message.success(t('p115.configSaved')) }
    catch { message.error(t('p115.saveFailed')) } finally { setOrgSaving(false) }
  }
  const handleOrgRun = async () => {
    setOrgRunning(true)
    try {
      const r = await p115StrmApi.runOrganize()
      r.data?.success ? message.success(t('p115.organizeStarted')) : message.warning(r.data?.message || t('p115.organizeStartFailed'))
      setTimeout(fetchOrganizeAll, 1500)
    } catch { message.error(t('common.failed')) } finally { setOrgRunning(false) }
  }

  // ===================================================================
  //                        未启用提示
  // ===================================================================

  if (!status.enabled && !loading) {
    return (
      <div style={{ padding: 24 }}>
        <Alert type="warning" message={t('p115.notEnabled')} description={t('p115.enableHint')} showIcon />
      </div>
    )
  }

  // ===================================================================
  //                         常量
  // ===================================================================

  const qrStatusHint = {
    idle: '', loading: t('p115.qrLoading'), waiting: t('p115.qrWaiting'),
    scanned: t('p115.qrScanned'), success: t('p115.qrSuccess'),
    expired: t('p115.qrExpired'), failed: t('p115.qrFailed'),
  }

  const APP_OPTIONS = [
    { value: 'web',       label: t('p115.appWeb'),         icon: <DesktopOutlined /> },
    { value: 'android',   label: t('p115.appAndroid'),     icon: <MobileOutlined /> },
    { value: 'ios',       label: t('p115.appIos'),         icon: <MobileOutlined /> },
    { value: 'alipaymini',label: t('p115.appAlipay'),      icon: <AlipayCircleOutlined /> },
    { value: 'wechatmini',label: t('p115.appWechat'),      icon: <WechatOutlined /> },
    { value: 'tv',        label: t('p115.appTv'),          icon: <DesktopOutlined /> },
    { value: 'qandroid',  label: t('p115.appQandroid'),    icon: <MobileOutlined /> },
    { value: '115android',label: t('p115.app115Android'),  icon: <MobileOutlined /> },
    { value: '115ios',    label: t('p115.app115Ios'),      icon: <MobileOutlined /> },
    { value: '115ipad',   label: t('p115.app115Ipad'),     icon: <MobileOutlined /> },
  ]

  // 空间使用率
  const formatSize = (bytes) => {
    if (!bytes) return '0 B'
    const units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB', 'EB']
    const i = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1)
    return (bytes / Math.pow(1024, i)).toFixed(1) + ' ' + units[i]
  }
  const spacePercent = account.space_total
    ? Math.round((account.space_used / account.space_total) * 100)
    : 0

  // ===================================================================
  //  STRM 统计快照（Tab1 用）
  // ===================================================================
  const strmProgress = strmStatus.progress || {}
  const fullStats    = strmStatus.last_full_sync_stats || {}
  const incStats     = strmStatus.last_inc_sync_stats  || {}

  // ===================================================================
  //  Tab 1 — 115 网盘（左：账号信息+高级设置，右：生活事件监控）
  // ===================================================================
  const tab1 = (
    <Spin spinning={loading || settingsLoading}>
      <Row gutter={[24, 24]}>
        {/* 左列：账号信息 + 高级设置 */}
        <Col xs={24} lg={14}>
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
            {/* 账号信息 */}
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

            {/* Cookie / OpenAPI 状态 */}
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

            {/* 高级设置 */}
            <Form form={settingsForm} layout="vertical" size="small"
              initialValues={{ api_interval: 1, api_concurrent: 3, strm_link_host: '', file_extensions: 'mp4,mkv,avi,ts,iso,mov,m2ts' }}
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
              <Form.Item name="strm_link_host" label={t('p115.strmLinkHost')} tooltip={t('p115.strmLinkHostHint')}>
                <Input placeholder={defaultStrmHost} />
              </Form.Item>
              <Form.Item name="file_extensions" label={t('p115.fileExtensions')} tooltip={t('p115.fileExtensionsHint')}>
                <Input placeholder="mp4,mkv,avi,ts,iso,mov,m2ts" />
              </Form.Item>
            </Form>
          </Card>
        </Col>

        {/* 右列：生活事件监控 */}
        <Col xs={24} lg={10}>
          <Card
            title={<Space><ClockCircleOutlined />{t('p115.monitorStatusTitle')}</Space>}
            extra={<Button icon={<SyncOutlined />} size="small" onClick={fetchMonitorAll}>{t('common.refresh')}</Button>}
            style={{ height: '100%' }}
          >
            {/* 运行状态 */}
            <div style={{ marginBottom: 16 }}>
              <Badge
                status={monitorStatus.running ? 'processing' : 'default'}
                text={<Text strong>{monitorStatus.running ? t('p115.monitorRunning') : t('p115.monitorStopped')}</Text>}
              />
            </div>
            <div style={{ marginBottom: 12 }}>
              <Text type="secondary">{t('p115.lastEvent')}: </Text>
              <Text>{monitorStatus.last_event_time ? new Date(monitorStatus.last_event_time * 1000).toLocaleString() : '—'}</Text>
            </div>

            {/* 启停按钮 */}
            <div style={{ marginBottom: 20 }}>
              <Button
                type={monitorStatus.running ? 'default' : 'primary'}
                icon={monitorStatus.running ? <PauseCircleOutlined /> : <PlayCircleOutlined />}
                onClick={handleMonitorToggle}
                block
              >
                {monitorStatus.running ? t('p115.stopMonitor') : t('p115.startMonitor')}
              </Button>
            </div>

            <Divider style={{ margin: '0 0 16px' }} />

            {/* 监控配置 */}
            <Form layout="vertical" size="small">
              <Form.Item label={t('p115.pollInterval')}>
                <InputNumber min={10} max={3600} value={monitorCfg.poll_interval}
                  style={{ width: '100%' }}
                  addonAfter={t('p115.seconds')}
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

            {/* 最近事件 */}
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
                      <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{ev.file_name}</span>
                      <span style={{ color: '#aaa', flexShrink: 0 }}>{new Date(ev.time * 1000).toLocaleTimeString()}</span>
                    </div>
                  ))}
                </div>
              </>
            )}
          </Card>
        </Col>
      </Row>
    </Spin>
  )

  // ===================================================================
  //  Tab 2 — 整理 & 路径
  // ===================================================================
  const tab2 = (
    <>
      {/* 上方：路径映射 + 整理分类 左右布局 */}
      <Row gutter={[24, 24]}>
        {/* 路径映射 */}
        <Col xs={24} lg={12}>
          <Spin spinning={mappingLoading}>
            <Card title={<Space><NodeIndexOutlined />{t('p115.pathMappingTitle')}</Space>}
              extra={<Button type="primary" icon={<SaveOutlined />} loading={mappingSaving} onClick={handleSavePathMapping}>{t('common.save')}</Button>}
            >
              <Alert type="info" showIcon style={{ marginBottom: 16 }} message={t('p115.pathMappingHint')} />
              <Form form={mappingForm} layout="vertical" size="small"
                initialValues={{ media_prefix: '', cloud_prefix: '', strm_prefix: '', local_media_prefix: '' }}>
                <Form.Item name="cloud_prefix" label={t('p115.cloudPrefix')} tooltip={t('p115.cloudPrefixHint')}>
                  <Input placeholder="/media" addonAfter={
                    <Button type="link" size="small" icon={<FolderOpenOutlined />} onClick={() => openDirPicker('cloud_prefix')} style={{ padding: 0, height: 'auto' }}>
                      {t('p115.selectDir')}
                    </Button>} />
                </Form.Item>
                <Form.Item name="media_prefix" label={t('p115.mediaPrefix')} tooltip={t('p115.mediaPrefixHint')}>
                  <Input placeholder="/media/movies" />
                </Form.Item>
                <Form.Item name="strm_prefix" label={t('p115.strmPrefix')} tooltip={t('p115.strmPrefixHint')}>
                  <Input placeholder="/config/strm/movies" addonAfter={
                    <Button type="link" size="small" icon={<FolderOpenOutlined />} onClick={() => openLocalDirPicker('strm_prefix')} style={{ padding: 0, height: 'auto' }}>
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
                        ? <Button type="link" size="small" icon={<FolderOpenOutlined />} onClick={() => setStorageDirPickerOpen(true)} style={{ padding: 0, height: 'auto' }}>{t('p115.selectDir')}</Button>
                        : localMediaSource === 'local'
                          ? <Button type="link" size="small" icon={<FolderOpenOutlined />} onClick={() => openLocalDirPicker('local_media_prefix')} style={{ padding: 0, height: 'auto' }}>{t('p115.selectDir')}</Button>
                          : null
                    }
                  />
                </Form.Item>
              </Form>
            </Card>
          </Spin>
        </Col>

        {/* 整理分类 */}
        <Col xs={24} lg={12}>
          <Card title={<Space><FolderAddOutlined />{t('p115.organizeTitle')}</Space>}
            extra={
              <Space>
                <Button icon={<SyncOutlined />} onClick={fetchOrganizeAll} />
                <Button type="primary" icon={<FolderAddOutlined />} loading={orgRunning || orgStatus.running} onClick={handleOrgRun}>{t('p115.startOrganize')}</Button>
              </Space>
            }
          >
            {orgStatus.last_organize && (
              <Alert style={{ marginBottom: 8 }} type="info" showIcon
                message={<Space size={4} wrap>
                  <span>{t('p115.lastOrganize')}: {new Date(orgStatus.last_organize * 1000).toLocaleString()}</span>
                  <StatTag value={orgStatus.last_organize_stats?.moved}   label={t('p115.statMoved')}    color="green" />
                  <StatTag value={orgStatus.last_organize_stats?.skipped} label={t('p115.statSkipped')}  color="default" />
                  <StatTag value={orgStatus.last_organize_stats?.errors}  label={t('p115.statFailed')}   color="red" />
                </Space>} />
            )}
            {orgStatus.running && <Alert style={{ marginBottom: 8 }} type="info" showIcon message={t('p115.organizeInProgress')} />}
            <Alert style={{ marginBottom: 12 }} type="warning" showIcon message={t('p115.organizeWarning')} />
            <Form layout="vertical" size="small">
              <Form.Item label={t('p115.organizeTargetRoot')} tooltip={t('p115.organizeTargetRootHint')}>
                <Input value={orgCfg.target_root} placeholder={t('p115.organizeTargetRootHint')}
                  onChange={e => setOrgCfg(c => ({ ...c, target_root: e.target.value }))} />
              </Form.Item>
              <Form.Item label={t('p115.dryRun')} tooltip={t('p115.dryRunHint')}>
                <Switch checked={orgCfg.dry_run} onChange={v => setOrgCfg(c => ({ ...c, dry_run: v }))} />
              </Form.Item>
              <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>{t('p115.sourcePaths')}</div>
              {orgPaths.map((p, idx) => (
                <Row gutter={8} key={idx} style={{ marginBottom: 8 }} align="middle">
                  <Col flex="1"><Input placeholder={t('p115.sourceDirPlaceholder')} value={p}
                    onChange={e => setOrgPaths(prev => prev.map((v, i) => i === idx ? e.target.value : v))} /></Col>
                  <Col><Button danger icon={<DeleteOutlined />} onClick={() => setOrgPaths(prev => prev.filter((_, i) => i !== idx))} /></Col>
                </Row>
              ))}
              <Button icon={<PlusOutlined />} onClick={() => setOrgPaths(p => [...p, ''])} style={{ marginBottom: 12 }}>{t('p115.addSourcePath')}</Button>
              <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>{t('p115.categoryRules')}</div>
              {Object.entries(orgCfg.categories || {}).map(([cat, sub]) => (
                <Row gutter={8} key={cat} style={{ marginBottom: 8 }} align="middle">
                  <Col span={6}><Tag color="blue">{cat}</Tag></Col>
                  <Col flex="1"><Input value={sub}
                    onChange={e => setOrgCfg(c => ({ ...c, categories: { ...c.categories, [cat]: e.target.value } }))} /></Col>
                </Row>
              ))}
              <Button type="primary" icon={<CheckCircleOutlined />} onClick={handleOrgSave} loading={orgSaving} style={{ marginTop: 8 }}>
                {t('p115.saveOrganizeConfig')}
              </Button>
            </Form>
          </Card>
        </Col>
      </Row>

      {/* 下方：STRM 生成三列横排卡片 */}
      <Row gutter={[16, 16]} style={{ marginTop: 24 }}>
        {/* 全量同步卡片 */}
        <Col xs={24} md={8}>
          <Card
            title={<Space><ThunderboltOutlined />{t('p115.fullSync')}</Space>}
            style={{ height: '100%' }}
            extra={<Button icon={<SyncOutlined spin={strmStatus.running} />} size="small" onClick={fetchStrmAll}>{t('p115.refreshStatus')}</Button>}
          >
            <div style={{ fontSize: 12, color: '#888', marginBottom: 4 }}>{t('p115.lastFullSync')}</div>
            <div style={{ fontWeight: 600, marginBottom: 12 }}>
              {strmStatus.last_full_sync ? new Date(strmStatus.last_full_sync * 1000).toLocaleString() : '—'}
            </div>
            <Space size={4} wrap style={{ marginBottom: 16 }}>
              <StatTag value={fullStats.created} label={t('p115.statGenerated')} color="green" />
              <StatTag value={fullStats.skipped} label={t('p115.statSkipped')} color="default" />
              <StatTag value={fullStats.errors}  label={t('p115.statFailed')} color="red" />
            </Space>
            {strmStatus.running && (
              <Alert style={{ marginBottom: 12 }} type="info" showIcon
                message={t('p115.syncInProgress', { count: strmProgress.created || 0 })} />
            )}
            <Button type="primary" icon={<ThunderboltOutlined />} block
              loading={strmSyncing || strmStatus.running} onClick={handleFullSync}>
              {t('p115.fullSync')}
            </Button>
          </Card>
        </Col>

        {/* 增量同步卡片 */}
        <Col xs={24} md={8}>
          <Card
            title={<Space><SyncOutlined />{t('p115.incSync')}</Space>}
            style={{ height: '100%' }}
          >
            <div style={{ fontSize: 12, color: '#888', marginBottom: 4 }}>{t('p115.lastIncSync')}</div>
            <div style={{ fontWeight: 600, marginBottom: 12 }}>
              {strmStatus.last_inc_sync ? new Date(strmStatus.last_inc_sync * 1000).toLocaleString() : '—'}
            </div>
            <Space size={4} wrap style={{ marginBottom: 16 }}>
              <StatTag value={incStats.created} label={t('p115.statGenerated')} color="green" />
              <StatTag value={incStats.skipped} label={t('p115.statSkipped')} color="default" />
              <StatTag value={incStats.errors}  label={t('p115.statFailed')} color="red" />
            </Space>
            <Button icon={<SyncOutlined />} block
              loading={strmSyncing || strmStatus.running} onClick={handleIncSync}>
              {t('p115.incSync')}
            </Button>
          </Card>
        </Col>

        {/* 同步配置卡片（路径来自整理与路径） */}
        <Col xs={24} md={8}>
          <Card
            title={<Space><NodeIndexOutlined />{t('p115.syncConfigTitle')}</Space>}
            style={{ height: '100%' }}
          >
            <Alert
              type="info" showIcon style={{ marginBottom: 16 }}
              message={t('p115.strmPathFromMapping')}
            />
            <Form layout="vertical" size="small">
              <Form.Item label={t('p115.cloudPrefix')}>
                <Input disabled value={mappingForm.getFieldValue('cloud_prefix') || '—'} />
              </Form.Item>
              <Form.Item label={t('p115.strmPrefix')}>
                <Input disabled value={mappingForm.getFieldValue('strm_prefix') || '—'} />
              </Form.Item>
            </Form>
            <Button type="primary" icon={<CheckCircleOutlined />} onClick={handleStrmSaveCfg}
              loading={strmCfgSaving} block style={{ marginTop: 8 }}>
              {t('p115.saveSyncConfig')}
            </Button>
          </Card>
        </Col>
      </Row>
    </>
  )

  // ===================================================================
  //  主渲染
  // ===================================================================
  return (
    <div style={{ padding: 24 }}>
      <Tabs
        items={[
          { key: 'p115',     label: <Space><CloudSyncOutlined />{t('p115.tabDrive')}</Space>,       children: tab1 },
          { key: 'organize', label: <Space><FolderAddOutlined />{t('p115.tabOrganizePath')}</Space>, children: tab2 },
        ]}
      />

      {/* Cookie 弹窗 */}
      <Modal title={t('p115.setCookie')} open={cookieModal} onCancel={() => setCookieModal(false)} onOk={handleSetCookie} confirmLoading={cookieSaving}>
        <TextArea rows={4} value={cookieValue} onChange={e => setCookieValue(e.target.value)} placeholder={t('p115.cookiePlaceholder')} />
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
    </div>
  )
}
export default Drive115
