// LevelSegmented.jsx — 三档日志级别滑动选择器，选中态颜色跟随级别色
import { useMemo } from 'react'
import { Segmented } from 'antd'

// 三档选项及对应的"显示哪些级别"映射
// CRITICAL / ERROR 在任何档位都强制显示
export const LEVEL_SLIDER_OPTIONS = ['DEBUG', 'INFO', 'WARNING']
export const LEVEL_SHOW_MAP = {
  DEBUG:   new Set(['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']),
  INFO:    new Set(['INFO', 'WARNING', 'ERROR', 'CRITICAL']),
  WARNING: new Set(['WARNING', 'ERROR', 'CRITICAL']),
}

// 各级别的选中主色（亮/暗主题）
const LEVEL_ACTIVE_COLOR = {
  dark:  { DEBUG: '#1677ff', INFO: '#52c41a', WARNING: '#faad14' },
  light: { DEBUG: '#1565c0', INFO: '#2e7d32', WARNING: '#e65100' },
}

// 每个实例生成唯一 className，避免多个组件互相干扰
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

