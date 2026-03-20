// src/pages/strm/index.jsx
// STRM 管理

import { useEffect, useRef, useState } from 'react'
import { Card, Table, Button, Tag, Tabs, message, Space, Typography, Tooltip, Alert } from 'antd'
import { PlayCircleOutlined, ReloadOutlined, SaveOutlined, CodeOutlined } from '@ant-design/icons'
import { useTranslation } from 'react-i18next'
import { strmApi } from '@/apis'

const { Text } = Typography

const statusColorMap = {
  pending: 'default',
  running: 'processing',
  completed: 'success',
  failed: 'error',
}

const DEFAULT_TEMPLATE =
  '{{ base_url }}?pickcode={{ pickcode }}{% if file_name %}&file_name={{ file_name | urlencode }}{% endif %}'

const PARAMS = [
  { label: '{{ base_url }}',                 insert: '{{ base_url }}',                    desc: '反代服务根地址' },
  { label: '{{ pickcode }}',                 insert: '{{ pickcode }}',                    desc: '115 pickcode' },
  { label: '{{ file_name }}',                insert: '{{ file_name }}',                   desc: '文件名（原始）' },
  { label: 'file_name | urlencode',          insert: '{{ file_name | urlencode }}',       desc: '文件名 URL 编码' },
  { label: '{{ sha1 }}',                     insert: '{{ sha1 }}',                        desc: '文件 SHA1' },
  { label: '{% if file_name %}…{% endif %}', insert: '{% if file_name %}{% endif %}',     desc: '条件块（含文件名时输出）' },
]

// ─── STRM URL 模板 Tab ──────────────────────────────────────
const UrlTemplateTab = () => {
  const [template, setTemplate] = useState('')
  const [saving, setSaving] = useState(false)
  const textareaRef = useRef(null)

  useEffect(() => {
    strmApi.getUrlTemplate()
      .then(({ data }) => setTemplate(data.template || DEFAULT_TEMPLATE))
      .catch(() => setTemplate(DEFAULT_TEMPLATE))
  }, [])

  const insertAtCursor = (snippet) => {
    const el = textareaRef.current
    if (!el) { setTemplate(t => t + snippet); return }
    const start = el.selectionStart ?? template.length
    const end   = el.selectionEnd   ?? template.length
    const next  = template.slice(0, start) + snippet + template.slice(end)
    setTemplate(next)
    requestAnimationFrame(() => {
      el.focus()
      el.setSelectionRange(start + snippet.length, start + snippet.length)
    })
  }

  const handleSave = async () => {
    setSaving(true)
    try {
      await strmApi.saveUrlTemplate(template)
      message.success('模板已保存')
    } catch { message.error('保存失败') }
    finally { setSaving(false) }
  }

  return (
    <div style={{ maxWidth: 820 }}>
      <Alert type="info" showIcon style={{ marginBottom: 16 }}
        message="使用 Jinja2 语法拼接 STRM 文件内容。点击下方参数按钮可将其插入至光标所在位置。" />

      <div style={{ marginBottom: 12 }}>
        <Text type="secondary" style={{ display: 'block', marginBottom: 8 }}>
          <CodeOutlined style={{ marginRight: 4 }} />可选参数（点击插入）
        </Text>
        <Space wrap>
          {PARAMS.map(p => (
            <Tooltip key={p.label} title={p.desc}>
              <Button size="small" onClick={() => insertAtCursor(p.insert)}>{p.label}</Button>
            </Tooltip>
          ))}
        </Space>
      </div>

      <textarea
        ref={textareaRef}
        value={template}
        onChange={e => setTemplate(e.target.value)}
        rows={5}
        spellCheck={false}
        style={{
          width: '100%', padding: '8px 12px', fontFamily: 'monospace', fontSize: 13,
          border: '1px solid #d9d9d9', borderRadius: 6, resize: 'vertical',
          outline: 'none', lineHeight: 1.6, boxSizing: 'border-box',
          background: 'var(--ant-color-bg-container, #fff)',
          color: 'var(--ant-color-text, #000)',
        }}
      />

      <Space style={{ marginTop: 12 }}>
        <Button type="primary" icon={<SaveOutlined />} loading={saving} onClick={handleSave}>
          保存模板
        </Button>
        <Button onClick={() => setTemplate(DEFAULT_TEMPLATE)}>恢复默认</Button>
      </Space>
    </div>
  )
}


// ─── 页面主体 ────────────────────────────────────────────────
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
    } finally { setLoading(false) }
  }

  const fetchFiles = async (page = 1, size = 20) => {
    setFileLoading(true)
    try {
      const { data } = await strmApi.listFiles({ page, size })
      setFiles(data.items || [])
      setFilePagination({ current: data.page, pageSize: data.size, total: data.total })
    } finally { setFileLoading(false) }
  }

  useEffect(() => { fetchTasks() }, [])

  const handleCreateTask = async () => {
    try {
      await strmApi.createTask('manual')
      message.success(t('common.success'))
      fetchTasks()
    } catch { message.error(t('common.failed')) }
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
      key: 'url-template',
      label: 'STRM URL 模板',
      children: <UrlTemplateTab />,
    },
    {
      key: 'tasks',
      label: t('strm.taskList'),
      children: (
        <Table rowKey="id" columns={taskColumns} dataSource={tasks} loading={loading}
          scroll={{ x: 1000 }}
          pagination={{ ...taskPagination, onChange: (p, s) => fetchTasks(p, s), showTotal: (total) => `共 ${total} 条` }}
        />
      ),
    },
    {
      key: 'files',
      label: t('strm.fileList'),
      children: (
        <Table rowKey="id" columns={fileColumns} dataSource={files} loading={fileLoading}
          scroll={{ x: 800 }}
          pagination={{ ...filePagination, onChange: (p, s) => fetchFiles(p, s), showTotal: (total) => `共 ${total} 条` }}
        />
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
