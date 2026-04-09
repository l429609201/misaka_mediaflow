 // web/src/pages/drive115-strm/index.jsx
 // 115 STRM 同步管理 — 全量同步 + 增量触发 + 刮削配置 + URL模板
 // 从原 drive115/index.jsx 右列拆分而来，全部 i18n，增量改为纯触发按钮
 
 import { useCallback, useEffect, useRef, useState } from 'react'
 import {
   Alert, Button, Card, Col, Divider, Form, Input, Row,
   Select, Space, Switch, Tag, Tooltip, Typography, message, theme,
 } from 'antd'
 import {
   CodeOutlined, FolderOpenOutlined, NodeIndexOutlined,
   SaveOutlined, SyncOutlined,
 } from '@ant-design/icons'
 import { useTranslation } from 'react-i18next'
 import { p115StrmApi, strmApi } from '@/apis'
 import DirPickerModal from '@/components/DirPickerModal'
 import LocalDirPickerModal from '@/components/LocalDirPickerModal'
 
 const { Text, Title } = Typography
 
 const DEFAULT_TEMPLATE =
   '{{ base_url }}?pickcode={{ pickcode }}{% if file_name %}&file_name={{ file_name | urlencode }}{% endif %}'
 
 const TEMPLATE_PARAMS = [
   { label: '{{ base_url }}',                 insert: '{{ base_url }}' },
   { label: '{{ pickcode }}',                 insert: '{{ pickcode }}' },
   { label: '{{ file_name }}',                insert: '{{ file_name }}' },
   { label: 'file_name | urlencode',          insert: '{{ file_name | urlencode }}' },
   { label: '{{ file_path }}',                insert: '{{ file_path }}' },
   { label: 'file_path | urlencode',          insert: '{{ file_path | urlencode }}' },
   { label: '{{ sha1 }}',                     insert: '{{ sha1 }}' },
   { label: '{% if file_name %}…{% endif %}', insert: '{% if file_name %}{% endif %}' },
 ]
 
 const StatTag = ({ value, label, color }) => (
   <Tag color={color} style={{ fontSize: 13, padding: '2px 10px' }}>
     {label}: <b>{value ?? 0}</b>
   </Tag>
 )
 
 export const Drive115Strm = () => {
   const { t } = useTranslation()
   const { token } = theme.useToken()
 
   const [strmStatus,    setStrmStatus]    = useState({})
   const [strmSyncing,   setStrmSyncing]   = useState(false)
   const [strmCfgSaving, setStrmCfgSaving] = useState(false)
 
   const SYNC_DEFAULTS = { use_custom: false, cloud_path: '', strm_path: '' }
   const [fullSyncCfg,     setFullSyncCfg]     = useState({ ...SYNC_DEFAULTS })
   const [fullOverwriteMode, setFullOverwriteMode] = useState('skip')
   const [scrapeEnabled,   setScrapeEnabled]   = useState(false)
   const [scrapeDownloadImg, setScrapeDownloadImg] = useState(true)
   const [episodeGroupId,  setEpisodeGroupId]  = useState('')
   const [urlTemplate,     setUrlTemplate]     = useState('')
   const templateRef = useRef(null)
 
   const [syncPickerState, setSyncPickerState] = useState({ open: false, field: null, type: 'cloud' })
 
   // ── 数据加载 ──────────────────────────────────────────────────────────
   const fetchAll = useCallback(async () => {
     try {
       const [cfgRes, stRes, tmplRes] = await Promise.all([
         p115StrmApi.getSyncConfig(),
         p115StrmApi.getSyncStatus(),
         strmApi.getUrlTemplate(),
       ])
       setStrmStatus(stRes.data || {})
       setUrlTemplate(tmplRes.data?.template || DEFAULT_TEMPLATE)
       const cfg = cfgRes.data || {}
       if (cfg.full_sync_cfg)         setFullSyncCfg(c => ({ ...c, ...cfg.full_sync_cfg }))
       if (cfg.full_overwrite_mode)   setFullOverwriteMode(cfg.full_overwrite_mode)
       if (cfg.enable_scrape         !== undefined) setScrapeEnabled(cfg.enable_scrape)
       if (cfg.scrape_download_image !== undefined) setScrapeDownloadImg(cfg.scrape_download_image)
       if (cfg.episode_group_id      !== undefined) setEpisodeGroupId(cfg.episode_group_id)
     } catch { /* ignore */ }
   }, [])
 
   useEffect(() => { fetchAll() }, [fetchAll])
 
   // ── 全量同步 ───────────────────────────────────────────────────────────
   const handleFullSync = async () => {
     setStrmSyncing(true)
     try {
       const payload = fullSyncCfg.use_custom && fullSyncCfg.cloud_path && fullSyncCfg.strm_path
         ? { cloud_path: fullSyncCfg.cloud_path, strm_path: fullSyncCfg.strm_path }
         : undefined
       const r = await p115StrmApi.fullSync(payload)
       r.data?.success
         ? message.success(t('p115.syncStarted'))
         : message.warning(r.data?.message || t('p115.syncStartFailed'))
       setTimeout(fetchAll, 1500)
     } catch { message.error(t('common.failed')) }
     finally { setStrmSyncing(false) }
   }
 
   // ── 增量同步（纯触发，无路径配置）────────────────────────────────────
   const handleIncSync = async () => {
     setStrmSyncing(true)
     try {
       const r = await p115StrmApi.incSync()
       r.data?.success
         ? message.success(t('p115.syncStarted'))
         : message.warning(r.data?.message || t('p115.syncStartFailed'))
       setTimeout(fetchAll, 1500)
     } catch { message.error(t('common.failed')) }
     finally { setStrmSyncing(false) }
   }
 
   // ── 保存配置 ─────────────────────────────────────────────────────────
   const handleSaveConfig = async () => {
     setStrmCfgSaving(true)
     try {
       await p115StrmApi.saveSyncConfig({
         full_sync_cfg:         fullSyncCfg,
         full_overwrite_mode:   fullOverwriteMode,
         enable_scrape:         scrapeEnabled,
         scrape_download_image: scrapeDownloadImg,
         episode_group_id:      episodeGroupId,
       })
       await strmApi.saveUrlTemplate(urlTemplate)
       message.success(t('p115.configSaved'))
     } catch { message.error(t('p115.saveFailed')) }
     finally { setStrmCfgSaving(false) }
   }
 
   // ── 目录选择器 ────────────────────────────────────────────────────────
   const openSyncPicker = (field, type) => setSyncPickerState({ open: true, field, type })
   const handleSyncDirSelected = (p) => {
     setFullSyncCfg(c => ({ ...c, [syncPickerState.field]: p }))
     setSyncPickerState(s => ({ ...s, open: false }))
   }
 
   // ── URL模板光标插入 ───────────────────────────────────────────────────
   const insertAtCursor = (snippet) => {
     const el = templateRef.current
     if (!el) { setUrlTemplate(s => s + snippet); return }
     const start = el.selectionStart ?? urlTemplate.length
     const end   = el.selectionEnd   ?? urlTemplate.length
     setUrlTemplate(urlTemplate.slice(0, start) + snippet + urlTemplate.slice(end))
     requestAnimationFrame(() => { el.focus(); el.setSelectionRange(start + snippet.length, start + snippet.length) })
   }
 
   const strmProgress = strmStatus.progress || {}
   const fullStats    = strmStatus.last_full_sync_stats || {}
   const incStats     = strmStatus.last_inc_sync_stats  || {}
 
   return (
     <div style={{ padding: 24 }}>
       <Title level={4} style={{ marginBottom: 16 }}>
         <Space><SyncOutlined />{t('menu.drive115Strm')}</Space>
       </Title>
       <Row gutter={[24, 24]}>
 
         {/* 左列：全量同步 + 刮削 + 覆盖模式 */}
         <Col xs={24} lg={12}>
           <Card
             title={<Space><SyncOutlined />{t('p115.strmGeneration')}</Space>}
             extra={
               <Space size="small">
                 <Button icon={<SyncOutlined spin={strmStatus.running} />} size="small" onClick={fetchAll}>
                   {t('p115.refreshStatus')}
                 </Button>
                 <Button type="primary" icon={<SaveOutlined />} size="small" loading={strmCfgSaving} onClick={handleSaveConfig}>
                   {t('common.save')}
                 </Button>
               </Space>
             }
           >
             {/* ── 全量同步 ── */}
             <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
               <Text strong style={{ fontSize: 13 }}>{t('p115.fullSync')}</Text>
               <Text type="secondary" style={{ fontSize: 11 }}>
                 {t('p115.lastFullSync')}：{strmStatus.last_full_sync
                   ? new Date(strmStatus.last_full_sync * 1000).toLocaleString() : '—'}
               </Text>
             </div>
             <Space size={4} wrap style={{ marginBottom: 10 }}>
               <StatTag value={fullStats.created} label={t('p115.statGenerated')} color="green" />
               <StatTag value={fullStats.skipped} label={t('p115.statSkipped')}   color="default" />
               <StatTag value={fullStats.errors}  label={t('p115.statFailed')}    color="red" />
             </Space>
             {/* 全局/自定义路径开关 */}
             <div style={{
               display: 'flex', alignItems: 'center', justifyContent: 'space-between',
               background: fullSyncCfg.use_custom ? '#f6ffed' : '#f5f5f5',
               border: `1px solid ${fullSyncCfg.use_custom ? '#b7eb8f' : '#d9d9d9'}`,
               borderRadius: 8, padding: '7px 12px', marginBottom: 8, transition: 'all .25s',
             }}>
               <div>
                 <Text strong style={{ fontSize: 12 }}>{fullSyncCfg.use_custom ? t('p115.strmPrefixHint') : t('p115.strmPathFromMapping')}</Text>
                 <div style={{ fontSize: 11, color: '#888' }}>
                   {fullSyncCfg.use_custom ? t('p115.cloudPrefixHint') : t('p115.strmPathFromMapping')}
                 </div>
               </div>
               <Switch size="small" checked={fullSyncCfg.use_custom}
                 onChange={v => setFullSyncCfg(c => ({ ...c, use_custom: v }))} />
             </div>
             <Form layout="vertical" size="small" style={{ marginBottom: 0 }}>
               <Form.Item label={t('p115.cloudPrefix')} style={{ marginBottom: 6 }}>
                 <Input size="small" disabled={!fullSyncCfg.use_custom}
                   placeholder={fullSyncCfg.use_custom ? '/影音' : t('p115.strmPathFromMapping')}
                   value={fullSyncCfg.cloud_path}
                   onChange={e => setFullSyncCfg(c => ({ ...c, cloud_path: e.target.value }))}
                   addonAfter={
                     <Button type="link" size="small" icon={<FolderOpenOutlined />} disabled={!fullSyncCfg.use_custom}
                       onClick={() => fullSyncCfg.use_custom && openSyncPicker('cloud_path', 'cloud')}
                       style={{ padding: 0, height: 'auto' }}>{t('p115.selectDir')}</Button>
                   }
                 />
               </Form.Item>
               <Form.Item label={t('p115.strmPrefix')} style={{ marginBottom: 10 }}>
                 <Input size="small" disabled={!fullSyncCfg.use_custom}
                   placeholder={fullSyncCfg.use_custom ? '/data/strm' : t('p115.strmPathFromMapping')}
                   value={fullSyncCfg.strm_path}
                   onChange={e => setFullSyncCfg(c => ({ ...c, strm_path: e.target.value }))}
                   addonAfter={
                     <Button type="link" size="small" icon={<FolderOpenOutlined />} disabled={!fullSyncCfg.use_custom}
                       onClick={() => fullSyncCfg.use_custom && openSyncPicker('strm_path', 'local')}
                       style={{ padding: 0, height: 'auto' }}>{t('p115.selectDir')}</Button>
                   }
                 />
               </Form.Item>
             </Form>
             {/* 刮削配置 */}
             <Divider orientation="left" orientationMargin={0} style={{ margin: '4px 0 10px', fontSize: 13, fontWeight: 600 }}>
               <Space size={6}><NodeIndexOutlined />{t('p115.scrapeTitle')}</Space>
             </Divider>
             <div style={{ background: '#f6ffed', border: '1px solid #b7eb8f', borderRadius: 8, padding: '10px 14px', marginBottom: 10 }}>
               <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: scrapeEnabled ? 10 : 0 }}>
                 <div>
                   <Text strong style={{ fontSize: 12 }}>{t('p115.scrapeEnabled')}</Text>
                   <div style={{ fontSize: 11, color: '#888' }}>{t('p115.scrapeEnabledHint')}</div>
                 </div>
                 <Switch checked={scrapeEnabled} onChange={setScrapeEnabled} size="small" />
               </div>
               {scrapeEnabled && (
                 <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                   <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                     <Text style={{ fontSize: 12 }}>{t('p115.scrapeParamTitle')}</Text>
                     <Switch checked={scrapeDownloadImg} onChange={setScrapeDownloadImg} size="small" />
                   </div>
                   <div>
                     <Text style={{ fontSize: 12, display: 'block', marginBottom: 4 }}>
                       {t('p115.scrapeParamSeasonEpisode')}
                       <Tooltip title={t('p115.scrapeTvFormatHint')}>
                         <span style={{ marginLeft: 4, color: '#999', cursor: 'help' }}>(?)</span>
                       </Tooltip>
                     </Text>
                     <Input size="small" value={episodeGroupId} onChange={e => setEpisodeGroupId(e.target.value)} allowClear />
                   </div>
                 </div>
               )}
             </div>
             {/* 覆盖模式 */}
             <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', background: '#f9f0ff', border: '1px solid #d3adf7', borderRadius: 8, padding: '7px 12px', marginBottom: 12 }}>
               <div>
                 <Text strong style={{ fontSize: 12 }}>{t('p115.strmMode')}</Text>
                 <div style={{ fontSize: 11, color: '#888' }}>
                   {fullOverwriteMode === 'skip' ? t('p115.statSkipped') : t('p115.scrapeEnabled')}
                 </div>
               </div>
               <Select size="small" value={fullOverwriteMode} onChange={setFullOverwriteMode} style={{ width: 90 }}
                 options={[
                   { value: 'skip',      label: t('p115.statSkipped') },
                   { value: 'overwrite', label: t('p115.scrapeEnabled') },
                 ]}
               />
             </div>
             {strmStatus.running && (
               <Alert style={{ marginBottom: 8 }} type="info" showIcon
                 message={t('p115.syncInProgress', { count: strmProgress.created || 0 })} />
             )}
             <Button type="primary" block style={{ marginBottom: 8 }}
               loading={strmSyncing || strmStatus.running} onClick={handleFullSync}>
               {t('p115.fullSync')}
             </Button>
 
             <Divider style={{ margin: '4px 0 12px' }} />
 
             {/* ── 增量同步（纯触发按钮）── */}
             <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
               <div>
                 <Text strong style={{ fontSize: 13 }}>{t('p115.incSync')}</Text>
                 <div style={{ fontSize: 11, color: '#888' }}>
                   {t('p115.lastIncSync')}：{strmStatus.last_inc_sync
                     ? new Date(strmStatus.last_inc_sync * 1000).toLocaleString() : '—'}
                 </div>
               </div>
               <Space size={4} wrap>
                 <StatTag value={incStats.created} label={t('p115.statGenerated')} color="green" />
                 <StatTag value={incStats.errors}  label={t('p115.statFailed')}    color="red" />
               </Space>
             </div>
             <Button block loading={strmSyncing || strmStatus.running} onClick={handleIncSync}>
               {t('p115.incSync')}
             </Button>
           </Card>
         </Col>
 
         {/* 右列：STRM URL 模板 */}
         <Col xs={24} lg={12}>
           <Card title={<Space><CodeOutlined />STRM URL {t('p115.strmMode')}</Space>}>
             <Alert type="info" showIcon style={{ marginBottom: 12 }}
               message={t('p115.strmPreviewHint')} />
             <div style={{ marginBottom: 10 }}>
               <Text type="secondary" style={{ display: 'block', marginBottom: 6, fontSize: 12 }}>
                 {t('p115.strmPreviewLabel')}
               </Text>
               <Space wrap size={[6, 6]}>
                 {TEMPLATE_PARAMS.map(p => (
                   <Tooltip key={p.label} title={p.label}>
                     <Button size="small" onClick={() => insertAtCursor(p.insert)}>{p.label}</Button>
                   </Tooltip>
                 ))}
               </Space>
             </div>
             <textarea
               ref={templateRef}
               value={urlTemplate}
               onChange={e => setUrlTemplate(e.target.value)}
               rows={5}
               spellCheck={false}
               style={{
                 width: '100%', padding: '8px 12px', fontFamily: 'monospace', fontSize: 12,
                 border: `1px solid ${token.colorBorder}`, borderRadius: token.borderRadius,
                 resize: 'vertical', outline: 'none', lineHeight: 1.6, boxSizing: 'border-box',
                 background: token.colorBgContainer, color: token.colorText,
               }}
             />
             <Space style={{ marginTop: 10 }}>
               <Button onClick={() => setUrlTemplate(DEFAULT_TEMPLATE)}>{t('common.reset')}</Button>
             </Space>
           </Card>
         </Col>
 
       </Row>
 
       <DirPickerModal
         open={syncPickerState.open && syncPickerState.type === 'cloud'}
         onClose={() => setSyncPickerState(s => ({ ...s, open: false }))}
         onSelect={handleSyncDirSelected}
       />
       <LocalDirPickerModal
         open={syncPickerState.open && syncPickerState.type === 'local'}
         onClose={() => setSyncPickerState(s => ({ ...s, open: false }))}
         onSelect={handleSyncDirSelected}
       />
     </div>
   )
 }
 
 export default Drive115Strm
