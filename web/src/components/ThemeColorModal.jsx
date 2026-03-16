// src/components/ThemeColorModal.jsx
// 主题色选择弹窗 — 对齐弹幕库（从头像下拉菜单打开）

import { Modal, Typography } from 'antd'
import { useTranslation } from 'react-i18next'
import { useThemeContext } from '@/ThemeProvider'
import { CheckOutlined } from '@ant-design/icons'

const { Text } = Typography

export default function ThemeColorModal({ open, onClose }) {
  const { t } = useTranslation()
  const { colorPrimary, setColorPrimary, PRESET_COLORS } = useThemeContext()

  return (
    <Modal
      title={t('settings.themeColor', '主题色')}
      open={open}
      onCancel={onClose}
      footer={null}
      destroyOnClose
      width={400}
    >
      {/* 预设颜色 */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, padding: '12px 0' }}>
        {PRESET_COLORS.map(c => {
          const isActive = c.color === colorPrimary
          return (
            <div
              key={c.key}
              onClick={() => setColorPrimary(c.color)}
              style={{
                display: 'flex', flexDirection: 'column', alignItems: 'center',
                cursor: 'pointer', gap: 6,
              }}
            >
              <div style={{
                width: 40, height: 40, borderRadius: 8,
                background: c.color,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                border: isActive ? '2px solid #fff' : '2px solid transparent',
                boxShadow: isActive ? `0 0 0 2px ${c.color}` : 'none',
                transition: 'all 0.2s',
              }}>
                {isActive && <CheckOutlined style={{ color: '#fff', fontSize: 16 }} />}
              </div>
              <Text style={{ fontSize: 12 }}>{c.label}</Text>
            </div>
          )
        })}
      </div>
    </Modal>
  )
}

