// src/components/DirPickerModal.jsx
// 115 网盘目录选择弹窗 — 树状展开，选择后回传路径

import { useState, useCallback } from 'react'
import { Modal, List, Button, Space, Breadcrumb, Spin, Empty, message } from 'antd'
import { FolderOutlined, ArrowLeftOutlined, HomeOutlined } from '@ant-design/icons'
import { useTranslation } from 'react-i18next'
import { p115Api } from '@/apis'

const DirPickerModal = ({ open, onClose, onSelect }) => {
  const { t } = useTranslation()
  const [loading, setLoading] = useState(false)
  const [dirs, setDirs] = useState([])
  const [breadcrumbs, setBreadcrumbs] = useState([{ cid: '0', name: t('dirPicker.root') }])

  const currentCid = breadcrumbs[breadcrumbs.length - 1]?.cid || '0'
  const currentPath = '/' + breadcrumbs.slice(1).map(b => b.name).join('/')

  const fetchDir = useCallback(async (cid) => {
    setLoading(true)
    try {
      const { data } = await p115Api.browseDirTree(cid)
      if (data.error) {
        message.error(data.error)
        setDirs([])
      } else {
        setDirs(data.items || [])
      }
    } catch {
      message.error(t('common.failed'))
      setDirs([])
    } finally { setLoading(false) }
  }, [t])

  // 打开时加载根目录
  const handleAfterOpen = useCallback((isOpen) => {
    if (isOpen && dirs.length === 0 && breadcrumbs.length === 1) {
      fetchDir('0')
    }
  }, [fetchDir, dirs.length, breadcrumbs.length])

  const handleEnterDir = (item) => {
    setBreadcrumbs(prev => [...prev, { cid: item.file_id, name: item.name }])
    fetchDir(item.file_id)
  }

  const handleGoBack = () => {
    if (breadcrumbs.length <= 1) return
    const newCrumbs = breadcrumbs.slice(0, -1)
    setBreadcrumbs(newCrumbs)
    fetchDir(newCrumbs[newCrumbs.length - 1].cid)
  }

  const handleGoTo = (index) => {
    const newCrumbs = breadcrumbs.slice(0, index + 1)
    setBreadcrumbs(newCrumbs)
    fetchDir(newCrumbs[newCrumbs.length - 1].cid)
  }

  const handleConfirm = () => {
    onSelect(currentPath === '/' ? '/' : currentPath)
    onClose()
  }

  const handleCancel = () => {
    onClose()
  }

  return (
    <Modal
      title={t('dirPicker.title')}
      open={open}
      onCancel={handleCancel}
      afterOpenChange={handleAfterOpen}
      width={560}
      footer={
        <Space>
          <Button onClick={handleCancel}>{t('common.cancel')}</Button>
          <Button type="primary" onClick={handleConfirm}>
            {t('dirPicker.select')}: {currentPath || '/'}
          </Button>
        </Space>
      }
    >
      {/* 面包屑导航 */}
      <div style={{ marginBottom: 12, display: 'flex', alignItems: 'center', gap: 8 }}>
        <Button
          size="small" icon={<ArrowLeftOutlined />}
          disabled={breadcrumbs.length <= 1}
          onClick={handleGoBack}
        />
        <Breadcrumb
          items={breadcrumbs.map((b, i) => ({
            title: i === 0
              ? <a onClick={() => handleGoTo(i)}><HomeOutlined /> {b.name}</a>
              : <a onClick={() => handleGoTo(i)}>{b.name}</a>,
          }))}
        />
      </div>

      {/* 目录列表 */}
      <Spin spinning={loading}>
        {dirs.length === 0 && !loading ? (
          <Empty description={t('dirPicker.empty')} image={Empty.PRESENTED_IMAGE_SIMPLE} />
        ) : (
          <List
            size="small"
            dataSource={dirs}
            style={{ maxHeight: 400, overflow: 'auto' }}
            renderItem={(item) => (
              <List.Item
                style={{ cursor: 'pointer', padding: '8px 12px' }}
                onClick={() => handleEnterDir(item)}
              >
                <Space>
                  <FolderOutlined style={{ color: '#faad14', fontSize: 18 }} />
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

export default DirPickerModal

