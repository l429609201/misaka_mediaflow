// src/components/StorageTreeDrawer.jsx
// 存储源目录树 Modal —— 点击"浏览文件"后弹出，懒加载各级目录+文件

import { useEffect, useState, useCallback } from 'react'
import { Modal, Tree, Spin, Empty, Alert, Typography, Button, Space } from 'antd'
import { FolderOutlined, FolderOpenOutlined, FileOutlined, ReloadOutlined } from '@ant-design/icons'
import { useTranslation } from 'react-i18next'
import { storageApi } from '@/apis'

const { Text } = Typography

/** 格式化文件大小 */
function formatSize(bytes) {
  if (!bytes || bytes <= 0) return ''
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let i = 0
  let size = bytes
  while (size >= 1024 && i < units.length - 1) {
    size /= 1024
    i++
  }
  return `${size.toFixed(i > 0 ? 1 : 0)} ${units[i]}`
}

/** 把后端 items 转成 antd Tree 节点 */
function toTreeNodes(items) {
  return items.map((item) => ({
    key: item.key,
    title: item.is_dir
      ? item.title
      : `${item.title}${item.size ? '  (' + formatSize(item.size) + ')' : ''}`,
    path: item.path,
    isLeaf: item.isLeaf ?? !item.is_dir,
    icon: item.is_dir
      ? ({ expanded }) =>
          expanded
            ? <FolderOpenOutlined style={{ color: '#faad14' }} />
            : <FolderOutlined style={{ color: '#faad14' }} />
      : <FileOutlined style={{ color: '#8c8c8c' }} />,
  }))
}

/** 递归更新某节点的子集（antd Tree loadData 模式） */
function updateTreeData(list, key, children) {
  return list.map((node) => {
    if (node.key === key) return { ...node, children }
    if (node.children) return { ...node, children: updateTreeData(node.children, key, children) }
    return node
  })
}

export default function StorageTreeDrawer({ open, onClose, storage }) {
  const { t } = useTranslation()
  const [treeData, setTreeData] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  /** 加载根目录 */
  const loadRoot = useCallback(async () => {
    if (!storage) return
    setLoading(true)
    setError('')
    setTreeData([])
    try {
      const { data } = await storageApi.browseTree(storage.id, '/')
      setTreeData(toTreeNodes(data.items || []))
    } catch (e) {
      setError(e?.response?.data?.detail || e.message || t('common.failed'))
    } finally {
      setLoading(false)
    }
  }, [storage, t])

  useEffect(() => {
    if (open && storage) loadRoot()
  }, [open, storage, loadRoot])

  /** Tree 懒加载子目录 */
  const onLoadData = async (node) => {
    if (node.children || node.isLeaf) return
    try {
      const { data } = await storageApi.browseTree(storage.id, node.path)
      const children = toTreeNodes(data.items || [])
      if (children.length === 0) {
        setTreeData((prev) =>
          updateTreeData(prev, node.key, []).map((n) =>
            n.key === node.key ? { ...n, isLeaf: true, children: undefined } : n
          )
        )
      } else {
        setTreeData((prev) => updateTreeData(prev, node.key, children))
      }
    } catch {
      // 子目录加载失败：静默
    }
  }

  const title = storage
    ? <Space><FolderOpenOutlined />{storage.name} — {t('storage.browseTree')}</Space>
    : t('storage.browseTree')

  return (
    <Modal
      title={title}
      open={open}
      onCancel={onClose}
      footer={
        <Button icon={<ReloadOutlined />} onClick={loadRoot} loading={loading}>
          {t('common.refresh')}
        </Button>
      }
      width={600}
      styles={{ body: { padding: '12px 16px', maxHeight: '60vh', overflowY: 'auto' } }}
      destroyOnClose
    >
      {error && (
        <Alert type="error" message={error} style={{ marginBottom: 12 }} showIcon />
      )}

      {loading && !treeData.length ? (
        <div style={{ textAlign: 'center', padding: '40px 0' }}>
          <Spin tip={t('common.loading')} />
        </div>
      ) : !loading && !treeData.length && !error ? (
        <Empty description={t('common.noData')} />
      ) : (
        <>
          <Text type="secondary" style={{ display: 'block', marginBottom: 8, fontSize: 12 }}>
            / (Root)
          </Text>
          <Tree
            showIcon
            blockNode
            loadData={onLoadData}
            treeData={treeData}
            style={{ fontSize: 13 }}
          />
        </>
      )}
    </Modal>
  )
}

