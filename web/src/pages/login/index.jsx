// src/pages/login/index.jsx
// 登录页

import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { Form, Input, Button, Card, message, Typography, Spin } from 'antd'
import { UserOutlined, LockOutlined } from '@ant-design/icons'
import { useTranslation } from 'react-i18next'
import { authApi } from '@/apis'
import LanguageSwitch from '@/components/LanguageSwitch'

const { Title, Text } = Typography

export const Login = () => {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [loading, setLoading] = useState(false)
  const [checking, setChecking] = useState(true)

  // 进入登录页时先检查白名单/已有token，命中直接跳首页
  useEffect(() => {
    const check = async () => {
      try {
        const token = localStorage.getItem('token')
        const headers = {}
        if (token) headers['Authorization'] = `Bearer ${token}`
        const resp = await fetch('/api/v1/auth/verify', { headers })
        if (resp.ok) {
          const data = await resp.json()
          if (data.valid) {
            if (data.token) localStorage.setItem('token', data.token)
            if (data.username) localStorage.setItem('username', data.username)
            navigate('/', { replace: true })
            return
          }
        }
      } catch { /* ignore */ }
      setChecking(false)
    }
    check()
  }, [navigate])

  const onFinish = async (values) => {
    setLoading(true)
    try {
      const { data } = await authApi.login(values.username, values.password)
      localStorage.setItem('token', data.token)
      localStorage.setItem('username', data.username)
      message.success(t('login.success'))
      navigate('/', { replace: true })
    } catch {
      message.error(t('login.failed'))
    } finally {
      setLoading(false)
    }
  }

  if (checking) {
    return (
      <div className="login-container">
        <Spin size="large" />
      </div>
    )
  }

  return (
    <div className="login-container">
      {/* 右上角语言切换 */}
      <div style={{ position: 'absolute', top: 20, right: 24, color: '#fff' }}>
        <LanguageSwitch />
      </div>

      <Card style={{ width: 400, borderRadius: 12 }} bordered={false}>
        <div style={{ textAlign: 'center', marginBottom: 32 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 10, marginBottom: 4 }}>
            <img src={`${import.meta.env.BASE_URL}images/logo.png`} alt="logo" style={{ height: 36, width: 36 }} />
            <Title level={3} style={{ margin: 0 }}>
              {t('login.title')}
            </Title>
          </div>
          <Text type="secondary">{t('login.subtitle')}</Text>
        </div>

        <Form onFinish={onFinish} size="large" autoComplete="off">
          <Form.Item
            name="username"
            rules={[{ required: true, message: t('login.usernameRequired') }]}
          >
            <Input
              prefix={<UserOutlined />}
              placeholder={t('login.usernamePlaceholder')}
            />
          </Form.Item>

          <Form.Item
            name="password"
            rules={[{ required: true, message: t('login.passwordRequired') }]}
          >
            <Input.Password
              prefix={<LockOutlined />}
              placeholder={t('login.passwordPlaceholder')}
            />
          </Form.Item>

          <Form.Item>
            <Button type="primary" htmlType="submit" loading={loading} block>
              {loading ? t('login.logging') : t('login.login')}
            </Button>
          </Form.Item>
        </Form>
      </Card>
    </div>
  )
}


export default Login
