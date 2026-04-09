// web/src/pages/drive115-monitor/index.jsx
// 实时监控页面：115 生活事件轮询 + Webhook 接收双通道
// 全部文案通过 i18n t() 获取，无硬编码中文

import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Alert, Badge, Button, Card, Checkbox, Col, Collapse,
  Descriptions, Divider, Form, Input, InputNumber,
  Radio, Row, Space, Spin, Table, Tag, Tooltip, Typography, message,
} from 'antd'
import {
  CheckCircleOutlined, ClearOutlined, CopyOutlined,
  DownloadOutlined, PauseCircleOutlined, PlayCircleOutlined,
  QuestionCircleOutlined, RadarChartOutlined, ReloadOutlined,
  SafetyCertificateOutlined, SyncOutlined, ThunderboltOutlined,
} from '@ant-design/icons'
import { useTranslation } from 'react-i18next'
import { p115StrmApi } from '@/apis'

const { Text, Title, Paragraph } = Typography

// 事件来源标签颜色
const SOURCE_COLOR = { life: 'blue', cd2: 'purple', generic: 'cyan' }
// 结果标签颜色
const RESULT_COLOR = { trigger: 'success', skip: 'default', dedup: 'warning' }

// ── 顶部总体状态栏 ─────────────────────────────────────────────────────────
function OverallStatusBar({ status, config, onRefresh, t }) {
  const lifePollOn  = config.life_poll_enabled !== false
  const webhookOn   = config.webhook_enabled === true
  const isRunning   = status.running

  return (
    <Card size="small" style={{ marginBottom: 16 }}>
      <Row gutter={[24, 8]} align="middle">
        <Col xs={24} sm={12} md={6}>
          <Text type="secondary">{t('p115.monitorLifePollStatus')}</Text><br />
          <Badge
            status={isRunning && lifePollOn ? 'processing' : 'default'}
            text={isRunning && lifePollOn ? t('p115.monitorRunning') : t('p115.monitorStopped')}
          />
        </Col>
        <Col xs={24} sm={12} md={6}>
          <Text type="secondary">{t('p115.monitorWebhookStatus')}</Text><br />
          <Badge
            status={webhookOn ? 'success' : 'default'}
            text={webhookOn ? t('common.enabled') : t('common.disabled')}
          />
        </Col>
        <Col xs={24} sm={12} md={8}>
          <Text type="secondary">{t('p115.monitorLastTrigger')}</Text><br />
          <Text>
            {status.last_event_time
              ? new Date(status.last_event_time * 1000).toLocaleString()
              : t('p115.monitorNeverTriggered')}
          </Text>
        </Col>
        <Col xs={24} sm={12} md={4} style={{ textAlign: 'right' }}>
          <Space>
            <Button
              size="small"
              type={isRunning ? 'default' : 'primary'}
              danger={isRunning}
              icon={isRunning ? <PauseCircleOutlined /> : <PlayCircleOutlined />}
              onClick={() => isRunning
                ? p115StrmApi.stopMonitor().then(onRefresh)
                : p115StrmApi.startMonitor().then(onRefresh)
              }
            >
              {isRunning ? t('p115.stopMonitor') : t('p115.startMonitor')}
            </Button>
            <Button size="small" icon={<ReloadOutlined />} onClick={onRefresh} />
          </Space>
        </Col>
      </Row>
    </Card>
  )
}

// ── Tab1：115 生活事件轮询 ────────────────────────────────────────────────
function LifePollTab({ config, onSave, saving, t }) {
  const [enabled,  setEnabled]  = useState(config.life_poll_enabled !== false)
  const [interval, setInterval] = useState(config.poll_interval || 30)

  useEffect(() => {
    setEnabled(config.life_poll_enabled !== false)
    setInterval(config.poll_interval || 30)
  }, [config])

  return (
    <Space direction="vertical" style={{ width: '100%' }}>
      <Alert type="info" showIcon message={t('p115.monitorLifePollDesc')} />
      <Card size="small">
        <Form layout="vertical" size="small">
          <Form.Item label={t('p115.monitorLifePollEnabled')}>
            <Radio.Group value={enabled} onChange={e => setEnabled(e.target.value)}>
              <Radio value={true}>{t('common.enabled')}</Radio>
              <Radio value={false}>{t('common.disabled')}</Radio>
            </Radio.Group>
          </Form.Item>
          <Form.Item
            label={t('p115.monitorLifePollInterval')}
            extra={t('p115.monitorLifePollIntervalHint')}
          >
            <InputNumber
              min={10} max={3600} value={interval}
              onChange={setInterval}
              addonAfter={t('p115.seconds')}
              style={{ width: 160 }}
            />
          </Form.Item>
          <Button
            type="primary" loading={saving}
            onClick={() => onSave({ life_poll_enabled: enabled, poll_interval: interval })}
          >
            {t('common.save')}
          </Button>
        </Form>
      </Card>
    </Space>
  )
}


