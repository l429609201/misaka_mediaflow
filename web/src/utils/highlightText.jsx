// src/utils/highlightText.jsx
// 搜索关键词高亮工具 — 日志组件共用

/**
 * 将文本中匹配 keyword 的部分用 <mark> 包裹高亮显示
 * @param {string} text - 原始文本
 * @param {string} keyword - 搜索关键词
 * @param {boolean} isDark - 是否暗色模式
 * @returns {React.ReactNode}
 */
export function highlightText(text, keyword, isDark) {
  if (!keyword || !text) return text
  try {
    // 转义正则特殊字符
    const escaped = keyword.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    const regex = new RegExp(`(${escaped})`, 'gi')
    const parts = text.split(regex)
    if (parts.length <= 1) return text
    return parts.map((part, i) =>
      regex.test(part)
        ? <mark key={i} style={{
            background: isDark ? '#b26a00' : '#ffe58f',
            color: isDark ? '#fff' : '#000',
            padding: '0 2px',
            borderRadius: 2,
          }}>{part}</mark>
        : part
    )
  } catch {
    return text
  }
}

