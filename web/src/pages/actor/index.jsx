// web/src/pages/actor/index.jsx
// 演员管理页面 — 黑户清理/幽灵检测/中文化/批量删除
import { useState, useCallback } from 'react'
import {
  Card, Table, Button, Space, Typography, Tag, Tabs, Empty,
  Popconfirm, message, Statistic, Row, Col, Spin, Badge, Tooltip,
} from 'antd'
import {
  TeamOutlined, SearchOutlined, DeleteOutlined, TranslationOutlined,
  ReloadOutlined, ExclamationCircleOutlined, UserDeleteOutlined,
} from '@ant-design/icons'
import { useTranslation } from 'react-i18next'
import { actorApi } from '@/apis/index.js'

const { Title, Text } = Typography

const ActorPage = () => {
  const { t } = useTranslation()
  const [activeTab, setActiveTab] = useState('overview')
  const [persons, setPersons] = useState([])
  const [orphans, setOrphans] = useState([])
  const [ghosts, setGhosts] = useState([])
  const [loading, setLoading] = useState({})
  const [selectedKeys, setSelectedKeys] = useState([])
  const [translateResult, setTranslateResult] = useState(null)

  const setPartialLoading = (key, val) => setLoading(prev => ({ ...prev, [key]: val }))

  const fetchPersons = useCallback(async () => {
    setPartialLoading('persons', true)
    try {
      const { data } = await actorApi.listPersons()
      setPersons(data?.items || [])
    } catch { message.error(t('common.failed')) }
    finally { setPartialLoading('persons', false) }
  }, [t])

  const fetchOrphans = useCallback(async () => {
    setPartialLoading('orphans', true)
    try {
      const { data } = await actorApi.findOrphans()
      setOrphans(data?.items || [])
      message.success(t('actor.scanDone', `发现 ${data?.total || 0} 位黑户演员`))
    } catch { message.error(t('common.failed')) }
    finally { setPartialLoading('orphans', false) }
  }, [t])

  const fetchGhosts = useCallback(async () => {
    setPartialLoading('ghosts', true)
    try {
      const { data } = await actorApi.findGhosts(100)
      setGhosts(data?.items || [])
      message.success(t('actor.ghostDone', `发现 ${data?.total || 0} 位幽灵演员`))
    } catch { message.error(t('common.failed')) }
    finally { setPartialLoading('ghosts', false) }
  }, [t])

  const handleTranslate = async () => {
    setPartialLoading('translate', true)
    try {
      const { data } = await actorApi.translate(200)
      setTranslateResult(data)
      if (data?.success) {
        message.success(t('actor.translateDone', `翻译完成: ${data.translated} 个`))
      } else {
        message.warning(data?.message || t('common.failed'))
      }
    } catch { message.error(t('common.failed')) }
    finally { setPartialLoading('translate', false) }
  }

  const handleBatchDelete = async (ids) => {
    try {
      const { data } = await actorApi.batchDelete(ids)
      message.success(t('actor.batchDeleteDone', `成功删除 ${data?.deleted || 0} 位`))
      setSelectedKeys([])
      fetchPersons()
    } catch { message.error(t('common.failed')) }
  }

  const personColumns = [
    { title: t('actor.colName', '演员名'), dataIndex: 'name', width: 200,
      render: (v, r) => <Space><Badge status={r.has_image ? 'success' : 'default'} /><Text strong>{v}</Text></Space> },
    { title: 'TMDB ID', dataIndex: 'provider_ids', width: 120,
      render: v => v?.Tmdb ? <Tag color="blue">{v.Tmdb}</Tag> : <Tag color="default">-</Tag> },
    { title: 'IMDB ID', dataIndex: 'provider_ids', width: 120,
      render: v => v?.Imdb ? <Tag>{v.Imdb}</Tag> : '-' },
    { title: t('actor.colImage', '头像'), dataIndex: 'has_image', width: 80,
      render: v => v ? <Tag color="green">有</Tag> : <Tag color="red">无</Tag> },
    { title: t('common.action'), key: 'action', width: 80, fixed: 'right',
      render: (_, r) => (
        <Popconfirm title={t('actor.confirmDelete', '确定删除此演员？')} onConfirm={async () => {
          await actorApi.deletePerson(r.id)
          message.success(t('common.success'))
          fetchPersons()
        }}>
          <Button type="text" danger icon={<DeleteOutlined />} size="small" />
        </Popconfirm>
      ),
    },
  ]

  const tabItems = [
    {
      key: 'overview',
      label: <Space><TeamOutlined />{t('actor.tabOverview', '总览')}</Space>,
      children: (
        <div>
          <Card size="small" style={{ marginBottom: 16 }}>
            <Space>
              <Button icon={<ReloadOutlined />} onClick={fetchPersons}
                loading={loading.persons}>{t('actor.loadPersons', '加载演员列表')}</Button>
              <Text type="secondary">{t('actor.totalCount', `共 ${persons.length} 位演员`)}</Text>
            </Space>
          </Card>
          <Card size="small">
            <Table rowKey="id" columns={personColumns} dataSource={persons} size="small"
              loading={loading.persons} scroll={{ x: 800 }}
              rowSelection={{ selectedRowKeys: selectedKeys, onChange: setSelectedKeys }}
              locale={{ emptyText: <Empty description={t('actor.noData', '点击上方按钮加载演员')} /> }}
              pagination={{ pageSize: 20, showSizeChanger: true, showTotal: t => `共 ${t} 条` }}
              title={() => selectedKeys.length > 0 ? (
                <Popconfirm title={t('actor.confirmBatchDelete', `确定删除选中的 ${selectedKeys.length} 位演员？`)}
                  onConfirm={() => handleBatchDelete(selectedKeys)}>
                  <Button danger icon={<DeleteOutlined />}>{t('actor.batchDelete', `批量删除 (${selectedKeys.length})`)}</Button>
                </Popconfirm>
              ) : null}
            />
          </Card>
        </div>
      ),
    },
    {
      key: 'orphan',
      label: <Space><UserDeleteOutlined />{t('actor.tabOrphan', '黑户清理')}</Space>,
      children: (
        <div>
          <Card size="small" style={{ marginBottom: 16 }}>
            <Space direction="vertical">
              <Text>{t('actor.orphanDesc', '黑户演员：在 Emby 中存在但没有关联任何电影或剧集的演员记录。')}</Text>
              <Button type="primary" icon={<SearchOutlined />} onClick={fetchOrphans}
                loading={loading.orphans}>{t('actor.scanOrphans', '扫描黑户演员')}</Button>
            </Space>
          </Card>
          <Card size="small">
            <Table rowKey="id" columns={personColumns} dataSource={orphans} size="small"
              loading={loading.orphans} scroll={{ x: 800 }}
              rowSelection={{ selectedRowKeys: selectedKeys, onChange: setSelectedKeys }}
              locale={{ emptyText: <Empty description={t('actor.orphanEmpty', '点击上方按钮扫描')} /> }}
              pagination={{ pageSize: 20 }}
              title={() => selectedKeys.length > 0 ? (
                <Popconfirm title={`确定删除选中的 ${selectedKeys.length} 位？`}
                  onConfirm={() => handleBatchDelete(selectedKeys)}>
                  <Button danger icon={<DeleteOutlined />}>批量删除 ({selectedKeys.length})</Button>
                </Popconfirm>
              ) : null}
            />
          </Card>
        </div>
      ),
    },
  ]

  return (
    <div style={{ padding: 24 }}>
      <Title level={4} style={{ marginBottom: 16 }}>{t('actor.title', '演员管理')}</Title>
      <Tabs activeKey={activeTab} onChange={setActiveTab} items={[
        ...tabItems,
        {
          key: 'ghost',
          label: <Space><ExclamationCircleOutlined />{t('actor.tabGhost', '幽灵检测')}</Space>,
          children: (
            <div>
              <Card size="small" style={{ marginBottom: 16 }}>
                <Space direction="vertical">
                  <Text>{t('actor.ghostDesc', '幽灵演员：没有 TMDB ID 且在 TMDB 中搜索不到的演员。')}</Text>
                  <Button type="primary" icon={<SearchOutlined />} onClick={fetchGhosts}
                    loading={loading.ghosts}>{t('actor.scanGhosts', '扫描幽灵演员')}</Button>
                </Space>
              </Card>
              <Card size="small">
                <Table rowKey="id" columns={personColumns} dataSource={ghosts} size="small"
                  loading={loading.ghosts} scroll={{ x: 800 }}
                  rowSelection={{ selectedRowKeys: selectedKeys, onChange: setSelectedKeys }}
                  locale={{ emptyText: <Empty description="点击上方按钮扫描" /> }}
                  pagination={{ pageSize: 20 }}
                  title={() => selectedKeys.length > 0 ? (
                    <Popconfirm title={`确定删除选中的 ${selectedKeys.length} 位？`}
                      onConfirm={() => handleBatchDelete(selectedKeys)}>
                      <Button danger icon={<DeleteOutlined />}>批量删除 ({selectedKeys.length})</Button>
                    </Popconfirm>
                  ) : null}
                />
              </Card>
            </div>
          ),
        },
        {
          key: 'translate',
          label: <Space><TranslationOutlined />{t('actor.tabTranslate', '中文化')}</Space>,
          children: (
            <div>
              <Card size="small" style={{ marginBottom: 16 }}>
                <Space direction="vertical">
                  <Text>{t('actor.translateDesc', '通过 TMDB 翻译接口获取演员中文名，并写回 Emby。需要配置 TMDB API Key。')}</Text>
                  <Button type="primary" icon={<TranslationOutlined />} onClick={handleTranslate}
                    loading={loading.translate}>{t('actor.startTranslate', '开始中文化')}</Button>
                </Space>
              </Card>
              {translateResult && (
                <Card size="small">
                  <Row gutter={16}>
                    <Col span={8}><Statistic title={t('actor.translated', '已翻译')} value={translateResult.translated || 0} valueStyle={{ color: '#52c41a' }} /></Col>
                    <Col span={8}><Statistic title={t('actor.skippedTr', '已跳过')} value={translateResult.skipped || 0} /></Col>
                    <Col span={8}><Statistic title={t('actor.errorsTr', '失败')} value={translateResult.errors || 0} valueStyle={{ color: '#ff4d4f' }} /></Col>
                  </Row>
                </Card>
              )}
            </div>
          ),
        },
      ]} />
    </div>
  )
}

export default ActorPage
