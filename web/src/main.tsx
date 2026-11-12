import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './styles/app.css'
import App from './App.tsx'
import { isDemo, startDemo } from './demo'

// 데모 빌드(VITE_DEMO=1)는 서버 대신 미리 받아 둔 응답으로 화면을 그린다
// 손으로 그은 선: 테두리를 살짝 떨리게 하는 필터 (styles/app.css 의 url(#chalk))
document.body.insertAdjacentHTML("afterbegin",
  '<svg width="0" height="0" style="position:absolute" aria-hidden="true"><filter id="chalk" x="-5%" y="-5%" width="110%" height="110%">' +
  '<feTurbulence type="fractalNoise" baseFrequency="0.035 0.06" numOctaves="2" seed="7" result="n"/>' +
  '<feDisplacementMap in="SourceGraphic" in2="n" scale="2.6" xChannelSelector="R" yChannelSelector="G"/></filter></svg>')

const ready = isDemo ? startDemo() : Promise.resolve()
ready.then(() => {
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  )
})
