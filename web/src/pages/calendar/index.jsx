// web/src/pages/calendar/index.jsx
// 追剧日历 — 今日热播 + 库中标记

import { useState, useEffect } from 'react'
import {
  Card, Row, Col, Typography, Tag, Badge, Spin, Empty,
  Space, Button, Image, Rate, Tooltip,
} from 'antd'
import {
  CalendarOutlined, CheckCircleOutlined, CloseCircleOutlined,
  ReloadOutlined, GlobalOutlined,
} from '@ant-design/icons'
import { calendarApi } from '@/apis'

const { Text, Title } = Typography

function ShowCard({ show }) {
  return (
    <Card
      size="small"
      hoverable
      style={{
        borderLeft: `3px solid ${show.in_library ? '#52c41a' : '#d9d9d9'}`,
        height: '100%',
      }}
      cover={show.poster_url ? (
        <Image src={show.poster_url} alt={show.name}
          style={{ height: 120, objectFit: 'cover' }}
          preview={false} fallback="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg'/>" />
      ) : null}
    >
      <div style={{ minHeight: 80 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 4 }}>
          <Text strong style={{ fontSize: 13, lineHeight: 1.3 }} ellipsis={{ tooltip: show.name }}>
            {show.name}
          </Text>
          {show.in_library
            ? <Tag color="success" style={{ fontSize: 10, margin: 0 }}>已入库</Tag>
            : <Tag style={{ fontSize: 10, margin: 0 }}>未入库</Tag>
          }
        </div>
        {show.original_name !== show.name && (
          <Text type="secondary" style={{ fontSize: 10, display: 'block' }} ellipsis>
            {show.original_name}
          </Text>
        )}
        <div style={{ marginTop: 4 }}>
          <Space size={4}>
            <Rate disabled value={show.vote_average / 2} count={5}
              style={{ fontSize: 10 }} allowHalf />
            <Text type="secondary" style={{ fontSize: 10 }}>{show.vote_average?.toFixed(1)}</Text>
          </Space>
        </div>
        {show.origin_country?.length > 0 && (
          <div style={{ marginTop: 2 }}>
            {show.origin_country.map(c => (
              <Tag key={c} style={{ fontSize: 9, padding: '0 4px' }}>{c}</Tag>
            ))}
          </div>
        )}
        {show.overview && (
          <Tooltip title={show.overview}>
            <Text type="secondary" style={{ fontSize: 10, display: 'block', marginTop: 4 }}
              ellipsis={{ rows: 2 }}>
              {show.overview}
            </Text>
          </Tooltip>
        )}
      </div>
    </Card>
  )
}

export const Calendar = () => {
  const [loading, setLoading] = useState(true)
  const [data, setData] = useState(null)

  const fetchData = async () => {
    setLoading(true)
    try {
      const { data: d } = await calendarApi.today()
      setData(d)
    } catch { /* ignore */ }
    finally { setLoading(false) }
  }

  useEffect(() => { fetchData() }, [])

  const shows = data?.shows || []
  const inLib = shows.filter(s => s.in_library)
  const notInLib = shows.filter(s => !s.in_library)

  return (
    <div style={{ padding: 24 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 }}>
        <Title level={4} style={{ margin: 0 }}>
          <Space><CalendarOutlined />追剧日历</Space>
        </Title>
        <Space>
          {data?.date && <Text type="secondary">{data.date}</Text>}
          <Button icon={<ReloadOutlined />} onClick={fetchData} loading={loading}>刷新</Button>
        </Space>
      </div>

      {loading ? (
        <div style={{ textAlign: 'center', padding: 80 }}>
          <Spin size="large" tip="加载中..." />
        </div>
      ) : !data || shows.length === 0 ? (
        <Empty description="暂无数据" />
      ) : (
        <>
          {/* 统计 */}
          <Row gutter={[12, 12]} style={{ marginBottom: 20 }}>
            <Col xs={8}>
              <Card size="small" style={{ borderTop: '3px solid #6366f1', textAlign: 'center' }}>
                <div style={{ fontSize: 28, fontWeight: 700, color: '#6366f1' }}>{shows.length}</div>
                <Text type="secondary" style={{ fontSize: 11 }}>今日更新</Text>
              </Card>
            </Col>
            <Col xs={8}>
              <Card size="small" style={{ borderTop: '3px solid #10b981', textAlign: 'center' }}>
                <div style={{ fontSize: 28, fontWeight: 700, color: '#10b981' }}>{inLib.length}</div>
                <Text type="secondary" style={{ fontSize: 11 }}>
                  <CheckCircleOutlined /> 已入库
                </Text>
              </Card>
            </Col>
            <Col xs={8}>
              <Card size="small" style={{ borderTop: '3px solid #ef4444', textAlign: 'center' }}>
                <div style={{ fontSize: 28, fontWeight: 700, color: '#ef4444' }}>{notInLib.length}</div>
                <Text type="secondary" style={{ fontSize: 11 }}>
                  <CloseCircleOutlined /> 未入库
                </Text>
              </Card>
            </Col>
          </Row>

          {/* 已入库 */}
          {inLib.length > 0 && (
            <Card title={<Space><CheckCircleOutlined style={{ color: '#52c41a' }} />已入库更新 <Badge count={inLib.length} style={{ backgroundColor: '#52c41a' }} /></Space>}
              size="small" style={{ marginBottom: 16 }}>
              <Row gutter={[8, 8]}>
                {inLib.map(s => (
                  <Col xs={12} sm={8} md={6} lg={4} key={s.tmdb_id}>
                    <ShowCard show={s} />
                  </Col>
                ))}
              </Row>
            </Card>
          )}

          {/* 未入库 */}
          {notInLib.length > 0 && (
            <Card title={<Space><GlobalOutlined />未入库热播 <Badge count={notInLib.length} /></Space>}
              size="small">
              <Row gutter={[8, 8]}>
                {notInLib.map(s => (
                  <Col xs={12} sm={8} md={6} lg={4} key={s.tmdb_id}>
                    <ShowCard show={s} />
                  </Col>
                ))}
              </Row>
            </Card>
          )}
        </>
      )}
    </div>
  )
}

export default Calendar
