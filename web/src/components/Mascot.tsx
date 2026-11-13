// 쫑긋: 수업을 대신 들어 주는 토끼. 이 앱의 얼굴이다.
// 그림은 AI 이미지 생성으로 만든 캐릭터 시트(public/mascot/*.webp, 배경을 지운 것)이고, 움직임은 여기서 준다.
//   mood  idle 평소(숨 쉬듯 살짝) · listen 듣는 중(소리가 클수록 몸을 기울임) · alert 쫑긋!(튀어나오며 놀람) ·
//         happy 신남(폴짝) · sleep 졸림(천천히 숨, Zz) · write 정리 중(끄적끄적)
// 움직이는 영상(public/mascot/<mood>.webp 가 움직이는 그림이면)도 그대로 쓸 수 있다: 같은 파일 이름으로 바꾸면 된다.
import { useEffect, useRef } from "react";

export type Mood = "idle" | "listen" | "alert" | "happy" | "sleep" | "write";

const src = (mood: Mood) => `${import.meta.env.BASE_URL}mascot/${mood}.webp`;

export function Mascot({ mood = "idle", size = 96, onClick, label }: { mood?: Mood; size?: number; onClick?: () => void; label?: string }) {
  const root = useRef<HTMLElement>(null);
  // 듣는 중: 마이크 크기(ln-level, 0~1)를 --lvl 로 넘겨 몸이 소리에 맞춰 움직이게 한다
  useEffect(() => {
    if (mood !== "listen") { root.current?.style.setProperty("--lvl", "0"); return; }
    const on = (e: Event) => root.current?.style.setProperty("--lvl", String(Math.min(1, Math.sqrt((e as CustomEvent<number>).detail) * 1.3)));
    window.addEventListener("ln-level", on);
    return () => window.removeEventListener("ln-level", on);
  }, [mood]);
  const art = (
    <>
      {/* key=mood: 표정이 바뀔 때마다 새로 튀어나오는 모션 */}
      <img key={mood} className="m-img" src={src(mood)} width={size} height={size} alt="" draggable={false} />
      {mood === "sleep" && <span className="m-zz" aria-hidden="true"><i>Z</i><i>z</i></span>}
      {mood === "alert" && <span className="m-bang" aria-hidden="true">!</span>}
    </>
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
