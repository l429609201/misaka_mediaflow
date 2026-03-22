// src/pages/setting/index.jsx
// 系统设置

import { useState, useEffect } from 'react'
import { Card, Tabs, Input, Button, message, Typography, Space } from 'antd'
import { CopyOutlined, SaveOutlined, KeyOutlined, SafetyOutlined } from '@ant-design/icons'
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
  ]

  return (
    <Card title={t('settings.title')}>
      <Tabs items={tabItems} />
    </Card>
  )
}

export default Setting
