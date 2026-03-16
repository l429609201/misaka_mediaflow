 // src/main.jsx
 // 应用入口 — 极简模式（对齐 misaka 项目）
 
 import React from 'react'
 import ReactDOM from 'react-dom/client'
 import { App } from './App'
 import './i18n'
 import './index.css'
 
 ReactDOM.createRoot(document.getElementById('root')).render(
   <React.StrictMode>
     <App />
   </React.StrictMode>,
 )