// ── Tab2：Webhook 接收 ───────────────────────────────────────────────────
function WebhookTab({ config, onSave, saving, baseUrl, t }) {
  const [enabled, setEnabled] = useState(config.webhook_enabled === true)
  const [token,   setToken]   = useState(config.webhook_token || '')
  const webhookUrl = `${baseUrl}/api/v1/webhook/cd2`

  useEffect(() => {
    setEnabled(config.webhook_enabled === true)
    setToken(config.webhook_token || '')
  }, [config])

  const genToken = () => {
    const chars = 'ABCDEFGHJKMNPQRSTWXYZabcdefhijkmnprstwxyz2345678'
    setToken(Array.from({ length: 32 }, () => chars[Math.floor(Math.random() * chars.length)]).join(''))
  }

  const copyUrl = () => {
    navigator.clipboard.writeText(webhookUrl).then(() => message.success(t('common.copySuccess')))
  }

  const downloadToml = () => {
    const content = `[global_params]\nbase_url = "${baseUrl}"\nenabled = true\n\n[global_params.default_headers]\ncontent-type = "application/json"\n${token ? `authorization = "Bearer ${token}"\n` : ''}user-agent = "clouddrive2/{version}"\n\n[file_system_watcher]\nurl = "{base_url}/api/v1/webhook/cd2"\nmethod = "POST"\nenabled = true\nbody = '''\n{\n  "device_name": "{device_name}",\n  "event_time": "{event_time}",\n  "data": [\n    {\n      "action": "{action}",\n      "is_dir": "{is_dir}",\n      "source_file": "{source_file}",\n      "destination_file": "{destination_file}"\n    }\n  ]\n}\n'''\n`
    const blob = new Blob([content], { type: 'text/plain' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob); a.download = 'webhook.toml'; a.click()
  }

  const wsStat = config.webhook_stats || {}

  return (
    <Space direction="vertical" style={{ width: '100%' }}>
      <Alert type="info" showIcon message={t('p115.monitorWebhookDesc')} />
      {(wsStat.cd2 > 0 || wsStat.generic > 0) && (
        <Descriptions size="small" bordered column={3}>
          <Descriptions.Item label={t('p115.monitorWebhookStatCd2')}>{wsStat.cd2 || 0}</Descriptions.Item>
          <Descriptions.Item label={t('p115.monitorWebhookStatGeneric')}>{wsStat.generic || 0}</Descriptions.Item>
          <Descriptions.Item label={t('p115.monitorWebhookStatLastTime')}>
            {wsStat.last_time ? new Date(wsStat.last_time * 1000).toLocaleString() : '-'}
          </Descriptions.Item>
        </Descriptions>
      )}
      <Card size="small">
        <Form layout="vertical" size="small">
          <Form.Item label={t('p115.monitorWebhookEnabled')}>
            <Radio.Group value={enabled} onChange={e => setEnabled(e.target.value)}>
              <Radio value={true}>{t('common.enabled')}</Radio>
              <Radio value={false}>{t('common.disabled')}</Radio>
            </Radio.Group>
          </Form.Item>
          <Form.Item label={t('p115.monitorWebhookUrl')} extra={t('p115.monitorWebhookUrlHint')}>
            <Input readOnly value={webhookUrl}
              addonAfter={<Tooltip title={t('common.copy')}><CopyOutlined onClick={copyUrl} style={{ cursor: 'pointer' }} /></Tooltip>}
            />
          </Form.Item>
          <Form.Item label={<Space>{t('p115.monitorWebhookToken')}<Tooltip title={t('p115.monitorWebhookTokenHint')}><QuestionCircleOutlined style={{ color: '#999' }} /></Tooltip></Space>}>
            <Input.Password value={token} onChange={e => setToken(e.target.value)}
              addonAfter={<Button type="link" size="small" onClick={genToken} style={{ padding: 0, height: 'auto' }}>{t('p115.monitorWebhookTokenGen')}</Button>}
            />
          </Form.Item>
          <Collapse size="small" style={{ marginBottom: 12 }} items={[{
            key: '1',
            label: <Space><SafetyCertificateOutlined />{t('p115.monitorWebhookGuide')}</Space>,
            children: (
              <Space direction="vertical" style={{ width: '100%' }}>
                <Text>{t('p115.monitorWebhookGuideStep1')}</Text>
                <Text>{t('p115.monitorWebhookGuideStep2')}：<Text code>{baseUrl}</Text></Text>
                <Text>{t('p115.monitorWebhookGuideStep3')}</Text>
                <Text>{t('p115.monitorWebhookGuideStep4')}</Text>
                <Button icon={<DownloadOutlined />} onClick={downloadToml}>{t('p115.monitorWebhookDownloadToml')}</Button>
              </Space>
            ),
          }]} />
          <Button type="primary" loading={saving}
            onClick={() => onSave({ webhook_enabled: enabled, webhook_token: token })}>
            {t('common.save')}
          </Button>
        </Form>
      </Card>
    </Space>
  )
}

// ── Tab3：触发规则 ────────────────────────────────────────────────────────
const TRIGGER_TYPES = [
  { value: 2,  labelKey: 'evType2'  }, { value: 6,  labelKey: 'evType6'  },
  { value: 14, labelKey: 'evType14' }, { value: 17, labelKey: 'evType17' },
  { value: 18, labelKey: 'evType18' }, { value: 22, labelKey: 'evType22' },
  { value: 1,  labelKey: 'evType1'  }, { value: 5,  labelKey: 'evType5'  },
]

function RulesTab({ config, onSave, saving, t }) {
  const [autoSync, setAutoSync] = useState(config.auto_inc_sync !== false)
  const [types,    setTypes]    = useState(config.trigger_types || [2,6,14,17,18,22])
  const [debounce, setDebounce] = useState(config.debounce_seconds ?? 5)

  useEffect(() => {
    setAutoSync(config.auto_inc_sync !== false)
    setTypes(config.trigger_types || [2,6,14,17,18,22])
    setDebounce(config.debounce_seconds ?? 5)
  }, [config])

  return (
    <Card size="small">
      <Form layout="vertical" size="small">
        <Form.Item label={t('p115.monitorRulesAction')}>
          <Radio.Group value={autoSync} onChange={e => setAutoSync(e.target.value)}>
            <Space direction="vertical">
              <Radio value={true}>{t('p115.monitorRulesAutoSync')}</Radio>
              <Radio value={false}>{t('p115.monitorRulesLogOnly')}</Radio>
            </Space>
          </Radio.Group>
        </Form.Item>
        <Form.Item label={t('p115.monitorRulesEventFilter')}>
          <Checkbox.Group value={types} onChange={setTypes}>
            <Row gutter={[8, 4]}>
              {TRIGGER_TYPES.map(({ value, labelKey }) => (
                <Col span={12} key={value}><Checkbox value={value}>{t(`p115.${labelKey}`)}</Checkbox></Col>
              ))}
            </Row>
          </Checkbox.Group>
        </Form.Item>
        <Form.Item label={t('p115.monitorRulesDebounce')} extra={t('p115.monitorRulesDebounceHint')}>
          <InputNumber min={0} max={300} value={debounce} onChange={setDebounce}
            addonAfter={t('p115.seconds')} style={{ width: 160 }} />
        </Form.Item>
        <Button type="primary" loading={saving}
          onClick={() => onSave({ auto_inc_sync: autoSync, trigger_types: types, debounce_seconds: debounce })}>
          {t('common.save')}
        </Button>
      </Form>
    </Card>
  )
}

// ── Tab4：事件日志 ────────────────────────────────────────────────────────
function EventLogTab({ events, onClear, t }) {
  const SOURCE_LABEL = { life: t('p115.monitorLogSourceLife'), cd2: t('p115.monitorLogSourceCd2'), generic: t('p115.monitorLogSourceGeneric') }

  const columns = [
    { title: t('p115.monitorLogColSource'), dataIndex: 'source', width: 90,
      render: v => <Tag color={SOURCE_COLOR[v] || 'default'}>{SOURCE_LABEL[v] || v}</Tag> },
    { title: t('p115.monitorLogColType'), width: 130,
      render: (_, row) => {
        if (row.type) return <Tag color="blue">{t(`p115.evType${row.type}`) || row.type_name || row.type}</Tag>
        if (row.action) return <Tag color="geekblue">{row.action}</Tag>
        return '-'
      }
    },
    { title: t('p115.monitorLogColFile'), ellipsis: true,
      render: (_, row) => <Text ellipsis style={{ maxWidth: 300 }}>{row.path || row.file_name || '-'}</Text> },
    { title: t('p115.monitorLogColTime'), dataIndex: 'time', width: 90,
      render: v => v ? new Date(v * 1000).toLocaleTimeString() : '-' },
    { title: t('p115.monitorLogColResult'), width: 90,
      render: (_, row) => {
        if (row.dedup) return <Tag color={RESULT_COLOR.dedup}>{t('p115.monitorLogResultDedup')}</Tag>
        if (row.type && ![2,6,14,17,18,22,1,5].includes(row.type)) return <Tag color={RESULT_COLOR.skip}>{t('p115.monitorLogResultSkip')}</Tag>
        return <Tag color={RESULT_COLOR.trigger}>{t('p115.monitorLogResultTrigger')}</Tag>
      }
    },
  ]

  return (
    <Card size="small"
      title={<Space><ThunderboltOutlined />{t('p115.monitorLogCount', { count: events.length })}</Space>}
      extra={<Button danger size="small" icon={<ClearOutlined />} onClick={onClear}>{t('p115.monitorLogClear')}</Button>}
    >
      <Table rowKey={(r, i) => i} columns={columns} dataSource={[...events].reverse()}
        size="small" pagination={{ pageSize: 20, size: 'small' }}
        locale={{ emptyText: t('p115.noEvents') }} scroll={{ x: 700 }}
      />
    </Card>
  )
}

// ── 主页面 ────────────────────────────────────────────────────────────────
export const Drive115Monitor = () => {
  const { t } = useTranslation()
  const [config,  setConfig]  = useState({})
  const [status,  setStatus]  = useState({})
  const [loading, setLoading] = useState(true)
  const [saving,  setSaving]  = useState(false)
  const [activeTab, setActiveTab] = useState('lifePoll')
  const [events,  setEvents]  = useState([])
  const pollRef = useRef(null)

  const baseUrl = window.location.origin

  const fetchAll = useCallback(async () => {
    try {
      const [cfgRes, stRes] = await Promise.all([
        p115StrmApi.getMonitorConfig(),
        p115StrmApi.getMonitorStatus(),
      ])
      setConfig(cfgRes.data || {})
      const st = stRes.data || {}
      setStatus(st)
      if (st.recent_events?.length) setEvents(st.recent_events)
    } catch { /* ignore */ }
    finally { setLoading(false) }
  }, [])

  useEffect(() => {
    fetchAll()
    pollRef.current = setInterval(fetchAll, 10000)
    return () => clearInterval(pollRef.current)
  }, [fetchAll])

  const handleSave = async (patch) => {
    setSaving(true)
    try {
      await p115StrmApi.saveMonitorConfig({ ...config, ...patch })
      message.success(t('p115.configSaved'))
      fetchAll()
    } catch { message.error(t('p115.saveFailed')) }
    finally { setSaving(false) }
  }

  const TAB_ITEMS = [
    { key: 'lifePoll', label: t('p115.monitorTabLifePoll'),
      children: <LifePollTab config={config} onSave={handleSave} saving={saving} t={t} /> },
    { key: 'webhook',  label: t('p115.monitorTabWebhook'),
      children: <WebhookTab config={config} onSave={handleSave} saving={saving} baseUrl={baseUrl} t={t} /> },
    { key: 'rules',    label: t('p115.monitorTabRules'),
      children: <RulesTab config={config} onSave={handleSave} saving={saving} t={t} /> },
    { key: 'log',      label: t('p115.monitorTabLog'),
      children: <EventLogTab events={events} onClear={() => setEvents([])} t={t} /> },
  ]

  if (loading) return <Spin size="large" style={{ display: 'block', margin: '80px auto' }} />

  return (
    <div style={{ padding: 24 }}>
      <Title level={4} style={{ marginBottom: 16 }}>
        <Space><RadarChartOutlined />{t('p115.monitorPageTitle')}</Space>
      </Title>
      <OverallStatusBar status={status} config={config} onRefresh={fetchAll} t={t} />
      <Card
        tabList={TAB_ITEMS.map(({ key, label }) => ({ key, tab: label }))}
        activeTabKey={activeTab}
        onTabChange={setActiveTab}
        bodyStyle={{ padding: 16 }}
      >
        {TAB_ITEMS.find(item => item.key === activeTab)?.children}
      </Card>
    </div>
  )
}

export default Drive115Monitor
