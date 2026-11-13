// 쫑긋: 수업을 대신 들어 주는 토끼. 이 앱의 얼굴이다.
// 그림은 AI 이미지 생성으로 만든 캐릭터(public/mascot/*.webp). 움직임은 그 그림을 귀 두 짝과 몸으로 잘라서 따로 움직여 만든다
// (영상 생성 없이, 무료로). 귀가 위로 선 표정(평소·쫑긋·정리 중)만 잘라 두었고, 듣는 중은 평소 그림의 귀를 소리에 맞춰 움직인다.
//   mood  idle 평소(귀 살랑, 숨) · listen 듣는 중(소리가 클수록 귀가 벌어지고 길어짐) · alert 쫑긋!(귀가 곧게 솟음) ·
//         happy 신남(폴짝) · sleep 졸림(Zz) · write 정리 중(귀 까딱, 끄적)
import { useEffect, useRef } from "react";
import rig from "./mascot-rig.json";

export type Mood = "idle" | "listen" | "alert" | "happy" | "sleep" | "write";

const file = (name: string) => `${import.meta.env.BASE_URL}mascot/${name}.webp`;
type Rig = Record<string, { ear: { l: number[]; r: number[] } }>;
/** 귀를 따로 움직일 수 있는 그림: 듣는 중은 평소 그림을 쓴다 */
const PARTS: Partial<Record<Mood, string>> = { idle: "idle", listen: "idle", alert: "alert", write: "write" };

export function Mascot({ mood = "idle", size = 96, onClick, label }: { mood?: Mood; size?: number; onClick?: () => void; label?: string }) {
  const root = useRef<HTMLElement>(null);
  // 듣는 중: 마이크 크기(ln-level, 0~1)를 --lvl 로 넘겨 귀가 소리에 맞춰 움직이게 한다
  useEffect(() => {
    if (mood !== "listen") { root.current?.style.setProperty("--lvl", "0"); return; }
    const on = (e: Event) => root.current?.style.setProperty("--lvl", String(Math.min(1, Math.sqrt((e as CustomEvent<number>).detail) * 1.3)));
    window.addEventListener("ln-level", on);
    return () => window.removeEventListener("ln-level", on);
  }, [mood]);
  const part = PARTS[mood];
  const ears = part ? (rig as Rig)[part].ear : null;
  const art = (
    // key: 그림이 바뀔 때만 통 하고 튀어나온다 (평소 ↔ 듣는 중은 같은 그림이라 그대로)
    <span className="m-stage" key={part ?? mood}>
      {part && ears ? (
        <>
          <img className="m-part m-ear m-ear-l" src={file(`${part}-earl`)} style={{ transformOrigin: `${ears.l[0]}% ${ears.l[1]}%` }} alt="" draggable={false} />
          <img className="m-part m-ear m-ear-r" src={file(`${part}-earr`)} style={{ transformOrigin: `${ears.r[0]}% ${ears.r[1]}%` }} alt="" draggable={false} />
          <img className="m-part m-torso" src={file(`${part}-body`)} alt="" draggable={false} />
        </>
      ) : <img className="m-part m-whole" src={file(mood)} alt="" draggable={false} />}
      {mood === "sleep" && <span className="m-zz" aria-hidden="true"><i>Z</i><i>z</i></span>}
      {mood === "alert" && <span className="m-bang" aria-hidden="true">!</span>}
    </span>
  );
  const cls = `mascot m-${mood}`;
  const style = { width: size, height: size } as React.CSSProperties;
  return onClick
    ? <button className={cls} style={style} ref={root as React.RefObject<HTMLButtonElement>} onClick={onClick} aria-label={label ?? "쫑긋"}>{art}</button>
    : <span className={cls} style={style} ref={root as React.RefObject<HTMLSpanElement>} role="img" aria-label={label ?? "쫑긋"}>{art}</span>;
}

/** 쫑긋이 하는 말 (말풍선) */
export function Says({ children }: { children: React.ReactNode }) {
  return <span className="says">{children}</span>;
}
