// web/src/pages/gaps/index.jsx
// 缺集管理 — TMDB vs Emby 比对

import { useState } from 'react'
import {
  Card, Button, Space, Row, Col, Typography, Tag, Badge,
  Spin, Empty, Collapse, message, Tooltip, Progress, Image,
} from 'antd'
import {
  AlertOutlined, ScanOutlined, CheckCircleOutlined,
  WarningOutlined, ReloadOutlined,
} from '@ant-design/icons'
import { gapsApi } from '@/apis'

const { Text, Title } = Typography

function MissingBadges({ missing }) {
  // 按季分组显示缺失集数
  const bySeason = {}
  missing.forEach(m => {
    if (!bySeason[m.season]) bySeason[m.season] = []
    bySeason[m.season].push(m.episode)
  })
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 8 }}>
      {Object.entries(bySeason).map(([s, eps]) => (
        <Tooltip key={s} title={`S${s.padStart(2, '0')} 缺 ${eps.length} 集: E${eps.join(', E')}`}>
          <Tag color="red" style={{ cursor: 'help' }}>
            S{s.padStart(2, '0')} 缺 {eps.length} 集
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
            <Badge count={`缺 ${gap.missing_count}`} style={{ backgroundColor: '#ef4444' }} />
          </div>
          <Progress percent={pct} size="small" strokeColor={pct === 100 ? '#52c41a' : '#1677ff'}
            format={() => `${pct}%`} style={{ marginTop: 6 }} />
          <MissingBadges missing={gap.missing} />
        </div>
      </div>
    </Card>
  )
}

export const Gaps = () => {
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)

  const handleScan = async () => {
    setLoading(true)
    try {
      const { data } = await gapsApi.scan()
      if (data?.error) {
        message.error(data.error)
      } else {
        setResult(data)
        message.success(`扫描完成: ${data.total_series} 部剧集, ${data.gaps_count} 部有缺集`)
      }
    } catch {
      message.error('扫描失败')
    } finally {
      setLoading(false)
    }
  }

  const gaps = result?.gaps || []

  return (
    <div style={{ padding: 24 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 }}>
        <Title level={4} style={{ margin: 0 }}>
          <Space><AlertOutlined />缺集管理</Space>
        </Title>
        <Button icon={<ScanOutlined />} type="primary" loading={loading} onClick={handleScan}>
          扫描缺集
        </Button>
      </div>

      {loading && (
        <div style={{ textAlign: 'center', padding: 60 }}>
          <Spin size="large" tip="正在扫描 Emby 库并与 TMDB 比对，请稍候..." />
        </div>
      )}

      {!loading && result && (
        <>
          <Row gutter={[12, 12]} style={{ marginBottom: 20 }}>
            <Col xs={8}>
              <Card size="small" style={{ borderTop: '3px solid #6366f1' }}>
                <Text type="secondary" style={{ fontSize: 11 }}>扫描剧集</Text>
                <div style={{ fontSize: 28, fontWeight: 700, color: '#6366f1' }}>
                  {result.total_series}
                </div>
              </Card>
            </Col>
            <Col xs={8}>
              <Card size="small" style={{ borderTop: '3px solid #ef4444' }}>
                <Text type="secondary" style={{ fontSize: 11 }}>有缺集</Text>
                <div style={{ fontSize: 28, fontWeight: 700, color: '#ef4444' }}>
                  {result.gaps_count}
                </div>
              </Card>
            </Col>
            <Col xs={8}>
              <Card size="small" style={{ borderTop: '3px solid #10b981' }}>
                <Text type="secondary" style={{ fontSize: 11 }}>完整</Text>
                <div style={{ fontSize: 28, fontWeight: 700, color: '#10b981' }}>
                  {result.total_series - result.gaps_count}
                </div>
              </Card>
            </Col>
          </Row>

          {gaps.length > 0 ? (
            <Card title={<Space><WarningOutlined style={{ color: '#ef4444' }} />缺集列表</Space>} size="small">
              {gaps.map(g => <GapCard key={g.tmdb_id} gap={g} />)}
            </Card>
          ) : (
            <Card size="small">
              <Empty
                image={<CheckCircleOutlined style={{ fontSize: 48, color: '#52c41a' }} />}
                description={<Text type="secondary">所有剧集已完整，没有缺集</Text>}
              />
            </Card>
          )}
        </>
      )}

      {!loading && !result && (
        <Card size="small">
          <Empty
            image={<AlertOutlined style={{ fontSize: 48, color: '#d9d9d9' }} />}
            description={<Text type="secondary">点击「扫描缺集」开始比对 Emby 库与 TMDB 数据</Text>}
          />
        </Card>
      )}
    </div>
  )
}

export default Gaps
