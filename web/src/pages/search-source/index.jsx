// src/pages/search-source/index.jsx
// 搜索源配置 — 参照弹幕库风格，每个源独立 Alert + 配置表单
import { useState, useEffect, useCallback, useRef } from 'react'
import {
  Card, Tabs, Table, Button, Form, Input, Switch, Space,
  Tag, Modal, Spin, Alert, Tooltip, Typography, message, Divider,
} from 'antd'
import {
  EditOutlined, ReloadOutlined, SearchOutlined,
  CheckCircleOutlined, CloseCircleOutlined, ExperimentOutlined,
  LinkOutlined, KeyOutlined, QuestionCircleOutlined,
  LoginOutlined, LogoutOutlined, UserOutlined,
} from '@ant-design/icons'
import { systemApi } from '@/apis'

const { Text, Paragraph } = Typography

// ─── 各源的描述信息（参照弹幕库 MetadataSourceConfig） ──────
const SOURCE_INFO = {
  tmdb: {
    name: 'TMDB',
    color: '#01d277',
    desc: 'The Movie Database (TMDB) 是全球最大的电影和电视节目数据库，提供丰富的元数据信息。',
    links: [
      { label: '获取 API Key', url: 'https://www.themoviedb.org/settings/api' },
    ],
  },
  bangumi: {
    name: 'Bangumi (BGM)',
    color: '#f09199',
    desc: 'Bangumi 是动画、漫画、游戏等 ACG 作品的数据库，可以提供作品的元数据信息。',
    links: [
      { label: '获取 Access Token', url: 'https://next.bgm.tv/demo/access-token' },
      { label: '创建应用', url: 'https://bgm.tv/dev/app' },
    ],
  },
  douban: {
    name: '豆瓣',
    color: '#00b51d',
    desc: '豆瓣是中文社区中最权威的影视数据源，提供电影、电视等作品的详细信息和评分。需要通过 Cookie 方式访问。',
    links: [],
  },
  imdb: {
    name: 'IMDB',
    color: '#f5c518',
    desc: 'IMDb 是全球最大的电影数据库。支持第三方 API (速度快) 和官方网站 HTML 解析 (更稳定) 两种方式。',
    links: [
      { label: 'IMDB 官网', url: 'https://www.imdb.com/' },
    ],
  },
  tvdb: {
    name: 'TVDB',
    color: '#6cd491',
    desc: 'The TVDB 是电视节目数据库，提供电视节目的详细集数、季信息和元数据。',
    links: [
      { label: '获取 API Key', url: 'https://thetvdb.com/dashboard/account/apikeys' },
    ],
  },
}

// ─── 动态字段渲染 ──────────────────────────────────────────
const DynamicField = ({ field }) => {
  const rules = field.required ? [{ required: true, message: `请输入 ${field.label}` }] : []
  const extra = field.hint ? <span style={{ fontSize: 12, color: '#888' }}>{field.hint}</span> : null

  // 为 secret 类型字段加锁图标
  const prefix = field.secret ? <KeyOutlined style={{ color: '#bbb' }} /> : undefined

  return (
    <Form.Item key={field.key} name={field.key} label={field.label} rules={rules} extra={extra}>
      {field.type === 'password'
        ? <Input.Password placeholder={field.placeholder} prefix={prefix} />
        : field.type === 'textarea'
          ? <Input.TextArea placeholder={field.placeholder} rows={3} />
          : <Input placeholder={field.placeholder} />}
    </Form.Item>
  )
}

