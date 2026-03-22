// web/src/pages/classify/index.jsx
// 整理分类刮削 — 三Tab页面
// Tab1：目录整理（MP风格自定义转移规则）
// Tab2：分类规则（原分类引擎配置）
// Tab3：重命名刮削（格式模板配置）

import { useEffect, useState, useCallback, useRef } from 'react'
import {
  Card, Row, Col, Input, Switch, Button, Select, Modal, Form,
  Space, Alert, Tooltip, Divider, message, Segmented, Tag,
  Typography, Spin, Tabs,
} from 'antd'
import {
  PlusOutlined, DeleteOutlined, SaveOutlined, ReloadOutlined,
  EditOutlined, ArrowUpOutlined, ArrowDownOutlined,
  CodeOutlined, AppstoreOutlined,
  CheckCircleFilled, ExclamationCircleFilled,
  FolderAddOutlined, FolderOpenOutlined, NodeIndexOutlined,
  PlayCircleOutlined, SyncOutlined,
} from '@ant-design/icons'
import { classifyApi, p115Api, p115StrmApi, storageApi } from '@/apis'
import DirPickerModal from '@/components/DirPickerModal'
import LocalDirPickerModal from '@/components/LocalDirPickerModal'
import StorageDirPickerModal from '@/components/StorageDirPickerModal'

const { Text } = Typography
const { TextArea } = Input

// ─── 默认配置 ─────────────────────────────────────────────────────────────────
const DEFAULT_CONFIG = {
  enabled: true, categories: [],
}

// ─── 分类颜色 ─────────────────────────────────────────────────────────────────
const CAT_COLORS = [
  '#6366f1','#10b981','#f59e0b','#ef4444',
  '#8b5cf6','#06b6d4','#f97316','#ec4899','#84cc16','#14b8a6',
]

// ─── TMDB 流派 ID 选项 ────────────────────────────────────────────────────────
const GENRE_OPTIONS = [
  { value: '16',    label: '动画 Animation' },
  { value: '99',    label: '纪录片 Documentary' },
  { value: '10767', label: '脱口秀 Talk' },
  { value: '10764', label: '真人秀 Reality' },
  { value: '28',    label: '动作 Action' },
  { value: '12',    label: '冒险 Adventure' },
  { value: '35',    label: '喜剧 Comedy' },
  { value: '18',    label: '剧情 Drama' },
  { value: '10751', label: '家庭 Family' },
  { value: '14',    label: '奇幻 Fantasy' },
  { value: '36',    label: '历史 History' },
  { value: '27',    label: '恐怖 Horror' },
  { value: '10402', label: '音乐 Music' },
  { value: '9648',  label: '悬疑 Mystery' },
  { value: '10749', label: '爱情 Romance' },
  { value: '878',   label: '科幻 Sci-Fi' },
  { value: '10770', label: 'TV Movie' },
  { value: '53',    label: '惊悚 Thriller' },
  { value: '10752', label: '战争 War' },
  { value: '37',    label: '西部 Western' },
  { value: '10759', label: '动作冒险 Action&Adventure' },
  { value: '10762', label: '儿童 Kids' },
  { value: '10763', label: '新闻 News' },
  { value: '10766', label: '肥皂剧 Soap' },
]

// ─── 产地选项 ─────────────────────────────────────────────────────────────────
const COUNTRY_OPTIONS = [
  { value: 'JP', label: '日本 JP' },
  { value: 'CN', label: '中国 CN' },
  { value: 'US', label: '美国 US' },
  { value: 'KR', label: '韩国 KR' },
  { value: 'GB', label: '英国 GB' },
  { value: 'FR', label: '法国 FR' },
  { value: 'DE', label: '德国 DE' },
  { value: 'TH', label: '泰国 TH' },
  { value: 'IN', label: '印度 IN' },
  { value: 'HK', label: '香港 HK' },
  { value: 'TW', label: '台湾 TW' },
]

// ─── 语言选项 ─────────────────────────────────────────────────────────────────
const LANG_OPTIONS = [
  { value: 'ja', label: '日语 ja' },
  { value: 'zh', label: '中文 zh' },
  { value: 'en', label: '英语 en' },
  { value: 'ko', label: '韩语 ko' },
  { value: 'fr', label: '法语 fr' },
  { value: 'de', label: '德语 de' },
  { value: 'th', label: '泰语 th' },
]

// ─── 适用对象 ─────────────────────────────────────────────────────────────────
const MEDIA_TYPE_OPTIONS = [
  { value: 'all',   label: '全部' },
  { value: 'movie', label: '电影' },
  { value: 'tv',    label: '剧集' },
]


// =============================================================================
// YAML 格式解析器（参考 MP 项目 category.yaml 格式）
//
// 格式说明：
//   顶层只有两个固定 key：movie（电影）、tv（电视剧），或 all（不区分）
//   二级 key 同时也是分类名和目标子目录
//   二级 key 下可选配置字段（缩进4格或2格均可）：
//     genre_ids:            '16'           # 逗号分隔多个
//     origin_country:       'JP,CN'        # 剧集产地
//     production_countries: 'JP,CN'        # 电影产地
//     original_language:    'ja,zh'        # 语言
//     keyword:              '动漫,动画'    # 文件名关键词
//     keyword_dir:          '番剧,动漫'    # 目录名关键词
//     regex:                '(?i)(OVA)'   # 正则
//   无任何字段的二级 key = 兜底分类
//
// 示例：
//   movie:
//     动漫电影:
//       genre_ids: '16'
//     电影:
//
//   tv:
//     动漫:
//       genre_ids: '16'
//       origin_country: 'JP'
//     电视剧:
// =============================================================================

const YAML_HEADER = `####### 整理分类配置 #######
# 顶层固定两个 key：movie（电影）、tv（电视剧）
# 二级名称同时作为分类名和目标子目录，按顺序从上到下匹配
# 无任何条件字段 = 兜底分类（匹配所有未归类）
#
# 可用字段：
#   genre_ids            TMDB 类型 ID，多个用逗号分隔（如 '16,28'）
#   origin_country       国家/地区（剧集），如 'JP,CN'
#   production_countries 国家/地区（电影），如 'JP,US'
#   original_language    语言，如 'ja,zh'
#   keyword              文件名关键词，多个用逗号分隔
#   keyword_dir          目录名关键词，多个用逗号分隔
#   regex                正则表达式（匹配文件名）
`

