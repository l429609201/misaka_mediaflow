import os

part1 = r'''// web/src/pages/classify/index.jsx
// 整理分类引擎 — 通用模块（MP 风格）

import { useEffect, useState, useCallback } from 'react'
import {
  Card, Row, Col, Input, Switch, Button, Select,
  Space, Alert, Tooltip, Divider, message, Segmented,
  Tag, Typography, Form, Spin,
} from 'antd'
import {
  PlusOutlined, DeleteOutlined, SaveOutlined, ReloadOutlined,
  ArrowUpOutlined, ArrowDownOutlined, CodeOutlined, AppstoreOutlined,
  FolderOpenOutlined, CheckCircleFilled, ExclamationCircleFilled,
} from '@ant-design/icons'
import { classifyApi } from '@/apis'
import DirPickerModal from '@/components/DirPickerModal'

const { Text, Title } = Typography
const { TextArea } = Input

const DEFAULT_CONFIG = {
  enabled: true, dry_run: false, target_root: '', unrecognized_dir: '', categories: [],
}

const CAT_COLORS = [
  '#6366f1','#10b981','#f59e0b','#ef4444',
  '#8b5cf6','#06b6d4','#f97316','#ec4899','#84cc16','#14b8a6',
]

const RULE_TYPE_GROUPS = [
  { label: '本地匹配', options: [
    { value: 'keyword', label: '关键词' },
    { value: 'regex',   label: '正则表达式' },
  ]},
  { label: '元数据匹配', options: [
    { value: 'genre_ids',         label: 'TMDB 类型 ID' },
    { value: 'origin_country',    label: '产地代码' },
    { value: 'original_language', label: '原始语言' },
  ]},
]

const FIELD_OPTIONS = [
  { value: 'filename', label: '文件名' },
  { value: 'dirname',  label: '目录名' },
]
const LOCAL_TYPES = ['keyword', 'regex']

// ─── 单条规则行 ───────────────────────────────────────────────────────────────
const RuleRow = ({ rule, onChange, onDelete }) => {
  const needsField = LOCAL_TYPES.includes(rule.type)
  return (
    <div style={{ display:'flex', alignItems:'center', gap:6, padding:'4px 0' }}>
      <Select size="small" value={rule.type} style={{ width:132, flexShrink:0 }}
        options={RULE_TYPE_GROUPS}
        onChange={v => onChange({ ...rule, type:v, field: LOCAL_TYPES.includes(v)?(rule.field||'filename'):undefined })}
      />
      {needsField
        ? <Select size="small" value={rule.field||'filename'} style={{ width:88, flexShrink:0 }}
            options={FIELD_OPTIONS} onChange={v => onChange({ ...rule, field:v })} />
        : <div style={{ width:88, flexShrink:0 }} />
      }
      <Input size="small" value={rule.value} style={{ flex:1 }}
        placeholder={
          rule.type==='genre_ids'         ? '如：16（动画）、28（动作）' :
          rule.type==='origin_country'    ? '如：JP、CN、US' :
          rule.type==='original_language' ? '如：ja、zh、en' : '匹配值'
        }
        onChange={e => onChange({ ...rule, value:e.target.value })}
      />
      <Button size="small" type="text" danger icon={<DeleteOutlined />} onClick={onDelete} />
    </div>
  )
}

// ─── 分类卡片 ─────────────────────────────────────────────────────────────────
const CategoryCard = ({ cat, idx, total, color, onUpdate, onDelete, onMove }) => {
  const rules = cat.rules || []
  const isDefault = rules.length === 0
  const addRule = () => onUpdate({ rules:[...rules,{ type:'keyword', field:'filename', value:'' }] })
  const updateRule = (ri,r) => onUpdate({ rules:rules.map((x,i)=>i===ri?r:x) })
  const deleteRule = (ri) => onUpdate({ rules:rules.filter((_,i)=>i!==ri) })

  return (
    <div style={{
      borderRadius:10, overflow:'hidden',
      border:'1px solid var(--ant-color-border,#e5e7eb)',
      marginBottom:10,
      background:'var(--ant-color-bg-container,#fff)',
      boxShadow:'0 1px 4px rgba(0,0,0,.05)',
    }}>
      {/* ── 头部 ── */}
      <div style={{
        display:'flex', alignItems:'center', gap:8, padding:'8px 12px',
        borderLeft:`4px solid ${color}`,
        background:'var(--ant-color-fill-quaternary,rgba(0,0,0,.02))',
        borderBottom:'1px solid var(--ant-color-border-secondary,#f0f0f0)',
      }}>
        <div style={{
          width:22, height:22, borderRadius:'50%', background:color, color:'#fff',
          display:'flex', alignItems:'center', justifyContent:'center',
          fontSize:11, fontWeight:700, flexShrink:0,
        }}>{idx+1}</div>

        <Input variant="borderless" size="small" value={cat.name} placeholder="分类名称"
          style={{ fontWeight:600, fontSize:13, flex:'0 0 130px', padding:'0 4px' }}
          onChange={e=>onUpdate({ name:e.target.value })} />

        <Text type="secondary" style={{ fontSize:12, flexShrink:0 }}>→</Text>

        <Input variant="borderless" size="small" value={cat.target_dir} placeholder="目标子目录（相对根目录）"
          style={{ flex:1, fontSize:12, color:'#888', padding:'0 4px' }}
          onChange={e=>onUpdate({ target_dir:e.target.value })} />

        {isDefault && <Tag color="orange" style={{ fontSize:11, flexShrink:0 }}>兜底</Tag>}
        <Tag style={{ fontSize:11, flexShrink:0, color:'#888' }}>{rules.length} 条规则</Tag>

        <Tooltip title="命中多条规则时：任一=OR，全部=AND">
          <Select size="small" variant="borderless" value={cat.match_all?'all':'any'}
            style={{ width:66, flexShrink:0 }}
            options={[{ value:'any', label:'任一' },{ value:'all', label:'全部' }]}
            onChange={v=>onUpdate({ match_all:v==='all' })} />
        </Tooltip>

        <Space size={2} style={{ flexShrink:0 }}>
          <Tooltip title="上移">
            <Button size="small" type="text" icon={<ArrowUpOutlined />} disabled={idx===0} onClick={()=>onMove(-1)} />
          </Tooltip>
          <Tooltip title="下移">
            <Button size="small" type="text" icon={<ArrowDownOutlined />} disabled={idx===total-1} onClick={()=>onMove(1)} />
          </Tooltip>
          <Tooltip title="删除">
            <Button size="small" type="text" danger icon={<DeleteOutlined />} onClick={onDelete} />
          </Tooltip>
        </Space>
      </div>

      {/* ── 规则区 ── */}
      <div style={{ padding:'8px 12px' }}>
        {isDefault ? (
          <div style={{ padding:'7px 12px', borderRadius:6, fontSize:12, color:'#b45309', background:'rgba(251,191,36,.08)', border:'1px dashed #fbbf24' }}>
            ⚡ 兜底分类：无规则时匹配所有未归类文件，建议放在列表最末。
          </div>
        ) : (
          <>
            <div style={{ display:'flex', gap:6, padding:'0 0 2px', fontSize:11, color:'#bbb' }}>
              <div style={{ width:132 }}>规则类型</div>
              <div style={{ width:88 }}>字段</div>
              <div style={{ flex:1 }}>匹配值</div>
              <div style={{ width:32 }} />
            </div>
            {rules.map((r,ri)=>(
              <RuleRow key={ri} rule={r} onChange={nr=>updateRule(ri,nr)} onDelete={()=>deleteRule(ri)} />
            ))}
          </>
        )}
        <Button size="small" type="dashed" icon={<PlusOutlined />} block style={{ marginTop:6, fontSize:12 }} onClick={addRule}>
          添加规则
        </Button>
      </div>
    </div>
  )
}
'''

