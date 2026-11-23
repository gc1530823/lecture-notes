// 모션 도구: 숫자 올라가기, 색종이, 글자 차례로 나타나기, 뼈대(불러오는 중) 자리.
// 기기에서 "동작 줄이기"를 켜면 CSS가 애니메이션을 끄고, 여기서는 숫자를 바로 최종값으로 보여 준다.
import { useEffect, useState, type CSSProperties } from "react";

export const reduced = () => typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;

/** 0에서 목표까지 부드럽게 올라가는 숫자 */
export function useCountUp(target: number, ms = 900): number {
  const [value, setValue] = useState(reduced() ? target : 0);
  useEffect(() => {
    if (reduced()) { setValue(target); return; }
    let frame = 0;
    const started = performance.now();
    const step = (now: number) => {
      const t = Math.min(1, (now - started) / ms);
      setValue(Math.round(target * (1 - Math.pow(1 - t, 3))));
      if (t < 1) frame = requestAnimationFrame(step);
    };
    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, [target, ms]);
  return value;
}

export function Count({ to, suffix = "" }: { to: number; suffix?: string }) {
  return <>{useCountUp(to)}{suffix}</>;
}


/** 위에서 흩날리는 색종이 (한 번만) */
export function Confetti({ count = 36 }: { count?: number }) {
  // 축하는 색종이 대신 밤하늘 별: 여기저기서 반짝이며 천천히 떠오른다
  if (reduced()) return null;
  const n = Math.min(count, 28);
  return (
    <div className="starfall" aria-hidden="true">
      {Array.from({ length: n }, (_, i) => {
        const size = 6 + ((i * 7) % 4) * 3;
        const style = { left: `${(i * 37 + 11) % 96}%`, top: `${(i * 53 + 7) % 78}%`, width: size, height: size,
          animationDelay: `${(i % 9) * 110}ms`, animationDuration: `${1400 + ((i * 61) % 900)}ms` } as CSSProperties;
        return <i key={i} style={style} className={i % 4 === 0 ? "big" : ""} />;
      })}
    </div>
  );
}

/** 낱말이 하나씩 떠오르는 글 */
export function Words({ text, step = 45, start = 0 }: { text: string; step?: number; start?: number }) {
  return (
    <>
      {text.split(/(\s+)/).map((w, i) => /\s+/.test(w) ? " " : (
        <span key={i} className="word" style={{ animationDelay: `${start + (i / 2) * step}ms` }}>{w}</span>
      ))}
    </>
  );
}

/** 불러오는 동안 보이는 뼈대 */
export function Skeleton({ lines = 3 }: { lines?: number }) {
  return (
    <div className="skeleton" role="status" aria-label="불러오는 중">
      {Array.from({ length: lines }, (_, i) => <span key={i} style={{ width: `${92 - i * 14}%`, animationDelay: `${i * 120}ms` }} />)}
    </div>
  );
}
