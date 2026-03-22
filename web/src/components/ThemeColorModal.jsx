// src/components/ThemeColorModal.jsx — 对标弹幕库 ThemeColorPicker
// 圆形色块 + 4列网格 + 自定义颜色输入框 + 当前主题色实时预览

import { useRef, useState } from 'react'
import { Modal, Tooltip, Typography, Divider } from 'antd'
import { CheckOutlined } from '@ant-design/icons'
import { useTranslation } from 'react-i18next'
import { useThemeContext } from '@/ThemeProvider'

const { Text } = Typography

export default function ThemeColorModal({ open, onClose }) {
  const { t } = useTranslation()
  const { isDark, colorPrimary, setColorPrimary, PRESET_COLORS } = useThemeContext()
  const [customColor, setCustomColor] = useState(colorPrimary)
  const colorInputRef = useRef(null)

  const handlePreset = (color) => { setColorPrimary(color); setCustomColor(color) }
  const handleCustom = (e) => { setCustomColor(e.target.value); setColorPrimary(e.target.value) }

  const labelClr = isDark ? '#aaa' : '#666'

  return (
    <Modal
      title={t('settings.themeColor', '主题色切换')}
      open={open} onCancel={onClose} footer={null}
      width={380} centered destroyOnClose
    >
      <div style={{ paddingTop: 8 }}>
        {/* 预设色板 — 4列网格，圆形色块（弹幕库同款） */}
        <Text style={{ fontSize: 12, color: labelClr, display: 'block', marginBottom: 12 }}>
          {t('settings.presetColors', '预设主题')}
        </Text>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16, marginBottom: 20 }}>
          {PRESET_COLORS.map(({ key, color, label }) => {
            const isActive = colorPrimary.toUpperCase() === color.toUpperCase()
            return (
              <Tooltip title={label} key={key}>
                <div onClick={() => handlePreset(color)}
                  style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
                  <div style={{
                    width: 44, height: 44, borderRadius: '50%', background: color,
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    transition: 'transform 0.2s, box-shadow 0.2s',
                    transform: isActive ? 'scale(1.12)' : 'scale(1)',
                    boxShadow: isActive
                      ? `0 0 0 3px var(--color-card, #fff), 0 0 0 5px ${color}`
                      : '0 2px 6px rgba(0,0,0,0.15)',
                  }}>
                    {isActive && <CheckOutlined style={{ color: '#fff', fontSize: 16, fontWeight: 700 }} />}
                  </div>
                  <Text style={{ fontSize: 11, color: isActive ? color : labelClr, fontWeight: isActive ? 700 : 400, userSelect: 'none' }}>
                    {label}
                  </Text>
                </div>
              </Tooltip>
            )
          })}
        </div>

        <Divider style={{ margin: '0 0 16px' }} />

        {/* 自定义颜色输入（圆圈点击唤起原生 picker） */}
        <Text style={{ fontSize: 12, color: labelClr, display: 'block', marginBottom: 10 }}>
          {t('settings.customColor', '自定义颜色')}
        </Text>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <div onClick={() => colorInputRef.current?.click()} style={{
            width: 44, height: 44, borderRadius: '50%', background: customColor, cursor: 'pointer', flexShrink: 0,
            boxShadow: '0 2px 8px rgba(0,0,0,0.2)',
            border: `3px solid ${isDark ? '#1f1f1f' : '#fff'}`,
            outline: `2px solid ${customColor}`,
            transition: 'all 0.2s',
          }} />
          <input ref={colorInputRef} type="color" value={customColor} onChange={handleCustom}
            style={{ position: 'absolute', opacity: 0, width: 0, height: 0, pointerEvents: 'none' }} />
          <div style={{ flex: 1 }}>
            <input type="text" value={customColor}
              onChange={e => { if (/^#[0-9a-fA-F]{0,6}$/.test(e.target.value)) handleCustom(e) }}
              placeholder="#1677ff"
              style={{ width: '100%', padding: '6px 10px', borderRadius: 6,
                border: `1px solid ${isDark ? '#3a3a3a' : '#d9d9d9'}`,
                background: isDark ? '#1f1f1f' : '#fff',
                color: isDark ? 'rgba(255,255,255,0.85)' : '#333',
                fontSize: 13, outline: 'none', fontFamily: 'monospace' }}
            />
            <Text style={{ fontSize: 11, color: labelClr, marginTop: 4, display: 'block' }}>
              {t('settings.clickCirclePick', '点击圆圈可唤起颜色选择器')}
            </Text>
          </div>
        </div>
      </div>
    </Modal>
  )
}


