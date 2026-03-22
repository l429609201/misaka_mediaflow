// src/pages/storage/index.jsx
// 存储管理 — 卡片布局 + 动态配置表单（字段由后端 /storage/meta 驱动）

import { useEffect, useState } from 'react'
import {
  Row, Col, Card, Button, Modal, Form, Input, Select,
  message, Popconfirm, Tag, Tooltip, Typography, Empty, Spin, Divider, Progress, Alert,
} from 'antd'
import {
  PlusOutlined, EditOutlined, DeleteOutlined, ApiOutlined,
  FolderOpenOutlined, CloudServerOutlined, LinkOutlined, DatabaseOutlined,
} from '@ant-design/icons'
import { useTranslation } from 'react-i18next'
import { storageApi } from '@/apis'
import StorageTreeDrawer from '@/components/StorageTreeDrawer'

const { Text } = Typography
const TYPE_COLOR = { clouddrive2: 'blue', alist: 'green', p115: 'orange' }

// secret 字段回传值为 true（bool）表示已设置但不回传明文
// 提交时如果值仍为 true，后端会保持原值不变
const SECRET_SET = true

export const Storage = () => {
  const { t } = useTranslation()
  const [data, setData]         = useState([])
  const [loading, setLoading]   = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [editingId, setEditingId] = useState(null)
  const [form] = Form.useForm()

  // 字段元信息：{ [type]: [FieldSpec, ...] }
  const [metaMap, setMetaMap]   = useState({})
  // 类型选项列表：[{ value, label }, ...]
  const [typeOptions, setTypeOptions] = useState([])
  // 当前弹窗选中的类型
  const [modalType, setModalType] = useState('')

  const [treeDrawerOpen, setTreeDrawerOpen] = useState(false)
  const [activeStorage, setActiveStorage]   = useState(null)
  const [testingIds, setTestingIds] = useState(new Set())

  // ── 初始化：拉列表 + 拉 meta ──
  useEffect(() => {
    fetchData()
    fetchMeta()
  }, [])

  const fetchData = async () => {
    setLoading(true)
    try {
      const { data: res } = await storageApi.list({ page: 1, size: 100 })
      setData(res.items || [])
    } finally {
      setLoading(false)
    }
  }

  const fetchMeta = async () => {
    try {
      const { data: res } = await storageApi.meta()
      const map = {}
      const opts = []
      for (const t of (res.types || [])) {
        map[t.type] = t.fields
        opts.push({ value: t.type, label: t.label })
      }
      setMetaMap(map)
      setTypeOptions(opts)
      if (opts.length > 0) setModalType(opts[0].value)
    } catch (e) {
      console.error('获取 storage meta 失败', e)
    }
  }

  const openAdd = () => {
    setEditingId(null)
    const defaultType = typeOptions[0]?.value || ''
    setModalType(defaultType)
    form.resetFields()
    const defaults = { type: defaultType, host: '' }
    for (const f of (metaMap[defaultType] || [])) {
      defaults[`config__${f.key}`] = f.default ?? ''
    }
    form.setFieldsValue(defaults)
    setModalOpen(true)
  }

  const handleEdit = (record) => {
    setEditingId(record.id)
    setModalType(record.type)
    form.resetFields()
    const configValues = {}
    for (const f of (metaMap[record.type] || [])) {
      configValues[`config__${f.key}`] = record.config?.[f.key] ?? f.default ?? ''
    }
    form.setFieldsValue({ name: record.name, type: record.type, host: record.host, ...configValues })
    setModalOpen(true)
  }

  const handleTypeChange = (val) => {
    setModalType(val)
    const clear = {}
    for (const f of (metaMap[val] || [])) {
      clear[`config__${f.key}`] = f.default ?? ''
    }
    form.setFieldsValue(clear)
  }

  // select 类型字段变化时强制重渲染（让 show_when 条件生效）
  const [, forceUpdate] = useState(0)
  const handleConfigFieldChange = () => forceUpdate(n => n + 1)

  const handleModalCancel = () => {
    setModalOpen(false)
    form.resetFields()
    setEditingId(null)
  }

  const handleSubmit = async () => {
    const values = await form.validateFields()
    const config = {}
    for (const f of (metaMap[modalType] || [])) {
      config[f.key] = values[`config__${f.key}`] ?? ''
    }
    const payload = { name: values.name, type: values.type, host: values.host, config }

    if (editingId) {
      await storageApi.update(editingId, payload)
    } else {
      await storageApi.create(payload)
    }
    message.success(t('common.success'))
    handleModalCancel()
    fetchData()
  }

  const handleDelete = async (id) => {
    await storageApi.remove(id)
    message.success(t('common.success'))
    fetchData()
  }

  const handleTest = async (record) => {
    setTestingIds(prev => new Set(prev).add(record.id))
    try {
      const { data: res } = await storageApi.test(record.id)
      if (res.success) {
        message.success(`${record.name} 连接成功`)
      } else {
        message.error(`${record.name} 连接失败: ${res.error || '未知错误'}`)
      }
    } catch (e) {
      message.error(`${record.name} 测试失败`)
    } finally {
      setTestingIds(prev => {
        const s = new Set(prev)
        s.delete(record.id)
        return s
      })
    }
  }

  const currentFields = metaMap[modalType] || []

  return (
    <>
      <Card
        title={
          <span>
            <CloudServerOutlined style={{ marginRight: 8 }} />
            {t('storage.title')}
          </span>
        }
        extra={
          <Button type="primary" icon={<PlusOutlined />} onClick={openAdd}>
            {t('storage.addStorage')}
          </Button>
        }
      >
        <Spin spinning={loading}>
          {data.length === 0 ? (
            <Empty description={t('storage.noStorage')} />
          ) : (
            <Row gutter={[16, 16]}>
              {data.map(item => (
                <Col xs={24} sm={12} lg={8} xl={6} key={item.id}>
                  <StorageCard
                    item={item}
                    onEdit={handleEdit}
                    onDelete={handleDelete}
                    onTest={handleTest}
                    onBrowse={(s) => { setActiveStorage(s); setTreeDrawerOpen(true) }}
                    testing={testingIds.has(item.id)}
                    t={t}
                  />
                </Col>
              ))}
            </Row>
          )}
        </Spin>
      </Card>

      {/* ── 新增 / 编辑弹窗 ── */}
      <Modal
        title={editingId ? t('storage.editStorage') : t('storage.addStorage')}
        open={modalOpen}
        onOk={handleSubmit}
        onCancel={handleModalCancel}
        okText={t('common.save')}
        cancelText={t('common.cancel')}
        width={500}
        destroyOnClose
      >
        <Form form={form} layout="vertical" style={{ marginTop: 8 }}>
          <Form.Item name="name" label={t('storage.storageName')} rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="type" label={t('storage.storageType')} rules={[{ required: true }]}>
            <Select options={typeOptions} onChange={handleTypeChange} />
          </Form.Item>
          <Form.Item name="host" label={t('storage.host')}
            rules={modalType === 'p115' ? [] : [{ required: true }]}
            style={modalType === 'p115' ? { display: 'none' } : {}}
          >
            <Input placeholder="http://127.0.0.1:19798" />
          </Form.Item>

          {/* 动态认证/配置字段：由 meta 驱动，支持 show_when 条件显示 */}
          {currentFields.length > 0 && (
            <>
              <Divider style={{ margin: '12px 0' }} />
              {currentFields.map(f => {
                // show_when 条件：检查其他 config 字段的值是否匹配
                if (f.show_when && Object.keys(f.show_when).length > 0) {
                  const visible = Object.entries(f.show_when).every(
                    ([k, v]) => form.getFieldValue(`config__${k}`) === v
                  )
                  if (!visible) return null
                }
                return (
                  <DynamicField
                    key={f.key}
                    field={f}
                    isEditing={!!editingId}
                    onFieldChange={handleConfigFieldChange}
                  />
                )
              })}
            </>
          )}
        </Form>
      </Modal>

      <StorageTreeDrawer
        open={treeDrawerOpen}
        onClose={() => setTreeDrawerOpen(false)}
        storage={activeStorage}
      />
    </>
  )
}


