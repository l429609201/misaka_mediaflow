// web/src/pages/ai/index.jsx
// AI 对话助手页面
import { useState, useRef, useEffect, useCallback } from 'react'
import {
  Card, Button, Space, Typography, Input, Spin, Tag, Tooltip,
  message, Drawer, Form, Select, Empty, theme,
} from 'antd'
import {
  RobotOutlined, SendOutlined, SettingOutlined,
  UserOutlined, CopyOutlined, TranslationOutlined, DeleteOutlined,
} from '@ant-design/icons'
import { useTranslation } from 'react-i18next'
import { aiApi } from '@/apis/index.js'

const { Text } = Typography

const ChatBubble = ({ msg, onCopy }) => {
  const { token } = theme.useToken()
  const isUser = msg.role === 'user'
  return (
    <div style={{ display: 'flex', justifyContent: isUser ? 'flex-end' : 'flex-start', marginBottom: 12, padding: '0 8px' }}>
      {!isUser && (
        <div style={{ width: 36, height: 36, borderRadius: '50%', flexShrink: 0, background: token.colorPrimary, display: 'flex', alignItems: 'center', justifyContent: 'center', marginRight: 8, marginTop: 2 }}>
          <RobotOutlined style={{ color: '#fff', fontSize: 18 }} />
        </div>
      )}
      <div style={{ maxWidth: '75%', padding: '10px 14px', borderRadius: 12, background: isUser ? token.colorPrimary : token.colorBgContainer, color: isUser ? '#fff' : token.colorText, border: isUser ? 'none' : `1px solid ${token.colorBorderSecondary}`, boxShadow: '0 1px 4px rgba(0,0,0,0.06)', position: 'relative' }}>
        <div style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontSize: 14, lineHeight: 1.6 }}>{msg.content}</div>
        {!isUser && msg.content && (
          <Tooltip title="复制"><Button type="text" size="small" icon={<CopyOutlined />} style={{ position: 'absolute', top: 4, right: 4, opacity: 0.5 }} onClick={() => onCopy(msg.content)} /></Tooltip>
        )}
        {msg.usage && <div style={{ fontSize: 11, opacity: 0.6, marginTop: 4, textAlign: 'right' }}>tokens: {msg.usage.total_tokens}</div>}
      </div>
      {isUser && (
        <div style={{ width: 36, height: 36, borderRadius: '50%', flexShrink: 0, background: token.colorBgTextHover, display: 'flex', alignItems: 'center', justifyContent: 'center', marginLeft: 8, marginTop: 2 }}>
          <UserOutlined style={{ fontSize: 16 }} />
        </div>
      )}
    </div>
  )
}

