// src/pages/setting/index.jsx
// 系统设置

 import { useState, useEffect } from 'react'
 import { Card, Divider, Form, Input, Button, message, Switch, Tabs, Typography, Space } from 'antd'
 import { BellOutlined, CopyOutlined, SaveOutlined, KeyOutlined, SafetyOutlined, SendOutlined } from '@ant-design/icons'
import { useTranslation } from 'react-i18next'
import { authApi, systemApi } from '@/apis'

const { Text } = Typography
const { TextArea } = Input

export const Setting = () => {
  const { t } = useTranslation()

  // ==================== API Token ====================
  const [apiToken, setApiToken] = useState('')

  const handleShowToken = async () => {
    try {
      const { data } = await authApi.getApiToken()
      setApiToken(data.api_token)
    } catch {
      message.error(t('common.failed'))
    }
  }

  const handleCopyToken = () => {
    navigator.clipboard.writeText(apiToken)
    message.success(t('common.copySuccess'))
  }

  // ==================== IP 白名单 ====================
  const [whitelistText, setWhitelistText] = useState('')
  const [whitelistLoading, setWhitelistLoading] = useState(false)

  useEffect(() => {
    const loadWhitelist = async () => {
      try {
        const { data } = await systemApi.getIpWhitelist()
        setWhitelistText((data.items || []).join('\n'))
      } catch { /* ignore */ }
    }
    loadWhitelist()
  }, [])

  const handleSaveWhitelist = async () => {
    setWhitelistLoading(true)
    try {
      const items = whitelistText.split('\n').map(s => s.trim()).filter(Boolean)
      await systemApi.updateIpWhitelist(items)
      message.success(t('settings.whitelistSaved'))
    } catch {
      message.error(t('common.failed'))
    } finally {
      setWhitelistLoading(false)
    }
  }

  // ==================== 通知渠道 ====================
  const [notifyCfg, setNotifyCfg] = useState({
    telegram:   { enabled: false, token: '', chat_id: '' },
    serverchan: { enabled: false, key: '' },
    webhook:    { enabled: false, url: '' },
  })
  const [notifySaving, setNotifySaving] = useState(false)
  const [notifyTesting, setNotifyTesting] = useState(false)

  useEffect(() => {
    systemApi.getNotifyConfig().then(({ data }) => {
      if (data) setNotifyCfg(prev => ({
        telegram:   { ...prev.telegram,   ...(data.telegram   || {}) },
        serverchan: { ...prev.serverchan, ...(data.serverchan || {}) },
        webhook:    { ...prev.webhook,    ...(data.webhook    || {}) },
      }))
    }).catch(() => {})
  }, [])

  const handleSaveNotify = async () => {
    setNotifySaving(true)
    try {
      await systemApi.saveNotifyConfig(notifyCfg)
      message.success(t('settings.notifySaved'))
    } catch { message.error(t('common.failed')) }
    finally { setNotifySaving(false) }
  }
  const handleTestNotify = async () => {
    setNotifyTesting(true)
    try {
      const { data } = await systemApi.testNotify()
      data?.success ? message.success(t('settings.notifyTestSuccess')) : message.warning(t('settings.notifyTestFail'))
    } catch { message.error(t('settings.notifyTestFail')) }
    finally { setNotifyTesting(false) }
  }
  const setTg  = (k, v) => setNotifyCfg(c => ({ ...c, telegram:   { ...c.telegram,   [k]: v } }))
  const setSC  = (k, v) => setNotifyCfg(c => ({ ...c, serverchan: { ...c.serverchan, [k]: v } }))
  const setWH  = (k, v) => setNotifyCfg(c => ({ ...c, webhook:    { ...c.webhook,    [k]: v } }))

  // ==================== Tab 定义 ====================
  const tabItems = [
    {
      key: 'token',
      label: <Space><KeyOutlined />{t('settings.apiToken')}</Space>,
      children: (
        <div style={{ maxWidth: 560, paddingTop: 8 }}>
          <Text type="secondary" style={{ display: 'block', marginBottom: 16 }}>
            {t('settings.apiTokenHint')}
          </Text>
          {apiToken ? (
            <Space.Compact style={{ width: '100%' }}>
              <Input value={apiToken} readOnly />
              <Button icon={<CopyOutlined />} onClick={handleCopyToken} />
            </Space.Compact>
          ) : (
            <Button type="primary" onClick={handleShowToken}>
              {t('settings.apiToken')}
            </Button>
          )}
        </div>
      ),
    },
    {
      key: 'whitelist',
      label: <Space><SafetyOutlined />{t('settings.ipWhitelist')}</Space>,
      children: (
        <div style={{ maxWidth: 560, paddingTop: 8 }}>
          <Text type="secondary" style={{ display: 'block', marginBottom: 12 }}>
            {t('settings.ipWhitelistHint')}
          </Text>
          <TextArea
            rows={8}
            placeholder={t('settings.ipWhitelistPlaceholder')}
            value={whitelistText}
            onChange={(e) => setWhitelistText(e.target.value)}
            style={{ marginBottom: 12 }}
          />
          <Button
            type="primary"
            icon={<SaveOutlined />}
            loading={whitelistLoading}
            onClick={handleSaveWhitelist}
          >
            {t('common.save')}
          </Button>
        </div>
      ),
    },
    {
      key: 'notify',
      label: <Space><BellOutlined />{t('settings.notify')}</Space>,
      children: (
        <div style={{ maxWidth: 560, paddingTop: 8 }}>
          <Form layout="vertical" size="small">
            {/* Telegram */}
            <Divider orientation="left">{t('settings.notifyTelegram')}</Divider>
            <Form.Item label={t('settings.notifyEnabled')}>
              <Switch checked={notifyCfg.telegram.enabled} onChange={v => setTg('enabled', v)} />
            </Form.Item>
            <Form.Item label={t('settings.notifyToken')}>
              <Input.Password value={notifyCfg.telegram.token}
                onChange={e => setTg('token', e.target.value)}
                placeholder={t('settings.notifyTokenPlaceholder')} disabled={!notifyCfg.telegram.enabled} />
            </Form.Item>
            <Form.Item label={t('settings.notifyChatId')}>
              <Input value={notifyCfg.telegram.chat_id}
                onChange={e => setTg('chat_id', e.target.value)}
                placeholder={t('settings.notifyChatIdPlaceholder')} disabled={!notifyCfg.telegram.enabled} />
            </Form.Item>
            {/* Server酱 */}
            <Divider orientation="left">{t('settings.notifyServerchan')}</Divider>
            <Form.Item label={t('settings.notifyEnabled')}>
              <Switch checked={notifyCfg.serverchan.enabled} onChange={v => setSC('enabled', v)} />
            </Form.Item>
            <Form.Item label={t('settings.notifyKey')}>
              <Input.Password value={notifyCfg.serverchan.key}
                onChange={e => setSC('key', e.target.value)}
                placeholder={t('settings.notifyKeyPlaceholder')} disabled={!notifyCfg.serverchan.enabled} />
            </Form.Item>
            {/* 自定义 Webhook */}
            <Divider orientation="left">{t('settings.notifyWebhook')}</Divider>
            <Form.Item label={t('settings.notifyEnabled')}>
              <Switch checked={notifyCfg.webhook.enabled} onChange={v => setWH('enabled', v)} />
            </Form.Item>
            <Form.Item label={t('settings.notifyWebhookUrl')}>
              <Input value={notifyCfg.webhook.url}
                onChange={e => setWH('url', e.target.value)}
                placeholder={t('settings.notifyWebhookUrlPlaceholder')} disabled={!notifyCfg.webhook.enabled} />
            </Form.Item>
            <Space>
              <Button type="primary" icon={<SaveOutlined />} loading={notifySaving} onClick={handleSaveNotify}>
                {t('common.save')}
              </Button>
              <Button icon={<SendOutlined />} loading={notifyTesting} onClick={handleTestNotify}>
                {t('settings.notifyTest')}
              </Button>
            </Space>
          </Form>
        </div>
      ),
    },
  ]

  return (
    <Card title={t('settings.title')}>
      <Tabs items={tabItems} />
    </Card>
  )
}

export default Setting
