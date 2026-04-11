// LevelSegmented.jsx — 三档日志级别滑动选择器
// 排列：INFO → WARN → DEBUG
// INFO = INFO + ERROR
// WARN = INFO + WARNING + ERROR
// DEBUG = 全部
import { useMemo } from 'react'
import { Segmented } from 'antd'

export const LEVEL_SLIDER_OPTIONS = ['INFO', 'WARN', 'DEBUG']
export const LEVEL_SHOW_MAP = {
  INFO:  new Set(['INFO', 'ERROR', 'CRITICAL']),
  WARN:  new Set(['INFO', 'WARNING', 'ERROR', 'CRITICAL']),
  DEBUG: new Set(['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']),
}

const LEVEL_ACTIVE_COLOR = {
  dark:  { INFO: '#52c41a', WARN: '#faad14', DEBUG: '#1677ff' },
  light: { INFO: '#2e7d32', WARN: '#e65100', DEBUG: '#1565c0' },
}

let _uid = 0

export default function LevelSegmented({ value, onChange, isDark }) {
  const cls = useMemo(() => `lvl-seg-${++_uid}`, [])
  const activeColor = (isDark ? LEVEL_ACTIVE_COLOR.dark : LEVEL_ACTIVE_COLOR.light)[value] ?? '#1677ff'

  return (
    <>
      <style>{`
        .${cls} .ant-segmented-item-selected {
          background-color: ${activeColor} !important;
          color: #fff !important;
          transition: background-color 0.25s, color 0.25s;
        }
        .${cls} .ant-segmented-item {
          transition: color 0.25s;
        }
      `}</style>
      <Segmented
        className={cls}
        size="small"
        value={value}
        onChange={onChange}
        options={LEVEL_SLIDER_OPTIONS.map(lv => ({ value: lv, label: lv }))}
      />
    </>
  )
}

