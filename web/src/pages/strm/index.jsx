// src/pages/strm/index.jsx
// STRM 管理

import { useEffect, useState } from 'react'
import { Card, Table, Button, Tag, Tabs, message, Space } from 'antd'
import { PlayCircleOutlined, ReloadOutlined } from '@ant-design/icons'
import { useTranslation } from 'react-i18next'
import { strmApi } from '@/apis'

const statusColorMap = {
  pending: 'default',
  running: 'processing',
  completed: 'success',
  failed: 'error',
}

export const Strm = () => {
  const { t } = useTranslation()
  const [tasks, setTasks] = useState([])
  const [files, setFiles] = useState([])
  const [loading, setLoading] = useState(false)
  const [fileLoading, setFileLoading] = useState(false)
  const [taskPagination, setTaskPagination] = useState({ current: 1, pageSize: 20, total: 0 })
  const [filePagination, setFilePagination] = useState({ current: 1, pageSize: 20, total: 0 })

  const fetchTasks = async (page = 1, size = 20) => {
    setLoading(true)
    try {
      const { data } = await strmApi.listTasks({ page, size })
      setTasks(data.items || [])
      setTaskPagination({ current: data.page, pageSize: data.size, total: data.total })
    } finally {
      setLoading(false)
    }
  }

  const fetchFiles = async (page = 1, size = 20) => {
    setFileLoading(true)
    try {
      const { data } = await strmApi.listFiles({ page, size })
      setFiles(data.items || [])
      setFilePagination({ current: data.page, pageSize: data.size, total: data.total })
    } finally {
      setFileLoading(false)
    }
  }

  useEffect(() => { fetchTasks() }, [])

  const handleCreateTask = async () => {
    try {
      await strmApi.createTask('manual')
      message.success(t('common.success'))
      fetchTasks()
    } catch {
      message.error(t('common.failed'))
    }
  }

  const taskColumns = [
    { title: 'ID', dataIndex: 'id', width: 60 },
    { title: t('strm.taskType'), dataIndex: 'task_type', width: 100, render: (v) => t(`strm.${v}`) || v },
    { title: t('strm.taskStatus'), dataIndex: 'status', width: 100, render: (v) => <Tag color={statusColorMap[v]}>{t(`strm.${v}`) || v}</Tag> },
    { title: t('strm.totalItems'), dataIndex: 'total_items', width: 80 },
    { title: t('strm.processed'), dataIndex: 'processed', width: 80 },
    { title: t('strm.created'), dataIndex: 'created_count', width: 80 },
    { title: t('strm.skipped'), dataIndex: 'skipped_count', width: 80 },
    { title: t('strm.errors'), dataIndex: 'error_count', width: 80 },
    { title: t('strm.startTime'), dataIndex: 'started_at', width: 160 },
    { title: t('strm.endTime'), dataIndex: 'finished_at', width: 160 },
  ]

  const fileColumns = [
    { title: 'ID', dataIndex: 'id', width: 60 },
    { title: t('strm.strmPath'), dataIndex: 'strm_path', ellipsis: true },
    { title: t('strm.strmContent'), dataIndex: 'strm_content', ellipsis: true },
    { title: t('strm.strmMode'), dataIndex: 'strm_mode', width: 100 },
    { title: t('common.time'), dataIndex: 'created_at', width: 160 },
  ]

  const tabItems = [
    {
      key: 'tasks', label: t('strm.taskList'),
      children: (
        <Table rowKey="id" columns={taskColumns} dataSource={tasks} loading={loading}
          scroll={{ x: 1000 }} pagination={{ ...taskPagination, onChange: (p, s) => fetchTasks(p, s), showTotal: (total) => `${t('common.total')} ${total}` }} />
      ),
    },
    {
      key: 'files', label: t('strm.fileList'),
      children: (
        <Table rowKey="id" columns={fileColumns} dataSource={files} loading={fileLoading}
          scroll={{ x: 800 }} pagination={{ ...filePagination, onChange: (p, s) => fetchFiles(p, s), showTotal: (total) => `${t('common.total')} ${total}` }} />
      ),
    },
  ]

  return (
    <Card
      title={t('strm.title')}
      extra={
        <Space>
          <Button icon={<ReloadOutlined />} onClick={() => fetchTasks()}>{t('common.refresh')}</Button>
          <Button type="primary" icon={<PlayCircleOutlined />} onClick={handleCreateTask}>
            {t('strm.createTask')}
          </Button>
        </Space>
      }
    >
      <Tabs items={tabItems} onChange={(k) => k === 'files' && fetchFiles()} />
    </Card>
  )
}


export default Strm
