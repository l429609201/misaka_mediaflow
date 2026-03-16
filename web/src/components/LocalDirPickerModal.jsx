// src/components/LocalDirPickerModal.jsx
// 本地文件系统目录选择弹窗

import { useState, useCallback } from 'react'
import { Modal, List, Button, Space, Breadcrumb, Spin, Empty, message } from 'antd'
import { FolderOutlined, ArrowLeftOutlined, HomeOutlined } from '@ant-design/icons'
import { useTranslation } from 'react-i18next'
import axios from 'axios'

const api = axios.create({ baseURL: '/api/v1' })
api.interceptors.request.use((cfg) => {
  const token = localStorage.getItem('token')
  if (token) cfg.headers.Authorization = `Bearer ${token}`
  return cfg
})

const LocalDirPickerModal = ({ open, onClose, onSelect }) => {
  const { t } = useTranslation()
  const [loading, setLoading] = useState(false)
  const [dirs, setDirs] = useState([])
  const [currentPath, setCurrentPath] = useState('')
  const [parentPath, setParentPath] = useState('')
  const [error, setError] = useState('')

  const fetchDir = useCallback(async (path = '') => {
    setLoading(true)
    setError('')
    try {
      const { data } = await api.get('/system/browse-local-dir', { params: { path } })
      if (data.error) {
        setError(data.error)
        setDirs([])
      } else {
        setDirs(data.items || [])
      }
      setCurrentPath(data.path || '')
      setParentPath(data.parent || '')
    } catch {
      message.error(t('common.failed'))
    } finally {
      setLoading(false)
    }
  }, [t])

  const handleOpen = useCallback(() => {
    if (open) fetchDir('')
  }, [open, fetchDir])

  // 弹窗打开时加载根目录
  useState(() => { if (open) fetchDir('') })

  const handleEnter = (item) => {
    fetchDir(item.path)
  }

  const handleGoUp = () => {
    if (parentPath) fetchDir(parentPath)
  }

  const handleGoRoot = () => {
    fetchDir('')
  }

  const handleConfirm = () => {
    if (currentPath) {
      onSelect(currentPath)
      onClose()
    }
  }

  // 路径拆分为面包屑
  const pathParts = currentPath ? currentPath.split('/').filter(Boolean) : []

  return (
    <Modal
      title={t('dirPicker.localTitle', '选择本地目录')}
      open={open}
      onCancel={onClose}
      afterOpenChange={(visible) => visible && fetchDir('')}
      width={560}
      footer={
        <Space>
          <Button onClick={onClose}>{t('common.cancel')}</Button>
          <Button type="primary" disabled={!currentPath} onClick={handleConfirm}>
            {t('dirPicker.confirm', '确认选择')}: {currentPath || '/'}
          </Button>
        </Space>
      }
    >
      {/* 导航栏 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
        <Button size="small" icon={<HomeOutlined />} onClick={handleGoRoot} disabled={!currentPath} />
        <Button size="small" icon={<ArrowLeftOutlined />} onClick={handleGoUp} disabled={!parentPath} />
        <Breadcrumb
          items={[
            { title: <HomeOutlined />, onClick: handleGoRoot, className: 'cursor-pointer' },
            ...pathParts.map((part, i) => ({
              title: part,
              onClick: () => fetchDir('/' + pathParts.slice(0, i + 1).join('/')),
              className: 'cursor-pointer',
            })),
          ]}
        />
      </div>

      {error && <div style={{ color: '#ff4d4f', marginBottom: 8 }}>{error}</div>}

      <Spin spinning={loading}>
        {dirs.length === 0 && !loading ? (
          <Empty description={t('dirPicker.empty', '无子目录')} image={Empty.PRESENTED_IMAGE_SIMPLE} />
        ) : (
          <List
            size="small"
            style={{ maxHeight: 400, overflow: 'auto' }}
            dataSource={dirs}
            renderItem={(item) => (
              <List.Item
                style={{ cursor: 'pointer', padding: '6px 12px' }}
                onClick={() => handleEnter(item)}
              >
                <Space>
                  <FolderOutlined style={{ color: '#faad14' }} />
                  {item.name}
                </Space>
              </List.Item>
            )}
          />
        )}
      </Spin>
    </Modal>
  )
}

export default LocalDirPickerModal

