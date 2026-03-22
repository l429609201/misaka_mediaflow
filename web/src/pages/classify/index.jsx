// web/src/pages/classify/index.jsx
// 整理分类引擎 — 通用模块
// UI 参考 MP 二级分类样式：大分类卡片（一级）内嵌规则列表（二级）
// 支持图形化 / 代码（JSON）双模式编辑，配置存入 SystemConfig

import { useEffect, useState, useCallback } from 'react'
import {
  Card, Row, Col, Form, Input, Switch, Button, Select,
  Space, Alert, Tooltip, Divider, message, Segmented,
  Badge, Typography, Tag, Empty,
} from 'antd'
import {
  PlusOutlined, DeleteOutlined, SaveOutlined, ReloadOutlined,
  ArrowUpOutlined, ArrowDownOutlined, CodeOutlined, AppstoreOutlined,
  InfoCircleOutlined, FolderOpenOutlined, HolderOutlined,
  CheckCircleFilled, ExclamationCircleFilled,
} from '@ant-design/icons'
import { classifyApi } from '@/apis'
import DirPickerModal from '@/components/DirPickerModal'

const { Text, Title } = Typography
const { TextArea } = Input

// ── 分类颜色池 ────────────────────────────────────────────────────────────────
const CAT_COLORS = [
  '#6366f1', '#10b981', '#f59e0b', '#ef4444',
  '#8b5cf6', '#06b6d4', '#f97316', '#84cc16',
  '#ec4899', '#14b8a6',
]

// ── 规则类型 ─────────────────────────────────────────────────────────────────
const RULE_TYPES = [
  { value: 'keyword',           label: '关键词',      group: 'local' },
  { value: 'regex',             label: '正则',        group: 'local' },
  { value: 'genre_ids',         label: 'TMDB 类型',   group: 'tmdb'  },
  { value: 'origin_country',    label: 'TMDB 产地',   group: 'tmdb'  },
  { value: 'original_language', label: 'TMDB 语言',   group: 'tmdb'  },
]
const TMDB_TYPES  = new Set(['genre_ids', 'origin_country', 'original_language'])
const FIELD_OPTS  = [
  { value: 'filename', label: '文件名' },
  { value: 'dirname',  label: '目录名' },
]
const RULE_PLACEHOLDER = {
  keyword:           '如：动漫、动画、番剧',
  regex:             '如：(?i)(anime|OVA|OAD)',
  genre_ids:         '如：16（动画）、99（纪录片）',
  origin_country:    '如：JP 或 CN,TW,HK',
  original_language: '如：ja、zh、en',
}

const DEFAULT_CONFIG = {
  enabled: true, dry_run: false,
  target_root: '', unrecognized_dir: '',
  categories: [],
}

