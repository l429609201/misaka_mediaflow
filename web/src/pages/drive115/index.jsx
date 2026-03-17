// src/pages/drive115/index.jsx
// 115 网盘 — 左: 115配置 + 高级设置  右: 路径映射

import { useEffect, useState, useRef, useCallback } from 'react'
import {
  Card, Descriptions, Tag, Button, Input, InputNumber, Modal, message,
  Space, Alert, Row, Col, Spin, Typography, Form, Select, QRCode,
  Avatar, Progress, Divider,
} from 'antd'
import {
  CheckCircleOutlined, CloseCircleOutlined, CloudSyncOutlined,
  KeyOutlined, QrcodeOutlined, SaveOutlined,
  MobileOutlined, DesktopOutlined, WechatOutlined, AlipayCircleOutlined,
  NodeIndexOutlined, FolderOpenOutlined, UserOutlined,
} from '@ant-design/icons'
import { useTranslation } from 'react-i18next'
import { p115Api } from '@/apis'
import DirPickerModal from '@/components/DirPickerModal'
import LocalDirPickerModal from '@/components/LocalDirPickerModal'

const { TextArea } = Input
const { Text } = Typography

export const Drive115 = () => {
  const { t } = useTranslation()

  // ==================== 115 状态 ====================
  const [status, setStatus] = useState({})
  const [loading, setLoading] = useState(true)

  // ==================== 115 账号信息 ====================
  const [account, setAccount] = useState({})

  // ==================== Cookie 弹窗 ====================
  const [cookieModal, setCookieModal] = useState(false)
  const [cookieValue, setCookieValue] = useState('')
  const [cookieSaving, setCookieSaving] = useState(false)

  // ==================== 扫码弹窗 ====================
  const [qrModal, setQrModal] = useState(false)
  const [qrData, setQrData] = useState(null)
  const [qrStatus, setQrStatus] = useState('idle')
  const [qrApp, setQrApp] = useState('web')
  const pollRef = useRef(null)

  // ==================== 高级设置 ====================
  const [settingsLoading, setSettingsLoading] = useState(true)
  const [settingsSaving, setSettingsSaving] = useState(false)
  const [settingsForm] = Form.useForm()

  // ==================== 路径映射 ====================
  const [mappingLoading, setMappingLoading] = useState(true)
  const [mappingSaving, setMappingSaving] = useState(false)
  const [mappingForm] = Form.useForm()
  const [dirPickerOpen, setDirPickerOpen] = useState(false)
  const [dirPickerTarget, setDirPickerTarget] = useState(null)
  const [localDirPickerOpen, setLocalDirPickerOpen] = useState(false)
  const [localDirPickerTarget, setLocalDirPickerTarget] = useState(null)

  // ===================================================================
  //                          数据加载
  // ===================================================================

  const fetchStatus = useCallback(async () => {
    try {
      const { data } = await p115Api.status()
      setStatus(data)
    } finally { setLoading(false) }
  }, [])

  const fetchAccount = useCallback(async () => {
    try {
      const { data } = await p115Api.getAccount()
      setAccount(data)
    } catch { /* ignore */ }
  }, [])

  const fetchPathMapping = useCallback(async () => {
    try {
      const { data } = await p115Api.getPathMapping()
      mappingForm.setFieldsValue(data)
    } catch { /* ignore */ }
    finally { setMappingLoading(false) }
  }, [mappingForm])

  const fetchSettings = useCallback(async () => {
    try {
      const { data } = await p115Api.getSettings()
      settingsForm.setFieldsValue(data)
    } catch { /* ignore */ }
    finally { setSettingsLoading(false) }
  }, [settingsForm])

  useEffect(() => {
    fetchStatus()
    fetchAccount()
    fetchPathMapping()
    fetchSettings()
  }, [fetchStatus, fetchAccount, fetchPathMapping, fetchSettings])

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
  //                          保存操作
  // ===================================================================

  const handleSavePathMapping = async () => {
    setMappingSaving(true)
    try {
      const values = await mappingForm.validateFields()
      await p115Api.savePathMapping(values)
      message.success(t('common.success'))
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

  // ===================================================================
  //                      目录选择器回调
  // ===================================================================

  const openDirPicker = (fieldName) => {
    setDirPickerTarget(fieldName)
    setDirPickerOpen(true)
  }

  const handleDirSelected = (path) => {
    if (dirPickerTarget) {
      mappingForm.setFieldValue(dirPickerTarget, path)
    }
  }

  const openLocalDirPicker = (fieldName) => {
    setLocalDirPickerTarget(fieldName)
    setLocalDirPickerOpen(true)
  }

  const handleLocalDirSelected = (path) => {
    if (localDirPickerTarget) {
      mappingForm.setFieldValue(localDirPickerTarget, path)
    }
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
  //                           渲染
  // ===================================================================

  return (
    <div style={{ padding: 24 }}>
      <Row gutter={[24, 24]}>
        {/* ========== 左栏: 115 配置（含高级设置） ========== */}
        <Col xs={24} lg={12}>
          <Spin spinning={loading || settingsLoading}>
            <Card
              title={<Space><CloudSyncOutlined />{t('p115.p115Title')}</Space>}
              extra={
                <Space>
                  {!loading && (
                    status.cookie
                      ? <Tag color="success">{t('p115.connected')}</Tag>
                      : <Tag color="error">{t('p115.disconnected')}</Tag>
                  )}
                  <Button type="primary" icon={<SaveOutlined />} loading={settingsSaving} onClick={handleSaveSettings}>
                    {t('common.save')}
                  </Button>
                </Space>
              }
            >
              {/* 账号信息区域 */}
              {account.logged_in && (
                <>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12 }}>
                    <Avatar
                      size={48} src={account.avatar}
                      icon={!account.avatar && <UserOutlined />}
                    />
                    <div style={{ flex: 1 }}>
                      <Space>
                        <Text strong style={{ fontSize: 16 }}>{account.user_name}</Text>
                        {account.vip_name && <Tag color={account.vip_color || 'gold'}>{account.vip_name}</Tag>}
                      </Space>
                      <div style={{ marginTop: 4 }}>
                        <Progress
                          percent={spacePercent} size="small"
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
                      <Button size="small" icon={<KeyOutlined />} onClick={() => setCookieModal(true)}>
                        {t('p115.setCookie')}
                      </Button>
                      <Button size="small" icon={<QrcodeOutlined />} onClick={handleOpenQr}>
                        {t('p115.scanLogin')}
                      </Button>
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
                <Descriptions.Item label={t('p115.cacheSize')}>
                  {status.cache_size ?? 0}
                </Descriptions.Item>
              </Descriptions>

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
                  <Input placeholder="http://192.168.1.100:14996" />
                </Form.Item>
                <Form.Item name="file_extensions" label={t('p115.fileExtensions')} tooltip={t('p115.fileExtensionsHint')}>
                  <Input placeholder="mp4,mkv,avi,ts,iso,mov,m2ts" />
                </Form.Item>
              </Form>
            </Card>
          </Spin>
        </Col>

        {/* ========== 右栏: 路径映射 ========== */}
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
                initialValues={{ media_prefix: '', cloud_prefix: '', strm_prefix: '' }}
              >
                {/* 网盘媒体库根目录 + 选择按钮 */}
                <Form.Item name="cloud_prefix" label={t('p115.cloudPrefix')} tooltip={t('p115.cloudPrefixHint')}>
                  <Input
                    placeholder="/影视/电影"
                    addonAfter={
                      <Button
                        type="link" size="small" icon={<FolderOpenOutlined />}
                        onClick={() => openDirPicker('cloud_prefix')}
                        style={{ padding: 0, height: 'auto' }}
                      >
                        {t('p115.selectDir')}
                      </Button>
                    }
                  />
                </Form.Item>
                {/* 媒体库挂载路径 */}
                <Form.Item name="media_prefix" label={t('p115.mediaPrefix')} tooltip={t('p115.mediaPrefixHint')}>
                  <Input placeholder="/media/movies" />
                </Form.Item>
                {/* 本地 STRM 根目录 */}
                <Form.Item name="strm_prefix" label={t('p115.strmPrefix')} tooltip={t('p115.strmPrefixHint')}>
                  <Input
                    placeholder="/config/strm/movies"
                    addonAfter={
                      <Button
                        type="link" size="small" icon={<FolderOpenOutlined />}
                        onClick={() => openLocalDirPicker('strm_prefix')}
                        style={{ padding: 0, height: 'auto' }}
                      >
                        {t('p115.selectDir')}
                      </Button>
                    }
                  />
                </Form.Item>
              </Form>
            </Card>
          </Spin>
        </Col>
      </Row>

      {/* ========== 目录选择弹窗 ========== */}
      <DirPickerModal
        open={dirPickerOpen}
        onClose={() => setDirPickerOpen(false)}
        onSelect={handleDirSelected}
      />

      {/* ========== 本地目录选择弹窗 ========== */}
      <LocalDirPickerModal
        open={localDirPickerOpen}
        onClose={() => setLocalDirPickerOpen(false)}
        onSelect={handleLocalDirSelected}
      />

      {/* ========== Cookie 弹窗 ========== */}
      <Modal
        title={t('p115.setCookie')} open={cookieModal}
        onCancel={() => setCookieModal(false)}
        onOk={handleSetCookie} confirmLoading={cookieSaving}
      >
        <TextArea rows={4} value={cookieValue}
          onChange={(e) => setCookieValue(e.target.value)}
          placeholder={t('p115.cookiePlaceholder')}
        />
      </Modal>

      {/* ========== 扫码弹窗 ========== */}
      <Modal
        title={t('p115.scanLogin')} open={qrModal}
        onCancel={handleCloseQr} footer={null} width={420}
      >
        <div style={{ marginBottom: 12 }}>
          <Text type="secondary">{t('p115.selectAppType')}</Text>
          <Select
            value={qrApp} onChange={(v) => setQrApp(v)}
            style={{ width: '100%', marginTop: 8 }}
            options={APP_OPTIONS.map(o => ({ value: o.value, label: <Space>{o.icon}{o.label}</Space> }))}
          />
        </div>
        <div style={{ textAlign: 'center', padding: '16px 0' }}>
          {qrStatus === 'loading' && <Spin tip={t('p115.qrLoading')} />}
          {qrStatus === 'waiting' && qrData?.qrcode_content && (
            <QRCode value={qrData.qrcode_content} size={200} />
          )}
          {qrStatus === 'scanned' && <Alert type="info" message={t('p115.qrScanned')} showIcon />}
          {qrStatus === 'success' && <Alert type="success" message={t('p115.qrSuccess')} showIcon />}
          {qrStatus === 'expired' && (
            <Space direction="vertical">
              <Alert type="warning" message={t('p115.qrExpired')} showIcon />
              <Button onClick={handleOpenQr}>{t('p115.qrRetry')}</Button>
            </Space>
          )}
          {qrStatus === 'failed' && (
            <Space direction="vertical">
              <Alert type="error" message={t('p115.qrFailed')} showIcon />
              <Button onClick={handleOpenQr}>{t('p115.qrRetry')}</Button>
            </Space>
          )}
        </div>
        <div style={{ textAlign: 'center' }}>
          <Text type="secondary">{qrStatusHint[qrStatus]}</Text>
        </div>
      </Modal>
    </div>
  )
}

export default Drive115