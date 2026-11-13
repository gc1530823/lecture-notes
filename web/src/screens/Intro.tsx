// 소개 화면 (처음 한 번): 스크롤에 맞춰 장면이 이어지는 영화 같은 소개.
// 화면은 고정돼 있고(sticky), 스크롤한 만큼(0~1)이 --p 로 들어가 쫑긋·글자·아이콘이 그 값에 맞춰 움직인다.
// 손가락·마우스 위치는 --mx/--my 로 들어가 깊이감(겹겹이 다르게 움직임)을 만든다.
import { useEffect, useRef, useState } from "react";
import { Mascot, type Mood } from "../components/Mascot";
import { Button, Icon } from "../components/ui";
import { Confetti } from "../lib/motion";
import { go } from "../router";

const SCENES = 5;
const FLOATERS = ["microphone", "star", "notebook", "target", "cards", "carrot", "headphones", "book-open-text", "megaphone", "brain"];
const NOTES = [
  { tone: "exam", text: "이거 시험에 꼭 나와요" }, { tone: "explanation", text: "교착 상태의 네 가지 조건" },
  { tone: "example", text: "예: 식사하는 철학자" }, { tone: "emphasis", text: "안전 상태가 핵심!" },
];

export default function Intro() {
  const root = useRef<HTMLDivElement>(null);
  const [scene, setScene] = useState(0);
  useEffect(() => {
    const el = root.current!;
    let frame = 0;
    const update = () => {
      frame = 0;
      const max = el.offsetHeight - window.innerHeight;
      const p = Math.min(1, Math.max(0, (window.scrollY - el.offsetTop) / Math.max(1, max)));
      el.style.setProperty("--p", p.toFixed(4));
      const at = p * (SCENES - 1);
      // 장면마다의 진행(0~1): --s0 … --s4. 그 장면에 들어오며 0→1
      for (let i = 0; i < SCENES; i++) el.style.setProperty(`--s${i}`, Math.min(1, Math.max(0, at - i + 1)).toFixed(4));
      setScene(Math.min(SCENES - 1, Math.round(at)));
    };
    const onScroll = () => { if (!frame) frame = requestAnimationFrame(update); };
    const onMove = (e: PointerEvent) => {
      el.style.setProperty("--mx", ((e.clientX / window.innerWidth) * 2 - 1).toFixed(3));
      el.style.setProperty("--my", ((e.clientY / window.innerHeight) * 2 - 1).toFixed(3));
    };
    update();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);
    window.addEventListener("pointermove", onMove, { passive: true });
    return () => { window.removeEventListener("scroll", onScroll); window.removeEventListener("resize", onScroll); window.removeEventListener("pointermove", onMove); cancelAnimationFrame(frame); };
  }, []);

  const start = () => { try { localStorage.setItem("ln.onboarded", "1"); } catch { /* 괜찮다 */ } go({ name: "home" }); };
  const mood: Mood = scene === 0 ? "idle" : scene === 1 ? "listen" : scene === 2 ? "alert" : scene === 3 ? "write" : "happy";

  return (
    <div className="intro" ref={root} style={{ height: `${SCENES * 100}dvh` }}>
      <div className={`intro-stage scene-${scene}`}>
        <div className="intro-sky" aria-hidden="true" />
        <div className="intro-word" aria-hidden="true">쫑긋</div>
        <div className="intro-floaters" aria-hidden="true">
          {FLOATERS.map((name, i) => <span key={name} className={`floater f${i}`}><Icon name={name} art size={64} /></span>)}
        </div>
        <div className="intro-notes" aria-hidden="true">
          {NOTES.map((n, i) => (
            <span key={i} className={`intro-note n${i}`} style={{ background: `var(--note-${n.tone}-paper)`, borderColor: `var(--note-${n.tone}-ink)` }}>{n.text}</span>
          ))}
        </div>
        <div className="intro-wave" aria-hidden="true">{Array.from({ length: 28 }, (_, i) => <i key={i} style={{ animationDelay: `${(i * 97) % 900}ms` }} />)}</div>
        <div className="intro-mascot"><Mascot mood={mood} size={220} /></div>
        {scene === 4 && <Confetti count={44} />}

        <div className="intro-copy c0"><p className="intro-kicker">수업을 대신 들어 주는 토끼</p><h1>귀를 쫑긋.</h1></div>
        <div className="intro-copy c1"><h2>녹음만 켜세요.<br />제가 듣고 있을게요.</h2><p>교수님 말이 실시간으로 글이 되고, 강의자료의 그 문단 옆에 필기로 붙어요.</p></div>
        <div className="intro-copy c2"><h2>“시험에 나와요”<br />쫑긋!</h2><p>시험·과제·공지 얘기가 나오면 귀를 세우고 바로 표시해 둬요.</p></div>
        <div className="intro-copy c3"><h2>수업이 끝나면<br />공부가 준비돼 있어요.</h2><p>요약 · 플래시카드 · 족보 노트 · 오늘의 복습까지 정리해 둘게요.</p></div>
        <div className="intro-copy c4"><h2>같이 시작해요!</h2><p>공부한 날마다 당근 하나.</p><Button onClick={start}>시작하기</Button></div>

        <div className="intro-hint" aria-hidden="true"><span />아래로 내려 보세요</div>
        <button className="intro-skip" onClick={start}>건너뛰기</button>
        <div className="intro-dots" aria-hidden="true">{Array.from({ length: SCENES }, (_, i) => <i key={i} className={i === scene ? "on" : ""} />)}</div>
      </div>
    </div>
  );
}
