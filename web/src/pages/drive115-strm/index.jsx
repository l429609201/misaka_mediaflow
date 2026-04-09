// web/src/pages/drive115-strm/index.jsx
// 115 STRM 多任务同步页（骨架，待完整实现）
// 当前先重导向到旧页面保证可用，后续再完整实现

import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'

export const Drive115Strm = () => {
  const navigate = useNavigate()
  // 临时：跳转到旧的 /115 页面，避免空白
  useEffect(() => { navigate('/115', { replace: true }) }, [navigate])
  return null
}

export default Drive115Strm
