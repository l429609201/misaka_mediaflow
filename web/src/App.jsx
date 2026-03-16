 // src/App.jsx
 // 根组件 — 仅做 Provider 包裹（对齐 misaka 项目模式）
 
 import { RouterProvider } from 'react-router-dom'
 import { router } from './general/Router'
 import { ThemeProvider } from './ThemeProvider'
 import { App as AppAntd } from 'antd'
 
 export const App = () => (
   <ThemeProvider>
     <AppAntd>
       <RouterProvider router={router} />
     </AppAntd>
   </ThemeProvider>
 )
