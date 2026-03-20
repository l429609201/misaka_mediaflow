// src/pages/search-source/index.jsx
import { useState, useEffect } from 'react'
import { Card, Tabs, Table, Button, Form, Input, Switch, Space, Tag, Modal, Spin, Alert, Tooltip, Typography, message } from 'antd'
import { EditOutlined, ReloadOutlined, SearchOutlined } from '@ant-design/icons'
import { systemApi } from '@/apis'

const { Text } = Typography

// ─── 动态字段渲染（对齐 storage 的 DynamicField 模式） ──────
const DynamicField = ({ field }) => {
  const rules = field.required ? [{ required: true, message: `请输入 ${field.label}` }] : []
  const extra = field.hint ? <span style={{ fontSize: 12, color: '#888' }}>{field.hint}</span> : null

  return (
    <Form.Item key={field.key} name={field.key} label={field.label} rules={rules} extra={extra}>
      {field.type === 'password'
        ? <Input.Password placeholder={field.placeholder} visibilityToggle />
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
  const [form] = Form.useForm()

  const discover = async () => {
    setLoading(true)
    try {
      const { data } = await systemApi.discoverSources()
      setSources(data.sources || [])
    } catch {
      message.error('发现搜索源失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { discover() }, [refreshKey])

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
    setEditOpen(true)
  }

  const handleEditOk = async () => {
    const values = await form.validateFields()
    setSources(prev => prev.map(s => s.key === editingRecord.key ? { ...s, values } : s))
    try {
      await systemApi.saveSource({ name: editingRecord.key, enabled: editingRecord.enabled, values })
      message.success('已保存')
    } catch { message.error('保存失败') }
    setEditOpen(false)
  }

  // 汇总当前已配置字段的摘要，显示在表格里
  const renderSummary = (record) => {
    const fields = record.fields || []
    const values = record.values || {}
    return fields
      .filter(f => f.type !== 'password' && values[f.key])
      .map(f => (
        <Tag key={f.key} color="blue" style={{ marginBottom: 2 }}>
          {f.label}: {values[f.key]}
        </Tag>
      ))
  }

  const columns = [
    {
      title: '名称', dataIndex: 'name', key: 'name', width: 120,
      render: (v, record) => (
        <Space>
          <Text strong>{v}</Text>
          <Tag color="success">已发现</Tag>
        </Space>
      ),
    },
    {
      title: '配置', key: 'summary',
      render: (_, record) => {
        const summary = renderSummary(record)
        return summary.length > 0 ? summary : <Text type="secondary">（使用默认值）</Text>
      },
    },
    {
      title: '启用', dataIndex: 'enabled', key: 'enabled', width: 70,
      render: (v, record) => (
        <Switch size="small" checked={v} onChange={(checked) => handleToggle(record, checked)} />
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
      <Alert type="info" showIcon style={{ marginBottom: 16 }}
        message="以下搜索源由系统本地发现，启用后将按顺序用于元信息刮削。留空的字段将使用内置默认值。" />
      <Spin spinning={loading}>
        <Table size="small" dataSource={sources} columns={columns} rowKey="key"
          pagination={false} locale={{ emptyText: '未发现可用搜索源' }} />
      </Spin>
      <Modal
        title={`编辑 ${editingRecord?.name} 配置`}
        open={editOpen} onOk={handleEditOk} onCancel={() => setEditOpen(false)} destroyOnClose
      >
        <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
          {(editingRecord?.fields || []).map(f => <DynamicField key={f.key} field={f} />)}
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


