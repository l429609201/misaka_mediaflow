// src/pages/mappings/index.jsx
// 路径映射管理

import { useEffect, useState } from 'react'
import { Card, Table, Button, Modal, Form, Input, InputNumber, Select, Switch, message, Space, Popconfirm, Alert } from 'antd'
import { PlusOutlined, EditOutlined, DeleteOutlined, NodeIndexOutlined } from '@ant-design/icons'
import { useTranslation } from 'react-i18next'
import { mappingApi, storageApi } from '@/apis'

export const Mappings = () => {
  const { t } = useTranslation()
  const [data, setData] = useState([])
  const [storages, setStorages] = useState([])
  const [loading, setLoading] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [editingId, setEditingId] = useState(null)
  const [form] = Form.useForm()

  const fetchData = async () => {
    setLoading(true)
    try {
      const [mapRes, storRes] = await Promise.all([
        mappingApi.list({ page: 1, size: 100 }),
        storageApi.list({ page: 1, size: 100 }),
      ])
      setData(mapRes.data.items || [])
      setStorages(storRes.data.items || [])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchData() }, [])

  const handleSubmit = async () => {
    const values = await form.validateFields()
    if (editingId) {
      await mappingApi.update(editingId, values)
    } else {
      await mappingApi.create(values)
    }
    message.success(t('common.success'))
    setModalOpen(false)
    form.resetFields()
    setEditingId(null)
    fetchData()
  }

  const handleEdit = (record) => {
    setEditingId(record.id)
    form.setFieldsValue(record)
    setModalOpen(true)
  }

  const handleDelete = async (id) => {
    await mappingApi.remove(id)
    message.success(t('common.success'))
    fetchData()
  }

  const handleToggle = async (id) => {
    await mappingApi.toggle(id)
    fetchData()
  }

  const columns = [
    { title: 'ID', dataIndex: 'id', width: 60 },
    {
      title: t('mappings.storageSource'), dataIndex: 'storage_id', width: 140,
      render: (v) => storages.find((s) => s.id === v)?.name || v,
    },
    { title: t('mappings.localPrefix'), dataIndex: 'local_prefix', ellipsis: true },
    { title: t('mappings.cloudPrefix'), dataIndex: 'cloud_prefix', ellipsis: true },
    { title: t('mappings.priority'), dataIndex: 'priority', width: 70 },
    {
      title: t('common.status'), dataIndex: 'is_active', width: 80,
      render: (v, record) => (
        <Switch
          size="small"
          checked={!!v}
          onChange={() => handleToggle(record.id)}
        />
      ),
    },
    {
      title: t('common.action'), width: 100,
      render: (_, record) => (
        <Space>
          <Button size="small" icon={<EditOutlined />} onClick={() => handleEdit(record)} />
          <Popconfirm title={t('mappings.deleteConfirm')} onConfirm={() => handleDelete(record.id)}>
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <Card
      title={<Space><NodeIndexOutlined />{t('mappings.title')}</Space>}
      extra={
        <Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditingId(null); form.resetFields(); setModalOpen(true) }}>
          {t('mappings.addMapping')}
        </Button>
      }
    >
      <Alert
        type="info" showIcon style={{ marginBottom: 16 }}
        message={t('mappings.hint')}
      />
      <Table rowKey="id" columns={columns} dataSource={data} loading={loading} pagination={false} />

      <Modal
        title={editingId ? t('mappings.editMapping') : t('mappings.addMapping')}
        open={modalOpen}
        onOk={handleSubmit}
        onCancel={() => { setModalOpen(false); form.resetFields(); setEditingId(null) }}
        okText={t('common.save')}
        cancelText={t('common.cancel')}
      >
        <Form form={form} layout="vertical" initialValues={{ priority: 0 }}>
          <Form.Item name="storage_id" label={t('mappings.storageSource')} rules={[{ required: true }]}>
            <Select options={storages.map((s) => ({ value: s.id, label: s.name }))} />
          </Form.Item>
          <Form.Item name="local_prefix" label={t('mappings.localPrefix')} rules={[{ required: true }]}
            tooltip={t('mappings.localPrefixHint')}>
            <Input placeholder="/mnt/115" />
          </Form.Item>
          <Form.Item name="cloud_prefix" label={t('mappings.cloudPrefix')} rules={[{ required: true }]}
            tooltip={t('mappings.cloudPrefixHint')}>
            <Input placeholder="/" />
          </Form.Item>
          <Form.Item name="priority" label={t('mappings.priority')} tooltip={t('mappings.priorityHint')}>
            <InputNumber min={0} max={999} style={{ width: '100%' }} />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  )
}


export default Mappings
