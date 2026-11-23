import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './styles/app.css'
import './styles/theme.css'
import App from './App.tsx'
import { isDemo, startDemo } from './demo'
import { installTapSound } from './lib/sound'
import { applyPrefs } from './lib/prefs'
import { watchPendingRecordings } from './lib/localRec'
import { followStatusBar } from './lib/native'

// 색 조합: editorial(기본) · digital · swiss — 설정에서 바꿀 수 있게 저장해 둔다
// 색: 브랜드 팔레트 하나 (어두운 화면은 같은 팔레트의 다크)
document.documentElement.dataset.sky = 'brand'
// 열린 시트·창은 Esc(키보드)로도 닫힌다: 맨 위 시트의 바깥(배경)을 누른 것과 같게
window.addEventListener('keydown', (e) => { if (e.key !== 'Escape') return; const bgs = document.querySelectorAll<HTMLElement>('.sheet-bg'); bgs[bgs.length - 1]?.click() })
installTapSound()
applyPrefs() // 화면 색 · 글자 크기 · 움직임 · 진동 (설정)
watchPendingRecordings() // 올리지 못한 녹음이 있으면 올린다 (녹음 오프라인 저장)
followStatusBar() // 안드로이드 상태바 · 브라우저 주소창 색을 화면 색에 맞춘다

// 데모 빌드(VITE_DEMO=1)는 서버 대신 미리 받아 둔 응답으로 화면을 그린다
const ready = isDemo ? startDemo() : Promise.resolve()
ready.then(() => {
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  )
})
