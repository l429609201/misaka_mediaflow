// web/src/pages/bgm-oauth-callback/index.jsx
// Bangumi OAuth 回调页面 — 弹窗中打开，完成授权后通知父窗口
import { useEffect, useState } from 'react'
import { Spin, Result, Button } from 'antd'
import { systemApi } from '@/apis'

export default function BgmOAuthCallback() {
  const [status, setStatus] = useState('loading')
  const [msg, setMsg] = useState('')

  useEffect(() => {
    const url = new URL(window.location.href)
    const code = url.searchParams.get('code')
    const state = url.searchParams.get('state')

    if (!code) {
      setStatus('error')
      setMsg('授权码为空，请重新授权')
      return
    }

    const redirectUri = `${window.location.origin}/bgm-oauth-callback`

    systemApi.bgmExchangeCode({ code, state: state || '', redirect_uri: redirectUri })
      .then(({ data }) => {
        if (data.success) {
          setStatus('success')
          setMsg('Bangumi 授权成功')
          try {
            if (window.opener) {
              window.opener.postMessage('BANGUMI-OAUTH-COMPLETE', '*')
              setTimeout(() => window.close(), 1500)
            }
          } catch (e) {
            console.error('Failed to notify parent:', e)
          }
        } else {
          setStatus('error')
          setMsg(data.message || '授权失败')
        }
      })
      .catch(err => {
        setStatus('error')
        setMsg(err.message || '请求失败，请重试')
      })
  }, [])

  return (
    <div style={{
      display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh',
      background: 'linear-gradient(135deg, #f09199 0%, #c06c84 100%)',
    }}>
      <div style={{
        background: 'white', padding: 40, borderRadius: 10,
        boxShadow: '0 10px 40px rgba(0,0,0,0.1)', textAlign: 'center', minWidth: 320,
      }}>
        {status === 'loading' && (
          <div><Spin size="large" /><p style={{ marginTop: 16, color: '#666' }}>正在完成授权...</p></div>
        )}
        {status === 'success' && (
          <Result status="success" title="授权成功" subTitle={msg || '窗口将自动关闭...'}
            extra={<Button onClick={() => window.close()}>关闭窗口</Button>} />
        )}
        {status === 'error' && (
          <Result status="error" title="授权失败" subTitle={msg}
            extra={<Button onClick={() => window.close()}>关闭窗口</Button>} />
        )}
      </div>
    </div>
  )
}
