// web/src/pages/ai/index.jsx
// AI 服务配置页 — 配置表单 + 功能开关 + Token统计 + 翻译缓存
import { useState, useEffect, useCallback } from 'react'
import {
  Card, Button, Space, Typography, Input, Tag, Switch, Divider,
  message, Form, Select, Statistic, Row, Col, Popconfirm, Table, Empty,
} from 'antd'
import {
  RobotOutlined, SettingOutlined, ThunderboltOutlined, SaveOutlined,
  DeleteOutlined, ReloadOutlined, BarChartOutlined, DatabaseOutlined,
} from '@ant-design/icons'
import { useTranslation } from 'react-i18next'
import { aiApi } from '@/apis/index.js'

const { Title, Text, Paragraph } = Typography

const AIPage = () => {
  const { t } = useTranslation()
  const [stats, setStats] = useState({})
  const [cache, setCache] = useState({ size: 0, entries: {} })
  const [loading, setLoading] = useState({})
  const [form] = Form.useForm()

  const setL = (k, v) => setLoading(p => ({ ...p, [k]: v }))

  const loadAll = useCallback(async () => {
    try {
      const [c, s, ca] = await Promise.all([aiApi.getConfig(), aiApi.getStats(), aiApi.getCache()])
      setStats(s.data || {}); setCache(ca.data || { size: 0, entries: {} })
      form.setFieldsValue(c.data || {})
    } catch { /* ignore */ }
  }, [form])

  useEffect(() => { loadAll() }, [loadAll])

  const handleSave = async () => {
    setL('save', true)
    try {
      const values = await form.validateFields()
      await aiApi.saveConfig(values)
      message.success(t('common.success')); loadAll()
    } catch { message.error(t('common.failed')) }
    finally { setL('save', false) }
  }

  const handleTest = async () => {
    setL('test', true)
    try {
      const { data } = await aiApi.testConnection()
      data?.success ? message.success(t('ai.testOk', 'AI 连接成功')) : message.error(data?.message || t('ai.testFail', '连接失败'))
    } catch (e) { message.error(e.message) }
    finally { setL('test', false) }
  }

  const cacheRows = Object.entries(cache.entries || {}).map(([k, v], i) => {
    const [orig] = k.split('|')
    return { key: i, original: orig, translated: v }
  })

  return (
    <div style={{ padding: 24 }}>
      <Title level={4} style={{ marginBottom: 16 }}><Space><RobotOutlined />{t('ai.title', 'AI 服务')}</Space></Title>
      <Row gutter={16}>
        <Col xs={24} lg={14}>
          <Card title={<Space><SettingOutlined />{t('ai.configTitle', 'AI 配置')}</Space>}
            extra={<Space>
              <Button icon={<ThunderboltOutlined />} onClick={handleTest} loading={loading.test}>{t('ai.testBtn', '测试连接')}</Button>
              <Button type="primary" icon={<SaveOutlined />} onClick={handleSave} loading={loading.save}>{t('common.save')}</Button>
            </Space>}
            style={{ marginBottom: 16 }}>
            <Form form={form} layout="vertical">
              <Form.Item name="provider" label={t('ai.provider', 'AI 提供商')}>
                <Select><Select.Option value="openai">OpenAI</Select.Option><Select.Option value="claude">Claude</Select.Option><Select.Option value="compatible">{t('ai.compatible', 'OpenAI 兼容')}</Select.Option></Select>
              </Form.Item>
              <Form.Item name="base_url" label={t('ai.baseUrl', 'API 地址')} extra={t('ai.baseUrlHint', '留空使用官方默认地址')}>
                <Input placeholder="https://api.openai.com/v1" />
              </Form.Item>
              <Form.Item name="api_key" label="API Key" rules={[{ required: true }]}>
                <Input.Password placeholder="sk-..." />
              </Form.Item>
              <Form.Item name="model" label={t('ai.model', '模型')} extra={t('ai.modelHint', '如 gpt-4o-mini / deepseek-chat')}>
                <Input placeholder="gpt-4o-mini" />
              </Form.Item>
              <Divider>{t('ai.featureToggle', '功能开关')}</Divider>
              <Form.Item name="actor_translate_enabled" label={t('ai.actorTranslate', '演员名 AI 翻译')} valuePropName="checked"
                extra={t('ai.actorTranslateHint', '演员中文化时用 AI 翻译补充 TMDB')}>
                <Switch />
              </Form.Item>
              <Form.Item name="overview_translate_enabled" label={t('ai.overviewTranslate', '剧情概述翻译')} valuePropName="checked"
                extra={t('ai.overviewTranslateHint', '刮削时将英文剧情概述翻译为中文')}>
                <Switch />
              </Form.Item>
            </Form>
            <Paragraph type="secondary" style={{ fontSize: 12, marginTop: 8 }}>
              {t('ai.configHint', '支持 OpenAI、Claude 及所有 OpenAI 兼容 API（DeepSeek、通义千问、Ollama 等）。')}
            </Paragraph>
          </Card>
        </Col>
        <Col xs={24} lg={10}>
          <Card title={<Space><BarChartOutlined />{t('ai.statsTitle', 'Token 统计')}</Space>}
            extra={<Popconfirm title={t('ai.resetConfirm', '重置统计？')} onConfirm={async () => { await aiApi.resetStats(); message.success(t('common.success')); loadAll() }}>
              <Button size="small" danger icon={<DeleteOutlined />}>{t('common.reset')}</Button>
            </Popconfirm>}
            style={{ marginBottom: 16 }}>
            <Row gutter={[16, 12]}>
              <Col span={8}><Statistic title={t('ai.statRequests', '总请求')} value={stats.total_requests || 0} valueStyle={{ fontSize: 20 }} /></Col>
              <Col span={8}><Statistic title={t('ai.statTranslate', '翻译请求')} value={stats.translate_requests || 0} valueStyle={{ fontSize: 20, color: '#1677ff' }} /></Col>
              <Col span={8}><Statistic title={t('ai.statCacheHits', '缓存命中')} value={stats.cache_hits || 0} valueStyle={{ fontSize: 20, color: '#52c41a' }} /></Col>
              <Col span={8}><Statistic title={t('ai.statPromptTokens', '输入 Tokens')} value={stats.total_prompt_tokens || 0} valueStyle={{ fontSize: 16 }} /></Col>
              <Col span={8}><Statistic title={t('ai.statCompTokens', '输出 Tokens')} value={stats.total_completion_tokens || 0} valueStyle={{ fontSize: 16 }} /></Col>
              <Col span={8}><Statistic title={t('ai.statTotalTokens', '总 Tokens')} value={stats.total_tokens || 0} valueStyle={{ fontSize: 16, color: '#fa8c16' }} /></Col>
            </Row>
          </Card>
          <Card title={<Space><DatabaseOutlined />{t('ai.cacheTitle', '翻译缓存')}</Space>}
            extra={<Space>
              <Tag>{cache.size || 0} {t('ai.cacheEntries', '条')}</Tag>
              <Popconfirm title={t('ai.clearCacheConfirm', '清空缓存？')} onConfirm={async () => { await aiApi.clearCache(); message.success(t('common.success')); loadAll() }}>
                <Button size="small" danger icon={<DeleteOutlined />}>{t('ai.clearCache', '清空')}</Button>
              </Popconfirm>
              <Button size="small" icon={<ReloadOutlined />} onClick={loadAll}>{t('common.refresh')}</Button>
            </Space>}>
            <Table size="small" rowKey="key" dataSource={cacheRows}
              locale={{ emptyText: <Empty description={t('ai.cacheEmpty', '暂无缓存')} /> }}
              pagination={{ pageSize: 8, showSizeChanger: false, size: 'small' }}
              columns={[
                { title: t('ai.cacheOriginal', '原文'), dataIndex: 'original', ellipsis: true },
                { title: t('ai.cacheTranslated', '译文'), dataIndex: 'translated', ellipsis: true,
                  render: v => <Text style={{ color: '#1677ff' }}>{v}</Text> },
              ]} />
          </Card>
        </Col>
      </Row>
    </div>
  )
}

export default AIPage
