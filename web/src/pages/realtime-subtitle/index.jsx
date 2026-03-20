import { useCallback, useEffect, useState } from 'react'
import { Alert, Button, Card, Col, Form, Input, Row, Select, Space, Spin, Switch, Typography, message } from 'antd'
import { FontSizeOutlined, SaveOutlined } from '@ant-design/icons'
import { systemApi } from '@/apis'

const { Text } = Typography

const CONFIG_META = {
  font_in_ass_enabled: '启用外置 fontInAss 实时子集化',
  font_in_ass_url: 'fontInAss 服务地址，例如 http://fontinass:8011',
  embedded_sub_enabled: '启用无外挂字幕时的内封字幕提取与缓存',
  embedded_sub_tracks: '优先匹配的字幕轨道关键字列表',
}

const DEFAULTS = {
  font_in_ass_enabled: false,
  font_in_ass_url: '',
  embedded_sub_enabled: false,
  embedded_sub_tracks: [],
}

export const RealtimeSubtitle = () => {
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)

  const fetchConfigs = useCallback(async () => {
    setLoading(true)
    try {
      const { data } = await systemApi.getConfig()
      const items = Array.isArray(data?.items) ? data.items : []
      const map = Object.fromEntries(items.map(item => [item.key, item.value]))
      form.setFieldsValue({
        font_in_ass_enabled: map.font_in_ass_enabled === 'true',
        font_in_ass_url: map.font_in_ass_url || '',
        embedded_sub_enabled: map.embedded_sub_enabled === 'true',
        embedded_sub_tracks: (() => {
          try {
            const parsed = JSON.parse(map.embedded_sub_tracks || '[]')
            return Array.isArray(parsed) ? parsed : []
          } catch {
            return []
          }
        })(),
      })
    } catch {
      form.setFieldsValue(DEFAULTS)
      message.error('加载实时字幕子集化配置失败')
    } finally {
      setLoading(false)
    }
  }, [form])

  useEffect(() => {
    fetchConfigs()
  }, [fetchConfigs])

  const saveOne = async (key, value) => {
    await systemApi.setConfig({ key, value, description: CONFIG_META[key] || key })
  }

  const handleSave = async () => {
    setSaving(true)
    try {
      const values = await form.validateFields()
      await saveOne('font_in_ass_enabled', String(!!values.font_in_ass_enabled))
      await saveOne('font_in_ass_url', (values.font_in_ass_url || '').trim())
      await saveOne('embedded_sub_enabled', String(!!values.embedded_sub_enabled))
      await saveOne('embedded_sub_tracks', JSON.stringify(values.embedded_sub_tracks || []))
      message.success('实时字幕子集化配置已保存')
      fetchConfigs()
    } catch {
      message.error('保存实时字幕子集化配置失败')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div style={{ padding: 24 }}>
      <Spin spinning={loading}>
        <Card
          title={<Space><FontSizeOutlined />实时字幕子集化</Space>}
          extra={<Button type="primary" icon={<SaveOutlined />} loading={saving} onClick={handleSave}>保存</Button>}
        >
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 16 }}
            message="这里用于配置播放时的字幕子集化行为：外挂字幕走外置 fontInAss；无外挂字幕时可选启用内封字幕提取缓存。"
          />
          <Form form={form} layout="vertical" initialValues={DEFAULTS}>
            <Row gutter={[24, 24]}>
              <Col xs={24} lg={12}>
                <Card size="small" title="外置 fontInAss">
                  <Form.Item name="font_in_ass_enabled" label="启用实时子集化" valuePropName="checked">
                    <Switch />
                  </Form.Item>
                  <Form.Item name="font_in_ass_url" label="fontInAss 地址">
                    <Input placeholder="http://fontinass:8011" />
                  </Form.Item>
                  <Text type="secondary">开启后，ASS/SSA/SRT 字幕会优先交给外置 fontInAss 处理。</Text>
                </Card>
              </Col>
              <Col xs={24} lg={12}>
                <Card size="small" title="内封字幕提取缓存">
                  <Form.Item name="embedded_sub_enabled" label="启用内封字幕提取" valuePropName="checked">
                    <Switch />
                  </Form.Item>
                  <Form.Item name="embedded_sub_tracks" label="轨道匹配优先级">
                    <Select mode="tags" tokenSeparators={[',']} placeholder="例如 zh, chi, chs, jpn" open={false} />
                  </Form.Item>
                  <Text type="secondary">默认关闭。开启后仅在没有外挂字幕时触发，按顺序匹配轨道，未匹配则取第一条。</Text>
                </Card>
              </Col>
            </Row>
          </Form>
        </Card>
      </Spin>
    </div>
  )
}

export default RealtimeSubtitle

