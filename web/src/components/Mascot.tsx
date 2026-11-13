// 쫑긋 구슬: 이 앱의 얼굴. 귀를 기울여 듣는 주황 구슬이다 (동물이 아니라, 소리에 반응하는 빛나는 구슬).
//   mood  idle 평소(천천히 숨, 빛이 돈다) · listen 듣는 중(마이크 소리에 맞춰 부풀고 물결이 퍼진다) ·
//         alert 쫑긋!(톡 튀어 오르며 느낌표) · happy 신남(폴짝, 반짝) · sleep 쉬는 중(작고 흐려짐, Zz) · write 정리 중(고리가 돈다)
// 그림 파일 없이 CSS로만 그린다 (가볍고, 어떤 크기에서도 또렷하다).
import { useEffect, useRef } from "react";

export type Mood = "idle" | "listen" | "alert" | "happy" | "sleep" | "write";

export function Mascot({ mood = "idle", size = 96, onClick, label }: { mood?: Mood; size?: number; onClick?: () => void; label?: string }) {
  const root = useRef<HTMLElement>(null);
  // 듣는 중: 마이크 크기(ln-level, 0~1)를 --lvl 로 넘겨 구슬이 소리에 맞춰 부풀게 한다
  useEffect(() => {
    if (mood !== "listen") { root.current?.style.setProperty("--lvl", "0"); return; }
    const on = (e: Event) => root.current?.style.setProperty("--lvl", String(Math.min(1, Math.sqrt((e as CustomEvent<number>).detail) * 1.3)));
    window.addEventListener("ln-level", on);
    return () => window.removeEventListener("ln-level", on);
  }, [mood]);
  const art = (
    <span className="orb-stage" key={mood} aria-hidden="true">
      <i className="orb-ring r1" /><i className="orb-ring r2" />
      <span className="orb"><i className="orb-shine" /><i className="orb-face" /></span>
      {mood === "alert" && <span className="orb-bang">!</span>}
      {mood === "sleep" && <span className="orb-zz"><i>Z</i><i>z</i></span>}
      {mood === "happy" && <span className="orb-spark"><i /><i /><i /><i /></span>}
    </span>
  );
  const cls = `mascot orb-${mood}`;
  const style = { width: size, height: size, "--sz": `${size}px` } as React.CSSProperties;
  return onClick
    ? <button className={cls} style={style} ref={root as React.RefObject<HTMLButtonElement>} onClick={onClick} aria-label={label ?? "쫑긋"}>{art}</button>
    : <span className={cls} style={style} ref={root as React.RefObject<HTMLSpanElement>} role="img" aria-label={label ?? "쫑긋"}>{art}</span>;
}

/** 쫑긋이 하는 말 (말풍선) */
export function Says({ children }: { children: React.ReactNode }) {
  return <span className="says">{children}</span>;
}
