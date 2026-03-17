// src/pages/p115/index.jsx
// 媒体库与 302 反代 — 左: 媒体服务器配置  右: 302反代配置 + Go反代进程管理

import { useEffect, useState, useCallback } from 'react'
import {
  Card, Descriptions, Tag, Button, Input, InputNumber, message,
  Space, Alert, Row, Col, Spin, Typography, Form, Badge, Select, Checkbox, Divider, Statistic,
} from 'antd'
import {
  SettingOutlined, SaveOutlined,
  PlayCircleOutlined, StopOutlined, ReloadOutlined,
  ApiOutlined, VideoCameraOutlined,
  ArrowUpOutlined, ArrowDownOutlined, DashboardOutlined,
} from '@ant-design/icons'
import { useTranslation } from 'react-i18next'
import { systemApi } from '@/apis'

const { Text } = Typography

// 流量格式化（字节 → 人类可读）
const formatTraffic = (bytes) => {
  if (!bytes || bytes === 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(1024))
  return `${(bytes / Math.pow(1024, i)).toFixed(i === 0 ? 0 : 2)} ${units[i] || 'TB'}`
}

export const P115 = () => {
  const { t } = useTranslation()

  // ==================== 302 反代配置 ====================
  const [proxyLoading, setProxyLoading] = useState(true)
  const [proxySaving, setProxySaving] = useState(false)
  const [proxyForm] = Form.useForm()

  // ==================== Go 反代进程 ====================
  const [goStatus, setGoStatus] = useState({ running: false, binary_found: false })
  const [goLoading, setGoLoading] = useState(false)
  const [traffic, setTraffic] = useState({ available: false })

  // ==================== 媒体服务器 ====================
  const [msForm] = Form.useForm()
  const [msLoading, setMsLoading] = useState(false)
  const [msTesting, setMsTesting] = useState(false)
  const [msTestResult, setMsTestResult] = useState(null)
  const [mediaLibraries, setMediaLibraries] = useState([])
  const [selectedLibIds, setSelectedLibIds] = useState([])
  const [libLoading, setLibLoading] = useState(false)

  // ===================================================================
  //                          数据加载
  // ===================================================================

  const fetchProxyConfig = useCallback(async () => {
    try {
      const { data } = await systemApi.getProxyConfig()
      proxyForm.setFieldsValue(data)
    } finally { setProxyLoading(false) }
  }, [proxyForm])

  const fetchGoStatus = useCallback(async () => {
    try {
      const { data } = await systemApi.getGoProxyStatus()
      setGoStatus(data)
    } catch { /* ignore */ }
  }, [])

  const fetchMediaServer = useCallback(async () => {
    try {
      const { data } = await systemApi.getMediaServer()
      msForm.setFieldsValue(data)
    } catch { /* ignore */ }
  }, [msForm])

  const fetchSelectedLibraries = useCallback(async () => {
    try {
      const { data } = await systemApi.getSelectedLibraries()
      setSelectedLibIds(data.library_ids || [])
    } catch { /* ignore */ }
  }, [])

  const fetchMediaLibraries = useCallback(async () => {
    setLibLoading(true)
    try {
      const { data } = await systemApi.getMediaLibraries()
      if (data.success) {
        setMediaLibraries(data.libraries || [])
      }
    } catch { /* ignore */ }
    finally { setLibLoading(false) }
  }, [])

  useEffect(() => {
    fetchProxyConfig()
    fetchGoStatus()
    fetchMediaServer()
    fetchSelectedLibraries()
    fetchMediaLibraries()

    // SSE 订阅 Go 反代状态（状态变化时推送）
    const token = localStorage.getItem('token') || ''
    const statusEvt = new EventSource(`/api/v1/system/go-proxy/status/stream?token=${token}`)
    statusEvt.onmessage = (e) => {
      try { setGoStatus(JSON.parse(e.data)) } catch { /* ignore */ }
    }
    statusEvt.onerror = () => statusEvt.close()

    // SSE 订阅流量统计（每 2 秒推送，替代轮询）
    const trafficEvt = new EventSource(`/api/v1/system/go-proxy/traffic/stream?token=${token}`)
    trafficEvt.onmessage = (e) => {
      try { setTraffic(JSON.parse(e.data)) } catch { /* ignore */ }
    }
    trafficEvt.onerror = () => trafficEvt.close()

    return () => {
      statusEvt.close()
      trafficEvt.close()
    }
  }, [fetchProxyConfig, fetchGoStatus, fetchMediaServer, fetchSelectedLibraries, fetchMediaLibraries])

  // ===================================================================
  //                          保存操作
  // ===================================================================

  const handleSaveProxyConfig = async () => {
    setProxySaving(true)
    try {
      const values = await proxyForm.validateFields()
      await systemApi.updateProxyConfig(values)
      message.success(t('p115.saveSuccess'))
    } catch { message.error(t('common.failed')) }
    finally { setProxySaving(false) }
  }

  const handleSaveMediaServer = async () => {
    setMsLoading(true)
    try {
      const values = await msForm.validateFields()
      await systemApi.updateMediaServer(values)
      await systemApi.saveSelectedLibraries(selectedLibIds)
      message.success(t('common.success'))
    } catch { message.error(t('common.failed')) }
    finally { setMsLoading(false) }
  }

  const handleTestMediaServer = async () => {
    setMsTesting(true)
    setMsTestResult(null)
    try {
      const values = await msForm.validateFields()
      const { data } = await systemApi.testMediaServer(values)
      setMsTestResult(data)
      if (data.success) {
        setMediaLibraries(data.libraries || [])
        message.success(data.message)
      } else {
        message.error(data.message)
      }
    } catch (e) {
      setMsTestResult({ success: false, message: String(e) })
      message.error(t('common.connectionFail'))
    } finally { setMsTesting(false) }
  }

  // ===================================================================
  //                        Go 反代操作
  // ===================================================================

  const handleStartGo = async () => {
    setGoLoading(true)
    try {
      const { data } = await systemApi.startGoProxy()
      if (data.success) { message.success(`Go 反代已启动 (pid: ${data.pid})`); fetchGoStatus() }
      else message.error(data.message)
    } catch { message.error(t('common.failed')) }
    finally { setGoLoading(false) }
  }

  const handleStopGo = async () => {
    setGoLoading(true)
    try {
      await systemApi.stopGoProxy()
      message.success('Go 反代已停止')
      fetchGoStatus()
    } catch { message.error(t('common.failed')) }
    finally { setGoLoading(false) }
  }

  const handleRestartGo = async () => {
    setGoLoading(true)
    try {
      await systemApi.stopGoProxy()
      await new Promise(r => setTimeout(r, 500))
      const { data } = await systemApi.startGoProxy()
      if (data.success) { message.success(`Go 反代已重启 (pid: ${data.pid})`); fetchGoStatus() }
      else message.error(data.message)
    } catch { message.error(t('common.failed')) }
    finally { setGoLoading(false) }
  }

  // ===================================================================
  //                           渲染
  // ===================================================================

  return (
    <div style={{ padding: 24 }}>
      <Row gutter={[24, 24]}>
        {/* 左: 媒体服务器配置 */}
        <Col xs={24} lg={12}>
          <Card title={<Space><VideoCameraOutlined />{t('p115.mediaServerTitle')}</Space>}>
            <Form form={msForm} layout="vertical" initialValues={{ type: 'emby' }}>
              <Form.Item name="type" label={t('p115.mediaServerType')} rules={[{ required: true }]}>
                <Select options={[
                  { value: 'emby', label: 'Emby' },
                  { value: 'jellyfin', label: 'Jellyfin' },
                ]} />
              </Form.Item>
              <Form.Item name="host" label={t('p115.mediaServerHost')} rules={[{ required: true }]}>
                <Input placeholder="http://192.168.1.100:8096" />
              </Form.Item>
              <Form.Item name="api_key" label={t('p115.mediaServerApiKey')} rules={[{ required: true }]}>
                <Input.Password placeholder="API Key" visibilityToggle />
              </Form.Item>
            </Form>

            {msTestResult && (
              <Alert
                type={msTestResult.success ? 'success' : 'error'}
                message={msTestResult.message}
                showIcon closable
                onClose={() => setMsTestResult(null)}
                style={{ marginBottom: 16 }}
              />
            )}

            {/* 媒体库选择 */}
            <Spin spinning={libLoading}>
              {mediaLibraries.length > 0 && (
                <div style={{ marginBottom: 16 }}>
                  <Text strong style={{ display: 'block', marginBottom: 8 }}>{t('p115.selectLibraries')}</Text>
                  <Checkbox.Group
                    value={selectedLibIds}
                    onChange={setSelectedLibIds}
                    style={{ display: 'flex', flexDirection: 'column', gap: 6 }}
                  >
                    {mediaLibraries.map(lib => (
                      <Checkbox key={lib.id} value={lib.id}>
                        {lib.name}
                        <Tag style={{ marginLeft: 8 }} color="blue">{lib.type || 'unknown'}</Tag>
                      </Checkbox>
                    ))}
                  </Checkbox.Group>
                </div>
              )}
            </Spin>

            <Space>
              <Button type="primary" icon={<SaveOutlined />} loading={msLoading} onClick={handleSaveMediaServer}>
                {t('common.save')}
              </Button>
              <Button icon={<ApiOutlined />} loading={msTesting} onClick={handleTestMediaServer}>
                {t('common.testConnection')}
              </Button>
            </Space>
          </Card>
        </Col>

        {/* 右: Go 302 反代（配置 + 进程 + 流量统计 合并） */}
        <Col xs={24} lg={12}>
          <Spin spinning={proxyLoading}>
            <Card
              title={<Space><DashboardOutlined />{t('p115.goProxyCardTitle')}</Space>}
              extra={
                <Button type="primary" icon={<SaveOutlined />} loading={proxySaving} onClick={handleSaveProxyConfig}>
                  {t('p115.saveConfig')}
                </Button>
              }
            >
              {/* ---- 进程状态 & 控制 ---- */}
              <Descriptions column={2} bordered size="small" style={{ marginBottom: 16 }}>
                <Descriptions.Item label={t('p115.goProxyStatus')}>
                  {goStatus.running
                    ? <Badge status="processing" text={<Tag color="success">{`${t('p115.goProxyRunning')} (PID: ${goStatus.pid})`}</Tag>} />
                    : <Badge status="default" text={<Tag color="default">{t('p115.goProxyStopped')}</Tag>} />}
                </Descriptions.Item>
                <Descriptions.Item label={t('p115.goProxyBinary')}>
                  {goStatus.binary_found
                    ? <Tag color="success">{t('p115.goProxyFound')}</Tag>
                    : <Tag color="error">{t('p115.goProxyNotFound')}</Tag>}
                </Descriptions.Item>
              </Descriptions>

              <Space style={{ marginBottom: 16 }}>
                {!goStatus.running ? (
                  <Button type="primary" icon={<PlayCircleOutlined />} loading={goLoading}
                    disabled={!goStatus.binary_found} onClick={handleStartGo}>
                    {t('p115.goProxyStart')}
                  </Button>
                ) : (
                  <>
                    <Button danger icon={<StopOutlined />} loading={goLoading} onClick={handleStopGo}>
                      {t('p115.goProxyStop')}
                    </Button>
                    <Button icon={<ReloadOutlined />} loading={goLoading} onClick={handleRestartGo}>
                      {t('p115.goProxyRestart')}
                    </Button>
                  </>
                )}
              </Space>

              {/* ---- 流量统计 ---- */}
              {goStatus.running && (
                <>
                  <Divider orientation="left" plain style={{ margin: '8px 0 12px' }}>{t('p115.goProxyTraffic')}</Divider>
                  {traffic.available ? (
                    <Row gutter={16}>
                      <Col span={12}>
                        <Statistic
                          title={t('p115.goProxyTrafficUp')} value={traffic.total_upload || 0}
                          prefix={<ArrowUpOutlined />} suffix="B"
                          formatter={(v) => formatTraffic(v)}
                        />
                      </Col>
                      <Col span={12}>
                        <Statistic
                          title={t('p115.goProxyTrafficDown')} value={traffic.total_download || 0}
                          prefix={<ArrowDownOutlined />} suffix="B"
                          formatter={(v) => formatTraffic(v)}
                        />
                      </Col>
                      <Col span={12} style={{ marginTop: 12 }}>
                        <Statistic
                          title={t('p115.goProxyRateUp')} value={traffic.current_upload || 0}
                          prefix={<ArrowUpOutlined style={{ color: '#52c41a' }} />}
                          formatter={(v) => `${formatTraffic(v)}/s`}
                        />
                      </Col>
                      <Col span={12} style={{ marginTop: 12 }}>
                        <Statistic
                          title={t('p115.goProxyRateDown')} value={traffic.current_download || 0}
                          prefix={<ArrowDownOutlined style={{ color: '#1677ff' }} />}
                          formatter={(v) => `${formatTraffic(v)}/s`}
                        />
                      </Col>
                    </Row>
                  ) : (
                    <Alert type="info" showIcon message={traffic.message || t('p115.goProxyNoTraffic')} />
                  )}
                </>
              )}

              {/* ---- 配置表单 ---- */}
              <Divider orientation="left" plain style={{ margin: '16px 0 12px' }}>{t('p115.goProxyConfig')}</Divider>
              <Alert message={t('p115.configReadonly')} type="info" showIcon style={{ marginBottom: 16 }} />
              <Form form={proxyForm} layout="vertical" size="small">
                <Form.Item name="go_port" label={t('p115.goPort')}>
                  <InputNumber min={1} max={65535} style={{ width: '100%' }} />
                </Form.Item>
                <Form.Item name="cache_ttl" label={t('p115.cacheTtl')}>
                  <InputNumber min={0} style={{ width: '100%' }} />
                </Form.Item>
                <Form.Item name="mem_cache_size" label={t('p115.memCacheSize')}>
                  <InputNumber min={100} style={{ width: '100%' }} />
                </Form.Item>
                <Form.Item name="connect_timeout" label={t('p115.connectTimeout')}>
                  <InputNumber min={1} style={{ width: '100%' }} />
                </Form.Item>
                <Form.Item name="ws_ping_interval" label={t('p115.wsPingInterval')}>
                  <InputNumber min={1} style={{ width: '100%' }} />
                </Form.Item>
              </Form>
            </Card>
          </Spin>
        </Col>
      </Row>
    </div>
  )
}

export default P115

