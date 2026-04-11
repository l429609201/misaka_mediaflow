// web/src/pages/ai/index.jsx
// AI 服务页 — 参照弹幕库风格 Tabs 分页 + 单列居中 + 余额 + 模型刷新
import { useState, useEffect, useCallback } from 'react'
import {
  Card, Button, Space, Typography, Input, Tag, Switch, Tabs,
  message, Form, Select, Statistic, Row, Col, Popconfirm, Table, Empty, Spin,
} from 'antd'
import {
  RobotOutlined, SettingOutlined, ThunderboltOutlined, SaveOutlined,
  DeleteOutlined, ReloadOutlined, BarChartOutlined, DatabaseOutlined,
  WalletOutlined, ApiOutlined,
} from '@ant-design/icons'
import { useTranslation } from 'react-i18next'
import { aiApi } from '@/apis/index.js'

const { Title, Text, Paragraph } = Typography

const PROVIDERS = [
  { value: 'openai', label: 'OpenAI' },
  { value: 'deepseek', label: 'DeepSeek' },
  { value: 'siliconflow', label: '硅基流动' },
  { value: 'claude', label: 'Claude' },
  { value: 'compatible', label: 'OpenAI 兼容' },
]

const AIPage = () => {
  const { t } = useTranslation()
  const [stats, setStats] = useState({})
  const [cache, setCache] = useState({ size: 0, entries: {} })
  const [balance, setBalance] = useState(null)
  const [models, setModels] = useState([])
  const [modelsLoading, setModelsLoading] = useState(false)
  const [loading, setLoading] = useState({})
  const [form] = Form.useForm()

  const setL = (k, v) => setLoading(p => ({ ...p, [k]: v }))

  const loadConfig = useCallback(async () => {
    try { const { data } = await aiApi.getConfig(); form.setFieldsValue(data || {}) } catch {}
  }, [form])

  const loadStats = useCallback(async () => {
    try { const { data } = await aiApi.getStats(); setStats(data || {}) } catch {}
  }, [])

  const loadCache = useCallback(async () => {
    try { const { data } = await aiApi.getCache(); setCache(data || { size: 0, entries: {} }) } catch {}
  }, [])

  const loadBalance = useCallback(async () => {
    try { const { data } = await aiApi.getBalance(); setBalance(data) } catch {}
  }, [])

  const loadModels = useCallback(async () => {
    setModelsLoading(true)
    try { const { data } = await aiApi.getModels(); setModels(data?.items || []) } catch {}
    finally { setModelsLoading(false) }
  }, [])

  useEffect(() => { loadConfig(); loadStats(); loadCache(); loadBalance() }, [loadConfig, loadStats, loadCache, loadBalance])

  const handleSave = async () => {
    setL('save', true)
    try {
      const values = await form.validateFields()
      await aiApi.saveConfig(values)
      message.success(t('common.success'))
      loadConfig(); loadBalance()
    } catch { message.error(t('common.failed')) }
    finally { setL('save', false) }
  }

  const handleTest = async () => {
    setL('test', true)
    try {
      const { data } = await aiApi.testConnection()
      data?.success ? message.success(t('ai.testOk', 'AI 连接成功')) : message.error(data?.message || t('ai.testFail'))
    } catch (e) { message.error(e.message) }
    finally { setL('test', false) }
  }

  const cacheRows = Object.entries(cache.entries || {}).map(([k, v], i) => ({ key: i, original: k.split('|')[0], translated: v }))

  // ── 居中容器 ───────────────────────────────────────────────
  const CenterWrap = ({ children }) => (
    <div style={{ maxWidth: 640, margin: '0 auto' }}>{children}</div>
  )

  return (
    <div style={{ padding: 24 }}>
      <Title level={4} style={{ marginBottom: 16 }}><Space><RobotOutlined />{t('ai.title', 'AI 服务')}</Space></Title>
      <Card>
        <Tabs items={[
          // ── Tab1: AI 连接配置 ────────────────────────────────
          { key: 'config', label: <Space><SettingOutlined />AI 连接配置</Space>, children: (
            <CenterWrap>
              <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
                <Form.Item name="provider" label="AI 提供商">
                  <Select options={PROVIDERS} />
                </Form.Item>
                <Form.Item name="api_key" label="API 密钥" rules={[{ required: true }]}>
                  <Input.Password placeholder="sk-..." />
                </Form.Item>
                <Form.Item name="base_url" label="Base URL" extra="留空使用官方默认地址，自定义部署填写完整地址">
                  <Input placeholder="https://api.openai.com/v1" />
                </Form.Item>
                <Form.Item name="model" label="模型名称">
                  <Space.Compact style={{ width: '100%' }}>
                    <Select
                      showSearch allowClear
                      style={{ flex: 1 }}
                      placeholder={modelsLoading ? '加载中...' : '选择或输入模型'}
                      loading={modelsLoading}
                      value={form.getFieldValue('model') || undefined}
                      onChange={v => form.setFieldValue('model', v)}
                      options={models.map(m => ({ value: m.id, label: m.id }))}
                      notFoundContent={models.length === 0 ? <Text type="secondary">点击刷新加载模型列表</Text> : null}
                      filterOption={(input, opt) => opt.label.toLowerCase().includes(input.toLowerCase())}
                    />
                    <Button icon={<ReloadOutlined />} loading={modelsLoading} onClick={loadModels} />
                  </Space.Compact>
                </Form.Item>
              </Form>
              {/* 账户余额 */}
              {balance?.supported && (
                <Card size="small" style={{ marginBottom: 16, background: '#f6ffed', borderColor: '#b7eb8f' }}>
                  <Space style={{ width: '100%', justifyContent: 'space-between' }}>
                    <Space><WalletOutlined style={{ color: '#52c41a' }} /><Text strong>账户余额 ({balance.provider})</Text></Space>
                    <Button size="small" icon={<ReloadOutlined />} onClick={loadBalance}>刷新</Button>
                  </Space>
                  <Row gutter={16} style={{ marginTop: 12 }}>
                    <Col span={8}><Statistic title="总余额" prefix="¥" value={balance.total} valueStyle={{ color: '#52c41a', fontSize: 20 }} /></Col>
                    <Col span={8}><Statistic title="赠金" prefix="¥" value={balance.granted} valueStyle={{ fontSize: 16 }} /></Col>
                    <Col span={8}><Statistic title="充值" prefix="¥" value={balance.topped_up} valueStyle={{ fontSize: 16 }} /></Col>
                  </Row>
                </Card>
              )}
              <Space style={{ width: '100%', justifyContent: 'flex-end' }}>
                <Button icon={<ThunderboltOutlined />} onClick={handleTest} loading={loading.test}>测试 AI 连接</Button>
                <Button type="primary" icon={<SaveOutlined />} onClick={handleSave} loading={loading.save}>保存 AI 连接配置</Button>
              </Space>
            </CenterWrap>
          )},
          // ── Tab2: 功能开关 ──────────────────────────────────
          { key: 'features', label: <Space><ApiOutlined />功能开关</Space>, children: (
            <CenterWrap>
              <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
                <Form.Item name="actor_translate_enabled" label="演员名 AI 翻译" valuePropName="checked"
                  extra="开启后，演员管理「中文化」将使用 AI 翻译作为 TMDB 翻译的补充">
                  <Switch />
                </Form.Item>
                <Form.Item name="overview_translate_enabled" label="剧情概述翻译" valuePropName="checked"
                  extra="开启后，刮削时自动将英文剧情概述翻译为中文">
                  <Switch />
                </Form.Item>
              </Form>
              <Space style={{ width: '100%', justifyContent: 'flex-end' }}>
                <Button type="primary" icon={<SaveOutlined />} onClick={handleSave} loading={loading.save}>保存</Button>
              </Space>
            </CenterWrap>
          )},
          // ── Tab3: 使用统计 ──────────────────────────────────
          { key: 'stats', label: <Space><BarChartOutlined />AI 使用统计</Space>, children: (
            <CenterWrap>
              <Card size="small" style={{ marginTop: 16, marginBottom: 16 }}
                extra={<Popconfirm title="重置统计？" onConfirm={async () => { await aiApi.resetStats(); loadStats(); message.success(t('common.success')) }}>
                  <Button size="small" danger icon={<DeleteOutlined />}>重置</Button></Popconfirm>}>
                <Row gutter={[16, 16]}>
                  <Col span={8}><Statistic title="总请求" value={stats.total_requests || 0} /></Col>
                  <Col span={8}><Statistic title="翻译请求" value={stats.translate_requests || 0} valueStyle={{ color: '#1677ff' }} /></Col>
                  <Col span={8}><Statistic title="缓存命中" value={stats.cache_hits || 0} valueStyle={{ color: '#52c41a' }} /></Col>
                  <Col span={8}><Statistic title="输入 Tokens" value={stats.total_prompt_tokens || 0} /></Col>
                  <Col span={8}><Statistic title="输出 Tokens" value={stats.total_completion_tokens || 0} /></Col>
                  <Col span={8}><Statistic title="总 Tokens" value={stats.total_tokens || 0} valueStyle={{ color: '#fa8c16' }} /></Col>
                </Row>
              </Card>
              {/* 翻译缓存 */}
              <Card size="small" title={<Space><DatabaseOutlined />翻译缓存</Space>}
                extra={<Space>
                  <Tag>{cache.size || 0} 条</Tag>
                  <Popconfirm title="清空缓存？" onConfirm={async () => { await aiApi.clearCache(); loadCache(); message.success(t('common.success')) }}>
                    <Button size="small" danger icon={<DeleteOutlined />}>清空</Button>
                  </Popconfirm>
                  <Button size="small" icon={<ReloadOutlined />} onClick={loadCache}>刷新</Button>
                </Space>}>
                <Table size="small" rowKey="key" dataSource={cacheRows}
                  locale={{ emptyText: <Empty description="暂无缓存" /> }}
                  pagination={{ pageSize: 10, showSizeChanger: false, size: 'small' }}
                  columns={[
                    { title: '原文', dataIndex: 'original', ellipsis: true },
                    { title: '译文', dataIndex: 'translated', ellipsis: true, render: v => <Text style={{ color: '#1677ff' }}>{v}</Text> },
                  ]} />
              </Card>
            </CenterWrap>
          )},
        ]} />
      </Card>
    </div>
  )
}

export default AIPage
