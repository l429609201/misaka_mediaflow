// src/components/ChangePasswordModal.jsx
// 修改密码弹窗 — 对齐弹幕库（从头像下拉菜单打开）

import { useState } from 'react'
import { Modal, Form, Input, message } from 'antd'
import { LockOutlined } from '@ant-design/icons'
import { useTranslation } from 'react-i18next'
import { authApi } from '@/apis'

export default function ChangePasswordModal({ open, onClose }) {
  const { t } = useTranslation()
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)

  const handleOk = async () => {
    try {
      const values = await form.validateFields()
      if (values.new_password !== values.confirm_password) {
        message.error(t('settings.passwordMismatch', '两次输入的密码不一致'))
        return
      }
      if (values.new_password.length < 6) {
        message.error(t('settings.passwordTooShort', '密码至少 6 位'))
        return
      }
      setLoading(true)
      await authApi.changePassword(values.old_password, values.new_password)
      message.success(t('settings.passwordChanged', '密码修改成功'))
      form.resetFields()
      onClose()
    } catch {
      message.error(t('common.failed', '操作失败'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <Modal
      title={t('settings.changePassword', '修改密码')}
      open={open}
      onCancel={() => { form.resetFields(); onClose() }}
      onOk={handleOk}
      confirmLoading={loading}
      destroyOnClose
      width={420}
    >
      <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
        <Form.Item
          name="old_password"
          label={t('settings.oldPassword', '旧密码')}
          rules={[{ required: true, message: t('login.passwordRequired', '请输入密码') }]}
        >
          <Input.Password prefix={<LockOutlined />} placeholder={t('settings.oldPassword', '旧密码')} />
        </Form.Item>
        <Form.Item
          name="new_password"
          label={t('settings.newPassword', '新密码')}
          rules={[{ required: true, message: t('login.passwordRequired', '请输入密码') }]}
        >
          <Input.Password prefix={<LockOutlined />} placeholder={t('settings.newPassword', '新密码')} />
        </Form.Item>
        <Form.Item
          name="confirm_password"
          label={t('settings.confirmPassword', '确认密码')}
          rules={[{ required: true, message: t('login.passwordRequired', '请输入密码') }]}
        >
          <Input.Password prefix={<LockOutlined />} placeholder={t('settings.confirmPassword', '确认密码')} />
        </Form.Item>
      </Form>
    </Modal>
  )
}

