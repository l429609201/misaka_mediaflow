// src/pages/search-source/index.jsx
// 搜索源配置 — 顶部 Tabs，当前仅含「元信息搜索源」

import { useState, useEffect } from 'react'
import {
  Card, Tabs, Table, Button, Form, Input, Switch, Space,
  Tag, Modal, Spin, Alert, Tooltip, Typography,
} from 'antd'
import { EditOutlined, ReloadOutlined, SearchOutlined } from '@ant-design/icons'

const { Text } = Typography

// ─── 模拟本地发现（后续接后端接口替换） ───────────────────────
const mockDiscover = () =>
  new Promise((resolve) =>
    setTimeout(() =>
      resolve([
        { key: 'tmdb',    name: 'TMDB',    base_url: 'https://api.themoviedb.org', api_key: '', enabled: true,  status: 'ok' },
        { key: 'tvdb',    name: 'TVDB',    base_url: 'https://api4.thetvdb.com',   api_key: '', enabled: false, status: 'ok' },
        { key: 'bangumi', name: 'Bangumi', base_url: 'https://api.bgm.tv',         api_key: '', enabled: false, status: 'ok' },
      ]),
    300,
    ),
  )

// ─── 元信息搜索源 Tab 内容 ──────────────────────────────────
const MetaSourceTab = () => {
  const [loading, setLoading] = useState(false)
  const [sources, setSources] = useState([])
  const [editOpen, setEditOpen] = useState(false)
  const [editingRecord, setEditingRecord] = useState(null)
  const [form] = Form.useForm()

  const discover = async () => {
    setLoading(true)
    try {
      const data = await mockDiscover()
      setSources(data)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { discover() }, [])

  const handleToggle = (key) => {
    setSources(prev => prev.map(s => s.key === key ? { ...s, enabled: !s.enabled } : s))
  }

  const openEdit = (record) => {
    setEditingRecord(record)
    form.setFieldsValue({ base_url: record.base_url, api_key: record.api_key })
    setEditOpen(true)
  }

  const handleEditOk = () => {
    form.validateFields().then(values => {
      setSources(prev => prev.map(s => s.key === editingRecord.key ? { ...s, ...values } : s))
      setEditOpen(false)
    })
  }

  const columns = [
    {
      title: '名称', dataIndex: 'name', key: 'name',
      render: (v, record) => (
        <Space>
          <Text strong>{v}</Text>
          {record.status === 'ok'
            ? <Tag color="success">已发现</Tag>
            : <Tag color="error">不可用</Tag>}
        </Space>
      ),
    },
    { title: '接口地址', dataIndex: 'base_url', key: 'base_url', ellipsis: true },
    {
      title: 'API Key', dataIndex: 'api_key', key: 'api_key',
      render: (v) => v ? <Tag color="green">已配置</Tag> : <Tag color="default">未配置</Tag>,
    },
    {
      title: '启用', dataIndex: 'enabled', key: 'enabled', width: 70,
      render: (v, record) => (
        <Switch size="small" checked={v} onChange={() => handleToggle(record.key)} />
      ),
    },
    {
      title: '操作', key: 'action', width: 70,
      render: (_, record) => (
        <Tooltip title="编辑配置">
          <Button type="text" size="small" icon={<EditOutlined />} onClick={() => openEdit(record)} />
        </Tooltip>
      ),
    },
  ]

  return (
    <>
      <Alert
        type="info" showIcon style={{ marginBottom: 16 }}
        message="以下搜索源由系统本地发现，启用后将按顺序用于元信息刮削。可编辑接口地址与 API Key 以覆盖默认值。"
      />
      <Spin spinning={loading}>
        <Table
          size="small"
          dataSource={sources}
          columns={columns}
          rowKey="key"
          pagination={false}
          locale={{ emptyText: '未发现可用搜索源，请点击右上角「重新发现」' }}
        />
      </Spin>

      <Modal
        title={`编辑 ${editingRecord?.name} 配置`}
        open={editOpen}
        onOk={handleEditOk}
        onCancel={() => setEditOpen(false)}
        destroyOnClose
      >
        <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item name="base_url" label="接口地址">
            <Input placeholder="留空则使用默认地址" />
          </Form.Item>
          <Form.Item name="api_key" label="API Key">
            <Input.Password placeholder="留空则使用系统默认" visibilityToggle />
          </Form.Item>
        </Form>
      </Modal>
    </>
  )
}

// ─── 页面主体 ────────────────────────────────────────────────
export const SearchSource = () => {
  const [discovering, setDiscovering] = useState(false)
  const [refreshKey, setRefreshKey] = useState(0)

  const handleDiscover = () => {
    setDiscovering(true)
    setTimeout(() => { setRefreshKey(k => k + 1); setDiscovering(false) }, 400)
  }

  const tabItems = [
    {
      key: 'meta',
      label: <Space><SearchOutlined />元信息搜索源</Space>,
      children: <MetaSourceTab key={refreshKey} />,
    },
  ]

  return (
    <Card
      title="搜索源配置"
      extra={
        <Button icon={<ReloadOutlined />} loading={discovering} onClick={handleDiscover}>
          重新发现
        </Button>
      }
    >
      <Tabs items={tabItems} />
    </Card>
  )
}

export default SearchSource

