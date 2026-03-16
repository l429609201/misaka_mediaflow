// src/pages/setting/index.jsx
// 系统设置（注意：目录名用 setting 单数，对齐 misaka 命名）

import { useState, useEffect } from 'react'
import { Card, Tabs, Form, Input, Button, Select, message, Typography, Descriptions, Space } from 'antd'
import { CopyOutlined, SaveOutlined } from '@ant-design/icons'
import { useTranslation } from 'react-i18next'
import { authApi } from '@/apis'
import { LANGUAGES, changeLanguage, getCurrentLanguage } from '@/i18n'

const { Text } = Typography
const { TextArea } = Input

export const Setting = () => {
  const { t } = useTranslation()

  // ==================== 修改密码 ====================
  const [pwdForm] = Form.useForm()
  const [pwdLoading, setPwdLoading] = useState(false)

  const handleChangePassword = async () => {
    const values = await pwdForm.validateFields()
    if (values.new_password !== values.confirm_password) {
      message.error(t('settings.passwordMismatch'))
      return
    }
    if (values.new_password.length < 6) {
      message.error(t('settings.passwordTooShort'))
      return
    }
    setPwdLoading(true)
    try {
      await authApi.changePassword(values.old_password, values.new_password)
      message.success(t('settings.passwordChanged'))
      pwdForm.resetFields()
    } catch {
      message.error(t('common.failed'))
    } finally {
      setPwdLoading(false)
    }
  }

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

  // ==================== 语言设置 ====================
  const handleLanguageChange = (lang) => {
    changeLanguage(lang)
  }

  const tabItems = [
    {
      key: 'security',
      label: t('settings.security'),
      children: (
        <div style={{ maxWidth: 500 }}>
          <Card title={t('settings.changePassword')} size="small" style={{ marginBottom: 16 }}>
            <Form form={pwdForm} layout="vertical">
              <Form.Item name="old_password" label={t('settings.oldPassword')} rules={[{ required: true }]}>
                <Input.Password />
              </Form.Item>
              <Form.Item name="new_password" label={t('settings.newPassword')} rules={[{ required: true }]}>
                <Input.Password />
              </Form.Item>
              <Form.Item name="confirm_password" label={t('settings.confirmPassword')} rules={[{ required: true }]}>
                <Input.Password />
              </Form.Item>
              <Button type="primary" loading={pwdLoading} onClick={handleChangePassword}>
                {t('common.save')}
              </Button>
            </Form>
          </Card>

          <Card title={t('settings.apiToken')} size="small" style={{ marginBottom: 16 }}>
            <Text type="secondary">{t('settings.apiTokenHint')}</Text>
            <div style={{ marginTop: 12 }}>
              {apiToken ? (
                <Space>
                  <Input value={apiToken} readOnly style={{ width: 360 }} />
                  <Button icon={<CopyOutlined />} onClick={handleCopyToken} />
                </Space>
              ) : (
                <Button onClick={handleShowToken}>{t('settings.apiToken')}</Button>
              )}
            </div>
          </Card>

          <Card title={t('settings.ipWhitelist')} size="small">
            <Text type="secondary">{t('settings.ipWhitelistHint')}</Text>
            <div style={{ marginTop: 12 }}>
              <TextArea
                rows={5}
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
          </Card>
        </div>
      ),
    },
    {
      key: 'language',
      label: t('settings.language'),
      children: (
        <div style={{ maxWidth: 400 }}>
          <Form layout="vertical">
            <Form.Item label={t('settings.language')}>
              <Select
                value={getCurrentLanguage()}
                onChange={handleLanguageChange}
                options={LANGUAGES.map((l) => ({ value: l.key, label: l.label }))}
                style={{ width: 200 }}
              />
            </Form.Item>
          </Form>
        </div>
      ),
    },
    {
      key: 'about',
      label: t('settings.about'),
      children: (
        <Descriptions column={1} bordered size="small" style={{ maxWidth: 500 }}>
          <Descriptions.Item label={t('app.name')}>Misaka MediaFlow</Descriptions.Item>
          <Descriptions.Item label={t('settings.version')}>1.0.0</Descriptions.Item>
        </Descriptions>
      ),
    },
  ]

  return (
    <Card title={t('settings.title')}>
      <Tabs items={tabItems} tabPosition="left" />
    </Card>
  )
}


export default Setting
