import { useCallback, useEffect, useState } from 'react'
import { Alert, Button, Card, Col, Form, Input, Radio, Row, Select, Space, Spin, Switch, Typography, message } from 'antd'
import { FontSizeOutlined, SaveOutlined } from '@ant-design/icons'
import { systemApi } from '@/apis'

const { Text } = Typography

const DEFAULTS = {
  font_in_ass_enabled: false,
  subtitle_engine: 'external',
  font_in_ass_url: '',
  embedded_sub_enabled: false,
  embedded_sub_tracks: [],
  embedded_sub_include_movies: false,
}

export const RealtimeSubtitle = () => {
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [engine, setEngine] = useState('external')

  const fetchConfigs = useCallback(async () => {
    setLoading(true)
    try {
      const { data } = await systemApi.getConfig()
      const items = Array.isArray(data?.items) ? data.items : []
      const map = Object.fromEntries(items.map(item => [item.key, item.value]))
      const eng = map.subtitle_engine || 'external'
      setEngine(eng)
      form.setFieldsValue({
        font_in_ass_enabled: map.font_in_ass_enabled === 'true',
        subtitle_engine: eng,
        font_in_ass_url: map.font_in_ass_url || '',
        embedded_sub_enabled: map.embedded_sub_enabled === 'true',
        embedded_sub_tracks: (() => {
          try {
            const parsed = JSON.parse(map.embedded_sub_tracks || '[]')
            return Array.isArray(parsed) ? parsed : []
          } catch { return [] }
        })(),
        embedded_sub_include_movies: map.embedded_sub_include_movies === 'true',
      })
    } catch (e) {
      message.error('加载配置失败: ' + (e?.message || '未知错误'))
    } finally {
      setLoading(false)
    }
  }, [form])

  useEffect(() => { fetchConfigs() }, [fetchConfigs])

  const handleSave = async () => {
    let values
    try { values = await form.validateFields() } catch { return }
    setSaving(true)
    try {
      const saveOne = async (key, value) => { await systemApi.setConfig({ key, value }) }
      await saveOne('font_in_ass_enabled', String(!!values.font_in_ass_enabled))
      await saveOne('subtitle_engine', values.subtitle_engine || 'external')
      await saveOne('font_in_ass_url', values.font_in_ass_url || '')
      await saveOne('embedded_sub_enabled', String(!!values.embedded_sub_enabled))
      await saveOne('embedded_sub_tracks', JSON.stringify(values.embedded_sub_tracks || []))
      await saveOne('embedded_sub_include_movies', String(!!values.embedded_sub_include_movies))
      message.success('保存成功')
    } catch (e) {
      message.error('保存失败: ' + (e?.message || '未知错误'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Spin spinning={loading}>
      <Form form={form} layout="vertical" initialValues={DEFAULTS}>
        <Row gutter={[16, 16]}>

          <Col span={24}>
            <Card size="small" title={<><FontSizeOutlined style={{ marginRight: 6 }} />实时字幕字体子集化</>}>
              <Form.Item name="font_in_ass_enabled" label="启用实时字幕子集化" valuePropName="checked">
                <Switch />
              </Form.Item>
              <Text type="secondary">
                播放器请求 ASS/SSA/SRT 字幕时实时拦截，将字体子集化后嵌入字幕，使无字体的设备正确显示字幕。
              </Text>
            </Card>
          </Col>

          <Col span={24}>
            <Card size="small" title="子集化引擎">
              <Form.Item name="subtitle_engine" label="使用引擎">
                <Radio.Group onChange={e => setEngine(e.target.value)}>
                  <Space direction="vertical" style={{ width: '100%' }}>
                    <Radio value="external">
                      <Text strong>外置 fontInAss</Text>
                      <br />
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        转发给独立部署的 fontInAss 服务（需额外容器，镜像 riderlty/fontinass:noproxy）
                      </Text>
                    </Radio>
                    <Radio value="builtin">
                      <Text strong>内置引擎</Text>
                      <br />
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        使用内置 fonttools 处理，无需外部服务；字体放入挂载目录
                        {' '}<Text code style={{ fontSize: 11 }}>/data/config/fonts</Text>
                        {' '}（在线字体自动下载到 downloads 子目录）
                      </Text>
                    </Radio>
                  </Space>
                </Radio.Group>
              </Form.Item>

              {engine === 'external' && (
                <Form.Item
                  name="font_in_ass_url"
                  label="fontInAss 服务地址"
                  rules={[{ required: true, message: '请填写 fontInAss 服务地址' }]}
                >
                  <Input placeholder="http://fontinass:8011" allowClear />
                </Form.Item>
              )}

              {engine === 'builtin' && (
                <Alert
                  type="info"
                  showIcon
                  style={{ marginTop: 8 }}
                  message="字体目录说明"
                  description={
                    <span>
                      将字体文件（.ttf / .otf / .ttc）放入{' '}
                      <Text code>/data/config/fonts</Text>{' '}
                      下（递归扫描，但排除 <Text code>downloads</Text> 子目录）。
                      找不到的字体从 fontInAss 在线字体库自动下载，保存至{' '}
                      <Text code>/data/config/fonts/downloads</Text>。
                    </span>
                  }
                />
              )}
            </Card>
          </Col>

          <Col span={24}>
            <Card size="small" title="内封字幕提取缓存">
              <Form.Item name="embedded_sub_enabled" label="启用内封字幕提取" valuePropName="checked">
                <Switch />
              </Form.Item>
              <Form.Item name="embedded_sub_tracks" label="轨道匹配优先级">
                <Select mode="tags" tokenSeparators={[',']} placeholder="例如 zh, chi, chs, jpn" open={false} />
              </Form.Item>
              <Form.Item name="embedded_sub_include_movies" label="对电影也生效" valuePropName="checked">
                <Switch />
              </Form.Item>
              <Text type="secondary">
                默认只对剧集生效。开启后仅在没有外挂字幕时触发，按顺序匹配轨道，未匹配则取第一条。
              </Text>
            </Card>
          </Col>

        </Row>
        <div style={{ marginTop: 16 }}>
          <Button type="primary" icon={<SaveOutlined />} loading={saving} onClick={handleSave}>
            保存配置
          </Button>
        </div>
      </Form>
    </Spin>
  )
}

