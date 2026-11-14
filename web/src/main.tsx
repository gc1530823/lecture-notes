import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './styles/app.css'
import App from './App.tsx'
import { isDemo, startDemo } from './demo'
import { installTapSound } from './lib/sound'
import { applyPrefs } from './lib/prefs'

installTapSound()
applyPrefs() // 화면 색 · 글자 크기 · 움직임 · 진동 (설정)

// 데모 빌드(VITE_DEMO=1)는 서버 대신 미리 받아 둔 응답으로 화면을 그린다
const ready = isDemo ? startDemo() : Promise.resolve()
ready.then(() => {
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  )
})