// ─────────────────────────────────────────────────────────────────────────────
// 二级：规则行
// ─────────────────────────────────────────────────────────────────────────────
const RuleRow = ({ rule, idx, total, onChange, onDelete }) => {
  const isTmdb = TMDB_TYPES.has(rule.type)
  return (
    <Row gutter={6} align="middle" wrap={false} style={{ marginBottom: 6 }}>
      {/* 序号 */}
      <Col style={{ width: 22, color: '#999', fontSize: 11, textAlign: 'center', flexShrink: 0 }}>
        {idx + 1}
      </Col>

      {/* 类型 */}
      <Col style={{ width: 108, flexShrink: 0 }}>
        <Select size="small" style={{ width: '100%' }} value={rule.type}
          onChange={v => onChange({ type: v, field: TMDB_TYPES.has(v) ? undefined : (rule.field || 'filename') })}>
          <Select.OptGroup label="本地匹配">
            {RULE_TYPES.filter(r => r.group === 'local').map(r =>
              <Select.Option key={r.value} value={r.value}>{r.label}</Select.Option>
            )}
          </Select.OptGroup>
          <Select.OptGroup label="TMDB 元数据">
            {RULE_TYPES.filter(r => r.group === 'tmdb').map(r =>
              <Select.Option key={r.value} value={r.value}>{r.label}</Select.Option>
            )}
          </Select.OptGroup>
        </Select>
      </Col>

      {/* 字段（本地规则才显示） */}
      {!isTmdb && (
        <Col style={{ width: 72, flexShrink: 0 }}>
          <Select size="small" style={{ width: '100%' }}
            value={rule.field || 'filename'} options={FIELD_OPTS}
            onChange={v => onChange({ field: v })} />
        </Col>
      )}

      {/* 值 */}
      <Col flex="1">
        <Input size="small" value={rule.value}
          placeholder={RULE_PLACEHOLDER[rule.type] || ''}
          onChange={e => onChange({ value: e.target.value })} />
      </Col>

      {/* 删除 */}
      <Col style={{ flexShrink: 0 }}>
        <Button danger size="small" type="text" icon={<DeleteOutlined />} onClick={onDelete} />
      </Col>
    </Row>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// 一级：分类卡片（MP 风格，带彩色左边框 + 内嵌规则列表）
// ─────────────────────────────────────────────────────────────────────────────
const CategoryCard = ({ cat, idx, total, color, onUpdate, onDelete, onMove }) => {
  const rules     = cat.rules || []
  const isDefault = rules.length === 0

  const updRule = (ri, patch) =>
    onUpdate({ rules: rules.map((r, i) => i === ri ? { ...r, ...patch } : r) })
  const addRule = () =>
    onUpdate({ rules: [...rules, { type: 'keyword', field: 'filename', value: '' }] })
  const delRule = (ri) =>
    onUpdate({ rules: rules.filter((_, i) => i !== ri) })

  return (
    <div style={{
      borderRadius: 10,
      border: '1px solid var(--ant-color-border, #e5e7eb)',
      borderLeft: `4px solid ${color}`,
      marginBottom: 14,
      background: 'var(--ant-color-bg-container, #fff)',
      boxShadow: '0 1px 4px rgba(0,0,0,.06)',
      overflow: 'hidden',
    }}>
      {/* ── 卡片头部 ── */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 10,
        padding: '10px 14px',
        background: 'var(--ant-color-fill-quinary, rgba(0,0,0,.02))',
        borderBottom: '1px solid var(--ant-color-border-secondary, #f0f0f0)',
      }}>
        {/* 序号圆标 */}
        <span style={{
          width: 24, height: 24, borderRadius: '50%', flexShrink: 0,
          background: color, color: '#fff',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 11, fontWeight: 700,
        }}>{idx + 1}</span>

        {/* 分类名 */}
        <Input
          size="small" variant="borderless"
          value={cat.name} placeholder="分类名称（如：动漫）"
          style={{ fontWeight: 600, fontSize: 14, flex: '0 0 130px' }}
          onChange={e => onUpdate({ name: e.target.value })}
        />

        {/* 箭头 */}
        <Text type="secondary" style={{ fontSize: 12, flexShrink: 0 }}>→</Text>

        {/* 目标子目录 */}
        <Input
          size="small" variant="borderless"
          value={cat.target_dir} placeholder="目标子目录（相对于根目录）"
          style={{ flex: 1, fontSize: 13, color: '#666' }}
          onChange={e => onUpdate({ target_dir: e.target.value })}
        />

        {/* 标签 */}
        {isDefault && (
          <Tag color="orange" style={{ flexShrink: 0, fontSize: 11 }}>兜底</Tag>
        )}
        <Tag color="default" style={{ flexShrink: 0, fontSize: 11 }}>
          {rules.length} 条规则
        </Tag>

        {/* 操作按钮 */}
        <Space size={2} style={{ flexShrink: 0 }}>
          <Tooltip title="上移">
            <Button size="small" type="text" icon={<ArrowUpOutlined />}
              disabled={idx === 0} onClick={() => onMove(-1)} />
          </Tooltip>
          <Tooltip title="下移">
            <Button size="small" type="text" icon={<ArrowDownOutlined />}
              disabled={idx === total - 1} onClick={() => onMove(1)} />
          </Tooltip>
          <Tooltip title="删除分类">
            <Button size="small" type="text" danger icon={<DeleteOutlined />}
              onClick={onDelete} />
          </Tooltip>
        </Space>
      </div>

      {/* ── 卡片内容：规则列表（二级） ── */}
      <div style={{ padding: '12px 14px 10px' }}>
        {/* 匹配逻辑切换（多条规则时才显示） */}
        {rules.length > 1 && (
          <div style={{ marginBottom: 10, display: 'flex', alignItems: 'center', gap: 8 }}>
            <Text type="secondary" style={{ fontSize: 12 }}>多规则匹配逻辑：</Text>
            <Switch size="small" checked={cat.match_all}
              checkedChildren="AND 全部满足" unCheckedChildren="OR 满足任一"
              onChange={v => onUpdate({ match_all: v })} />
          </div>
        )}

        {/* 规则列表表头 */}
        {rules.length > 0 && (
          <Row gutter={6} style={{ marginBottom: 4, color: '#999', fontSize: 11 }}>
            <Col style={{ width: 22 }} />
            <Col style={{ width: 108 }}>类型</Col>
            <Col style={{ width: 72 }}>字段</Col>
            <Col flex="1">匹配值</Col>
            <Col style={{ width: 32 }} />
          </Row>
        )}

        {/* 规则行 */}
        {isDefault
          ? (
            <div style={{
              padding: '8px 12px',
              background: 'var(--ant-color-warning-bg, #fffbe6)',
              borderRadius: 6, border: '1px dashed #ffd666',
              fontSize: 12, color: '#ad6800',
            }}>
              ⚡ 无匹配规则 — 此分类作为<b>默认兜底</b>，未被其他分类命中的文件将归入此处
            </div>
          )
          : rules.map((rule, ri) => (
            <RuleRow key={ri} rule={rule} idx={ri} total={rules.length}
              onChange={patch => updRule(ri, patch)}
              onDelete={() => delRule(ri)} />
          ))
        }

        <Button size="small" icon={<PlusOutlined />} onClick={addRule}
          style={{ marginTop: 8, borderStyle: 'dashed' }}>
          添加规则
        </Button>
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// 代码编辑器面板
// ─────────────────────────────────────────────────────────────────────────────
const CodePanel = ({ value, onChange }) => {
  const [jsonErr, setJsonErr] = useState('')

  const handleChange = (v) => {
    onChange(v)
    try { JSON.parse(v); setJsonErr('') }
    catch (e) { setJsonErr(e.message) }
  }

  return (
    <Row gutter={20}>
      <Col xs={24} xl={16}>
        {jsonErr && (
          <Alert type="error" showIcon style={{ marginBottom: 8 }}
            message={`JSON 格式错误：${jsonErr}`} />
        )}
        <TextArea
          value={value} rows={26} spellCheck={false}
          onChange={e => handleChange(e.target.value)}
          style={{
            fontFamily: "'Cascadia Code','Fira Code','JetBrains Mono',monospace",
            fontSize: 12.5, lineHeight: 1.65, resize: 'vertical',
          }}
        />
      </Col>
      <Col xs={24} xl={8}>
        <Card size="small" title={<Space><InfoCircleOutlined />字段说明</Space>}
          style={{ position: 'sticky', top: 16 }}>
          <div style={{ fontSize: 12, lineHeight: 2, color: 'var(--ant-color-text-secondary, #666)' }}>
            <div><Text code>enabled</Text>　启用分类引擎</div>
            <div><Text code>dry_run</Text>　试运行，不移动文件</div>
            <div><Text code>target_root</Text>　目标根目录（网盘路径）</div>
            <div><Text code>unrecognized_dir</Text>　未识别文件目录</div>
            <Divider style={{ margin: '6px 0' }} />
            <div style={{ fontWeight: 600 }}>categories[]</div>
            <div style={{ paddingLeft: 8 }}>
              <div><Text code>name</Text>　分类名</div>
              <div><Text code>target_dir</Text>　目标子目录</div>
              <div><Text code>match_all</Text>　true=AND / false=OR</div>
              <div><Text code>rules[]</Text>　空数组 = 兜底分类</div>
            </div>
            <Divider style={{ margin: '6px 0' }} />
            <div style={{ fontWeight: 600 }}>rules[].type 取值</div>
            <div style={{ paddingLeft: 8 }}>
              <div><Text code>keyword</Text>　关键词（不区分大小写）</div>
              <div><Text code>regex</Text>　正则表达式</div>
              <div><Text code>genre_ids</Text>　TMDB 类型 ID</div>
              <div><Text code>origin_country</Text>　TMDB 产地代码</div>
              <div><Text code>original_language</Text>　TMDB 原始语言</div>
            </div>
            <Divider style={{ margin: '6px 0' }} />
            <div style={{ fontWeight: 600 }}>常用 genre_ids</div>
            <div style={{ paddingLeft: 8, lineHeight: 1.8 }}>
              16=动画　99=纪录片　10767=脱口秀<br />
              28=动作　12=冒险　35=喜剧　18=剧情
            </div>
          </div>
        </Card>
      </Col>
    </Row>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// 全局设置面板（横向紧凑布局）
// ─────────────────────────────────────────────────────────────────────────────
const GlobalSettings = ({ cfg, onChange, onPickDir }) => (
  <Card size="small" style={{ marginBottom: 16 }}
    bodyStyle={{ padding: '12px 16px' }}>
    <Row gutter={[24, 0]} align="middle" wrap>
      <Col xs={24} sm={12} md={6}>
        <Form.Item label="启用分类引擎" style={{ margin: 0 }}>
          <Switch checked={cfg.enabled}
            checkedChildren="启用" unCheckedChildren="禁用"
            onChange={v => onChange({ enabled: v })} />
        </Form.Item>
      </Col>
      <Col xs={24} sm={12} md={6}>
        <Form.Item label="试运行" tooltip="只记录日志，不实际移动文件" style={{ margin: 0 }}>
          <Switch checked={cfg.dry_run}
            checkedChildren="开" unCheckedChildren="关"
            onChange={v => onChange({ dry_run: v })} />
        </Form.Item>
      </Col>
      <Col xs={24} md={6}>
        <Form.Item label="整理目标根目录" style={{ margin: 0 }}>
          <Input size="small" value={cfg.target_root} placeholder="/整理后"
            onChange={e => onChange({ target_root: e.target.value })}
            suffix={
              <Tooltip title="选择目录">
                <FolderOpenOutlined
                  style={{ cursor: 'pointer', color: '#888' }}
                  onClick={() => onPickDir('target_root')} />
              </Tooltip>
            } />
        </Form.Item>
      </Col>
      <Col xs={24} md={6}>
        <Form.Item label="未识别文件目录" tooltip="无法匹配任何分类的文件归入此处" style={{ margin: 0 }}>
          <Input size="small" value={cfg.unrecognized_dir} placeholder="/未识别"
            onChange={e => onChange({ unrecognized_dir: e.target.value })}
            suffix={
              <Tooltip title="选择目录">
                <FolderOpenOutlined
                  style={{ cursor: 'pointer', color: '#888' }}
                  onClick={() => onPickDir('unrecognized_dir')} />
              </Tooltip>
            } />
        </Form.Item>
      </Col>
    </Row>
  </Card>
)

// ─────────────────────────────────────────────────────────────────────────────
// 主页面
// ─────────────────────────────────────────────────────────────────────────────
export const Classify = () => {
  const [cfg,        setCfg]        = useState(DEFAULT_CONFIG)
  const [mode,       setMode]       = useState('gui')
  const [codeText,   setCodeText]   = useState('')
  const [saving,     setSaving]     = useState(false)
  const [loading,    setLoading]    = useState(true)
  // providers: [{ name, label, available }]
  const [providers,  setProviders]  = useState([])
  const [dirOpen,    setDirOpen]    = useState(false)
  const [dirField,   setDirField]   = useState(null)

  // ── 加载 ──
  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [r1, r2] = await Promise.all([
        classifyApi.getConfig(),
        classifyApi.getMetadataStatus(),
      ])
      const data = r1.data || DEFAULT_CONFIG
      setCfg(data)
      setCodeText(JSON.stringify(data, null, 2))
      setProviders(Array.isArray(r2.data) ? r2.data : [])
    } catch {
      message.error('加载分类配置失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  // ── 模式切换 ──
  const switchMode = (m) => {
    if (m === 'code') {
      setCodeText(JSON.stringify(cfg, null, 2))
    } else {
      try {
        setCfg(JSON.parse(codeText))
      } catch {
        message.warning('JSON 格式有误，已保留图形化设置')
      }
    }
    setMode(m)
  }

  // ── 保存 ──
  const handleSave = async () => {
    let payload = cfg
    if (mode === 'code') {
      try { payload = JSON.parse(codeText) }
      catch { message.error('JSON 格式错误，无法保存'); return }
    }
    setSaving(true)
    try {
      await classifyApi.saveConfig(payload)
      setCfg(payload)
      setCodeText(JSON.stringify(payload, null, 2))
      message.success('分类配置已保存')
    } catch {
      message.error('保存失败')
    } finally {
      setSaving(false)
    }
  }

  // ── 全局字段更新 ──
  const patchCfg = (patch) => setCfg(c => ({ ...c, ...patch }))

  // ── 分类操作 ──
  const updateCat = (i, patch) =>
    setCfg(c => ({ ...c, categories: c.categories.map((v, ci) => ci === i ? { ...v, ...patch } : v) }))
  const deleteCat = (i) =>
    setCfg(c => ({ ...c, categories: c.categories.filter((_, ci) => ci !== i) }))
  const moveCat = (i, dir) =>
    setCfg(c => {
      const a = [...c.categories]
      ;[a[i], a[i + dir]] = [a[i + dir], a[i]]
      return { ...c, categories: a }
    })
  const addCat = () =>
    setCfg(c => ({
      ...c,
      categories: [...c.categories, {
        name: '', target_dir: '', match_all: false, rules: [],
      }],
    }))

  // ── 目录选择器 ──
  const openDirPicker = (field) => { setDirField(field); setDirOpen(true) }
  const onDirSelect   = (path)  => {
    if (dirField) patchCfg({ [dirField]: path })
  }

  const cats = cfg.categories || []

  return (
    <div>
      {/* ── 页头 ── */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        marginBottom: 16, flexWrap: 'wrap', gap: 12,
      }}>
        <Space align="center" size={12}>
          <Title level={4} style={{ margin: 0 }}>整理分类引擎</Title>
          <Badge count={cats.length} showZero style={{ backgroundColor: '#6366f1' }} />
          {/* 显示所有已注册元数据 Provider 的可用状态 */}
          {providers.map(p => (
            <Tag
              key={p.name}
              icon={p.available ? <CheckCircleFilled /> : <ExclamationCircleFilled />}
              color={p.available ? 'success' : 'warning'}
              style={{ fontSize: 12 }}
            >
              {p.label} {p.available ? '已配置' : '未配置'}
            </Tag>
          ))}
        </Space>

        <Space>
          <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>刷新</Button>
          <Segmented
            value={mode}
            onChange={switchMode}
            options={[
              { value: 'gui',  label: <Space size={4}><AppstoreOutlined />图形化</Space> },
              { value: 'code', label: <Space size={4}><CodeOutlined />代码</Space> },
            ]}
          />
          <Button type="primary" icon={<SaveOutlined />} loading={saving} onClick={handleSave}>
            保存配置
          </Button>
        </Space>
      </div>

      {/* ── 元数据 Provider 未配置提示 ── */}
      {providers.length > 0 && providers.every(p => !p.available) && (
        <Alert type="warning" showIcon style={{ marginBottom: 12 }}
          message="所有元数据 Provider 均未配置，TMDB 类型 / 产地 / 语言规则将不生效，仅关键词和正则规则有效。"
          description="可在「搜索源」或「系统设置」中配置 Provider API Key。" />
      )}

      {/* ── 全局设置（仅图形化模式显示） ── */}
      {mode === 'gui' && (
        <Form layout="vertical">
          <GlobalSettings cfg={cfg} onChange={patchCfg} onPickDir={openDirPicker} />
        </Form>
      )}

      {/* ── 编辑区 ── */}
      {mode === 'code'
        ? <CodePanel value={codeText} onChange={setCodeText} />
        : (
          <>
            {/* 分类规则标题行 */}
            <div style={{
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              marginBottom: 10,
            }}>
              <Space>
                <Text strong style={{ fontSize: 14 }}>分类规则</Text>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  从上到下顺序匹配，命中第一个分类即停止
                </Text>
              </Space>
              <Button icon={<PlusOutlined />} onClick={addCat}>新增分类</Button>
            </div>

            {cats.length === 0
              ? (
                <Empty
                  description={<span>暂无分类规则，<a onClick={addCat}>点击新增</a></span>}
                  style={{ padding: '40px 0' }}
                />
              )
              : cats.map((cat, idx) => (
                <CategoryCard
                  key={idx}
                  cat={cat}
                  idx={idx}
                  total={cats.length}
                  color={CAT_COLORS[idx % CAT_COLORS.length]}
                  onUpdate={(p) => updateCat(idx, p)}
                  onDelete={() => deleteCat(idx)}
                  onMove={(dir) => moveCat(idx, dir)}
                />
              ))
            }

            {cats.length > 0 && (
              <Button block icon={<PlusOutlined />} onClick={addCat}
                style={{ borderStyle: 'dashed', marginTop: 2 }}>
                新增分类
              </Button>
            )}
          </>
        )
      }

      {/* ── 目录选择 ── */}
      <DirPickerModal
        open={dirOpen}
        onClose={() => setDirOpen(false)}
        onSelect={(path) => { onDirSelect(path); setDirOpen(false) }}
      />
    </div>
  )
}

export default Classify

