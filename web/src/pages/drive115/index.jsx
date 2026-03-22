// src/pages/drive115/index.jsx
// 115 网盘 — Tab布局:
//   Tab1: 115网盘（左：账号信息+高级设置，右：生活事件监控）
//   Tab2: 整理&路径（左：路径映射，右：整理分类；下方：STRM生成三列卡片）

import { useEffect, useState, useRef, useCallback } from 'react'
import {
  Card, Descriptions, Tag, Button, Input, InputNumber, Modal, message,
  Space, Alert, Row, Col, Spin, Typography, Form, Select, QRCode,
  Avatar, Progress, Divider, Tabs, Switch, Badge, Collapse, Tooltip,
} from 'antd'
import {
  CheckCircleOutlined, CloseCircleOutlined, CloudSyncOutlined,
  KeyOutlined, QrcodeOutlined, SaveOutlined,
  MobileOutlined, DesktopOutlined, WechatOutlined, AlipayCircleOutlined,
  NodeIndexOutlined, FolderOpenOutlined, UserOutlined,
  ThunderboltOutlined, SyncOutlined, PlayCircleOutlined,
  PauseCircleOutlined, FolderAddOutlined, PlusOutlined, DeleteOutlined,
  ClockCircleOutlined, ArrowUpOutlined, ArrowDownOutlined,
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
  const [orgCfg,         setOrgCfg]         = useState({
    source_paths: [], target_root: '', dry_run: false,
    categories: [],  // 新结构：数组，每项 {name, target_dir, match_all, rules:[]}
  })
  const [orgStatus,      setOrgStatus]      = useState({})
  const [orgPaths,       setOrgPaths]       = useState([])
  const [orgSaving,      setOrgSaving]      = useState(false)
  const [orgRunning,     setOrgRunning]     = useState(false)
  const [tmdbConfigured, setTmdbConfigured] = useState(null) // null=未知, true/false

  // ── 刮削重命名 ────────────────────────────────────────────────────────
  const [scrapeCfg,      setScrapeCfg]      = useState({
    enabled: false,
    movie_format: '{title} ({year})/{title} ({year})',
    tv_format:    '{title} ({year})/Season {season:02d}/{title} - {season_episode} - {episode_title}',
  })
  const [scrapeSaving,   setScrapeSaving]   = useState(false)
  // 当前聚焦的格式输入框：'movie' | 'tv'
  const [scrapeActiveInput, setScrapeActiveInput] = useState('movie')
  const movieFormatRef = useRef(null)
  const tvFormatRef    = useRef(null)

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
      const [cfgRes, stRes, tmdbRes] = await Promise.all([
        p115StrmApi.getOrganizeConfig(),
        p115StrmApi.getOrganizeStatus(),
        p115StrmApi.getOrganizeTmdbStatus(),
      ])
      const cfg = cfgRes.data || {}
      setOrgCfg(cfg); setOrgPaths(cfg.source_paths || []); setOrgStatus(stRes.data || {})
      setTmdbConfigured(!!tmdbRes.data?.available)
    } catch { /* ignore */ }
  }, [])

  const fetchScrapeConfig = useCallback(async () => {
    try { const { data } = await p115Api.getScrapeConfig(); setScrapeCfg(data) }
    catch { /* ignore */ }
  }, [])

  useEffect(() => {
    fetchStatus(); fetchAccount(); fetchPathMapping()
    fetchSettings(); fetchStorageSources()
    fetchStrmAll(); fetchMonitorAll(); fetchOrganizeAll()
    fetchScrapeConfig()
  }, [fetchStatus, fetchAccount, fetchPathMapping, fetchSettings,
      fetchStorageSources, fetchStrmAll, fetchMonitorAll, fetchOrganizeAll,
      fetchScrapeConfig])

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
  const handleDirSelected    = (p) => {
    if (!dirPickerTarget) return
    if (dirPickerTarget === '__org_target_root__') {
      // 整理分类卡片的目标根目录
      setOrgCfg(c => ({ ...c, target_root: p }))
    } else {
      mappingForm.setFieldValue(dirPickerTarget, p)
    }
  }
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

  // 刮削
  const handleSaveScrapeConfig = async () => {
    setScrapeSaving(true)
    try { await p115Api.saveScrapeConfig(scrapeCfg); message.success(t('p115.configSaved')) }
    catch { message.error(t('p115.saveFailed')) } finally { setScrapeSaving(false) }
  }
  // 将参数插入当前聚焦的格式输入框光标位置
  const insertScrapeParam = (param) => {
    const key    = scrapeActiveInput === 'movie' ? 'movie_format' : 'tv_format'
    const ref    = scrapeActiveInput === 'movie' ? movieFormatRef : tvFormatRef
    const el     = ref.current?.input || ref.current
    if (el) {
      const start = el.selectionStart ?? el.value.length
      const end   = el.selectionEnd   ?? el.value.length
      const val   = scrapeCfg[key] || ''
      const next  = val.slice(0, start) + param + val.slice(end)
      setScrapeCfg(c => ({ ...c, [key]: next }))
      // 恢复光标
      setTimeout(() => { el.focus(); el.setSelectionRange(start + param.length, start + param.length) }, 0)
    } else {
      setScrapeCfg(c => ({ ...c, [key]: (c[key] || '') + param }))
    }
  }

  // 刮削参数定义（参考 MP MetaInfo + MediaInfo）
  const SCRAPE_PARAMS_MOVIE = [
    { param: '{title}',          labelKey: 'scrapeParamTitle' },
    { param: '{original_title}', labelKey: 'scrapeParamOriginalTitle' },
    { param: '{en_title}',       labelKey: 'scrapeParamEnTitle' },
    { param: '{year}',           labelKey: 'scrapeParamYear' },
    { param: '{tmdbid}',         labelKey: 'scrapeParamTmdbId' },
    { param: '{imdbid}',         labelKey: 'scrapeParamImdbId' },
    { param: '{resource_type}',  labelKey: 'scrapeParamResourceType' },
    { param: '{resource_pix}',   labelKey: 'scrapeParamResourcePix' },
    { param: '{video_encode}',   labelKey: 'scrapeParamVideoEncode' },
    { param: '{audio_encode}',   labelKey: 'scrapeParamAudioEncode' },
    { param: '{edition}',        labelKey: 'scrapeParamEdition' },
    { param: '{resource_team}',  labelKey: 'scrapeParamResourceTeam' },
  ]
  const SCRAPE_PARAMS_TV = [
    ...SCRAPE_PARAMS_MOVIE,
    { param: '{season}',          labelKey: 'scrapeParamSeason' },
    { param: '{season:02d}',      labelKey: 'scrapeParamSeasonZero' },
    { param: '{episode}',         labelKey: 'scrapeParamEpisode' },
    { param: '{episode:02d}',     labelKey: 'scrapeParamEpisodeZero' },
    { param: '{season_episode}',  labelKey: 'scrapeParamSeasonEpisode' },
  ]

  // 格式预览（基于示例数据）
  const MOVIE_SAMPLE = { title: '星际穿越', original_title: 'Interstellar', en_title: 'Interstellar',
    year: '2014', tmdbid: '157336', imdbid: 'tt0816692', resource_type: 'BluRay',
    resource_pix: '2160p', video_encode: 'HEVC', audio_encode: 'TrueHD', edition: 'Remux', resource_team: 'CHDBits' }
  const TV_SAMPLE = { ...MOVIE_SAMPLE, title: '权力的游戏', en_title: 'Game of Thrones',
    year: '2011', tmdbid: '1399', season: 1, 'season:02d': '01', episode: 1,
    'episode:02d': '01', season_episode: 'S01E01', episode_title: '凛冬将至' }
  const previewFormat = (fmt, sample) => {
    if (!fmt) return '—'
    return fmt.replace(/\{([^}]+)\}/g, (_, k) => sample[k] !== undefined ? sample[k] : `{${k}}`)
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
  //  Tab 2 — 整理 & 路径（三列等宽等高：STRM生成 | 整理与路径 | 整理分类）
  // ===================================================================
  const tab2 = (
    <Row gutter={[24, 24]} align="stretch">

      {/* ── 左列：STRM 生成 ── */}
      <Col xs={24} lg={8} style={{ display: 'flex', flexDirection: 'column' }}>
        <Card
          title={<Space><ThunderboltOutlined />{t('p115.strmGeneration')}</Space>}
          style={{ flex: 1 }}
          extra={<Button icon={<SyncOutlined spin={strmStatus.running} />} size="small" onClick={fetchStrmAll}>{t('p115.refreshStatus')}</Button>}
        >
          {/* 当前路径提示 */}
          <Alert type="info" showIcon style={{ marginBottom: 16 }}
            message={t('p115.strmPathFromMapping')} />

          {/* 路径只读展示 */}
          <Form layout="vertical" size="small">
            <Form.Item label={t('p115.cloudPrefix')}>
              <Input disabled value={mappingForm.getFieldValue('cloud_prefix') || '—'} />
            </Form.Item>
            <Form.Item label={t('p115.strmPrefix')}>
              <Input disabled value={mappingForm.getFieldValue('strm_prefix') || '—'} />
            </Form.Item>
          </Form>

          <Divider style={{ margin: '12px 0' }} />

          {/* 全量同步 */}
          <div style={{ fontSize: 12, color: '#888', marginBottom: 2 }}>{t('p115.lastFullSync')}</div>
          <div style={{ fontWeight: 600, marginBottom: 6 }}>
            {strmStatus.last_full_sync ? new Date(strmStatus.last_full_sync * 1000).toLocaleString() : '—'}
          </div>
          <Space size={4} wrap style={{ marginBottom: 10 }}>
            <StatTag value={fullStats.created} label={t('p115.statGenerated')} color="green" />
            <StatTag value={fullStats.skipped} label={t('p115.statSkipped')} color="default" />
            <StatTag value={fullStats.errors}  label={t('p115.statFailed')} color="red" />
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

          {/* 增量同步 */}
          <div style={{ fontSize: 12, color: '#888', marginBottom: 2 }}>{t('p115.lastIncSync')}</div>
          <div style={{ fontWeight: 600, marginBottom: 6 }}>
            {strmStatus.last_inc_sync ? new Date(strmStatus.last_inc_sync * 1000).toLocaleString() : '—'}
          </div>
          <Space size={4} wrap style={{ marginBottom: 10 }}>
            <StatTag value={incStats.created} label={t('p115.statGenerated')} color="green" />
            <StatTag value={incStats.skipped} label={t('p115.statSkipped')} color="default" />
            <StatTag value={incStats.errors}  label={t('p115.statFailed')} color="red" />
          </Space>
          <Button icon={<SyncOutlined />} block
            loading={strmSyncing || strmStatus.running} onClick={handleIncSync}>
            {t('p115.incSync')}
          </Button>

          <Divider style={{ margin: '12px 0' }} />

          {/* STRM URL 模板 */}
          <Form form={settingsForm} layout="vertical" size="small">
            <Form.Item name="strm_link_host" label={t('p115.strmLinkHost')} tooltip={t('p115.strmLinkHostHint')}>
              <Input placeholder={defaultStrmHost} />
            </Form.Item>
          </Form>
        </Card>
      </Col>

      {/* ── 中列：整理与路径 ── */}
      <Col xs={24} lg={8} style={{ display: 'flex', flexDirection: 'column' }}>
        <Spin spinning={mappingLoading} style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
          <Card title={<Space><NodeIndexOutlined />{t('p115.pathMappingTitle')}</Space>}
            style={{ flex: 1 }}
            extra={<Button type="primary" icon={<SaveOutlined />} loading={mappingSaving} onClick={handleSavePathMapping}>{t('common.save')}</Button>}
          >
            <Alert type="info" showIcon style={{ marginBottom: 16 }} message={t('p115.pathMappingHint')} />
            <Form form={mappingForm} layout="vertical" size="small"
              initialValues={{ media_prefix: '', cloud_prefix: '', strm_prefix: '', local_media_prefix: '', organize_source: '', organize_unrecognized: '' }}>
              <Form.Item name="cloud_prefix" label={t('p115.cloudPrefix')} tooltip={t('p115.cloudPrefixHint')}>
                <Input placeholder="/media" addonAfter={
                  <Button type="link" size="small" icon={<FolderOpenOutlined />} onClick={() => openDirPicker('cloud_prefix')} style={{ padding: 0, height: 'auto' }}>
                    {t('p115.selectDir')}
                  </Button>} />
              </Form.Item>
              <Form.Item name="organize_source" label={t('p115.organizeSource')} tooltip={t('p115.organizeSourceHint')}>
                <Input placeholder="/待整理" addonAfter={
                  <Button type="link" size="small" icon={<FolderOpenOutlined />} onClick={() => openDirPicker('organize_source')} style={{ padding: 0, height: 'auto' }}>
                    {t('p115.selectDir')}
                  </Button>} />
              </Form.Item>
              <Form.Item name="organize_unrecognized" label={t('p115.organizeUnrecognized')} tooltip={t('p115.organizeUnrecognizedHint')}>
                <Input placeholder="/未识别" addonAfter={
                  <Button type="link" size="small" icon={<FolderOpenOutlined />} onClick={() => openDirPicker('organize_unrecognized')} style={{ padding: 0, height: 'auto' }}>
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

      {/* ── 右列：整理分类 ── */}
      <Col xs={24} lg={8} style={{ display: 'flex', flexDirection: 'column' }}>
        <Card title={<Space><FolderAddOutlined />{t('p115.organizeTitle')}</Space>}
          style={{ flex: 1, overflow: 'auto' }}
          extra={
            <Space>
              <Button icon={<SyncOutlined />} size="small" onClick={fetchOrganizeAll} />
              <Button type="primary" size="small" icon={<FolderAddOutlined />}
                loading={orgRunning || orgStatus.running} onClick={handleOrgRun}>
                {t('p115.startOrganize')}
              </Button>
            </Space>
          }
        >
          {/* 状态/上次结果 */}
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

          {/* 基础配置 */}
          <Form layout="vertical" size="small">
            <Form.Item label={t('p115.organizeTargetRoot')} tooltip={t('p115.organizeTargetRootHint')}>
              <Input value={orgCfg.target_root} placeholder={t('p115.organizeTargetRootHint')}
                onChange={e => setOrgCfg(c => ({ ...c, target_root: e.target.value }))}
                addonAfter={
                  <Button type="link" size="small" icon={<FolderOpenOutlined />}
                    onClick={() => {
                      setDirPickerTarget('__org_target_root__')
                      setDirPickerOpen(true)
                    }}
                    style={{ padding: 0, height: 'auto' }}>
                    {t('p115.selectDir')}
                  </Button>
                } />
            </Form.Item>
            <Form.Item label={t('p115.dryRun')} tooltip={t('p115.dryRunHint')}>
              <Switch checked={orgCfg.dry_run} onChange={v => setOrgCfg(c => ({ ...c, dry_run: v }))} />
            </Form.Item>
            <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>{t('p115.sourcePaths')}</div>
            {orgPaths.map((p, idx) => (
              <Row gutter={8} key={idx} style={{ marginBottom: 8 }} align="middle">
                <Col flex="1"><Input placeholder={t('p115.sourceDirPlaceholder')} value={p}
                  onChange={e => setOrgPaths(prev => prev.map((v, i) => i === idx ? e.target.value : v))} /></Col>
                <Col><Button danger icon={<DeleteOutlined />} size="small" onClick={() => setOrgPaths(prev => prev.filter((_, i) => i !== idx))} /></Col>
              </Row>
            ))}
            <Button icon={<PlusOutlined />} size="small" onClick={() => setOrgPaths(p => [...p, ''])} style={{ marginBottom: 16 }}>
              {t('p115.addSourcePath')}
            </Button>
          </Form>

          {/* 分类规则 */}
          {tmdbConfigured !== null && (
            <Alert
              style={{ marginBottom: 8 }}
              type={tmdbConfigured ? 'success' : 'warning'}
              showIcon
              message={tmdbConfigured ? t('p115.orgTmdbHint') : t('p115.orgTmdbNoKey')}
            />
          )}
          <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 4 }}>{t('p115.orgCategoryRuleTitle')}</div>
          <div style={{ fontSize: 12, color: '#888', marginBottom: 8 }}>{t('p115.orgPriority')}</div>

          {(orgCfg.categories || []).map((cat, catIdx) => {
            const cats = orgCfg.categories || []
            const updateCat = (patch) => setOrgCfg(c => ({
              ...c, categories: c.categories.map((v, i) => i === catIdx ? { ...v, ...patch } : v)
            }))
            const updateRule = (rIdx, patch) => updateCat({
              rules: cat.rules.map((r, i) => i === rIdx ? { ...r, ...patch } : r)
            })
            const addRule = () => updateCat({ rules: [...(cat.rules || []), { type: 'keyword', field: 'filename', value: '' }] })
            const delRule = (rIdx) => updateCat({ rules: cat.rules.filter((_, i) => i !== rIdx) })
            const isDefault = !cat.rules || cat.rules.length === 0

            return (
              <Collapse key={catIdx} size="small" style={{ marginBottom: 8 }}
                items={[{
                  key: String(catIdx),
                  label: (
                    <Row align="middle" gutter={4} wrap={false}>
                      <Col flex="1">
                        <Space size={4}>
                          <Tag color="blue" style={{ margin: 0 }}>{cat.name || `分类${catIdx + 1}`}</Tag>
                          <Text type="secondary" style={{ fontSize: 11 }}>→ {cat.target_dir || '—'}</Text>
                          {isDefault && <Tag color="orange" style={{ fontSize: 11, margin: 0 }}>{t('p115.orgCategoryDefault')}</Tag>}
                        </Space>
                      </Col>
                      <Col>
                        <Space size={2} onClick={e => e.stopPropagation()}>
                          <Tooltip title={t('p115.orgMoveUp')}>
                            <Button size="small" icon={<ArrowUpOutlined />} disabled={catIdx === 0}
                              onClick={() => {
                                const arr = [...cats]
                                ;[arr[catIdx - 1], arr[catIdx]] = [arr[catIdx], arr[catIdx - 1]]
                                setOrgCfg(c => ({ ...c, categories: arr }))
                              }} />
                          </Tooltip>
                          <Tooltip title={t('p115.orgMoveDown')}>
                            <Button size="small" icon={<ArrowDownOutlined />} disabled={catIdx === cats.length - 1}
                              onClick={() => {
                                const arr = [...cats]
                                ;[arr[catIdx], arr[catIdx + 1]] = [arr[catIdx + 1], arr[catIdx]]
                                setOrgCfg(c => ({ ...c, categories: arr }))
                              }} />
                          </Tooltip>
                          <Tooltip title={t('p115.orgDeleteCategory')}>
                            <Button size="small" danger icon={<DeleteOutlined />}
                              onClick={() => setOrgCfg(c => ({ ...c, categories: c.categories.filter((_, i) => i !== catIdx) }))} />
                          </Tooltip>
                        </Space>
                      </Col>
                    </Row>
                  ),
                  children: (
                    <div style={{ fontSize: 12 }}>
                      {/* 分类名 + 目标目录 */}
                      <Row gutter={8} style={{ marginBottom: 8 }}>
                        <Col span={11}>
                          <div style={{ color: '#888', marginBottom: 2 }}>{t('p115.orgCategoryName')}</div>
                          <Input size="small" value={cat.name} onChange={e => updateCat({ name: e.target.value })} />
                        </Col>
                        <Col span={11}>
                          <div style={{ color: '#888', marginBottom: 2 }}>{t('p115.orgCategoryTargetDir')}</div>
                          <Input size="small" value={cat.target_dir} onChange={e => updateCat({ target_dir: e.target.value })} />
                        </Col>
                      </Row>
                      {/* AND/OR */}
                      <Row style={{ marginBottom: 8 }} align="middle">
                        <Col><Text type="secondary" style={{ marginRight: 8 }}>{t('p115.orgMatchLogic')}：</Text></Col>
                        <Col>
                          <Switch size="small" checked={cat.match_all}
                            checkedChildren="AND" unCheckedChildren="OR"
                            onChange={v => updateCat({ match_all: v })} />
                        </Col>
                        <Col><Text type="secondary" style={{ marginLeft: 8, fontSize: 11 }}>
                          {cat.match_all ? t('p115.orgCategoryMatchAll') : t('p115.orgCategoryMatchAny')}
                        </Text></Col>
                      </Row>
                      {/* 规则列表 */}
                      {isDefault
                        ? <div style={{ color: '#aaa', fontStyle: 'italic', marginBottom: 8 }}>{t('p115.orgNoRules')}</div>
                        : (cat.rules || []).map((rule, rIdx) => {
                          const isTmdbType = ['genre_ids', 'origin_country', 'original_language'].includes(rule.type)
                          const placeholderMap = {
                            genre_ids:         t('p115.orgRuleGenreIdsHint'),
                            origin_country:    t('p115.orgRuleOriginCountryHint'),
                            original_language: t('p115.orgRuleOriginalLanguageHint'),
                            keyword:           t('p115.orgRuleValuePlaceholder'),
                            regex:             t('p115.orgRuleValuePlaceholder'),
                          }
                          return (
                            <Row key={rIdx} gutter={4} style={{ marginBottom: 6 }} align="middle" wrap={false}>
                              {/* 匹配类型 */}
                              <Col style={{ width: 118, flexShrink: 0 }}>
                                <Select size="small" style={{ width: '100%' }} value={rule.type}
                                  onChange={v => updateRule(rIdx, {
                                    type: v,
                                    field: ['genre_ids','origin_country','original_language'].includes(v)
                                      ? undefined : (rule.field || 'filename')
                                  })}
                                  options={[
                                    { value: 'genre_ids',         label: t('p115.orgRuleTypeGenreIds') },
                                    { value: 'origin_country',    label: t('p115.orgRuleTypeOriginCountry') },
                                    { value: 'original_language', label: t('p115.orgRuleTypeOriginalLanguage') },
                                    { value: 'keyword',           label: t('p115.orgRuleTypeKeyword') },
                                    { value: 'regex',             label: t('p115.orgRuleTypeRegex') },
                                  ]} />
                              </Col>
                              {/* 匹配字段（仅 keyword/regex 显示） */}
                              {!isTmdbType && (
                                <Col style={{ width: 78, flexShrink: 0 }}>
                                  <Select size="small" style={{ width: '100%' }} value={rule.field || 'filename'}
                                    onChange={v => updateRule(rIdx, { field: v })}
                                    options={[
                                      { value: 'filename', label: t('p115.orgRuleFieldFilename') },
                                      { value: 'dirname',  label: t('p115.orgRuleFieldDirname') },
                                    ]} />
                                </Col>
                              )}
                              {/* 匹配值 */}
                              <Col flex="1">
                                <Tooltip title={placeholderMap[rule.type]}>
                                  <Input size="small" value={rule.value}
                                    placeholder={placeholderMap[rule.type] || t('p115.orgRuleValuePlaceholder')}
                                    onChange={e => updateRule(rIdx, { value: e.target.value })} />
                                </Tooltip>
                              </Col>
                              <Col><Button danger size="small" icon={<DeleteOutlined />} onClick={() => delRule(rIdx)} /></Col>
                            </Row>
                          )
                        })
                      }
                      <Button size="small" icon={<PlusOutlined />} onClick={addRule} style={{ marginTop: 4 }}>
                        {t('p115.orgAddRule')}
                      </Button>
                    </div>
                  ),
                }]}
              />
            )
          })}

          {/* 新增分类 */}
          <Button icon={<PlusOutlined />} size="small" style={{ marginBottom: 12 }}
            onClick={() => setOrgCfg(c => ({
              ...c,
              categories: [...(c.categories || []), { name: '', target_dir: '', match_all: false, rules: [] }],
            }))}>
            {t('p115.orgAddCategory')}
          </Button>

          <div>
            <Button type="primary" icon={<CheckCircleOutlined />} onClick={handleOrgSave} loading={orgSaving} block>
              {t('p115.saveOrganizeConfig')}
            </Button>
          </div>
        </Card>
      </Col>

    </Row>
  )

  // ===================================================================
  //  Tab 3 — 刮削（重命名格式配置）
  // ===================================================================
  const currentParams = scrapeActiveInput === 'movie' ? SCRAPE_PARAMS_MOVIE : SCRAPE_PARAMS_TV
  const tab3 = (
    <Row gutter={[24, 24]}>
      <Col xs={24} lg={14}>
        <Card
          title={<Space><NodeIndexOutlined />{t('p115.scrapeTitle')}</Space>}
          extra={<Button type="primary" icon={<SaveOutlined />} loading={scrapeSaving} onClick={handleSaveScrapeConfig}>{t('p115.scrapeSave')}</Button>}
        >
          <Form layout="vertical" size="small">
            <Form.Item label={t('p115.scrapeEnabled')}>
              <Switch checked={scrapeCfg.enabled} onChange={v => setScrapeCfg(c => ({ ...c, enabled: v }))}
                checkedChildren={t('common.enabled')} unCheckedChildren={t('common.disabled')} />
            </Form.Item>

            <Divider orientation="left" orientationMargin={0} style={{ fontSize: 13 }}>
              <i className="iconfont icon-dianying" style={{ marginRight: 6 }} />
              {t('p115.scrapeFormatMovieSection')}
            </Divider>

            <Form.Item label={t('p115.scrapeMovieFormat')} tooltip={t('p115.scrapeMovieFormatHint')}>
              <Input
                ref={movieFormatRef}
                value={scrapeCfg.movie_format}
                placeholder={t('p115.scrapeMovieDefaultFormat')}
                onFocus={() => setScrapeActiveInput('movie')}
                onChange={e => setScrapeCfg(c => ({ ...c, movie_format: e.target.value }))}
                style={{ padding: '10px 11px' }}
              />
            </Form.Item>
            <div style={{ background: 'var(--ant-color-fill-quaternary,rgba(0,0,0,.04))', borderRadius: 6, padding: '8px 12px', marginBottom: 16, fontSize: 12 }}>
              <span style={{ color: '#888' }}>{t('p115.scrapeMoviePreview')}：</span>
              <code style={{ color: 'var(--ant-color-primary,#1677ff)', wordBreak: 'break-all' }}>
                {previewFormat(scrapeCfg.movie_format, MOVIE_SAMPLE)}
              </code>
            </div>

            <Divider orientation="left" orientationMargin={0} style={{ fontSize: 13 }}>
              <i className="iconfont icon-dianshiju" style={{ marginRight: 6 }} />
              {t('p115.scrapeFormatTvSection')}
            </Divider>

            <Form.Item label={t('p115.scrapeTvFormat')} tooltip={t('p115.scrapeTvFormatHint')}>
              <Input
                ref={tvFormatRef}
                value={scrapeCfg.tv_format}
                placeholder={t('p115.scrapeTvDefaultFormat')}
                onFocus={() => setScrapeActiveInput('tv')}
                onChange={e => setScrapeCfg(c => ({ ...c, tv_format: e.target.value }))}
                style={{ padding: '10px 11px' }}
              />
            </Form.Item>
            <div style={{ background: 'var(--ant-color-fill-quaternary,rgba(0,0,0,.04))', borderRadius: 6, padding: '8px 12px', fontSize: 12 }}>
              <span style={{ color: '#888' }}>{t('p115.scrapeTvPreview')}：</span>
              <code style={{ color: 'var(--ant-color-primary,#1677ff)', wordBreak: 'break-all' }}>
                {previewFormat(scrapeCfg.tv_format, TV_SAMPLE)}
              </code>
            </div>
          </Form>
        </Card>
      </Col>

      <Col xs={24} lg={10}>
        <Card title={<Space><PlusOutlined />{t('p115.scrapeParamsTitle')}</Space>}
          style={{ position: 'sticky', top: 24 }}>
          <Alert type="info" showIcon style={{ marginBottom: 12 }}
            message={scrapeActiveInput === 'movie'
              ? <><i className="iconfont icon-dianying" style={{ marginRight: 6 }} />{t('p115.scrapeFormatMovieSection')} — {t('p115.scrapeParamsTitle')}</>
              : <><i className="iconfont icon-dianshiju" style={{ marginRight: 6 }} />{t('p115.scrapeFormatTvSection')} — {t('p115.scrapeParamsTitle')}</>}
          />
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {currentParams.map(({ param, labelKey }) => (
              <Tooltip key={param} title={param}>
                <Button size="small" onClick={() => insertScrapeParam(param)}
                  style={{ fontFamily: 'monospace', fontSize: 12 }}>
                  {t(`p115.${labelKey}`)}
                </Button>
              </Tooltip>
            ))}
          </div>
          <Divider style={{ margin: '12px 0' }} />
          <div style={{ fontSize: 11, color: '#888', lineHeight: 1.8 }}>
            <div>• 点击参数按钮将其插入当前聚焦的格式输入框</div>
            <div>• <code>/</code> 分隔文件夹层级，如 <code>{'{title}'} ({'{year}'})/...</code></div>
            <div>• <code>:02d</code> 表示补零，如 <code>{'{season:02d}'}</code> → <code>01</code></div>
          </div>
        </Card>
      </Col>
    </Row>
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
          { key: 'scrape',   label: <Space><NodeIndexOutlined />{t('p115.tabScrape')}</Space>,      children: tab3 },
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
