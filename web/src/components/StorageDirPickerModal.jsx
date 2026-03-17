// src/components/StorageDirPickerModal.jsx
// 存储源目录选择弹窗 — 浏览指定存储源（如 CD2、Alist）的目录树

import { useState, useCallback, useEffect } from 'react'
import { Modal, List, Button, Space, Breadcrumb, Spin, Empty, message } from 'antd'
import { FolderOutlined, ArrowLeftOutlined, HomeOutlined } from '@ant-design/icons'
import { useTranslation } from 'react-i18next'
import { storageApi } from '@/apis'

const StorageDirPickerModal = ({ open, onClose, onSelect, storageId }) => {
  const { t } = useTranslation()
  const [loading, setLoading] = useState(false)
  const [dirs, setDirs] = useState([])
  const [currentPath, setCurrentPath] = useState('/')

  const fetchDir = useCallback(async (path = '/') => {
    if (!storageId) return
    setLoading(true)
    try {
      const { data } = await storageApi.browseTree(storageId, path)
      // 只显示目录
      const dirItems = (data.items || []).filter(item => item.is_dir)
      setDirs(dirItems)
      setCurrentPath(data.path || path)
    } catch {
      message.error(t('common.failed'))
      setDirs([])
    } finally { setLoading(false) }
  }, [storageId, t])

  // 弹窗打开时加载根目录
  useEffect(() => {
    if (open && storageId) {
      setCurrentPath('/')
      setDirs([])
      fetchDir('/')
    }
  }, [open, storageId, fetchDir])

  const handleEnterDir = (item) => {
    fetchDir(item.path)
  }

  const handleGoUp = () => {
    if (currentPath === '/' || currentPath === '') return
    const parts = currentPath.split('/').filter(Boolean)
    parts.pop()
    const parentPath = parts.length > 0 ? '/' + parts.join('/') : '/'
    fetchDir(parentPath)
  }

  const handleGoRoot = () => {
    fetchDir('/')
  }

  const handleConfirm = () => {
    onSelect(currentPath || '/')
    onClose()
  }

  // 路径拆分为面包屑
  const pathParts = currentPath ? currentPath.split('/').filter(Boolean) : []

  return (
    <Modal
      title={t('dirPicker.storageTitle', '选择存储目录')}
      open={open}
      onCancel={onClose}
      width={560}
      footer={
        <Space>
          <Button onClick={onClose}>{t('common.cancel')}</Button>
          <Button type="primary" onClick={handleConfirm}>
            {t('dirPicker.confirm', '确认选择')}: {currentPath || '/'}
          </Button>
        </Space>
      }
    >
      {/* 导航栏 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
        <Button size="small" icon={<HomeOutlined />} onClick={handleGoRoot} disabled={currentPath === '/'} />
        <Button size="small" icon={<ArrowLeftOutlined />} onClick={handleGoUp} disabled={currentPath === '/'} />
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
                onClick={() => handleEnterDir(item)}
              >
                <Space>
                  <FolderOutlined style={{ color: '#faad14' }} />
                  {item.title || item.name}
                </Space>
              </List.Item>
            )}
          />
        )}
      </Spin>
    </Modal>
  )
}

export default StorageDirPickerModal

