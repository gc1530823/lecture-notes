// 소리 무늬: 강의마다 실제 수업 흐름(말의 양·필기·시험 언급)으로 만든 파형. 강의의 얼굴(아이콘) 노릇을 한다.
// 녹음 중에는 마이크 크기로 실시간 파형이 흐른다.
import { useEffect, useRef, useState } from "react";
import { getJSON } from "../api/useApi";

export interface WaveData { w: string; x: number[] }

let cache: Promise<Record<string, WaveData>> | null = null;
/** 모든 강의의 소리 무늬 (한 번만 받아 온다. 강의가 끝나면 refreshWaves로 다시) */
export function useWaves(): Record<string, WaveData> {
  const [waves, setWaves] = useState<Record<string, WaveData>>({});
  useEffect(() => {
    cache ??= getJSON<Record<string, WaveData>>("/waves").catch(() => ({}));
    let alive = true;
    void cache.then((w) => { if (alive) setWaves(w); });
    return () => { alive = false; };
  }, []);
  return waves;
}
export function refreshWaves() { cache = null; }

/** 막대 수를 줄인다 (작은 아이콘용): 묶음에서 가장 큰 값 */
function resample(data: WaveData, bars: number): { h: number; exam: boolean }[] {
  const values = [...data.w].map(Number);
  if (values.length === 0) return Array.from({ length: bars }, () => ({ h: 0, exam: false }));
  return Array.from({ length: bars }, (_, i) => {
    const from = Math.floor((i * values.length) / bars), to = Math.max(from + 1, Math.floor(((i + 1) * values.length) / bars));
    return { h: Math.max(...values.slice(from, to)), exam: data.x.some((x) => x >= from && x < to) };
  });
}

/** 강의의 소리 무늬. bars = 막대 수 (아이콘은 9, 크게는 28) */
export function Wave({ data, bars = 9, className = "" }: { data?: WaveData; bars?: number; className?: string }) {
  const items = resample(data ?? { w: "", x: [] }, bars);
  const empty = !data?.w;
  return (
    <span className={`wave${empty ? " empty" : ""} ${className}`} style={{ gridTemplateColumns: `repeat(${bars}, 1fr)` }} aria-hidden="true">
      {items.map((b, i) => (
        <i key={i} className={b.exam ? "exam" : ""} style={{ height: empty ? "12%" : `${14 + (b.h / 9) * 86}%`, animationDelay: `${i * 22}ms` }} />
      ))}
    </span>
  );
}

const LIVE_BARS = 44;
/** 녹음 중 실시간 파형: 마이크 크기(ln-level 이벤트)가 오른쪽에서 들어와 왼쪽으로 흐른다 */
export function LiveWave({ loud }: { loud?: boolean }) {
  const root = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    const levels = new Array<number>(LIVE_BARS).fill(0.04);
    let last = 0;
    const push = (v: number) => {
      levels.shift();
      levels.push(Math.max(0.04, Math.min(1, v)));
      const bars = root.current?.children;
      if (!bars) return;
      for (let i = 0; i < bars.length; i++) (bars[i] as HTMLElement).style.transform = `scaleY(${levels[i]})`;
    };
    const onLevel = (e: Event) => { last = performance.now(); push(Math.sqrt((e as CustomEvent<number>).detail) * 1.25); };
    window.addEventListener("ln-level", onLevel);
    // 크기 정보가 안 오는 환경(옛 안드로이드 앱)에서는 잔잔하게만 움직인다
    const idle = window.setInterval(() => { if (performance.now() - last > 600) push(0.06 + Math.random() * 0.07); }, 180);
    return () => { window.removeEventListener("ln-level", onLevel); window.clearInterval(idle); };
  }, []);
  return (
    <span className={`live-wave${loud ? " loud" : ""}`} ref={root} aria-hidden="true">
      {Array.from({ length: LIVE_BARS }, (_, i) => <i key={i} />)}
    </span>
  );
}
