// src/general/Layout.jsx
// 主布局（侧边栏 + 顶栏 + 内容区）

import { useState } from 'react'
import { Outlet, useNavigate, useLocation } from 'react-router-dom'
import { Layout as AntLayout, Menu, Button, Dropdown, Space, Modal, Tooltip, theme } from 'antd'
import {
  DashboardOutlined,
  DatabaseOutlined,
  FileTextOutlined,
  CloudOutlined,
  CloudServerOutlined,
  UnorderedListOutlined,
  SettingOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  UserOutlined,
  LogoutOutlined,
  CodeOutlined,
  HistoryOutlined,
  BgColorsOutlined,
  LockOutlined,
  BulbOutlined,
  BulbFilled,
  NodeIndexOutlined,
} from '@ant-design/icons'
import { useTranslation } from 'react-i18next'
import LanguageSwitch from '@/components/LanguageSwitch'
import LiveLogModal from '@/components/LiveLogModal'
import HistoryLogModal from '@/components/HistoryLogModal'
import ChangePasswordModal from '@/components/ChangePasswordModal'
import ThemeColorModal from '@/components/ThemeColorModal'
import { useThemeContext } from '@/ThemeProvider'
import { RoutePaths } from './RoutePaths'

const { Header, Sider, Content } = AntLayout

export const Layout = () => {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const location = useLocation()
  const [collapsed, setCollapsed] = useState(false)
  const [liveLogOpen, setLiveLogOpen] = useState(false)
  const [historyLogOpen, setHistoryLogOpen] = useState(false)
  const [passwordModalOpen, setPasswordModalOpen] = useState(false)
  const [themeColorModalOpen, setThemeColorModalOpen] = useState(false)
  const { token: themeToken } = theme.useToken()
  const themeCtx = useThemeContext()

  const menuItems = [
    { key: RoutePaths.HOME,       icon: <DashboardOutlined />,    label: t('menu.dashboard') },
    { key: RoutePaths.STORAGE,    icon: <DatabaseOutlined />,     label: t('menu.storage') },
    { key: RoutePaths.MAPPINGS,   icon: <NodeIndexOutlined />,    label: t('menu.mappings') },
    { key: RoutePaths.STRM,       icon: <FileTextOutlined />,     label: t('menu.strm') },
    { key: RoutePaths.DRIVE115,   icon: <CloudOutlined />,        label: t('menu.drive115') },
    { key: RoutePaths.MEDIA_PROXY, icon: <CloudServerOutlined />, label: t('menu.mediaProxy') },
    { key: RoutePaths.LOGS,       icon: <UnorderedListOutlined />,label: t('menu.logs') },
    { key: RoutePaths.SETTING,    icon: <SettingOutlined />,      label: t('menu.settings') },
  ]

  const handleLogout = () => {
    Modal.confirm({
      title: t('login.logoutConfirm'),
      onOk: () => {
        localStorage.removeItem('token')
        localStorage.removeItem('username')
        navigate(RoutePaths.LOGIN, { replace: true })
      },
    })
  }

  // 头像下拉菜单（对齐弹幕库：主题色、修改密码、退出登录）
  const avatarMenuItems = [
    {
      key: 'themeColor',
      icon: <BgColorsOutlined />,
      label: t('settings.themeColor', '主题色'),
    },
    {
      key: 'changePassword',
      icon: <LockOutlined />,
      label: t('settings.changePassword', '修改密码'),
    },
    { type: 'divider' },
    {
      key: 'logout',
      icon: <LogoutOutlined />,
      label: t('login.logout', '退出登录'),
      danger: true,
    },
  ]

  const handleAvatarMenuClick = ({ key }) => {
    switch (key) {
      case 'themeColor':    setThemeColorModalOpen(true); break
      case 'changePassword': setPasswordModalOpen(true); break
      case 'logout':        handleLogout(); break
    }
  }

  const username = localStorage.getItem('username') || 'admin'

  return (
    <AntLayout style={{ minHeight: '100vh' }}>
      <Sider
        trigger={null} collapsible collapsed={collapsed}
        style={{ background: themeToken.colorBgContainer }}
        width={220}
      >
        <div style={{
          height: 64, display: 'flex', alignItems: 'center', justifyContent: 'center',
          gap: 8, borderBottom: `1px solid ${themeToken.colorBorderSecondary}`,
        }}>
          <img src={`${import.meta.env.BASE_URL}images/logo.png`} alt="logo" style={{ height: 32, width: 32 }} />
          {!collapsed && (
            <span style={{
              fontSize: 18, fontWeight: 700,
              color: themeToken.colorPrimary, letterSpacing: 1,
              whiteSpace: 'nowrap',
            }}>
              Misaka MediaFlow
            </span>
          )}
        </div>
        <Menu
          mode="inline" selectedKeys={[location.pathname]}
          items={menuItems} onClick={({ key }) => navigate(key)}
          style={{ borderRight: 'none', marginTop: 8 }}
        />
      </Sider>

      <AntLayout>
        <Header style={{
          padding: '0 24px', background: themeToken.colorBgContainer,
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          borderBottom: `1px solid ${themeToken.colorBorderSecondary}`,
        }}>
          <Button type="text"
            icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
            onClick={() => setCollapsed(!collapsed)}
          />

          <Space size="middle">
            {/* 实时日志 */}
            <Tooltip title={t('logs.liveTitle')}>
              <Button type="text" icon={<CodeOutlined />}
                onClick={() => setLiveLogOpen(true)}
              />
            </Tooltip>
            {/* 历史日志 */}
            <Tooltip title={t('logs.historyTitle')}>
              <Button type="text" icon={<HistoryOutlined />}
                onClick={() => setHistoryLogOpen(true)}
              />
            </Tooltip>
            {/* 暗色/亮色 */}
            <Tooltip title={themeCtx?.isDark ? t('settings.lightMode') : t('settings.darkMode')}>
              <Button type="text"
                icon={themeCtx?.isDark ? <BulbFilled /> : <BulbOutlined />}
                onClick={() => themeCtx?.toggleMode()}
              />
            </Tooltip>
            {/* 语言 */}
            <LanguageSwitch />
            {/* 头像下拉（主题色 + 修改密码 + 退出登录） */}
            <Dropdown
              menu={{ items: avatarMenuItems, onClick: handleAvatarMenuClick }}
              placement="bottomRight"
            >
              <Space style={{ cursor: 'pointer' }}>
                <UserOutlined />
                <span>{username}</span>
              </Space>
            </Dropdown>
          </Space>
        </Header>

        <Content style={{ margin: 24, minHeight: 280 }}>
          <Outlet />
        </Content>
      </AntLayout>

      {/* 实时日志弹窗 */}
      <LiveLogModal open={liveLogOpen} onClose={() => setLiveLogOpen(false)} />
      {/* 历史日志弹窗 */}
      <HistoryLogModal open={historyLogOpen} onClose={() => setHistoryLogOpen(false)} />
      {/* 修改密码弹窗 */}
      <ChangePasswordModal open={passwordModalOpen} onClose={() => setPasswordModalOpen(false)} />
      {/* 主题色弹窗 */}
      <ThemeColorModal open={themeColorModalOpen} onClose={() => setThemeColorModalOpen(false)} />
    </AntLayout>
  )
}