part2 = r'''
// ─── 代码模式面板 ─────────────────────────────────────────────────────────────
const CodePanel = ({ value, onChange }) => (
  <Row gutter={16}>
    <Col xs={24} lg={15}>
      <Card size="small" title={<span style={{ fontSize:13 }}>JSON 配置</span>} style={{ height:'100%' }}>
        <TextArea
          value={value}
          onChange={e => onChange(e.target.value)}
          autoSize={{ minRows:20, maxRows:40 }}
          style={{ fontFamily:'monospace', fontSize:12 }}
        />
      </Card>
    </Col>
    <Col xs={24} lg={9}>
      <Card size="small" title={<span style={{ fontSize:13 }}>字段说明</span>}
        style={{ position:'sticky', top:24, fontSize:12, lineHeight:1.9 }}>
        <div style={{ fontWeight:600, marginBottom:4 }}>顶层字段</div>
        <div><Text code>enabled</Text> 启用分类引擎</div>
        <div><Text code>dry_run</Text> 试运行（不移动文件）</div>
        <div><Text code>target_root</Text> 目标根目录</div>
        <div><Text code>unrecognized_dir</Text> 未识别目录</div>
        <Divider style={{ margin:'8px 0' }} />
        <div style={{ fontWeight:600, marginBottom:4 }}>categories[]</div>
        <div><Text code>name</Text> 分类名称</div>
        <div><Text code>target_dir</Text> 目标子目录</div>
        <div><Text code>match_all</Text> true=AND / false=OR</div>
        <div><Text code>rules[]</Text> 空数组 = 兜底分类</div>
        <Divider style={{ margin:'8px 0' }} />
        <div style={{ fontWeight:600, marginBottom:4 }}>rules[].type 取值</div>
        <div><Text code>keyword</Text> 关键词（不区分大小写）</div>
        <div><Text code>regex</Text> 正则表达式</div>
        <div><Text code>genre_ids</Text> TMDB 类型 ID</div>
        <div><Text code>origin_country</Text> TMDB 产地代码</div>
        <div><Text code>original_language</Text> TMDB 原始语言</div>
        <Divider style={{ margin:'8px 0' }} />
        <div style={{ fontWeight:600, marginBottom:4 }}>常用 genre_ids</div>
        <div style={{ color:'#888' }}>16=动画　99=纪录片　10767=脱口秀</div>
        <div style={{ color:'#888' }}>28=动作　12=冒险　35=喜剧　18=剧情</div>
      </Card>
    </Col>
  </Row>
)

// ─── 主页面 ───────────────────────────────────────────────────────────────────
export const Classify = () => {
  const [cfg,       setCfg]       = useState(DEFAULT_CONFIG)
  const [mode,      setMode]      = useState('gui')
  const [codeText,  setCodeText]  = useState('')
  const [saving,    setSaving]    = useState(false)
  const [loading,   setLoading]   = useState(true)
  const [providers, setProviders] = useState([])
  const [dirOpen,   setDirOpen]   = useState(false)
  const [dirField,  setDirField]  = useState(null)

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
  const switchMode = m => {
    if (m === 'code') {
      setCodeText(JSON.stringify(cfg, null, 2))
    } else {
      try { setCfg(JSON.parse(codeText)) }
      catch { message.warning('JSON 格式有误，已保留图形化设置') }
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

  // ── 分类操作 ──
  const cats = cfg.categories || []
  const updateCats = next => setCfg(c => ({ ...c, categories: next }))
  const addCat = () => updateCats([...cats, { name:'新分类', target_dir:'', match_all:false, rules:[] }])
  const updateCat = (i, patch) => updateCats(cats.map((c,ci) => ci===i ? { ...c, ...patch } : c))
  const deleteCat = i => updateCats(cats.filter((_,ci) => ci!==i))
  const moveCat = (i, dir) => {
    const ni = i + dir
    if (ni < 0 || ni >= cats.length) return
    const next = [...cats]; [next[i], next[ni]] = [next[ni], next[i]]; updateCats(next)
  }
  const setCfgField = patch => setCfg(c => ({ ...c, ...patch }))

  // ── 目录选择器 ──
  const openDir = field => { setDirField(field); setDirOpen(true) }
  const onDirSelect = val => {
    if (dirField) setCfgField({ [dirField]: val })
    setDirOpen(false)
  }

  const allUnavailable = providers.length > 0 && providers.every(p => !p.available)

  return (
    <div style={{ padding:24 }}>
      {/* ── 页头 ── */}
      <div style={{
        display:'flex', alignItems:'center', justifyContent:'space-between',
        flexWrap:'wrap', gap:12, marginBottom:20,
      }}>
        <Space align="center" size={10}>
          <Title level={4} style={{ margin:0 }}>整理分类引擎</Title>
          <Tag color="purple" style={{ borderRadius:20, fontWeight:600 }}>{cats.length} 个分类</Tag>
          {providers.map(p => (
            <Tag key={p.name}
              icon={p.available ? <CheckCircleFilled /> : <ExclamationCircleFilled />}
              color={p.available ? 'success' : 'warning'} style={{ fontSize:12 }}>
              {p.label} {p.available ? '已配置' : '未配置'}
            </Tag>
          ))}
        </Space>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>刷新</Button>
          <Segmented value={mode} onChange={switchMode}
            options={[
              { value:'gui',  label:<Space size={4}><AppstoreOutlined />图形化</Space> },
              { value:'code', label:<Space size={4}><CodeOutlined />代码</Space> },
            ]}
          />
          <Button type="primary" icon={<SaveOutlined />} loading={saving} onClick={handleSave}>保存配置</Button>
        </Space>
      </div>

      {/* ── 未配置提示 ── */}
      {allUnavailable && (
        <Alert type="warning" showIcon style={{ marginBottom:16 }}
          message="所有元数据 Provider 均未配置，TMDB 类型 / 产地 / 语言规则不生效，仅关键词和正则规则有效。"
          description='可在「搜索源」或「系统设置」中配置 Provider API Key。' />
      )}

      <Spin spinning={loading}>
        {mode === 'gui' ? (
          <>
            {/* ── 全局设置 ── */}
            <Card size="small" style={{ marginBottom:16 }}
              styles={{ body:{ padding:'14px 20px' } }}>
              <Row gutter={[32, 0]} align="middle" wrap>
                <Col xs={24} sm={12} md={6} lg={5}>
                  <Form.Item label="启用分类引擎" style={{ margin:0 }}>
                    <Switch checked={cfg.enabled}
                      checkedChildren="启用" unCheckedChildren="禁用"
                      onChange={v => setCfgField({ enabled:v })} />
                  </Form.Item>
                </Col>
                <Col xs={24} sm={12} md={6} lg={4}>
                  <Form.Item label="试运行" tooltip="只记录日志，不实际移动文件" style={{ margin:0 }}>
                    <Switch checked={cfg.dry_run}
                      checkedChildren="开" unCheckedChildren="关"
                      onChange={v => setCfgField({ dry_run:v })} />
                  </Form.Item>
                </Col>
                <Col xs={24} sm={24} md={12} lg={8}>
                  <Form.Item label="目标根目录" style={{ margin:0 }}>
                    <Input value={cfg.target_root} placeholder="/整理后"
                      suffix={<Tooltip title="选择目录"><FolderOpenOutlined style={{ cursor:'pointer', color:'#999' }} onClick={()=>openDir('target_root')} /></Tooltip>}
                      onChange={e => setCfgField({ target_root:e.target.value })} />
                  </Form.Item>
                </Col>
                <Col xs={24} sm={24} md={12} lg={7}>
                  <Form.Item label="未识别目录" style={{ margin:0 }}>
                    <Input value={cfg.unrecognized_dir} placeholder="/未识别"
                      suffix={<Tooltip title="选择目录"><FolderOpenOutlined style={{ cursor:'pointer', color:'#999' }} onClick={()=>openDir('unrecognized_dir')} /></Tooltip>}
                      onChange={e => setCfgField({ unrecognized_dir:e.target.value })} />
                  </Form.Item>
                </Col>
              </Row>
            </Card>

            {/* ── 分类列表 ── */}
            <div style={{ marginBottom:8, display:'flex', alignItems:'center', justifyContent:'space-between' }}>
              <Text type="secondary" style={{ fontSize:12 }}>匹配优先级从上到下，排在前面的分类优先匹配</Text>
              <Button type="primary" ghost size="small" icon={<PlusOutlined />} onClick={addCat}>
                添加分类
              </Button>
            </div>

            {cats.length === 0
              ? <div style={{ padding:'48px 0', textAlign:'center', color:'#bbb', fontSize:14 }}>
                  暂无分类规则，点击「添加分类」开始配置
                </div>
              : cats.map((cat, i) => (
                <CategoryCard key={i} cat={cat} idx={i} total={cats.length}
                  color={CAT_COLORS[i % CAT_COLORS.length]}
                  onUpdate={patch => updateCat(i, patch)}
                  onDelete={() => deleteCat(i)}
                  onMove={dir => moveCat(i, dir)}
                />
              ))
            }
          </>
        ) : (
          <CodePanel value={codeText} onChange={setCodeText} />
        )}
      </Spin>

      <DirPickerModal open={dirOpen} onCancel={() => setDirOpen(false)} onSelect={onDirSelect} />
    </div>
  )
}

export default Classify
'''

path = 'web/src/pages/classify/index.jsx'
os.makedirs(os.path.dirname(path), exist_ok=True)
with open(path, 'w', encoding='utf-8') as f:
    f.write(part1 + part2)
print('Written lines:', len((part1+part2).splitlines()))

