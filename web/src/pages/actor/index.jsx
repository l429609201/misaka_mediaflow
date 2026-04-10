// web/src/pages/actor/index.jsx
// 演员管理页面 — 头像+搜索+分页+编辑+批量删除+中文化
import { useState, useCallback, useEffect } from 'react'
import {
  Card, Table, Button, Space, Typography, Tag, Tabs, Empty, Avatar, Input,
  Popconfirm, message, Statistic, Row, Col, Modal, Form, Tooltip,
} from 'antd'
import {
  TeamOutlined, SearchOutlined, DeleteOutlined, TranslationOutlined,
  ReloadOutlined, ExclamationCircleOutlined, UserDeleteOutlined, EditOutlined, UserOutlined,
} from '@ant-design/icons'
import { useTranslation } from 'react-i18next'
import { actorApi } from '@/apis/index.js'

const { Title, Text } = Typography

const ActorPage = () => {
  const { t } = useTranslation()
  const [activeTab, setActiveTab] = useState('overview')
  const [persons, setPersons] = useState([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(50)
  const [search, setSearch] = useState('')
  const [orphans, setOrphans] = useState([])
  const [ghosts, setGhosts] = useState([])
  const [loading, setLoading] = useState({})
  const [selectedKeys, setSelectedKeys] = useState([])
  const [translateResult, setTranslateResult] = useState(null)
  // 编辑弹窗
  const [editOpen, setEditOpen] = useState(false)
  const [editPerson, setEditPerson] = useState(null)
  const [editForm] = Form.useForm()

  const setL = (k, v) => setLoading(p => ({ ...p, [k]: v }))

  const fetchPersons = useCallback(async (p, s, q) => {
    setL('persons', true)
    try {
      const { data } = await actorApi.listPersons({ page: p || page, size: s || pageSize, search: q ?? search })
      setPersons(data?.items || [])
      setTotal(data?.total || 0)
    } catch { message.error(t('common.failed')) }
    finally { setL('persons', false) }
  }, [page, pageSize, search, t])

  useEffect(() => { fetchPersons() }, [fetchPersons])

  const handleSearch = (val) => {
    setSearch(val); setPage(1)
    fetchPersons(1, pageSize, val)
  }

  const handlePageChange = (p, s) => {
    setPage(p); setPageSize(s)
    fetchPersons(p, s, search)
  }

  // 编辑
  const openEdit = (record) => {
    setEditPerson(record)
    editForm.setFieldsValue({
      name: record.name,
      tmdb_id: record.provider_ids?.Tmdb || '',
      imdb_id: record.provider_ids?.Imdb || '',
    })
    setEditOpen(true)
  }

  const handleEditSave = async () => {
    if (!editPerson) return
    try {
      const values = await editForm.validateFields()
      const providerIds = {}
      if (values.tmdb_id) providerIds.Tmdb = values.tmdb_id
      if (values.imdb_id) providerIds.Imdb = values.imdb_id
      await actorApi.updatePerson(editPerson.id, { name: values.name, provider_ids: providerIds })
      message.success(t('common.success'))
      setEditOpen(false)
      fetchPersons()
    } catch { message.error(t('common.failed')) }
  }

  // 批量删除
  const handleBatchDelete = async (ids) => {
    try {
      const { data } = await actorApi.batchDelete(ids)
      message.success(t('actor.batchDeleteDone', { count: data?.deleted || 0 }))
      setSelectedKeys([])
      fetchPersons()
    } catch { message.error(t('common.failed')) }
  }

  const handleTranslate = async () => {
    setL('translate', true)
    try {
      const { data } = await actorApi.translate(200)
      setTranslateResult(data)
      data?.success ? message.success(t('actor.translateDone')) : message.warning(data?.message)
    } catch { message.error(t('common.failed')) }
    finally { setL('translate', false) }
  }

  const fetchOrphans = async () => {
    setL('orphans', true)
    try { const { data } = await actorApi.findOrphans(); setOrphans(data?.items || []) }
    catch { message.error(t('common.failed')) }
    finally { setL('orphans', false) }
  }

  const fetchGhosts = async () => {
    setL('ghosts', true)
    try { const { data } = await actorApi.findGhosts(100); setGhosts(data?.items || []) }
    catch { message.error(t('common.failed')) }
    finally { setL('ghosts', false) }
  }

  // 表格列
  const cols = [
    { title: '', dataIndex: 'image_url', width: 50, render: (v) =>
      v ? <Avatar src={v} size={40} shape="square" /> : <Avatar icon={<UserOutlined />} size={40} shape="square" /> },
    { title: t('actor.colName', '演员名'), dataIndex: 'name', width: 180, ellipsis: true,
      render: (v) => <Text strong>{v}</Text> },
    { title: 'TMDB', dataIndex: 'provider_ids', width: 100,
      render: v => v?.Tmdb ? <Tag color="blue">{v.Tmdb}</Tag> : <Text type="secondary">-</Text> },
    { title: t('common.action'), key: 'action', width: 100, fixed: 'right',
      render: (_, r) => (
        <Space size={4}>
          <Tooltip title={t('common.edit')}><Button type="text" size="small" icon={<EditOutlined />} onClick={() => openEdit(r)} /></Tooltip>
          <Popconfirm title={t('actor.confirmDelete', '删除此演员？')} onConfirm={async () => {
            await actorApi.deletePerson(r.id); message.success(t('common.success')); fetchPersons()
          }}><Button type="text" danger size="small" icon={<DeleteOutlined />} /></Popconfirm>
        </Space>
      ),
    },
  ]

  // 简化列（用于 orphan/ghost tab）
  const simpleCols = [
    { title: '', dataIndex: 'image_url', width: 50, render: (v) =>
      v ? <Avatar src={v} size={36} shape="square" /> : <Avatar icon={<UserOutlined />} size={36} shape="square" /> },
    { title: t('actor.colName', '演员名'), dataIndex: 'name', ellipsis: true },
    { title: 'TMDB', dataIndex: 'provider_ids', width: 100, render: v => v?.Tmdb || '-' },
  ]

  return (
    <div style={{ padding: 24 }}>
      <Title level={4} style={{ marginBottom: 16 }}>{t('actor.title', '演员管理')}</Title>
      <Tabs activeKey={activeTab} onChange={setActiveTab} items={[
        { key: 'overview', label: <Space><TeamOutlined />{t('actor.tabOverview', '总览')}</Space>, children: (
          <div>
            <Card size="small" style={{ marginBottom: 12 }}>
              <Space wrap>
                <Input.Search placeholder={t('actor.searchPlaceholder', '搜索演员名...')} allowClear
                  style={{ width: 260 }} onSearch={handleSearch} enterButton={<SearchOutlined />} />
                <Button icon={<ReloadOutlined />} onClick={() => fetchPersons()}
                  loading={loading.persons}>{t('common.refresh')}</Button>
                <Text type="secondary">{t('actor.totalCount', { count: total })}</Text>
                {selectedKeys.length > 0 && (
                  <Popconfirm title={t('actor.confirmBatchDelete')} onConfirm={() => handleBatchDelete(selectedKeys)}>
                    <Button danger icon={<DeleteOutlined />}>{t('actor.batchDelete')} ({selectedKeys.length})</Button>
                  </Popconfirm>
                )}
              </Space>
            </Card>
            <Card size="small">
              <Table rowKey="id" columns={cols} dataSource={persons} size="small"
                loading={loading.persons} scroll={{ x: 500 }}
                rowSelection={{ selectedRowKeys: selectedKeys, onChange: setSelectedKeys }}
                pagination={{ current: page, pageSize, total, showSizeChanger: true,
                  showTotal: t => `共 ${t} 条`, onChange: handlePageChange }} />
            </Card>
          </div>
        )},
        { key: 'orphan', label: <Space><UserDeleteOutlined />{t('actor.tabOrphan', '黑户清理')}</Space>, children: (
          <div>
            <Card size="small" style={{ marginBottom: 12 }}>
              <Space direction="vertical">
                <Text>{t('actor.orphanDesc')}</Text>
                <Button type="primary" icon={<SearchOutlined />} onClick={fetchOrphans} loading={loading.orphans}>{t('actor.scanOrphans', '扫描黑户')}</Button>
              </Space>
            </Card>
            {orphans.length > 0 && <Card size="small"><Table rowKey="id" columns={simpleCols} dataSource={orphans} size="small"
              rowSelection={{ selectedRowKeys: selectedKeys, onChange: setSelectedKeys }}
              pagination={{ pageSize: 20 }}
              title={() => selectedKeys.length > 0 ? <Popconfirm title="批量删除?" onConfirm={() => handleBatchDelete(selectedKeys)}>
                <Button danger icon={<DeleteOutlined />}>删除 ({selectedKeys.length})</Button></Popconfirm> : null} /></Card>}
          </div>
        )},
        { key: 'ghost', label: <Space><ExclamationCircleOutlined />{t('actor.tabGhost', '幽灵检测')}</Space>, children: (
          <div>
            <Card size="small" style={{ marginBottom: 12 }}>
              <Space direction="vertical">
                <Text>{t('actor.ghostDesc')}</Text>
                <Button type="primary" icon={<SearchOutlined />} onClick={fetchGhosts} loading={loading.ghosts}>{t('actor.scanGhosts', '扫描幽灵')}</Button>
              </Space>
            </Card>
            {ghosts.length > 0 && <Card size="small"><Table rowKey="id" columns={simpleCols} dataSource={ghosts} size="small"
              rowSelection={{ selectedRowKeys: selectedKeys, onChange: setSelectedKeys }}
              pagination={{ pageSize: 20 }}
              title={() => selectedKeys.length > 0 ? <Popconfirm title="批量删除?" onConfirm={() => handleBatchDelete(selectedKeys)}>
                <Button danger icon={<DeleteOutlined />}>删除 ({selectedKeys.length})</Button></Popconfirm> : null} /></Card>}
          </div>
        )},
        { key: 'translate', label: <Space><TranslationOutlined />{t('actor.tabTranslate', '中文化')}</Space>, children: (
          <div>
            <Card size="small" style={{ marginBottom: 12 }}>
              <Space direction="vertical">
                <Text>{t('actor.translateDesc')}</Text>
                <Button type="primary" icon={<TranslationOutlined />} onClick={handleTranslate} loading={loading.translate}>{t('actor.startTranslate', '开始中文化')}</Button>
              </Space>
            </Card>
            {translateResult && <Card size="small"><Row gutter={16}>
              <Col span={8}><Statistic title={t('actor.translated', '已翻译')} value={translateResult.translated || 0} valueStyle={{ color: '#52c41a' }} /></Col>
              <Col span={8}><Statistic title={t('actor.skippedTr', '跳过')} value={translateResult.skipped || 0} /></Col>
              <Col span={8}><Statistic title={t('actor.errorsTr', '失败')} value={translateResult.errors || 0} valueStyle={{ color: '#ff4d4f' }} /></Col>
            </Row></Card>}
          </div>
        )},
      ]} />

      {/* 编辑弹窗 */}
      <Modal title={t('actor.editTitle', '编辑演员')} open={editOpen} onCancel={() => setEditOpen(false)}
        onOk={handleEditSave} destroyOnClose width={420}>
        {editPerson && (
          <div style={{ textAlign: 'center', marginBottom: 16 }}>
            {editPerson.image_url
              ? <Avatar src={editPerson.image_url} size={80} shape="square" />
              : <Avatar icon={<UserOutlined />} size={80} shape="square" />}
          </div>
        )}
        <Form form={editForm} layout="vertical">
          <Form.Item name="name" label={t('actor.colName', '演员名')} rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="tmdb_id" label="TMDB ID">
            <Input placeholder="12345" />
          </Form.Item>
          <Form.Item name="imdb_id" label="IMDB ID">
            <Input placeholder="nm0000001" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

export default ActorPage
