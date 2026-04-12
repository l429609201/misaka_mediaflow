// web/src/pages/gaps/index.jsx
// 缺集管理 — TMDB vs Emby 比对

import { useState, useEffect, useCallback } from 'react'
import {
  Card, Button, Space, Row, Col, Typography, Tag, Badge,
  Spin, Empty, Collapse, message, Tooltip, Progress, Image,
} from 'antd'
import {
  AlertOutlined, ScanOutlined, CheckCircleOutlined,
  WarningOutlined, ReloadOutlined,
} from '@ant-design/icons'
import { useTranslation } from 'react-i18next'
import { gapsApi } from '@/apis'

const { Text, Title } = Typography

function MissingBadges({ missing, t }) {
  const bySeason = {}
  missing.forEach(m => {
    if (!bySeason[m.season]) bySeason[m.season] = []
    bySeason[m.season].push(m.episode)
  })
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 8 }}>
      {Object.entries(bySeason).map(([s, eps]) => (
        <Tooltip key={s} title={`S${s.padStart(2, '0')} missing ${eps.length}: E${eps.join(', E')}`}>
          <Tag color="red" style={{ cursor: 'help' }}>
            {t('gaps.seasonMissing', { season: s.padStart(2, '0'), count: eps.length })}
          </Tag>
        </Tooltip>
      ))}
    </div>
  )
}

function GapCard({ gap }) {
  const pct = gap.total_episodes > 0
    ? Math.round((gap.owned_episodes / gap.total_episodes) * 100) : 0

  return (
    <Card size="small" style={{ marginBottom: 12, borderLeft: '3px solid #ef4444' }}>
      <div style={{ display: 'flex', gap: 12 }}>
        {gap.poster_url && (
          <Image src={gap.poster_url} width={60} height={90}
            style={{ borderRadius: 4, objectFit: 'cover', flexShrink: 0 }}
            fallback="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg'/>"
            preview={false} />
        )}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
            <div>
              <Text strong style={{ fontSize: 14 }}>{gap.series_name}</Text>
              <div style={{ fontSize: 11, color: '#888', marginTop: 2 }}>
                TMDB: {gap.tmdb_id} · 共 {gap.total_episodes} 集 · 已有 {gap.owned_episodes} 集
              </div>
            </div>
            <Badge count={`-${gap.missing_count}`} style={{ backgroundColor: '#ef4444' }} />
          </div>
          <Progress percent={pct} size="small" strokeColor={pct === 100 ? '#52c41a' : '#1677ff'}
            format={() => `${pct}%`} style={{ marginTop: 6 }} />
          <MissingBadges missing={gap.missing} t={() => ''} />
        </div>
      </div>
    </Card>
  )
}

export const Gaps = () => {
  const { t } = useTranslation()
  const [loading, setLoading] = useState(false)
  const [scanning, setScanning] = useState(false)
  const [result, setResult] = useState(null)

  // 打开页面时从 DB 读取缓存数据
  const loadFromDB = useCallback(async () => {
    setLoading(true)
    try {
      const { data } = await gapsApi.list()
      if (data && !data.error) {
        setResult(data)
      }
    } catch { /* ignore */ }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { loadFromDB() }, [loadFromDB])

  // 手动触发扫描（后台异步）
  const handleScan = async () => {
    setScanning(true)
    try {
      const { data } = await gapsApi.scan()
      if (data?.error) {
        message.error(data.error)
      } else {
        message.success('缺集扫描已启动，请在任务中心查看进度')
      }
    } catch {
      message.error(t('gaps.scanFail'))
    } finally {
      setScanning(false)
    }
  }

  const gaps = result?.gaps || []

  return (
    <div style={{ padding: 24 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 }}>
        <Title level={4} style={{ margin: 0 }}>
          <Space><AlertOutlined />{t('gaps.title')}</Space>
        </Title>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={loadFromDB} loading={loading}>
            刷新
          </Button>
          <Button icon={<ScanOutlined />} type="primary" loading={scanning} onClick={handleScan}>
            {t('gaps.scan')}
          </Button>
        </Space>
      </div>

      {loading && (
        <div style={{ textAlign: 'center', padding: 60 }}>
          <Spin size="large" />
        </div>
      )}

      {!loading && result && result.synced === false && (
        <Empty description="暂无数据，请先点击「扫描缺集」同步 Emby 数据" style={{ padding: 60 }} />
      )}

      {!loading && result && result.synced !== false && (
        <>
          <Row gutter={[12, 12]} style={{ marginBottom: 20 }}>
            <Col xs={8}>
              <Card size="small" style={{ borderTop: '3px solid #6366f1' }}>
                <Text type="secondary" style={{ fontSize: 11 }}>{t('gaps.totalSeries')}</Text>
                <div style={{ fontSize: 28, fontWeight: 700, color: '#6366f1' }}>
                  {result.total_series}
                </div>
              </Card>
            </Col>
            <Col xs={8}>
              <Card size="small" style={{ borderTop: '3px solid #ef4444' }}>
                <Text type="secondary" style={{ fontSize: 11 }}>{t('gaps.hasGaps')}</Text>
                <div style={{ fontSize: 28, fontWeight: 700, color: '#ef4444' }}>
                  {result.gaps_count}
                </div>
              </Card>
            </Col>
            <Col xs={8}>
              <Card size="small" style={{ borderTop: '3px solid #10b981' }}>
                <Text type="secondary" style={{ fontSize: 11 }}>{t('gaps.complete')}</Text>
                <div style={{ fontSize: 28, fontWeight: 700, color: '#10b981' }}>
                  {result.total_series - result.gaps_count}
                </div>
              </Card>
            </Col>
          </Row>

          {gaps.length > 0 ? (
            <Card title={<Space><WarningOutlined style={{ color: '#ef4444' }} />{t('gaps.gapList')}</Space>} size="small">
              {gaps.map(g => <GapCard key={g.tmdb_id} gap={g} />)}
            </Card>
          ) : (
            <Card size="small">
              <Empty
                image={<CheckCircleOutlined style={{ fontSize: 48, color: '#52c41a' }} />}
                description={<Text type="secondary">{t('gaps.allComplete')}</Text>}
              />
            </Card>
          )}
        </>
      )}

      {!loading && !result && (
        <Card size="small">
          <Empty
            image={<AlertOutlined style={{ fontSize: 48, color: '#d9d9d9' }} />}
            description={<Text type="secondary">{t('gaps.emptyHint')}</Text>}
          />
        </Card>
      )}
    </div>
  )
}

export default Gaps
