// src/pages/logs/index.jsx
// 任务中心

import { useEffect, useState } from 'react'
import { Card, Table, Select, Button, Space, Tag } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import { useTranslation } from 'react-i18next'
import { systemApi } from '@/apis'

const moduleColors = {
  proxy: 'blue',
  strm: 'green',
  storage: 'purple',
  p115: 'orange',
  system: 'default',
}

export const Tasks = () => {
  const { t } = useTranslation()
  const [data, setData] = useState([])
  const [loading, setLoading] = useState(false)
  const [module, setModule] = useState('')
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20, total: 0 })

  const fetchData = async (page = 1, size = 20) => {
    setLoading(true)
    try {
      const params = { page, size }
      if (module) params.module = module
      const { data: res } = await systemApi.getLogs(params)
      setData(res.items || [])
      setPagination({ current: res.page, pageSize: res.size, total: res.total })
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchData() }, [module])

  const columns = [
    { title: 'ID', dataIndex: 'id', width: 60 },
    {
      title: t('tasks.module'), dataIndex: 'module', width: 100,
      render: (v) => <Tag color={moduleColors[v] || 'default'}>{v}</Tag>,
    },
    { title: t('tasks.action'), dataIndex: 'action', width: 120 },
    { title: t('tasks.detail'), dataIndex: 'detail', ellipsis: true },
    { title: t('tasks.ip'), dataIndex: 'ip_address', width: 130 },
    { title: t('tasks.time'), dataIndex: 'created_at', width: 160 },
  ]

  return (
    <Card
      title={t('tasks.title')}
      extra={
        <Space>
          <Select
            value={module}
            onChange={setModule}
            style={{ width: 140 }}
            allowClear
            placeholder={t('tasks.allModules')}
            options={[
              { value: 'proxy',   label: t('tasks.proxy') },
              { value: 'strm',    label: t('tasks.strmModule') },
              { value: 'storage', label: t('tasks.storageModule') },
              { value: 'p115',    label: t('tasks.p115Module') },
              { value: 'system',  label: t('tasks.system') },
            ]}
          />
          <Button icon={<ReloadOutlined />} onClick={() => fetchData()}>
            {t('common.refresh')}
          </Button>
        </Space>
      }
    >
      <Table
        rowKey="id"
        columns={columns}
        dataSource={data}
        loading={loading}
        scroll={{ x: 800 }}
        pagination={{
          ...pagination,
          onChange: (p, s) => fetchData(p, s),
          showTotal: (total) => `${t('common.total')} ${total}`,
        }}
      />
    </Card>
  )
}


export default Tasks
