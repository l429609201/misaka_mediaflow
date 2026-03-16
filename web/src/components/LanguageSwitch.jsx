// src/components/LanguageSwitch.jsx
// 语言切换下拉菜单 — 使用 iconfont 语言图标

import { Dropdown } from 'antd'
import { useTranslation } from 'react-i18next'
import { LANGUAGES, changeLanguage } from '@/i18n'

export default function LanguageSwitch() {
  const { i18n } = useTranslation()

  // 当前语言对应的图标
  const currentLang = LANGUAGES.find(l => l.key === i18n.language) || LANGUAGES[0]

  const items = LANGUAGES.map((lang) => ({
    key: lang.key,
    icon: <i className={`iconfont ${lang.icon}`} style={{ fontSize: 16 }} />,
    label: (
      <span style={{ fontWeight: i18n.language === lang.key ? 600 : 400 }}>
        {lang.label}
      </span>
    ),
  }))

  const handleClick = ({ key }) => {
    changeLanguage(key)
  }

  return (
    <Dropdown menu={{ items, onClick: handleClick }} placement="bottomRight">
      <span style={{ cursor: 'pointer', padding: '0 8px', fontSize: 16, display: 'inline-flex', alignItems: 'center' }}>
        <i className={`iconfont ${currentLang.icon}`} style={{ fontSize: 18 }} />
      </span>
    </Dropdown>
  )
}