const AIPage = () => {
  const { t } = useTranslation()
  const { token } = theme.useToken()
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [configOpen, setConfigOpen] = useState(false)
  const [config, setConfig] = useState({})
  const [configForm] = Form.useForm()
  const chatEndRef = useRef(null)

  const scrollToBottom = () => chatEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  useEffect(scrollToBottom, [messages])

  const loadConfig = useCallback(async () => {
    try { const { data } = await aiApi.getConfig(); setConfig(data || {}); configForm.setFieldsValue(data || {}) } catch {}
  }, [configForm])
  useEffect(() => { loadConfig() }, [loadConfig])

  const handleSend = async () => {
    const text = input.trim()
    if (!text || loading) return
    const userMsg = { role: 'user', content: text }
    const newMsgs = [...messages, userMsg]
    setMessages(newMsgs); setInput(''); setLoading(true)
    try {
      const { data } = await aiApi.chat(newMsgs.map(m => ({ role: m.role, content: m.content })))
      if (data?.success) setMessages(prev => [...prev, { role: 'assistant', content: data.content, usage: data.usage }])
      else setMessages(prev => [...prev, { role: 'assistant', content: 'Error: '+(data?.message || 'failed') }])
    } catch (e) { setMessages(prev => [...prev, { role: 'assistant', content: 'Error: '+e.message }]) }
    finally { setLoading(false) }
  }

  const handleCopy = (text) => { navigator.clipboard.writeText(text); message.success(t('common.copied', 'Copied')) }

  const handleSaveConfig = async () => {
    try {
      const values = await configForm.validateFields()
      await aiApi.saveConfig(values)
      message.success(t('common.success'))
      setConfigOpen(false); loadConfig()
    } catch { message.error(t('common.failed')) }
  }

  return (
    <div style={{ padding: 24, height: 'calc(100vh - 112px)', display: 'flex', flexDirection: 'column' }}>
      <Card size="small" style={{ marginBottom: 12, flexShrink: 0 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Space>
            <RobotOutlined style={{ fontSize: 20, color: token.colorPrimary }} />
            <Typography.Title level={5} style={{ margin: 0 }}>{t('ai.title', 'AI 助手')}</Typography.Title>
            {config.api_key_set ? <Tag color="green">{config.provider || 'openai'} / {config.model || '?'}</Tag> : <Tag color="red">{t('ai.notConfigured', '未配置')}</Tag>}
          </Space>
          <Space>
            <Tooltip title={t('ai.quickTranslate', '快捷翻译')}><Button type="text" icon={<TranslationOutlined />} onClick={() => setInput('请帮我翻译以下演员名为中文：')} /></Tooltip>
            <Tooltip title={t('ai.clearChat', '清空对话')}><Button type="text" icon={<DeleteOutlined />} onClick={() => setMessages([])} /></Tooltip>
            <Tooltip title={t('ai.settings', '配置')}><Button type="text" icon={<SettingOutlined />} onClick={() => setConfigOpen(true)} /></Tooltip>
          </Space>
        </div>
      </Card>
      <Card size="small" style={{ flex: 1, overflow: 'auto', marginBottom: 12, display: 'flex', flexDirection: 'column' }} bodyStyle={{ flex: 1, overflow: 'auto', padding: '16px 8px' }}>
        {messages.length === 0 ? (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%' }}>
            <Empty image={<RobotOutlined style={{ fontSize: 64, color: token.colorPrimary, opacity: 0.3 }} />} description={<Space direction="vertical" align="center"><Text type="secondary">{t('ai.welcome', '你好！我是 Misaka MediaFlow AI 助手')}</Text><Text type="secondary" style={{ fontSize: 12 }}>{t('ai.welcomeHint', '你可以问我关于媒体库管理、STRM 同步、演员信息等问题')}</Text></Space>} />
          </div>
        ) : (
          <div>
            {messages.map((msg, idx) => <ChatBubble key={idx} msg={msg} onCopy={handleCopy} />)}
            {loading && (
              <div style={{ display: 'flex', padding: '0 8px', marginBottom: 12 }}>
                <div style={{ width: 36, height: 36, borderRadius: '50%', flexShrink: 0, background: token.colorPrimary, display: 'flex', alignItems: 'center', justifyContent: 'center', marginRight: 8 }}><RobotOutlined style={{ color: '#fff', fontSize: 18 }} /></div>
                <div style={{ padding: '10px 14px', borderRadius: 12, background: token.colorBgContainer, border: '1px solid '+token.colorBorderSecondary }}><Spin size="small" /> <Text type="secondary" style={{ marginLeft: 8 }}>{t('ai.thinking', '思考中...')}</Text></div>
              </div>
            )}
            <div ref={chatEndRef} />
          </div>
        )}
      </Card>
      <Card size="small" style={{ flexShrink: 0 }} bodyStyle={{ padding: '8px 12px' }}>
        <Space.Compact style={{ width: '100%' }}>
          <Input.TextArea value={input} onChange={e => setInput(e.target.value)} placeholder={t('ai.inputPlaceholder', '输入消息...')} autoSize={{ minRows: 1, maxRows: 4 }} onPressEnter={e => { if (!e.shiftKey) { e.preventDefault(); handleSend() } }} style={{ borderRadius: '8px 0 0 8px' }} />
          <Button type="primary" icon={<SendOutlined />} onClick={handleSend} loading={loading} style={{ height: 'auto', borderRadius: '0 8px 8px 0' }}>{t('ai.send', '发送')}</Button>
        </Space.Compact>
      </Card>
      <Drawer title={t('ai.configTitle', 'AI 配置')} open={configOpen} onClose={() => setConfigOpen(false)} width={400} extra={<Button type="primary" onClick={handleSaveConfig}>{t('common.save')}</Button>}>
        <Form form={configForm} layout="vertical">
          <Form.Item name="provider" label={t('ai.provider', 'AI 提供商')}><Select><Select.Option value="openai">OpenAI</Select.Option><Select.Option value="claude">Claude</Select.Option><Select.Option value="compatible">{t('ai.compatible', 'OpenAI 兼容')}</Select.Option></Select></Form.Item>
          <Form.Item name="base_url" label={t('ai.baseUrl', 'API 地址')}><Input placeholder="https://api.openai.com/v1" /></Form.Item>
          <Form.Item name="api_key" label="API Key" rules={[{ required: true }]}><Input.Password placeholder="sk-..." /></Form.Item>
          <Form.Item name="model" label={t('ai.model', '模型')}><Input placeholder="gpt-4o-mini" /></Form.Item>
        </Form>
        <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>{t('ai.configHint', '支持 OpenAI、Claude 及所有 OpenAI 兼容 API。')}</Typography.Paragraph>
      </Drawer>
    </div>
  )
}

export default AIPage
