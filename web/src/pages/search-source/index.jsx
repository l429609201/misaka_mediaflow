// src/pages/search-source/index.jsx
// 元信息搜索源配置

import { useState } from 'react'
import {
  Card, Table, Button, Form, Input, Select, Switch, Space,
  Tag, Modal, message, Alert, Tooltip,
} from 'antd'
import {
  PlusOutlined, DeleteOutlined, EditOutlined, SearchOutlined,
} from '@ant-design/icons'

const SOURCE_TYPES = [
  { value: 'tmdb', label: 'TMDB' },
  { value: 'tvdb', label: 'TVDB' },
  { value: 'douban', label: '豆瓣' },
  { value: 'bangumi', label: 'Bangumi' },
  { value: 'custom', label: '自定义' },
]

export const SearchSource = () => {
  const [sources, setSources] = useState([
    { key: '1', name: 'TMDB（默认）', type: 'tmdb', api_key: '', base_url: 'https://api.themoviedb.org', enabled: true },
  ])
  const [modalOpen, setModalOpen] = useState(false)
  const [editingKey, setEditingKey] = useState(null)
  const [form] = Form.useForm()

  const openAdd = () => {
    setEditingKey(null)
    form.resetFields()
    form.setFieldsValue({ type: 'tmdb', enabled: true })
    setModalOpen(true)
  }

  const openEdit = (record) => {
    setEditingKey(record.key)
    form.setFieldsValue(record)
    setModalOpen(true)
  }

  const handleOk = () => {
    form.validateFields().then(values => {
      if (editingKey) {
        setSources(prev => prev.map(s => s.key === editingKey ? { ...s, ...values } : s))
        message.success('已更新')
      } else {
        setSources(prev => [...prev, { key: Date.now().toString(), ...values }])
        message.success('已添加')
      }
      setModalOpen(false)
    })
  }

  const handleDelete = (key) => {
    Modal.confirm({
      title: '确认删除该搜索源？',
      onOk: () => {
        setSources(prev => prev.filter(s => s.key !== key))
        message.success('已删除')
      },
    })
  }

  const handleToggle = (key) => {
    setSources(prev => prev.map(s => s.key === key ? { ...s, enabled: !s.enabled } : s))
  }

  const columns = [
    { title: '名称', dataIndex: 'name', key: 'name' },
    {
      title: '类型', dataIndex: 'type', key: 'type',
      render: (v) => {
        const found = SOURCE_TYPES.find(t => t.value === v)
        return <Tag color="blue">{found?.label || v}</Tag>
      },
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
      title: '操作', key: 'action', width: 100,
      render: (_, record) => (
        <Space size="small">
          <Tooltip title="编辑">
            <Button type="text" size="small" icon={<EditOutlined />} onClick={() => openEdit(record)} />
          </Tooltip>
          <Tooltip title="删除">
            <Button danger type="text" size="small" icon={<DeleteOutlined />} onClick={() => handleDelete(record.key)} />
          </Tooltip>
        </Space>
      ),
    },
  ]

  return (
    <Card
      title={<Space><SearchOutlined />搜索源配置</Space>}
      extra={<Button type="primary" icon={<PlusOutlined />} onClick={openAdd}>添加搜索源</Button>}
    >
      <Alert
        type="info" showIcon style={{ marginBottom: 16 }}
        message="搜索源用于元信息刮削，Emby 刮削时将按顺序依次查询已启用的搜索源。"
      />
      <Table
        size="small"
        dataSource={sources}
        columns={columns}
        pagination={false}
        locale={{ emptyText: '暂无搜索源，点击右上角「添加」按钮新增' }}
      />

      <Modal
        title={editingKey ? '编辑搜索源' : '添加搜索源'}
        open={modalOpen}
        onOk={handleOk}
        onCancel={() => setModalOpen(false)}
        destroyOnClose
      >
        <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入名称' }]}>
            <Input placeholder="例如：TMDB（代理）" />
          </Form.Item>
          <Form.Item name="type" label="类型" rules={[{ required: true }]}>
            <Select options={SOURCE_TYPES} />
          </Form.Item>
          <Form.Item name="base_url" label="接口地址">
            <Input placeholder="https://api.themoviedb.org" />
          </Form.Item>
          <Form.Item name="api_key" label="API Key">
            <Input.Password placeholder="留空则使用系统默认" visibilityToggle />
          </Form.Item>
          <Form.Item name="enabled" label="启用" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  )
}

export default SearchSource

