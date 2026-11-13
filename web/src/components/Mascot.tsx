// 쫑긋: 수업을 대신 들어 주는 토끼. 이 앱의 얼굴이다.
// 귀가 주인공: 녹음 중에는 마이크 크기에 맞춰 귀가 움직이고, "시험" 같은 말이 나오면 귀가 쫑긋 선다.
//   mood  idle 평소(눈 깜빡, 귀 살랑) · listen 듣는 중(귀가 소리에 반응) · alert 쫑긋!(귀가 곧게 섬) ·
//         happy 신남(폴짝, 웃는 눈) · sleep 졸림(귀가 처짐, Zz) · write 정리 중(연필을 끄적)
import { useEffect, useRef } from "react";

export type Mood = "idle" | "listen" | "alert" | "happy" | "sleep" | "write";

export function Mascot({ mood = "idle", size = 96, onClick, label }: { mood?: Mood; size?: number; onClick?: () => void; label?: string }) {
  const root = useRef<HTMLSpanElement>(null);
  // 듣는 중: 마이크 크기(ln-level, 0~1)를 --lvl 로 넘겨 귀가 따라 움직이게 한다
  useEffect(() => {
    if (mood !== "listen") { root.current?.style.setProperty("--lvl", "0"); return; }
    const on = (e: Event) => root.current?.style.setProperty("--lvl", String(Math.min(1, Math.sqrt((e as CustomEvent<number>).detail) * 1.3)));
    window.addEventListener("ln-level", on);
    return () => window.removeEventListener("ln-level", on);
  }, [mood]);
  const art = (
    <svg viewBox="0 0 120 132" width={size} height={size * 1.1} aria-hidden="true">
      <g className="m-body">
        <g className="m-ear m-ear-l"><ellipse cx="41" cy="34" rx="12" ry="30" className="m-fur" /><ellipse cx="41" cy="37" rx="5.5" ry="19" className="m-pink" /></g>
        <g className="m-ear m-ear-r"><ellipse cx="79" cy="34" rx="12" ry="30" className="m-fur" /><ellipse cx="79" cy="37" rx="5.5" ry="19" className="m-pink" /></g>
        <ellipse cx="60" cy="88" rx="42" ry="36" className="m-fur" />
        <circle cx="33" cy="98" r="8" className="m-cheek" /><circle cx="87" cy="98" r="8" className="m-cheek" />
        <g className="m-eyes-open"><circle cx="45" cy="84" r="5" className="m-ink" /><circle cx="75" cy="84" r="5" className="m-ink" />
          <circle cx="46.6" cy="82.2" r="1.6" fill="#fff" /><circle cx="76.6" cy="82.2" r="1.6" fill="#fff" /></g>
        <g className="m-eyes-happy"><path d="M39 86 q6 -8 12 0" className="m-line" /><path d="M69 86 q6 -8 12 0" className="m-line" /></g>
        <g className="m-eyes-sleep"><path d="M39 85 h12" className="m-line" /><path d="M69 85 h12" className="m-line" /></g>
        <path d="M57 93 h6 l-3 3.5 z" className="m-nose" />
        <path className="m-mouth" d="M53 99 q3.5 4 7 0 q3.5 4 7 0" />
        <path className="m-mouth-open" d="M54 99 q6 9 12 0 z" />
      </g>
      <g className="m-bang"><circle cx="103" cy="24" r="13" className="m-accent" /><path d="M103 16 v9 M103 30 v.5" stroke="#fff" strokeWidth="3.6" strokeLinecap="round" /></g>
      <g className="m-zzz"><text x="96" y="30" className="m-z">Z</text><text x="106" y="16" className="m-z m-z2">z</text></g>
      <g className="m-pencil"><rect x="90" y="96" width="8" height="26" rx="2" className="m-accent" transform="rotate(28 94 109)" /><path d="M84.5 121 l3.5 6 l3.5 -6 z" className="m-ink" transform="rotate(28 88 121) translate(-1 -1)" /></g>
    </svg>
  );
  const cls = `mascot m-${mood}`;
  return onClick
    ? <button className={cls} ref={root as React.RefObject<HTMLButtonElement & HTMLSpanElement>} onClick={onClick} aria-label={label ?? "쫑긋"}>{art}</button>
    : <span className={cls} ref={root} role="img" aria-label={label ?? "쫑긋"}>{art}</span>;
}

/** 쫑긋이 하는 말 (말풍선) */
export function Says({ children }: { children: React.ReactNode }) {
  return <span className="says">{children}</span>;
}