/* ===== DynamicField：根据 FieldSpec 渲染对应输入控件 ===== */
function DynamicField({ field, isEditing, onFieldChange }) {
  const formName = `config__${field.key}`
  const isSecret = field.type === 'password' || field.secret

  const extra = field.hint && field.type !== 'info'
    ? <span style={{ fontSize: 12, color: '#999' }}>{field.hint}</span>
    : null

  // info 类型：只读提示块，不产生表单值
  if (field.type === 'info') {
    return (
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message={field.hint || field.label}
      />
    )
  }

  // select 类型：渲染为下拉选择框
  if (field.type === 'select') {
    return (
      <Form.Item
        name={formName}
        label={field.label}
        rules={field.required ? [{ required: true, message: `请选择${field.label}` }] : []}
        extra={extra}
      >
        <Select
          options={field.options || []}
          onChange={() => onFieldChange?.()}
        />
      </Form.Item>
    )
  }

  return (
    <Form.Item
      name={formName}
      label={field.label}
      rules={field.required ? [{ required: true, message: `请填写${field.label}` }] : []}
      extra={extra}
    >
      {isSecret ? (
        <Form.Item name={formName} noStyle>
          <SecretInput
            placeholder={field.placeholder}
          />
        </Form.Item>
      ) : field.type === 'textarea' ? (
        <Input.TextArea placeholder={field.placeholder} rows={3} />
      ) : (
        <Input placeholder={field.placeholder} />
      )}
    </Form.Item>
  )
}