// ─── 元信息搜索源 Tab ────────────────────────────────────────
const MetaSourceTab = ({ refreshKey }) => {
  const [loading, setLoading] = useState(false)
  const [sources, setSources] = useState([])
  const [editOpen, setEditOpen] = useState(false)
  const [editingRecord, setEditingRecord] = useState(null)
  const [testing, setTesting] = useState('')
  const [form] = Form.useForm()
  // 连接状态: { sourceKey: 'ok' | 'error' | 'checking' | 'unknown' }
  const [healthMap, setHealthMap] = useState({})
  const [bgmAuth, setBgmAuth] = useState({})
  const [bgmMode, setBgmMode] = useState('token') // 'token' | 'oauth'
  const oauthPopupRef = useRef(null)

  const discover = useCallback(async () => {
    setLoading(true)
    try {
      const { data } = await systemApi.discoverSources()
      const list = data.sources || []
      setSources(list)
      // 自动并行检测所有源的连接状态
      checkAllHealth(list)
    } catch {
      message.error('发现搜索源失败')
    } finally {
      setLoading(false)
    }
  }, [])

  const checkAllHealth = useCallback((list) => {
    const names = (list || sources).map(s => s.key)
    // 先全部设为 checking
    setHealthMap(prev => {
      const next = { ...prev }
      names.forEach(n => { next[n] = 'checking' })
      return next
    })
    // 并行检测
    names.forEach(async (name) => {
      try {
        const { data } = await systemApi.testSource(name)
        setHealthMap(prev => ({ ...prev, [name]: data.success ? 'ok' : 'error' }))
      } catch {
        setHealthMap(prev => ({ ...prev, [name]: 'error' }))
      }
    })
  }, [sources])

  useEffect(() => { discover() }, [refreshKey, discover])

  // ── BGM OAuth ──
  const loadBgmAuth = useCallback(async () => {
    try {
      const { data } = await systemApi.bgmAuthState()
      setBgmAuth(data || {})
    } catch {}
  }, [])

  useEffect(() => {
    loadBgmAuth()
    const handleMsg = (e) => {
      if (e.data === 'SUCCESS_OAUTH_COMPLETE') {
        if (oauthPopupRef.current) oauthPopupRef.current.close()
        loadBgmAuth()
        discover()
      }
    }
    window.addEventListener('message', handleMsg)
    return () => window.removeEventListener('message', handleMsg)
  }, [loadBgmAuth, discover])

  const handleBgmOAuth = async () => {
    if (oauthPopupRef.current && !oauthPopupRef.current.closed) {
      oauthPopupRef.current.focus()
      return
    }
    try {
      const { data } = await systemApi.bgmAuthUrl({ origin_url: window.location.origin })
      if (data.error) { message.error(data.error); return }
      const w = 600, h = 700
      const left = window.screen.width / 2 - w / 2, top = window.screen.height / 2 - h / 2
      oauthPopupRef.current = window.open(
        data.url, 'BangumiAuth',
        `width=${w},height=${h},top=${top},left=${left},resizable=yes,scrollbars=yes`
      )
      if (!oauthPopupRef.current || oauthPopupRef.current.closed) {
        message.error('弹窗被浏览器拦截，请允许弹窗后重试')
      }
    } catch { message.error('获取授权链接失败') }
  }

  const handleBgmLogout = async () => {
    try {
      await systemApi.bgmLogout()
      setBgmAuth({})
      discover()
      message.success('已注销 Bangumi 授权')
    } catch { message.error('注销失败') }
  }

  const handleToggle = async (record, enabled) => {
    setSources(prev => prev.map(s => s.key === record.key ? { ...s, enabled } : s))
    try {
      await systemApi.saveSource({ name: record.key, enabled, values: record.values || {} })
    } catch { message.error('保存失败') }
  }

  const openEdit = (record) => {
    setEditingRecord(record)
    form.resetFields()
    form.setFieldsValue(record.values || {})
    // BGM: 根据已有配置自动选择模式
    if (record.key === 'bangumi') {
      const v = record.values || {}
      setBgmMode(v.client_id ? 'oauth' : 'token')
    }
    setEditOpen(true)
  }

  const handleEditOk = async () => {
    const values = await form.validateFields()
    const name = editingRecord.key
    setSources(prev => prev.map(s => s.key === name ? { ...s, values } : s))
    try {
      await systemApi.saveSource({ name, enabled: editingRecord.enabled, values })
      message.success('已保存')
      // 保存后重新检测该源
      setTimeout(() => handleTest(name), 500)
    } catch { message.error('保存失败') }
    setEditOpen(false)
  }

  const handleTest = async (name) => {
    setTesting(name)
    setHealthMap(prev => ({ ...prev, [name]: 'checking' }))
    try {
      const { data } = await systemApi.testSource(name)
      setHealthMap(prev => ({ ...prev, [name]: data.success ? 'ok' : 'error' }))
      if (data.success) {
        message.success(`${name}: ${data.message}`)
      } else {
        message.error(`${name}: ${data.message}`)
      }
    } catch {
      setHealthMap(prev => ({ ...prev, [name]: 'error' }))
      message.error(`${name}: 连接测试失败`)
    } finally {
      setTesting('')
    }
  }

  const info = editingRecord ? (SOURCE_INFO[editingRecord.key] || {}) : {}

  return (
    <>
      <Alert type="info" showIcon style={{ marginBottom: 16 }}
        message="以下搜索源由系统自动发现，启用后可用于元信息刮削。点击配置可设置 API Key 等参数。" />
      <Spin spinning={loading}>
        <Space direction="vertical" style={{ width: '100%' }} size={12}>
          {sources.map(source => {
            const si = SOURCE_INFO[source.key] || {}
            const hasSecret = (source.fields || []).some(f => f.secret || f.type === 'password')
            const configured = hasSecret
              ? (source.fields || []).filter(f => f.secret || f.type === 'password').some(f => (source.values || {})[f.key])
              : true
            // 左侧边框颜色 = 连接状态
            const health = healthMap[source.key] || 'unknown'
            const borderColor = health === 'ok' ? '#52c41a'
              : health === 'error' ? '#ff4d4f'
              : health === 'checking' ? '#faad14'
              : '#d9d9d9'
            return (
              <Card key={source.key} size="small"
                style={{ borderLeft: `3px solid ${borderColor}`, transition: 'border-color 0.3s' }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                    <Text strong style={{ fontSize: 15 }}>{si.name || source.name}</Text>
                    {source.enabled
                      ? <Tag color="success">已启用</Tag>
                      : <Tag>未启用</Tag>}
                    {configured
                      ? <Tag icon={<CheckCircleOutlined />} color="blue">已配置</Tag>
                      : <Tag icon={<CloseCircleOutlined />} color="default">未配置</Tag>}
                  </div>
                  <Space>
                    <Tooltip title="测试连接">
                      <Button size="small" icon={<ExperimentOutlined />}
                        loading={testing === source.key}
                        onClick={() => handleTest(source.key)} />
                    </Tooltip>
                    <Tooltip title="编辑配置">
                      <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(source)} />
                    </Tooltip>
                    <Switch size="small" checked={source.enabled}
                      onChange={(checked) => handleToggle(source, checked)} />
                  </Space>
                </div>
                <Paragraph type="secondary" style={{ margin: '8px 0 0', fontSize: 12 }}>
                  {si.desc || ''}
                  {(si.links || []).map(link => (
                    <span key={link.url}> <a href={link.url} target="_blank" rel="noopener noreferrer">
                      <LinkOutlined /> {link.label}
                    </a></span>
                  ))}
                </Paragraph>
              </Card>
            )
          })}
          {sources.length === 0 && !loading && (
            <div style={{ textAlign: 'center', padding: 40, color: '#999' }}>未发现可用搜索源</div>
          )}
        </Space>
      </Spin>
      <Modal
        title={`配置: ${info.name || editingRecord?.name}`}
        open={editOpen} onOk={handleEditOk} onCancel={() => setEditOpen(false)} destroyOnClose
        width={600}
      >
        {info.desc && (
          <Alert type="info" showIcon style={{ marginBottom: 16 }}
            message={info.name || editingRecord?.name}
            description={<>
              {info.desc}
              {(info.links || []).map(link => (
                <span key={link.url}> <a href={link.url} target="_blank" rel="noopener noreferrer">
                  <LinkOutlined /> {link.label}
                </a></span>
              ))}
            </>}
          />
        )}
        <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
          {/* BGM: 按模式分别渲染字段 */}
          {editingRecord?.key === 'bangumi' ? (
            <>
              <Form.Item label="认证方式" style={{ marginBottom: 16 }}>
                <Switch
                  checkedChildren="OAuth 授权"
                  unCheckedChildren="Access Token"
                  checked={bgmMode === 'oauth'}
                  onChange={(checked) => setBgmMode(checked ? 'oauth' : 'token')}
                />
              </Form.Item>

              {bgmMode === 'token' && (
                (editingRecord.fields || [])
                  .filter(f => f.key === 'access_token' || f.key === 'api_url')
                  .map(f => <DynamicField key={f.key} field={f} />)
              )}

              {bgmMode === 'oauth' && (
                <>
                  {(editingRecord.fields || [])
                    .filter(f => f.key === 'client_id' || f.key === 'client_secret' || f.key === 'api_url')
                    .map(f => <DynamicField key={f.key} field={f} />)}

                  <Divider style={{ margin: '12px 0' }}>授权状态</Divider>
                  {bgmAuth.isAuthenticated ? (
                    <Card size="small" style={{ marginBottom: 12 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                        {bgmAuth.avatarUrl && (
                          <img src={bgmAuth.avatarUrl} alt="" style={{ width: 48, height: 48, borderRadius: '50%', objectFit: 'cover' }}
                            onError={e => { e.target.style.display = 'none' }} />
                        )}
                        <div style={{ flex: 1 }}>
                          <div><Text strong>{bgmAuth.nickname}</Text></div>
                          {bgmAuth.username && (
                            <a href={`https://bgm.tv/user/${bgmAuth.username}`} target="_blank" rel="noopener noreferrer"
                              style={{ fontSize: 12 }}>@{bgmAuth.username}</a>
                          )}
                        </div>
                        <Tag color="success">已授权</Tag>
                      </div>
                      {bgmAuth.sign && <div style={{ fontSize: 12, color: '#888', marginTop: 8, borderTop: '1px solid #f0f0f0', paddingTop: 8 }}>{bgmAuth.sign}</div>}
                      <div style={{ marginTop: 8 }}>
                        <Button size="small" danger icon={<LogoutOutlined />} onClick={handleBgmLogout}>注销授权</Button>
                      </div>
                    </Card>
                  ) : (
                    <div style={{ textAlign: 'center', padding: '16px 0' }}>
                      <div style={{ marginBottom: 12, color: '#888' }}>当前未通过 OAuth 授权</div>
                      <Button type="primary" icon={<LoginOutlined />} onClick={handleBgmOAuth}>
                        通过 Bangumi 登录
                      </Button>
                      <div style={{ fontSize: 12, color: '#999', marginTop: 8 }}>需要先填写 App ID 和 App Secret 并保存后，再点击授权</div>
                    </div>
                  )}
                </>
              )}
            </>
          ) : (
            /* 其他源: 通用渲染所有字段 */
            (editingRecord?.fields || []).map(f => <DynamicField key={f.key} field={f} />)
          )}
        </Form>
      </Modal>
    </>
  )
}

// ─── 页面主体 ────────────────────────────────────────────────
export const SearchSource = () => {
  const [refreshKey, setRefreshKey] = useState(0)
  const [discovering, setDiscovering] = useState(false)

  const handleDiscover = () => {
    setDiscovering(true)
    setTimeout(() => { setRefreshKey(k => k + 1); setDiscovering(false) }, 300)
  }

  const tabItems = [
    {
      key: 'meta',
      label: <Space><SearchOutlined />元信息搜索源</Space>,
      children: <MetaSourceTab refreshKey={refreshKey} />,
    },
  ]

  return (
    <Card title="搜索源配置"
      extra={<Button icon={<ReloadOutlined />} loading={discovering} onClick={handleDiscover}>重新发现</Button>}>
      <Tabs items={tabItems} />
    </Card>
  )
}

export default SearchSource