// ── 简易 YAML 解析（只支持本配置所需的子集）─────────────────────────────────
function parseYamlCfg(text) {
  const lines = text.split('\n')
  const categories = []
  let mediaType = 'all'   // 当前顶层 key
  let cur = null

  const strVal = s => (s || '').replace(/^['"]|['"]$/g, '').trim()
  const listVal = s => strVal(s).split(',').map(x => x.trim()).filter(Boolean)

  for (let i = 0; i < lines.length; i++) {
    const raw = lines[i]
    const stripped = raw.trimEnd()
    if (!stripped || stripped.trimStart().startsWith('#')) continue

    const indent = raw.length - raw.trimStart().length
    const content = raw.trimStart()

    // 顶层 key（无缩进，以冒号结尾，且是 movie/tv/all）
    if (indent === 0 && /^(movie|tv|all)\s*:/.test(content)) {
      mediaType = content.split(':')[0].trim()
      if (cur) { categories.push(cur); cur = null }
      continue
    }

    // 二级 key（缩进2~4，格式 "分类名:"）
    if (indent >= 2 && indent <= 6) {
      const catMatch = content.match(/^([^:]+):\s*$/)
      if (catMatch) {
        if (cur) categories.push(cur)
        cur = {
          name: catMatch[1].trim(),
          target_dir: catMatch[1].trim(),
          media_type: mediaType,
          match_all: false,
          genre_ids: [], country: [], language: [],
          keyword: [], keyword_dir: [], regex: [],
        }
        continue
      }
    }

    // 三级字段（缩进>4，格式 "key: value"）
    if (indent > 4 && cur) {
      const colonIdx = content.indexOf(':')
      if (colonIdx < 0) continue
      const key = content.slice(0, colonIdx).trim()
      const val = content.slice(colonIdx + 1).trim()

      if (key === 'genre_ids')                            cur.genre_ids  = listVal(val)
      else if (key === 'origin_country')                  cur.country    = listVal(val)
      else if (key === 'production_countries')            cur.country    = listVal(val)
      else if (key === 'original_language')               cur.language   = listVal(val)
      else if (key === 'keyword')                         cur.keyword    = listVal(val)
      else if (key === 'keyword_dir')                     cur.keyword_dir= listVal(val)
      else if (key === 'regex')                           cur.regex      = listVal(val)
      else if (key === 'match_all')                       cur.match_all  = val === 'true'
      continue
    }

    // 兼容 indent=2 时的三级字段（部分编辑器缩进两格）
    if (indent === 4 && cur) {
      const colonIdx = content.indexOf(':')
      if (colonIdx < 0) continue
      const key = content.slice(0, colonIdx).trim()
      const val = content.slice(colonIdx + 1).trim()
      if (key === 'genre_ids')             cur.genre_ids  = listVal(val)
      else if (key === 'origin_country')   cur.country    = listVal(val)
      else if (key === 'production_countries') cur.country= listVal(val)
      else if (key === 'original_language')cur.language   = listVal(val)
      else if (key === 'keyword')          cur.keyword    = listVal(val)
      else if (key === 'keyword_dir')      cur.keyword_dir= listVal(val)
      else if (key === 'regex')            cur.regex      = listVal(val)
      else if (key === 'match_all')        cur.match_all  = val === 'true'
    }
  }
  if (cur) categories.push(cur)
  return categories
}

// ── YAML 序列化（uiCats → YAML 文本）────────────────────────────────────────
function uiCatsToYaml(cats) {
  const movieCats = cats.filter(c => c.media_type === 'movie' || c.media_type === 'all')
  const tvCats    = cats.filter(c => c.media_type === 'tv'    || c.media_type === 'all')

  function renderCat(cat) {
    const lines = [`  ${cat.name}:`]
    const hasRules = cat.genre_ids?.length || cat.country?.length ||
      cat.language?.length || cat.keyword?.length ||
      cat.keyword_dir?.length || cat.regex?.length
    if (!hasRules) return lines.join('\n')  // 兜底分类，无字段

    if (cat.genre_ids?.length)
      lines.push(`    genre_ids: '${cat.genre_ids.join(',')}'`)
    if (cat.country?.length) {
      // 电影用 production_countries，剧集用 origin_country
      const key = cat.media_type === 'movie' ? 'production_countries' : 'origin_country'
      lines.push(`    ${key}: '${cat.country.join(',')}'`)
    }
    if (cat.language?.length)
      lines.push(`    original_language: '${cat.language.join(',')}'`)
    if (cat.keyword?.length)
      lines.push(`    keyword: '${cat.keyword.join(',')}'`)
    if (cat.keyword_dir?.length)
      lines.push(`    keyword_dir: '${cat.keyword_dir.join(',')}'`)
    if (cat.regex?.length)
      lines.push(`    regex: '${cat.regex.join(',')}'`)
    return lines.join('\n')
  }

  const sections = []

  if (movieCats.length) {
    sections.push('movie:')
    sections.push(...movieCats.map(renderCat))
    sections.push('')
  }
  if (tvCats.length) {
    sections.push('tv:')
    sections.push(...tvCats.map(renderCat))
    sections.push('')
  }
  // 没有分 movie/tv 的情况（all only）
  if (!movieCats.length && !tvCats.length && cats.length) {
    sections.push('all:')
    sections.push(...cats.map(renderCat))
    sections.push('')
  }

  return YAML_HEADER + '\n' + sections.join('\n')
}

// ── UI 内部格式 ↔ 后端 API 格式 ──────────────────────────────────────────────
function uiCatToApiCat(cat) {
  const rules = []
  if (cat.genre_ids?.length)   rules.push({ type:'genre_ids',         value: cat.genre_ids.join(',') })
  if (cat.country?.length)     rules.push({ type:'origin_country',    value: cat.country.join(',') })
  if (cat.language?.length)    rules.push({ type:'original_language', value: cat.language.join(',') })
  for (const k of (cat.keyword     || [])) rules.push({ type:'keyword', field:'filename', value:k })
  for (const k of (cat.keyword_dir || [])) rules.push({ type:'keyword', field:'dirname',  value:k })
  for (const r of (cat.regex       || [])) rules.push({ type:'regex',   field:'filename', value:r })
  return { name: cat.name, target_dir: cat.target_dir, match_all: cat.match_all, rules }
}

function apiCatToUiCat(cat) {
  const ui = {
    name: cat.name, target_dir: cat.target_dir||'', media_type:'all',
    match_all:!!cat.match_all, genre_ids:[], country:[], language:[],
    keyword:[], keyword_dir:[], regex:[],
  }
  for (const r of (cat.rules || [])) {
    if (r.type === 'genre_ids')              ui.genre_ids.push(...(r.value||'').split(',').map(s=>s.trim()).filter(Boolean))
    else if (r.type === 'origin_country')    ui.country.push(...(r.value||'').split(',').map(s=>s.trim()).filter(Boolean))
    else if (r.type === 'original_language') ui.language.push(...(r.value||'').split(',').map(s=>s.trim()).filter(Boolean))
    else if (r.type === 'keyword' && r.field === 'dirname') ui.keyword_dir.push(r.value)
    else if (r.type === 'keyword')  ui.keyword.push(r.value)
    else if (r.type === 'regex')    ui.regex.push(r.value)
  }
  return ui
}

// =============================================================================
// 分类编辑弹窗（MP 风格：每个维度专属控件）
// =============================================================================
const EditCategoryModal = ({ open, cat, onOk, onCancel }) => {
  const [form] = Form.useForm()

  useEffect(() => {
    if (open && cat) form.setFieldsValue({ ...cat })
  }, [open, cat, form])

  const handleOk = () => {
    form.validateFields().then(vals => onOk({ ...cat, ...vals }))
  }

  return (
    <Modal
      open={open}
      title={<Space><EditOutlined />{cat?.name ? `编辑分类：${cat.name}` : '新建分类'}</Space>}
      onOk={handleOk}
      onCancel={onCancel}
      width={600}
      okText="确定"
      cancelText="取消"
      destroyOnClose
    >
      <Form form={form} layout="vertical" size="middle" style={{ marginTop: 8 }}>
        <Row gutter={16}>
          <Col span={12}>
            <Form.Item name="name" label="分类名称" rules={[{ required:true, message:'请输入分类名称' }]}>
              <Input placeholder="如：动漫" />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item name="target_dir" label="目标子目录" tooltip="相对于目标根目录的子目录名">
              <Input placeholder="如：动漫 / Anime" />
            </Form.Item>
          </Col>
        </Row>

        <Row gutter={16}>
          <Col span={12}>
            <Form.Item name="media_type" label="适用对象">
              <Select options={MEDIA_TYPE_OPTIONS} />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item name="match_all" label="规则匹配逻辑" tooltip="AND=所有条件都满足；OR=任意条件满足">
              <Select options={[{ value:false, label:'任意满足 (OR)' },{ value:true, label:'全部满足 (AND)' }]} />
            </Form.Item>
          </Col>
        </Row>

        <Divider style={{ margin:'8px 0 16px' }}>TMDB 元数据匹配</Divider>

        <Form.Item name="genre_ids" label="流派 / 类型">
          <Select mode="multiple" allowClear placeholder="选择流派（可多选）" options={GENRE_OPTIONS}
            optionFilterProp="label" maxTagCount="responsive" />
        </Form.Item>

        <Row gutter={16}>
          <Col span={12}>
            <Form.Item name="country" label="原始国家 / 地区">
              <Select mode="multiple" allowClear placeholder="如：JP、CN" options={COUNTRY_OPTIONS}
                optionFilterProp="label" maxTagCount="responsive" />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item name="language" label="原始语言">
              <Select mode="multiple" allowClear placeholder="如：ja、zh" options={LANG_OPTIONS}
                optionFilterProp="label" maxTagCount="responsive" />
            </Form.Item>
          </Col>
        </Row>

        <Divider style={{ margin:'8px 0 16px' }}>本地文件名匹配</Divider>

        <Form.Item name="keyword" label="文件名关键词" tooltip="包含任意关键词即命中，多个关键词用回车或逗号分隔">
          <Select mode="tags" allowClear placeholder="输入关键词后回车，如：动漫、动画" tokenSeparators={[',']} />
        </Form.Item>

        <Form.Item name="keyword_dir" label="目录名关键词" tooltip="匹配文件所在目录名">
          <Select mode="tags" allowClear placeholder="输入目录关键词后回车" tokenSeparators={[',']} />
        </Form.Item>

        <Form.Item name="regex" label="正则表达式" tooltip="匹配文件名，多条正则分别匹配（任一命中）">
          <Select mode="tags" allowClear placeholder="如：(?i)(anime|OVA|OAD)" tokenSeparators={[',']} />
        </Form.Item>

        <Alert type="info" showIcon style={{ marginTop:8 }} message={
          <span>无任何匹配条件的分类将作为<b>兜底分类</b>，匹配所有未归类文件，建议放在列表最末。</span>
        } />
      </Form>
    </Modal>
  )
}

// =============================================================================
// 分类卡片（列表项）
// =============================================================================
const CategoryItem = ({ cat, idx, total, color, onEdit, onDelete, onMove }) => {
  const hasRules = (cat.genre_ids?.length || cat.country?.length || cat.language?.length ||
    cat.keyword?.length || cat.keyword_dir?.length || cat.regex?.length)
  const isDefault = !hasRules

  const tagStyle = { fontSize:11 }

  return (
    <div style={{
      display:'flex', alignItems:'center', gap:10,
      padding:'10px 14px',
      borderRadius:10,
      border:'1px solid var(--ant-color-border,#e5e7eb)',
      marginBottom:8,
      background:'var(--ant-color-bg-container,#fff)',
      boxShadow:'0 1px 3px rgba(0,0,0,.05)',
      borderLeft:`4px solid ${color}`,
      cursor:'default',
    }}>
      {/* 序号 */}
      <div style={{
        width:24, height:24, borderRadius:'50%', background:color,
        color:'#fff', display:'flex', alignItems:'center', justifyContent:'center',
        fontSize:12, fontWeight:700, flexShrink:0,
      }}>{idx+1}</div>

      {/* 分类名 + 目标目录 */}
      <div style={{ flex:1, minWidth:0 }}>
        <div style={{ fontWeight:600, fontSize:14 }}>{cat.name || <Text type="secondary">（未命名）</Text>}</div>
        <div style={{ fontSize:12, color:'#888', marginTop:1 }}>
          → {cat.target_dir || <Text type="secondary">未设置目标目录</Text>}
        </div>
      </div>

      {/* 条件标签 */}
      <div style={{ display:'flex', flexWrap:'wrap', gap:4, flex:2, minWidth:0 }}>
        {isDefault
          ? <Tag color="orange" style={tagStyle}>⚡ 兜底</Tag>
          : <>
              {cat.genre_ids?.map(id => {
                const opt = GENRE_OPTIONS.find(o => o.value === id)
                return <Tag key={id} color="blue" style={tagStyle}>{opt ? opt.label.split(' ')[0] : `类型${id}`}</Tag>
              })}
              {cat.country?.map(c => <Tag key={c} color="green" style={tagStyle}>{c}</Tag>)}
              {cat.language?.map(l => <Tag key={l} color="purple" style={tagStyle}>{l}</Tag>)}
              {cat.keyword?.map(k => <Tag key={k} color="default" style={tagStyle}>🔑{k}</Tag>)}
              {cat.keyword_dir?.map(k => <Tag key={k} color="default" style={tagStyle}>📁{k}</Tag>)}
              {cat.regex?.map(r => <Tag key={r} color="magenta" style={tagStyle}>正则</Tag>)}
            </>
        }
      </div>

      {/* 逻辑标签 */}
      <Tag style={{ flexShrink:0, fontSize:11, color:'#888' }}>
        {cat.match_all ? 'AND' : 'OR'}
      </Tag>

      {/* 操作 */}
      <Space size={2} style={{ flexShrink:0 }}>
        <Tooltip title="编辑"><Button type="primary" ghost size="small" icon={<EditOutlined />} onClick={onEdit} /></Tooltip>
        <Tooltip title="上移"><Button size="small" type="text" icon={<ArrowUpOutlined />} disabled={idx===0} onClick={()=>onMove(-1)} /></Tooltip>
        <Tooltip title="下移"><Button size="small" type="text" icon={<ArrowDownOutlined />} disabled={idx===total-1} onClick={()=>onMove(1)} /></Tooltip>
        <Tooltip title="删除"><Button size="small" type="text" danger icon={<DeleteOutlined />} onClick={onDelete} /></Tooltip>
      </Space>
    </div>
  )
}

// =============================================================================
// 代码模式面板
// =============================================================================
const CodePanel = ({ value, onChange }) => (
  <Row gutter={16}>
    <Col xs={24} lg={16}>
      <Card size="small" title={
        <Space>
          <CodeOutlined />
          <span>分类规则配置</span>
          <Tag color="blue">YAML 格式 · 参考 MP</Tag>
        </Space>
      }>
        <TextArea value={value} onChange={e=>onChange(e.target.value)}
          autoSize={{ minRows:24, maxRows:50 }}
          style={{ fontFamily:'monospace', fontSize:12, lineHeight:1.7 }}
        />
      </Card>
    </Col>
    <Col xs={24} lg={8}>
      <Card size="small" title="格式说明" style={{ position:'sticky', top:24, fontSize:12, lineHeight:2 }}>
        <div style={{ fontWeight:600, marginBottom:4 }}>格式示例（YAML）</div>
        <pre style={{ fontSize:11, background:'rgba(0,0,0,.04)', borderRadius:6, padding:'8px 10px', margin:'0 0 10px', whiteSpace:'pre', overflowX:'auto' }}>{
`movie:
  动漫电影:
    genre_ids: '16'
    production_countries: 'JP'
  电影:

tv:
  动漫:
    genre_ids: '16'
    origin_country: 'JP'
    original_language: 'ja'
    keyword: '动漫,动画,番剧'
    regex: '(?i)(OVA|OAD)'
  电视剧:
  # 无字段 = 兜底分类`
        }</pre>
        <Divider style={{ margin:'8px 0' }} />
        <div><Text code>genre_ids</Text> TMDB 类型 ID（字符串）</div>
        <div><Text code>origin_country</Text> 产地（剧集）如 <Text code>'JP,CN'</Text></div>
        <div><Text code>production_countries</Text> 产地（电影）</div>
        <div><Text code>original_language</Text> 语言 如 <Text code>'ja,zh'</Text></div>
        <div><Text code>keyword</Text> 文件名关键词（逗号分隔）</div>
        <div><Text code>keyword_dir</Text> 目录名关键词</div>
        <div><Text code>regex</Text> 正则（匹配文件名）</div>
        <Divider style={{ margin:'8px 0' }} />
        <div style={{ color:'#888' }}>· 无任何字段 = 兜底分类</div>
        <div style={{ color:'#888' }}>· # 开头行为注释</div>
        <div style={{ color:'#888' }}>· movie/tv 下分类继承适用对象</div>
        <div style={{ color:'#888' }}>· 多值用英文逗号分隔，外加引号</div>
      </Card>
    </Col>
  </Row>
)

// =============================================================================
// 目录整理 — 默认规则结构
// =============================================================================
const DEFAULT_ORG_RULE = {
  name: '新规则',
  enabled: true,
  media_type: 'all',
  // 源（待整理）
  source_storage: 'local',
  source_paths: [],
  // 目标（整理后存放）
  target_storage: 'local',
  target_root: '',
  // 未识别
  unrecognized_dir: '',
  // 自动整理
  auto_organize: 'monitor',   // 'monitor' | 'none'
  monitor_mode: 'compatibility', // 'compatibility' | 'performance'
  dry_run: false,
}

// 媒体类型配置
const MEDIA_TYPE_COLOR = { all: 'default', movie: 'blue', tv: 'purple' }
const MEDIA_TYPE_LABEL = { all: '全部', movie: '电影', tv: '剧集' }

// =============================================================================
// 刮削参数定义
// =============================================================================
const SCRAPE_PARAMS_MOVIE = [
  { param: '{title}',          label: '标题' },
  { param: '{original_title}', label: '原始标题' },
  { param: '{en_title}',       label: '英文标题' },
  { param: '{year}',           label: '年份' },
  { param: '{tmdbid}',         label: 'TMDB ID' },
  { param: '{imdbid}',         label: 'IMDB ID' },
  { param: '{resource_type}',  label: '资源类型' },
  { param: '{resource_pix}',   label: '分辨率' },
  { param: '{video_encode}',   label: '视频编码' },
  { param: '{audio_encode}',   label: '音频编码' },
  { param: '{edition}',        label: '版本' },
  { param: '{resource_team}',  label: '制作组' },
]
const SCRAPE_PARAMS_TV = [
  ...SCRAPE_PARAMS_MOVIE,
  { param: '{season}',         label: '季数（数字）' },
  { param: '{season:02d}',     label: '季数（补零）' },
  { param: '{episode}',        label: '集数（数字）' },
  { param: '{episode:02d}',    label: '集数（补零）' },
  { param: '{season_episode}', label: '季集（SxxExx）' },
  { param: '{episode_title}',  label: '集标题' },
]
const MOVIE_SAMPLE = {
  title: '星际穿越', original_title: 'Interstellar', en_title: 'Interstellar',
  year: '2014', tmdbid: '157336', imdbid: 'tt0816692', resource_type: 'BluRay',
  resource_pix: '2160p', video_encode: 'HEVC', audio_encode: 'TrueHD', edition: 'Remux', resource_team: 'CHDBits',
}
const TV_SAMPLE = {
  ...MOVIE_SAMPLE, title: '权力的游戏', en_title: 'Game of Thrones',
  year: '2011', tmdbid: '1399', season: 1, 'season:02d': '01', episode: 1,
  'episode:02d': '01', season_episode: 'S01E01', episode_title: '凛冬将至',
}
const previewFormat = (fmt, sample) => {
  if (!fmt) return '—'
  return fmt.replace(/\{([^}]+)\}/g, (_, k) => sample[k] !== undefined ? sample[k] : `{${k}}`)
}

// =============================================================================
// 目录整理 — 规则编辑 Modal（MP 同款：【存储器】【路径】两列布局）
// =============================================================================

// 通用"存储器+路径"行组件
const StoragePathRow = ({ label, tooltip, storageVal, pathVal, storageOptions,
  onStorageChange, onPathChange, onBrowse, browseLabel }) => (
  <Form.Item label={label} tooltip={tooltip} style={{ marginBottom: 12 }}>
    <Row gutter={8} align="middle">
      <Col flex="0 0 140px">
        <Select value={storageVal} onChange={onStorageChange}
          style={{ width: '100%' }} options={storageOptions} />
      </Col>
      <Col flex="1">
        <Input value={pathVal} placeholder="输入路径" onChange={e => onPathChange(e.target.value)} />
      </Col>
      <Col>
        <Button icon={<FolderOpenOutlined />} onClick={onBrowse}>{browseLabel || '浏览'}</Button>
      </Col>
    </Row>
  </Form.Item>
)

const OrgRuleModal = ({ open, rule, onOk, onCancel, storages }) => {
  const [draft, setDraft] = useState(rule)
  // 目录选择器：src用源存储，target/unrecognized用目标存储
  const [pickerState, setPickerState] = useState({ open: false, type: null, field: null })
  // type: 'p115' | 'local' | 'storage'

  useEffect(() => { if (open) setDraft(rule) }, [rule, open])

  const set = (patch) => setDraft(d => ({ ...d, ...patch }))

  const storageOptions = [
    { value: 'local', label: '本地' },
    ...storages.map(s => ({ value: String(s.id), label: s.name || s.type })),
  ]

  // 根据存储ID推断picker类型
  const pickerType = (storageId) => {
    if (!storageId || storageId === 'local') return 'local'
    const s = storages.find(x => String(x.id) === String(storageId))
    return s?.type === 'p115' ? 'p115' : 'storage'
  }

  const openPicker = (field, storageId) => {
    setPickerState({ open: true, type: pickerType(storageId), field, storageId })
  }

  const handleDirSelected = (p) => {
    const { field } = pickerState
    if (field === '__src__') set({ source_paths: [...(draft.source_paths || []), p] })
    else if (field) set({ [field]: p })
    setPickerState(s => ({ ...s, open: false }))
  }

  const pickerActiveStorage = pickerState.storageId
    ? storages.find(s => String(s.id) === String(pickerState.storageId)) || null
    : null

  const tgtBrowseLabel = pickerType(draft?.target_storage) === 'p115' ? '网盘' : '浏览'

  if (!draft) return null

  return (
    <>
      <Modal open={open} title={`编辑规则 — ${draft.name || ''}`}
        onOk={() => onOk(draft)} onCancel={onCancel}
        okText="确定" cancelText="取消" width={660} destroyOnHidden>
        <Form layout="vertical" size="small" style={{ marginTop: 8 }}>

          {/* ── 行1：规则别名 / 媒体类型 ── */}
          <Row gutter={16}>
            <Col span={14}>
              <Form.Item label="规则别名" style={{ marginBottom: 12 }}>
                <Input value={draft.name} onChange={e => set({ name: e.target.value })} placeholder="如：网盘待整理" />
              </Form.Item>
            </Col>
            <Col span={10}>
              <Form.Item label="媒体类型" style={{ marginBottom: 12 }}>
                <Select value={draft.media_type || 'all'} onChange={v => set({ media_type: v })} style={{ width: '100%' }}
                  options={[{ value: 'all', label: '全部' }, { value: 'movie', label: '电影' }, { value: 'tv', label: '剧集' }]} />
              </Form.Item>
            </Col>
          </Row>

          {/* ── 源目录（待整理目录，支持多条）── */}
          <Form.Item label="源目录（待整理目录）" tooltip="存放待整理文件的目录，支持添加多个；每条独立配置存储器和路径" style={{ marginBottom: 12 }}>
            {(draft.source_paths || []).map((p, si) => (
              <Row gutter={8} key={si} style={{ marginBottom: 6 }} align="middle">
                <Col flex="0 0 140px">
                  <Select
                    value={draft.source_storages?.[si] || draft.source_storage || 'local'}
                    onChange={v => {
                      const ss = [...(draft.source_storages || draft.source_paths.map(() => draft.source_storage || 'local'))]
                      ss[si] = v
                      set({ source_storages: ss })
                    }}
                    style={{ width: '100%' }} options={storageOptions} />
                </Col>
                <Col flex="1">
                  <Input value={p} placeholder="/待整理/下载"
                    onChange={e => set({ source_paths: draft.source_paths.map((v, i) => i === si ? e.target.value : v) })} />
                </Col>
                <Col>
                  <Button icon={<FolderOpenOutlined />}
                    onClick={() => openPicker('__src__', draft.source_storages?.[si] || draft.source_storage)} />
                </Col>
                <Col>
                  <Button danger size="small" icon={<DeleteOutlined />}
                    onClick={() => {
                      set({
                        source_paths: draft.source_paths.filter((_, i) => i !== si),
                        source_storages: (draft.source_storages || []).filter((_, i) => i !== si),
                      })
                    }} />
                </Col>
              </Row>
            ))}
            <Button size="small" icon={<PlusOutlined />} style={{ marginTop: 4 }}
              onClick={() => set({ source_paths: [...(draft.source_paths || []), ''] })}>
              添加源目录
            </Button>
          </Form.Item>

          {/* ── 目标目录 ── */}
          <StoragePathRow
            label="目标目录" tooltip="整理后文件的存放根目录，分类子目录将在此创建"
            storageVal={draft.target_storage || 'local'}
            pathVal={draft.target_root}
            storageOptions={storageOptions}
            onStorageChange={v => set({ target_storage: v })}
            onPathChange={v => set({ target_root: v })}
            onBrowse={() => openPicker('target_root', draft.target_storage)}
            browseLabel={tgtBrowseLabel}
          />

          {/* ── 未识别目录 ── */}
          <StoragePathRow
            label="未识别目录" tooltip="无法匹配分类规则的文件移入此目录，留空则保留在原位"
            storageVal={draft.target_storage || 'local'}
            pathVal={draft.unrecognized_dir}
            storageOptions={storageOptions}
            onStorageChange={v => set({ target_storage: v })}
            onPathChange={v => set({ unrecognized_dir: v })}
            onBrowse={() => openPicker('unrecognized_dir', draft.target_storage)}
            browseLabel={tgtBrowseLabel}
          />

          {/* ── 自动整理 + 监控模式 ── */}
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item label="自动整理" tooltip="选择自动整理触发方式" style={{ marginBottom: 12 }}>
                <Select value={draft.auto_organize || 'monitor'} onChange={v => set({ auto_organize: v })}
                  style={{ width: '100%' }}
                  options={[
                    { value: 'monitor', label: '目录监控' },
                    { value: 'none',    label: '不整理' },
                  ]} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label="监控模式"
                tooltip="兼容模式：轮询检测，稳定但有延迟；性能模式：系统事件驱动，实时但对部分网络盘不兼容"
                style={{ marginBottom: 12 }}>
                <Select
                  value={draft.monitor_mode || 'compatibility'}
                  onChange={v => set({ monitor_mode: v })}
                  disabled={draft.auto_organize === 'none'}
                  style={{ width: '100%' }}
                  options={[
                    { value: 'compatibility', label: '兼容模式' },
                    { value: 'performance',   label: '性能模式' },
                  ]} />
              </Form.Item>
            </Col>
          </Row>

          {/* ── 底部开关 ── */}
          <Row gutter={24}>
            <Col>
              <Form.Item label="试运行" tooltip="只记录日志，不实际移动文件" style={{ marginBottom: 0 }}>
                <Switch checked={draft.dry_run} onChange={v => set({ dry_run: v })} checkedChildren="开" unCheckedChildren="关" />
              </Form.Item>
            </Col>
            <Col>
              <Form.Item label="启用规则" style={{ marginBottom: 0 }}>
                <Switch checked={draft.enabled !== false} onChange={v => set({ enabled: v })} checkedChildren="是" unCheckedChildren="否" />
              </Form.Item>
            </Col>
          </Row>

        </Form>
      </Modal>

      {/* 目录选择器：根据存储类型切换 */}
      <DirPickerModal
        open={pickerState.open && pickerState.type === 'p115'}
        onClose={() => setPickerState(s => ({ ...s, open: false }))}
        onSelect={handleDirSelected} />
      <LocalDirPickerModal
        open={pickerState.open && pickerState.type === 'local'}
        onClose={() => setPickerState(s => ({ ...s, open: false }))}
        onSelect={handleDirSelected} />
      {pickerActiveStorage && (
        <StorageDirPickerModal
          open={pickerState.open && pickerState.type === 'storage'}
          onClose={() => setPickerState(s => ({ ...s, open: false }))}
          onSelect={handleDirSelected}
          storage={pickerActiveStorage} />
      )}
    </>
  )
}

// =============================================================================
// 目录整理 — 单条规则小卡片（固定 200px 宽，永不展开，点编辑图标弹 Modal）
// =============================================================================
const OrgRuleCard = ({ rule, idx, total, onEdit, onDelete, onMove, onRun, running, storages }) => {
  const enabled    = rule.enabled !== false
  const mediaType  = rule.media_type || 'all'
  const accentColor = mediaType === 'movie' ? '#1677ff' : mediaType === 'tv' ? '#7c3aed' : '#52c41a'
  const storageLabel = rule.source_storage === 'local' || !rule.source_storage
    ? '本地'
    : storages.find(s => String(s.id) === String(rule.source_storage))?.name || rule.source_storage

  return (
    <div style={{
      width: 200, flexShrink: 0, borderRadius: 10,
      border: `1px solid var(--ant-color-border, #e5e7eb)`,
      borderTop: `3px solid ${accentColor}`,
      background: 'var(--ant-color-bg-container, #fff)',
      boxShadow: '0 1px 4px rgba(0,0,0,.07)',
      opacity: enabled ? 1 : 0.5,
      display: 'flex', flexDirection: 'column',
      transition: 'box-shadow .2s',
    }}
      onMouseEnter={e => e.currentTarget.style.boxShadow = '0 4px 14px rgba(0,0,0,.14)'}
      onMouseLeave={e => e.currentTarget.style.boxShadow = '0 1px 4px rgba(0,0,0,.07)'}
    >
      {/* 卡片主体 */}
      <div style={{ padding: '14px 14px 8px', flex: 1, minHeight: 100 }}>
        <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 8, wordBreak: 'break-all', lineHeight: 1.3 }}>
          {rule.name || `规则 ${idx + 1}`}
        </div>
        <Space size={4} wrap style={{ marginBottom: 6 }}>
          <Tag color={MEDIA_TYPE_COLOR[mediaType]} style={{ fontSize: 11, margin: 0 }}>
            {MEDIA_TYPE_LABEL[mediaType]}
          </Tag>
          {rule.dry_run && <Tag color="orange" style={{ fontSize: 11, margin: 0 }}>试运行</Tag>}
          {!enabled && <Tag style={{ fontSize: 11, margin: 0 }}>已禁用</Tag>}
        </Space>
        <div style={{ fontSize: 11, color: '#999', marginTop: 2 }}>存储：{storageLabel}</div>
        {rule.target_root && (
          <div style={{ fontSize: 11, color: '#aaa', marginTop: 2, wordBreak: 'break-all' }}>
            目标：{rule.target_root}
          </div>
        )}
        {rule.source_paths?.length > 0 && (
          <div style={{ fontSize: 11, color: '#bbb', marginTop: 2 }}>
            {rule.source_paths.length} 个源目录
          </div>
        )}
      </div>
      {/* 底部操作栏 */}
      <div style={{
        borderTop: '1px solid var(--ant-color-border-secondary, #f0f0f0)',
        padding: '5px 8px', display: 'flex', justifyContent: 'space-between', alignItems: 'center',
      }}>
        <Space size={0}>
          <Tooltip title="上移">
            <Button size="small" type="text" icon={<ArrowUpOutlined />} disabled={idx === 0} onClick={() => onMove(-1)} />
          </Tooltip>
          <Tooltip title="下移">
            <Button size="small" type="text" icon={<ArrowDownOutlined />} disabled={idx === total - 1} onClick={() => onMove(1)} />
          </Tooltip>
          <Tooltip title="编辑配置">
            <Button size="small" type="text" icon={<EditOutlined />} onClick={onEdit} />
          </Tooltip>
        </Space>
        <Space size={0}>
          <Tooltip title="运行整理">
            <Button size="small" type="text" icon={<PlayCircleOutlined />} loading={running} onClick={onRun} />
          </Tooltip>
          <Tooltip title="删除">
            <Button size="small" type="text" danger icon={<DeleteOutlined />} onClick={onDelete} />
          </Tooltip>
        </Space>
      </div>
    </div>
  )
}


