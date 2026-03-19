// src/pages/media-proxy/index.jsx
// 媒体库与 302 反代 — 顶部 Tabs: 媒体服务器 / 302 反代 / 媒体源配置

import { useEffect, useState, useCallback } from 'react'
import {
  Card, Tabs, Descriptions, Tag, Button, Input, InputNumber, message,
  Space, Alert, Row, Col, Spin, Typography, Form, Badge, Select, Checkbox, Divider, Statistic,
  Switch, Table,
} from 'antd'
import {
  SaveOutlined,
  PlayCircleOutlined, StopOutlined, ReloadOutlined,
  ApiOutlined, VideoCameraOutlined,
  ArrowUpOutlined, ArrowDownOutlined, DashboardOutlined,
  CloudServerOutlined, PlusOutlined, DeleteOutlined,
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
  // 用户列表
  const [embyUsers, setEmbyUsers] = useState([])
  const [usersLoading, setUsersLoading] = useState(false)

  // ==================== 媒体源配置 ====================
  // 每条媒体源: { key, name, type, url, enabled }
  const [mediaSources, setMediaSources] = useState([])
  const [sourceForm] = Form.useForm()

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
      // 若已保存 host+api_key，自动拉取用户列表以填充下拉
      if (data.host && data.api_key) {
        fetchEmbyUsers(data.host, data.api_key)
      }
    } catch { /* ignore */ }
  }, [msForm]) // eslint-disable-line react-hooks/exhaustive-deps

  // 查询 Emby 用户列表（用传入的 host+api_key，或从表单实时取）
  const fetchEmbyUsers = useCallback(async (host, apiKey) => {
    const h = host ?? msForm.getFieldValue('host')
    const k = apiKey ?? msForm.getFieldValue('api_key')
    if (!h || !k) { message.warning('请先填写服务器地址和 API Key'); return }
    setUsersLoading(true)
    try {
      const { data } = await systemApi.getMediaServerUsers({ host: h, api_key: k })
      if (data.success) {
        setEmbyUsers(data.users || [])
        if (!data.users?.length) message.info('未找到任何用户')
      } else {
        message.error(data.message || '获取用户失败')
      }
    } catch { message.error('获取用户失败') }
    finally { setUsersLoading(false) }
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
      // type 固定 emby，user_id 从表单取（Form.Item name="user_id"）
      await systemApi.updateMediaServer({ ...values, type: 'emby' })
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
      const { data } = await systemApi.testMediaServer({ ...values, type: 'emby' })
      setMsTestResult(data)
      if (data.success) {
        setMediaLibraries(data.libraries || [])
        message.success(data.message)
        // 测试连接成功后自动拉取用户列表
        fetchEmbyUsers(values.host, values.api_key)
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

  // ==================== 媒体源配置操作 ====================
  const handleAddSource = () => {
    sourceForm.validateFields().then(values => {
      const newSource = {
        key: Date.now().toString(),
        name: values.src_name,
        type: values.src_type || '115网盘',
        url: values.src_url || '',
        enabled: true,
      }
      setMediaSources(prev => [...prev, newSource])
      sourceForm.resetFields()
    })
  }

  const handleToggleSource = (key) => {
    setMediaSources(prev => prev.map(s => s.key === key ? { ...s, enabled: !s.enabled } : s))
  }

  const handleDeleteSource = (key) => {
    setMediaSources(prev => prev.filter(s => s.key !== key))
  }

  // ===================================================================
  //                     Tab 内容定义
  // ===================================================================

  // Tab1: 媒体服务器
  const mediaServerTab = (
    <div style={{ maxWidth: 600, paddingTop: 4 }}>
      <Form form={msForm} layout="vertical">
        <Form.Item name="host" label={t('p115.mediaServerHost')} rules={[{ required: true }]}>
          <Input placeholder="http://192.168.1.100:8096" />
        </Form.Item>
        <Form.Item name="api_key" label={t('p115.mediaServerApiKey')} rules={[{ required: true }]}>
          <Input.Password placeholder="API Key" visibilityToggle />
        </Form.Item>
        <Form.Item label="播放用户">
          <Space.Compact style={{ width: '100%' }}>
            <Form.Item name="user_id" noStyle>
              <Select
                placeholder="请先点击「检索用户」"
                allowClear
                style={{ width: '100%' }}
                loading={usersLoading}
                options={embyUsers.map(u => ({ value: u.id, label: u.name }))}
              />
            </Form.Item>
            <Button loading={usersLoading} onClick={() => fetchEmbyUsers()}>检索用户</Button>
          </Space.Compact>
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
    </div>
  )

  // Tab2: 302 反代
  const proxyTab = (
    <Spin spinning={proxyLoading}>
      <div style={{ maxWidth: 700, paddingTop: 4 }}>
        {/* 进程状态 & 控制 */}
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

        {/* 流量统计 */}
        {goStatus.running && (
          <>
            <Divider orientation="left" plain style={{ margin: '8px 0 12px' }}>{t('p115.goProxyTraffic')}</Divider>
            {traffic.available ? (
              <Row gutter={16} style={{ marginBottom: 16 }}>
                <Col span={12}><Statistic title={t('p115.goProxyTrafficUp')} value={traffic.total_upload || 0} prefix={<ArrowUpOutlined />} formatter={(v) => formatTraffic(v)} /></Col>
                <Col span={12}><Statistic title={t('p115.goProxyTrafficDown')} value={traffic.total_download || 0} prefix={<ArrowDownOutlined />} formatter={(v) => formatTraffic(v)} /></Col>
                <Col span={12} style={{ marginTop: 12 }}><Statistic title={t('p115.goProxyRateUp')} value={traffic.current_upload || 0} prefix={<ArrowUpOutlined style={{ color: '#52c41a' }} />} formatter={(v) => `${formatTraffic(v)}/s`} /></Col>
                <Col span={12} style={{ marginTop: 12 }}><Statistic title={t('p115.goProxyRateDown')} value={traffic.current_download || 0} prefix={<ArrowDownOutlined style={{ color: '#1677ff' }} />} formatter={(v) => `${formatTraffic(v)}/s`} /></Col>
              </Row>
            ) : (
              <Alert type="info" showIcon message={traffic.message || t('p115.goProxyNoTraffic')} style={{ marginBottom: 16 }} />
            )}
          </>
        )}

        {/* 配置表单 */}
        <Divider orientation="left" plain style={{ margin: '8px 0 12px' }}>{t('p115.goProxyConfig')}</Divider>
        <Alert message={t('p115.configReadonly')} type="info" showIcon style={{ marginBottom: 16 }} />
        <Form form={proxyForm} layout="vertical" size="small">
          <Row gutter={16}>
            <Col span={12}><Form.Item name="go_port" label={t('p115.goPort')}><InputNumber min={1} max={65535} style={{ width: '100%' }} /></Form.Item></Col>
            <Col span={12}><Form.Item name="cache_ttl" label={t('p115.cacheTtl')}><InputNumber min={0} style={{ width: '100%' }} /></Form.Item></Col>
            <Col span={12}><Form.Item name="mem_cache_size" label={t('p115.memCacheSize')}><InputNumber min={100} style={{ width: '100%' }} /></Form.Item></Col>
            <Col span={12}><Form.Item name="connect_timeout" label={t('p115.connectTimeout')}><InputNumber min={1} style={{ width: '100%' }} /></Form.Item></Col>
            <Col span={12}><Form.Item name="ws_ping_interval" label={t('p115.wsPingInterval')}><InputNumber min={1} style={{ width: '100%' }} /></Form.Item></Col>
          </Row>
        </Form>
        <Button type="primary" icon={<SaveOutlined />} loading={proxySaving} onClick={handleSaveProxyConfig}>
          {t('p115.saveConfig')}
        </Button>
      </div>
    </Spin>
  )

  // Tab3: 媒体源配置
  const sourceColumns = [
    { title: '名称', dataIndex: 'name', key: 'name' },
    { title: '类型', dataIndex: 'type', key: 'type', render: (v) => <Tag color="blue">{v}</Tag> },
    { title: 'URL / 说明', dataIndex: 'url', key: 'url', ellipsis: true },
    {
      title: '启用', dataIndex: 'enabled', key: 'enabled', width: 70,
      render: (v, record) => <Switch size="small" checked={v} onChange={() => handleToggleSource(record.key)} />,
    },
    {
      title: '操作', key: 'action', width: 70,
      render: (_, record) => (
        <Button danger type="text" size="small" icon={<DeleteOutlined />} onClick={() => handleDeleteSource(record.key)} />
      ),
    },
  ]

  const mediaSourceTab = (
    <div style={{ maxWidth: 740, paddingTop: 4 }}>
      <Alert
        type="info" showIcon style={{ marginBottom: 16 }}
        message="媒体源配置用于定义参与直链解析的存储来源，当前支持 115网盘。后续版本将支持 Alist、本地路径等更多来源。"
      />
      {/* 添加新媒体源 */}
      <Card size="small" title="添加媒体源" style={{ marginBottom: 16 }}>
        <Form form={sourceForm} layout="inline" style={{ flexWrap: 'wrap', gap: 8 }}>
          <Form.Item name="src_name" rules={[{ required: true, message: '请输入名称' }]}>
            <Input placeholder="名称" style={{ width: 160 }} />
          </Form.Item>
          <Form.Item name="src_type">
            <Select
              placeholder="类型"
              style={{ width: 140 }}
              defaultValue="115网盘"
              options={[
                { value: '115网盘', label: '115网盘' },
                { value: 'Alist', label: 'Alist' },
                { value: '本地路径', label: '本地路径' },
              ]}
            />
          </Form.Item>
          <Form.Item name="src_url">
            <Input placeholder="URL / 路径（选填）" style={{ width: 220 }} />
          </Form.Item>
          <Form.Item>
            <Button type="primary" icon={<PlusOutlined />} onClick={handleAddSource}>添加</Button>
          </Form.Item>
        </Form>
      </Card>

      <Table
        size="small"
        dataSource={mediaSources}
        columns={sourceColumns}
        pagination={false}
        locale={{ emptyText: '暂无媒体源，点击上方「添加」按钮新增' }}
      />
    </div>
  )

  // ===================================================================
  //                           渲染
  // ===================================================================

  const tabItems = [
    {
      key: 'media-server',
      label: <Space><VideoCameraOutlined />媒体服务器</Space>,
      children: mediaServerTab,
    },
    {
      key: 'proxy',
      label: <Space><DashboardOutlined />302 反代</Space>,
      children: proxyTab,
    },
    {
      key: 'media-source',
      label: <Space><CloudServerOutlined />媒体源配置</Space>,
      children: mediaSourceTab,
    },
  ]

  return (
    <Card title={t('p115.mediaServerTitle')}>
      <Tabs items={tabItems} />
    </Card>
  )
}

export default P115