/* secret 字段输入控件：密码遮罩 + 眼睛切换，编辑时回填真实值 */
function SecretInput({ value, onChange, placeholder }) {
  return (
    <Input.Password
      value={value || ''}
      onChange={(e) => onChange?.(e.target.value)}
      placeholder={placeholder}
      visibilityToggle
    />
  )
}

/* 格式化字节为可读大小 */
function formatBytes(bytes) {
  if (!bytes || bytes <= 0) return '0'
  const units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
  let i = 0
  let size = bytes
  while (size >= 1024 && i < units.length - 1) { size /= 1024; i++ }
  return `${size.toFixed(i > 0 ? 1 : 0)} ${units[i]}`
}

/* ===== StorageCard：单个存储卡片 ===== */
function StorageCard({ item, onEdit, onDelete, onTest, onBrowse, testing, t }) {
  const [space, setSpace] = useState(null)

  useEffect(() => {
    let cancel = false
    storageApi.space(item.id)
      .then(({ data }) => { if (!cancel && data.success) setSpace(data) })
      .catch(() => {})
    return () => { cancel = true }
  }, [item.id])

  const usedPct = space && space.total > 0
    ? Math.round((space.used / space.total) * 100)
    : null

  return (
    <Card
      hoverable
      size="small"
      style={{ height: '100%' }}
      actions={[
        <Tooltip title={t('storage.edit')} key="edit">
          <EditOutlined onClick={() => onEdit(item)} />
        </Tooltip>,
        <Tooltip title={t('storage.testConnection')} key="test">
          <ApiOutlined spin={testing} onClick={() => onTest(item)} />
        </Tooltip>,
        <Tooltip title={t('storage.browseFiles')} key="browse">
          <FolderOpenOutlined onClick={() => onBrowse(item)} />
        </Tooltip>,
        <Popconfirm
          title={t('storage.confirmDelete')}
          onConfirm={() => onDelete(item.id)}
          key="delete"
        >
          <DeleteOutlined style={{ color: '#ff4d4f' }} />
        </Popconfirm>,
      ]}
    >
      <Card.Meta
        title={
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span>{item.name}</span>
            <Tag color={TYPE_COLOR[item.type] || 'default'}>{item.type}</Tag>
          </div>
        }
        description={
          <div style={{ marginTop: 4 }}>
            {/* 地址 + 容量同一行 */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
              <Text style={{ fontSize: 12, color: '#666', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                <LinkOutlined style={{ marginRight: 4 }} />
                {item.host}
              </Text>
              {usedPct !== null && (
                <Text style={{ fontSize: 11, color: '#888', whiteSpace: 'nowrap', marginLeft: 8 }}>
                  <DatabaseOutlined style={{ marginRight: 3 }} />
                  {formatBytes(space.used)} / {formatBytes(space.total)}
                </Text>
              )}
            </div>

            {/* 容量进度条 */}
            {usedPct !== null && (
              <Progress
                percent={usedPct}
                size="small"
                strokeColor={usedPct > 90 ? '#ff4d4f' : usedPct > 70 ? '#faad14' : '#52c41a'}
                format={() => ''}
                style={{ marginBottom: 4 }}
              />
            )}

            {/* 底部：时间 + 启用状态 */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 4 }}>
              <Text type="secondary" style={{ fontSize: 11 }}>
                {item.created_at || '-'}
              </Text>
              <Tag
                color={item.is_active ? 'green' : 'red'}
                style={{ margin: 0, fontSize: 11, lineHeight: '18px' }}
              >
                {item.is_active ? t('storage.enabled') : t('storage.disabled')}
              </Tag>
            </div>
          </div>
        }
      />
    </Card>
  )
}


export default Storage