// =============================================================================
// Tab1 — 目录整理
// =============================================================================
const OrganizeTab = () => {
  const [rules,      setRules]      = useState([])
  const [saving,     setSaving]     = useState(false)
  const [loading,    setLoading]    = useState(true)
  const [running,    setRunning]    = useState({})
  const [orgStatus,  setOrgStatus]  = useState({})
  const [editingIdx, setEditingIdx] = useState(null)
  const [storages,   setStorages]   = useState([])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [rulesRes, stRes, storageRes] = await Promise.all([
        classifyApi.getOrganizeRules(),
        p115StrmApi.getOrganizeStatus(),
        storageApi.list(),
      ])
      const rulesData = rulesRes.data?.rules || rulesRes.data || []
      setRules(Array.isArray(rulesData) ? rulesData : [])
      setOrgStatus(stRes.data || {})
      // 只取已启用的存储源
      const storageList = Array.isArray(storageRes.data?.items)
        ? storageRes.data.items.filter(s => s.is_active !== 0)
        : Array.isArray(storageRes.data) ? storageRes.data.filter(s => s.is_active !== 0) : []
      setStorages(storageList)
    } catch { message.error('加载整理配置失败') }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { load() }, [load])

  const save = async () => {
    setSaving(true)
    try {
      await classifyApi.saveOrganizeRules(rules)
      message.success('整理配置已保存')
    } catch { message.error('保存失败') }
    finally { setSaving(false) }
  }

  const runRule = async (idx) => {
    setRunning(r => ({ ...r, [idx]: true }))
    try {
      const rule = rules[idx]
      const r = await p115StrmApi.runOrganize(rule.source_paths?.length ? rule.source_paths : undefined)
      r.data?.success ? message.success('整理任务已启动') : message.warning(r.data?.message || '启动失败')
      setTimeout(async () => {
        try { const s = await p115StrmApi.getOrganizeStatus(); setOrgStatus(s.data || {}) } catch { /* ignore */ }
      }, 1500)
    } catch { message.error('操作失败') }
    finally { setRunning(r => ({ ...r, [idx]: false })) }
  }

  const addRule = () => {
    const newIdx = rules.length
    setRules(rs => [...rs, { ...DEFAULT_ORG_RULE, name: `规则 ${rs.length + 1}` }])
    setEditingIdx(newIdx)
  }
  const updateRule = (idx, rule) => setRules(rs => rs.map((r, i) => i === idx ? rule : r))
  const deleteRule = (idx) => {
    setRules(rs => rs.filter((_, i) => i !== idx))
    setEditingIdx(ei => ei === idx ? null : ei > idx ? ei - 1 : ei)
  }
  const moveRule = (idx, dir) => {
    const ni = idx + dir
    if (ni < 0 || ni >= rules.length) return
    const next = [...rules]; [next[idx], next[ni]] = [next[ni], next[idx]]; setRules(next)
    setEditingIdx(ei => ei === idx ? ni : ei === ni ? idx : ei)
  }

  return (
    <Spin spinning={loading}>
      {/* ── 顶部工具栏 ── */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
        <Space size={8} wrap>
          <Tag color="blue" style={{ fontSize: 13, padding: '2px 10px' }}>{rules.length} 条规则</Tag>
          {orgStatus.running && <Tag color="processing" icon={<SyncOutlined spin />}>整理进行中</Tag>}
          {!orgStatus.running && orgStatus.last_organize && (
            <span style={{ fontSize: 12, color: '#888' }}>
              上次：{new Date(orgStatus.last_organize * 1000).toLocaleString()}
              {orgStatus.last_organize_stats && (
                <> &nbsp;·&nbsp;移动 <b>{orgStatus.last_organize_stats.moved ?? 0}</b>
                  &nbsp;·&nbsp;失败 <b style={{ color: orgStatus.last_organize_stats.errors ? '#f5222d' : 'inherit' }}>
                    {orgStatus.last_organize_stats.errors ?? 0}
                  </b>
                </>
              )}
            </span>
          )}
        </Space>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>刷新</Button>
          <Button icon={<PlusOutlined />} onClick={addRule}>添加规则</Button>
          <Button type="primary" icon={<SaveOutlined />} loading={saving} onClick={save}>保存配置</Button>
        </Space>
      </div>

      {/* ── 说明条 ── */}
      <Alert type="info" showIcon style={{ marginBottom: 16, borderRadius: 8 }}
        message="将源目录中的文件按「分类规则」（Tab2）自动整理到目标根目录下的对应子目录，支持多条规则独立配置和运行。" />

      {/* ── 横向小卡片列（MP 风格）── */}
      {rules.length === 0 ? (
        <div style={{
          padding: '64px 0', textAlign: 'center', color: '#bbb', fontSize: 14,
          border: '2px dashed #e5e7eb', borderRadius: 10,
          background: 'var(--ant-color-fill-quaternary, rgba(0,0,0,.02))',
        }}>
          <FolderAddOutlined style={{ fontSize: 36, marginBottom: 12, display: 'block' }} />
          暂无整理规则，点击「添加规则」开始配置
        </div>
      ) : (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, paddingBottom: 8 }}>
          {rules.map((rule, idx) => (
            <OrgRuleCard
              key={idx}
              rule={rule}
              idx={idx}
              total={rules.length}
              onEdit={() => setEditingIdx(idx)}
              onDelete={() => deleteRule(idx)}
              onMove={dir => moveRule(idx, dir)}
              onRun={() => runRule(idx)}
              running={!!running[idx]}
              storages={storages}
            />
          ))}
        </div>
      )}

      <OrgRuleModal
        open={editingIdx !== null}
        rule={editingIdx !== null ? rules[editingIdx] : null}
        storages={storages}
        onOk={(updated) => { updateRule(editingIdx, updated); setEditingIdx(null) }}
        onCancel={() => setEditingIdx(null)}
      />
    </Spin>
  )
}

