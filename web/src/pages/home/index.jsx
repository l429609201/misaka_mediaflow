// src/pages/home/index.jsx
// 仪表盘（首页）

import { useEffect, useState } from 'react'
import { Row, Col, Card, Statistic, Descriptions, Spin, Tag } from 'antd'
import {
  PlayCircleOutlined,
  DatabaseOutlined,
  FileTextOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import { useTranslation } from 'react-i18next'
import { systemApi } from '@/apis'

export const Home = () => {
  const { t } = useTranslation()
  const [loading, setLoading] = useState(true)
  const [health, setHealth] = useState({})
  const [dashboard, setDashboard] = useState({})

  useEffect(() => {
    const load = async () => {
      try {
        const [h, d] = await Promise.all([
          systemApi.health(),
          systemApi.getDashboard().catch(() => ({ data: {} })),
        ])
        setHealth(h.data)
        setDashboard(d.data)
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  if (loading) return <Spin size="large" style={{ display: 'block', margin: '120px auto' }} />

  const stats = [
    { title: t('dashboard.mediaCount'),   value: dashboard.media_count || 0,   icon: <PlayCircleOutlined />,   color: '#6366f1' },
    { title: t('dashboard.storageCount'), value: dashboard.storage_count || 0, icon: <DatabaseOutlined />,     color: '#10b981' },
    { title: t('dashboard.strmFiles'),    value: dashboard.strm_count || 0,    icon: <FileTextOutlined />,     color: '#f59e0b' },
    { title: t('dashboard.cacheHits'),    value: dashboard.cache_hits || 0,    icon: <ThunderboltOutlined />,  color: '#ef4444' },
  ]

  return (
    <div>
      {/* 统计卡片 */}
      <Row gutter={[16, 16]}>
        {stats.map((s) => (
          <Col xs={24} sm={12} lg={6} key={s.title}>
            <Card className="stat-card" hoverable>
              <Statistic
                title={s.title}
                value={s.value}
                prefix={<span style={{ color: s.color }}>{s.icon}</span>}
              />
            </Card>
          </Col>
        ))}
      </Row>

      {/* 系统信息 */}
      <Card title={t('dashboard.systemInfo')} style={{ marginTop: 24 }}>
        <Descriptions column={{ xs: 1, sm: 2, lg: 3 }} bordered size="small">
          <Descriptions.Item label={t('dashboard.version')}>
            {health.version || '-'} <Tag color="blue">{health.version_tag || ''}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label={t('dashboard.timezone')}>
            {health.timezone || '-'}
          </Descriptions.Item>
          <Descriptions.Item label={t('common.time')}>
            {health.time || '-'}
          </Descriptions.Item>
        </Descriptions>
      </Card>
    </div>
  )
}


export default Home
