// 처음 쓰는 사람 안내: 첫 실행 때 세 장. 다 보면(또는 건너뛰면) 이 기기에 기억한다
import { useState } from "react";
import { Button, Icon } from "../components/ui";

const STEPS = [
  { icon: "microphone", title: "강의자료를 올리고 녹음만 켜세요",
    text: "교수님 설명을 듣고 AI가 강의자료의 그 문단 옆에 포스트잇으로 필기해요. 쪽도 알아서 넘겨요." },
  { icon: "hand-palm", title: "수업 중에는 버튼 하나면 돼요",
    text: "⭐ 여기 중요 · ✋ 모르겠어요 · 👋 방금 뭐라고. 흐름을 끊지 않고 표시만 해 두면 끝나고 정리해 줘요." },
  { icon: "graduation-cap", title: "끝나면 시험 공부가 준비돼요",
    text: "족보 노트 · 오늘의 복습 · 시험 예상 지도 · 시험 D-day. 필기를 누르면 교수님이 실제로 한 말(근거)도 볼 수 있어요." },
];

export function Onboarding() {
  const [step, setStep] = useState(() => { try { return localStorage.getItem("ln.onboarded") ? -1 : 0; } catch { return -1; } });
  if (step < 0) return null;
  const done = () => { try { localStorage.setItem("ln.onboarded", "1"); } catch { /* 괜찮다 */ } setStep(-1); };
  const s = STEPS[step];
  return (
    <>
      <div className="sheet-bg" onClick={done} />
      <div className="sheet onboarding" role="dialog" aria-modal="true" aria-labelledby="ob-title">
        <div className="ob-art" key={step}><Icon name={s.icon} size={56} /></div>
        <h3 className="t-title-m" id="ob-title">{s.title}</h3>
        <p className="t-body muted">{s.text}</p>
        <div className="ob-dots" aria-hidden="true">{STEPS.map((_, i) => <span key={i} className={i === step ? "on" : ""} />)}</div>
        <div className="row">
          <Button className="grow" variant="secondary" onClick={done}>건너뛰기</Button>
          <Button className="grow" onClick={() => (step + 1 < STEPS.length ? setStep(step + 1) : done())}>{step + 1 < STEPS.length ? "다음" : "시작하기"}</Button>
        </div>
      </div>
    </>
  );
}