// =============================================================================
// Tab3 — 重命名刮削
// =============================================================================
const ScrapeTab = () => {
  const [scrapeCfg, setScrapeCfg] = useState({
    enabled: false,
    movie_format: '{title} ({year})/{title} ({year})',
    tv_format:    '{title} ({year})/Season {season:02d}/{title} - {season_episode} - {episode_title}',
  })
  const [saving,           setSaving]           = useState(false)
  const [loading,          setLoading]          = useState(true)
  const [scrapeActiveInput, setScrapeActiveInput] = useState('movie')
  const movieFormatRef = useRef(null)
  const tvFormatRef    = useRef(null)

  useEffect(() => {
    p115Api.getScrapeConfig()
      .then(({ data }) => { if (data) setScrapeCfg(data) })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  const handleSave = async () => {
    setSaving(true)
    try { await p115Api.saveScrapeConfig(scrapeCfg); message.success('刮削配置已保存') }
    catch { message.error('保存失败') }
    finally { setSaving(false) }
  }

  const insertParam = (param) => {
    const key = scrapeActiveInput === 'movie' ? 'movie_format' : 'tv_format'
    const ref = scrapeActiveInput === 'movie' ? movieFormatRef : tvFormatRef
    const el  = ref.current?.input || ref.current
    if (el) {
      const start = el.selectionStart ?? el.value.length
      const end   = el.selectionEnd   ?? el.value.length
      const val   = scrapeCfg[key] || ''
      const next  = val.slice(0, start) + param + val.slice(end)
      setScrapeCfg(c => ({ ...c, [key]: next }))
      setTimeout(() => { el.focus(); el.setSelectionRange(start + param.length, start + param.length) }, 0)
    } else {
      setScrapeCfg(c => ({ ...c, [key]: (c[key] || '') + param }))
    }
  }

  const currentParams = scrapeActiveInput === 'movie' ? SCRAPE_PARAMS_MOVIE : SCRAPE_PARAMS_TV

  return (
    <Spin spinning={loading}>
      <Row gutter={[24, 24]}>
        <Col xs={24} lg={14}>
          <Card
            title={<Space><NodeIndexOutlined />重命名格式配置</Space>}
            extra={<Button type="primary" icon={<SaveOutlined />} loading={saving} onClick={handleSave}>保存配置</Button>}
          >
            <Form layout="vertical" size="small">
              <Form.Item label="启用刮削重命名">
                <Switch checked={scrapeCfg.enabled} onChange={v => setScrapeCfg(c => ({ ...c, enabled: v }))}
                  checkedChildren="启用" unCheckedChildren="禁用" />
              </Form.Item>

              <Divider orientation="left" orientationMargin={0} style={{ fontSize: 13 }}>
                <i className="iconfont icon-dianying" style={{ marginRight: 6 }} />电影
              </Divider>
              <Form.Item label="电影命名格式" tooltip="支持 / 分隔目录层级">
                <Input ref={movieFormatRef} value={scrapeCfg.movie_format}
                  placeholder="{title} ({year})/{title} ({year})"
                  onFocus={() => setScrapeActiveInput('movie')}
                  onChange={e => setScrapeCfg(c => ({ ...c, movie_format: e.target.value }))}
                  style={{ padding: '10px 11px' }} />
              </Form.Item>
              <div style={{ background: 'var(--ant-color-fill-quaternary,rgba(0,0,0,.04))', borderRadius: 6,
                padding: '8px 12px', marginBottom: 16, fontSize: 12 }}>
                <span style={{ color: '#888' }}>预览：</span>
                <code style={{ color: 'var(--ant-color-primary,#1677ff)', wordBreak: 'break-all' }}>
                  {previewFormat(scrapeCfg.movie_format, MOVIE_SAMPLE)}
                </code>
              </div>

              <Divider orientation="left" orientationMargin={0} style={{ fontSize: 13 }}>
                <i className="iconfont icon-dianshiju" style={{ marginRight: 6 }} />电视节目
              </Divider>
              <Form.Item label="剧集命名格式" tooltip="支持 / 分隔目录层级">
                <Input ref={tvFormatRef} value={scrapeCfg.tv_format}
                  placeholder="{title} ({year})/Season {season:02d}/{title} - {season_episode} - {episode_title}"
                  onFocus={() => setScrapeActiveInput('tv')}
                  onChange={e => setScrapeCfg(c => ({ ...c, tv_format: e.target.value }))}
                  style={{ padding: '10px 11px' }} />
              </Form.Item>
              <div style={{ background: 'var(--ant-color-fill-quaternary,rgba(0,0,0,.04))', borderRadius: 6,
                padding: '8px 12px', fontSize: 12 }}>
                <span style={{ color: '#888' }}>预览：</span>
                <code style={{ color: 'var(--ant-color-primary,#1677ff)', wordBreak: 'break-all' }}>
                  {previewFormat(scrapeCfg.tv_format, TV_SAMPLE)}
                </code>
              </div>
            </Form>
          </Card>
        </Col>

        <Col xs={24} lg={10}>
          <Card title={<Space><PlusOutlined />可用参数</Space>} style={{ position: 'sticky', top: 24 }}>
            <Alert type="info" showIcon style={{ marginBottom: 12 }}
              message={scrapeActiveInput === 'movie' ? '当前编辑：电影格式' : '当前编辑：剧集格式'} />
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
              {currentParams.map(({ param, label }) => (
                <Tooltip key={param} title={param}>
                  <Button size="small" onClick={() => insertParam(param)}
                    style={{ fontFamily: 'monospace', fontSize: 12 }}>{label}</Button>
                </Tooltip>
              ))}
            </div>
            <Divider style={{ margin: '12px 0' }} />
            <div style={{ fontSize: 11, color: '#888', lineHeight: 1.8 }}>
              <div>• 点击参数按钮将其插入当前聚焦的格式输入框</div>
              <div>• <code>/</code> 分隔文件夹层级，如 <code>{'{title}'} ({'{year}'})/...</code></div>
              <div>• <code>:02d</code> 表示补零，如 <code>{'{season:02d}'}</code> → <code>01</code></div>
            </div>
          </Card>
        </Col>
      </Row>
    </Spin>
  )
}

// =============================================================================
// 主页面
// =============================================================================
export const Classify = () => {
  const [cfg,       setCfg]       = useState(DEFAULT_CONFIG)
  const [uiCats,    setUiCats]    = useState([])
  const [mode,      setMode]      = useState('gui')
  const [codeText,  setCodeText]  = useState('')
  const [saving,    setSaving]    = useState(false)
  const [loading,   setLoading]   = useState(true)
  const [providers, setProviders] = useState([])
  const [editCat,   setEditCat]   = useState(null)
  const [editIdx,   setEditIdx]   = useState(null)

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
      const ui = (data.categories || []).map(apiCatToUiCat)
      setUiCats(ui)
      setCodeText(uiCatsToYaml(ui))
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
      setCodeText(uiCatsToYaml(uiCats))
    } else {
      try {
        const parsed = parseYamlCfg(codeText)
        setUiCats(parsed)
      } catch {
        message.warning('格式解析失败，已保留图形化设置')
      }
    }
    setMode(m)
  }

  // ── 保存 ──
  const handleSave = async () => {
    let cats = uiCats
    if (mode === 'code') {
      try { cats = parseYamlCfg(codeText) }
      catch { message.error('格式解析错误'); return }
      setUiCats(cats)
    }
    const payload = { ...cfg, categories: cats.map(uiCatToApiCat) }
    setSaving(true)
    try {
      await classifyApi.saveConfig(payload)
      setCfg(payload)
      message.success('分类配置已保存')
    } catch {
      message.error('保存失败')
    } finally {
      setSaving(false)
    }
  }

  // ── 分类操作 ──
  const addCat = () => {
    const newCat = { name:'新分类', target_dir:'', media_type:'all', match_all:false, genre_ids:[], country:[], language:[], keyword:[], keyword_dir:[], regex:[] }
    setUiCats(c => [...c, newCat])
    setEditCat(newCat)
    setEditIdx(uiCats.length)
  }
  const openEdit = (cat, idx) => { setEditCat({ ...cat }); setEditIdx(idx) }
  const onEditOk = updated => {
    setUiCats(c => c.map((x,i) => i===editIdx ? updated : x))
    setEditCat(null); setEditIdx(null)
  }
  const deleteCat = i => setUiCats(c => c.filter((_,ci) => ci!==i))
  const moveCat = (i, dir) => {
    const ni = i+dir
    if (ni<0||ni>=uiCats.length) return
    const next=[...uiCats]; [next[i],next[ni]]=[next[ni],next[i]]; setUiCats(next)
  }
  const setCfgField = patch => setCfg(c => ({ ...c, ...patch }))

  const allUnavailable = providers.length>0 && providers.every(p=>!p.available)

  // ── Tab2 分类规则内容 ──
  const classifyContent = (
    <Spin spinning={loading}>
      {/* Provider 未配置提示 */}
      {allUnavailable && (
        <Alert type="warning" showIcon style={{ marginBottom:16 }}
          message="元数据 Provider 均未配置，流派 / 产地 / 语言规则将不生效，仅文件名关键词和正则有效。"
          description='可在「搜索源」或「系统设置」中配置 API Key。' />
      )}
      {/* 页头操作区 */}
      <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between', flexWrap:'wrap', gap:12, marginBottom:16 }}>
        <Space align="center" size={10}>
          <Tag color="purple" style={{ borderRadius:20, fontWeight:600 }}>{uiCats.length} 个分类</Tag>
          {providers.map(p=>(
            <Tag key={p.name}
              icon={p.available?<CheckCircleFilled />:<ExclamationCircleFilled />}
              color={p.available?'success':'warning'} style={{ fontSize:12 }}>
              {p.label} {p.available?'已配置':'未配置'}
            </Tag>
          ))}
        </Space>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>刷新</Button>
          <Segmented value={mode} onChange={switchMode} options={[
            { value:'gui',  label:<Space size={4}><AppstoreOutlined />图形化</Space> },
            { value:'code', label:<Space size={4}><CodeOutlined />代码</Space> },
          ]} />
          <Button type="primary" icon={<SaveOutlined />} loading={saving} onClick={handleSave}>保存配置</Button>
        </Space>
      </div>

      {mode==='gui' ? (
        <>
          {/* 全局设置 */}
          <Card size="small" style={{ marginBottom:16 }}
            styles={{ body:{ padding:'14px 20px' } }}>
            <Row gutter={[32,0]} align="middle">
              <Col>
                <Form.Item label="启用分类引擎" style={{ margin:0 }}>
                  <Switch checked={cfg.enabled} checkedChildren="启用" unCheckedChildren="禁用"
                    onChange={v=>setCfgField({ enabled:v })} />
                </Form.Item>
              </Col>
              <Col>
                <Alert type="info" showIcon style={{ margin:0, padding:'4px 12px' }}
                  message="分类引擎只定义规则，源目录和目标目录由各调用任务（如115整理）传入" />
              </Col>
            </Row>
          </Card>

          {/* 分类列表 */}
          <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between', marginBottom:10 }}>
            <Typography.Text type="secondary" style={{ fontSize:12 }}>
              匹配优先级从上到下 · 点击「编辑」修改分类条件
            </Typography.Text>
            <Button type="primary" icon={<PlusOutlined />} onClick={addCat}>添加分类</Button>
          </div>

          {uiCats.length===0
            ? <div style={{ padding:'60px 0', textAlign:'center', color:'#bbb', fontSize:14, border:'2px dashed #e5e7eb', borderRadius:10 }}>
                暂无分类规则，点击「添加分类」开始配置
              </div>
            : uiCats.map((cat,i)=>(
              <CategoryItem key={i} cat={cat} idx={i} total={uiCats.length}
                color={CAT_COLORS[i%CAT_COLORS.length]}
                onEdit={()=>openEdit(cat,i)}
                onDelete={()=>deleteCat(i)}
                onMove={dir=>moveCat(i,dir)}
              />
            ))
          }
        </>
      ) : (
        <CodePanel value={codeText} onChange={setCodeText} />
      )}

      {/* 编辑弹窗 */}
      <EditCategoryModal
        open={editCat!==null}
        cat={editCat}
        onOk={onEditOk}
        onCancel={()=>{ setEditCat(null); setEditIdx(null) }}
      />
    </Spin>
  )

  return (
    <div style={{ padding: 24 }}>
      <Tabs
        items={[
          {
            key: 'organize',
            label: <Space><FolderAddOutlined />目录整理</Space>,
            children: <OrganizeTab />,
          },
          {
            key: 'classify',
            label: <Space><AppstoreOutlined />分类规则</Space>,
            children: classifyContent,
          },
          {
            key: 'scrape',
            label: <Space><NodeIndexOutlined />重命名刮削</Space>,
            children: <ScrapeTab />,
          },
        ]}
      />
    </div>
  )
}

export default Classify

