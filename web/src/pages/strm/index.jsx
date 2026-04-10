// src/pages/strm/index.jsx
// STRM 管理 - 本地 STRM 文件扫描、清理和维护工具

import { useState } from 'react'
import {
  Card, Button, Space, Alert, Row, Col, Statistic, Typography, message, Divider
} from 'antd'
import {
  ScanOutlined, DeleteOutlined, UnorderedListOutlined,
  FileTextOutlined, CheckCircleOutlined, CloseCircleOutlined,
  WarningOutlined
} from '@ant-design/icons'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { p115StrmApi } from '@/apis'

const { Title, Text } = Typography

// ─── 页面主体 ────────────────────────────────────────────────
export const Strm = () => {
  const { t } = useTranslation()
  const navigate = useNavigate()

  const [localScanLoading, setLocalScanLoading] = useState(false)
  const [localCleanLoading, setLocalCleanLoading] = useState(false)
  const [rescrapeLoading, setRescrapeLoading] = useState(false)
  const [localStrmStats, setLocalStrmStats] = useState(null)

  // ── 扫描本地 STRM ──────────────────────────────────────────────────────
  const handleScanLocalStrm = async () => {
    setLocalScanLoading(true)
    try {
      const r = await p115StrmApi.scanLocalStrm()
      if (r.data?.error) {
        message.error(r.data.error)
      } else {
        setLocalStrmStats(r.data)
        message.success(t('p115.scanFinished'))
      }
    } catch (e) {
      message.error(t('common.failed'))
    } finally {
      setLocalScanLoading(false)
    }
  }

  // ── 清理无效 STRM ──────────────────────────────────────────────────────
  const handleCleanInvalidStrm = async (dryRun = true) => {
    setLocalCleanLoading(true)
    try {
      const r = await p115StrmApi.cleanInvalidStrm({ dry_run: dryRun })
      if (r.data?.error) {
        message.error(r.data.error)
      } else {
        const stats = r.data
        const msg = dryRun
          ? `${t('p115.dryRunClean')}：将删除 ${stats.deleted_strm} 个 STRM、${stats.deleted_nfo} 个 NFO、${stats.deleted_images} 个图片`
          : `${t('p115.cleanFinished')}：已删除 ${stats.deleted_strm} 个 STRM、${stats.deleted_nfo} 个 NFO、${stats.deleted_images} 个图片`
        message.success(msg)
        // 清理后重新扫描
        if (!dryRun) {
          setTimeout(handleScanLocalStrm, 1000)
        }
      }
    } catch (e) {
      message.error(t('common.failed'))
    } finally {
      setLocalCleanLoading(false)
    }
  }

  // ── 补刮削缺失 NFO ─────────────────────────────────────────────────────
  const handleRescrapeNfo = async () => {
    setRescrapeLoading(true)
    try {
      const r = await p115StrmApi.rescrapeNfo()
      if (r.data?.error) {
        message.error(r.data.error)
      } else {
        const stats = r.data
        message.success(`${t('p115.rescrapeFinished')}：缺失 ${stats.missing_nfo}，成功 ${stats.scraped}，失败 ${stats.failed}`)
        setTimeout(handleScanLocalStrm, 1000)
      }
    } catch (e) {
      message.error(t('common.failed'))
    } finally {
      setRescrapeLoading(false)
    }
  }

  return (
    <div style={{ padding: 24 }}>
      <Title level={4} style={{ marginBottom: 16 }}>
        <Space><FileTextOutlined />{t('menu.strm')}</Space>
      </Title>

      {/* 顶部说明 */}
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 24 }}
        message={t('p115.localStrmToolsHint')}
        description={
          <div>
            <div>{t('p115.goTaskCenterHint')}</div>
            <Button
              size="small"
              icon={<UnorderedListOutlined />}
              onClick={() => navigate('/tasks')}
              style={{ marginTop: 8 }}
            >
              {t('p115.goTaskCenter')}
            </Button>
          </div>
        }
      />

      {/* 主操作区 */}
      <Card
        title={<Space><ScanOutlined />本地 STRM 工具</Space>}
        style={{ marginBottom: 24 }}
      >
        <Space wrap size="middle" style={{ marginBottom: 16 }}>
          <Button
            type="primary"
            icon={<ScanOutlined />}
            loading={localScanLoading}
            onClick={handleScanLocalStrm}
            size="large"
          >
            {t('p115.scanLocalStrm')}
          </Button>
          <Button
            icon={<DeleteOutlined />}
            loading={localCleanLoading}
            onClick={() => handleCleanInvalidStrm(true)}
            size="large"
          >
            {t('p115.dryRunClean')}
          </Button>
          <Button
            danger
            icon={<DeleteOutlined />}
            loading={localCleanLoading}
            onClick={() => handleCleanInvalidStrm(false)}
            size="large"
          >
            {t('p115.cleanInvalidStrm')}
          </Button>
          <Button
            icon={<CheckCircleOutlined />}
            loading={rescrapeLoading}
            onClick={handleRescrapeNfo}
            size="large"
          >
            {t('p115.rescrapeNfo')}
          </Button>
        </Space>

        <Alert
          type="warning"
          showIcon
          message="操作说明"
          description={
            <ul style={{ margin: 0, paddingLeft: 20 }}>
              <li><strong>扫描本地 STRM</strong>：统计当前配置路径下的所有 STRM 文件状态</li>
              <li><strong>试运行清理</strong>：预览将要删除的文件，不实际执行删除</li>
              <li><strong>清理无效 STRM</strong>：删除内容为空或明显异常的 STRM 文件及关联的 NFO/图片</li>
              <li><strong>补刮削 NFO</strong>：扫描缺失 NFO 的 STRM 文件并自动补全元数据和图片</li>
            </ul>
          }
        />
      </Card>

      {/* 扫描结果展示 */}
      {localStrmStats && (
        <Card title={<Space><CheckCircleOutlined />扫描结果</Space>}>
          <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
            <Col xs={12} sm={6}>
              <Statistic
                title={t('p115.localStrmTotal')}
                value={localStrmStats.total || 0}
                prefix={<FileTextOutlined />}
              />
            </Col>
            <Col xs={12} sm={6}>
              <Statistic
                title={t('p115.localStrmValid')}
                value={localStrmStats.valid || 0}
                valueStyle={{ color: '#3f8600' }}
                prefix={<CheckCircleOutlined />}
              />
            </Col>
            <Col xs={12} sm={6}>
              <Statistic
                title={t('p115.localStrmInvalid')}
                value={localStrmStats.invalid || 0}
                valueStyle={{ color: '#cf1322' }}
                prefix={<CloseCircleOutlined />}
              />
            </Col>
            <Col xs={12} sm={6}>
              <Statistic
                title={t('p115.localStrmMissingNfo')}
                value={localStrmStats.missing_nfo || 0}
                valueStyle={{ color: '#d48806' }}
                prefix={<WarningOutlined />}
              />
            </Col>
          </Row>

          <Divider />

          <div>
            <Text strong>{t('p115.localStrmScannedPaths')}：</Text>
            <div style={{ marginTop: 12, fontFamily: 'monospace', fontSize: 12, background: '#f5f5f5', padding: 12, borderRadius: 4 }}>
              {(localStrmStats.paths || []).map(p => (
                <div key={p} style={{ padding: '4px 0' }}>📁 {p}</div>
              ))}
            </div>
          </div>
        </Card>
      )}
    </div>
  )
}

export default Strm
