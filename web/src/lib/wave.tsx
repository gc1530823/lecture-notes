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
        <i key={i} className={b.exam ? "exam" : ""} style={{ height: empty ? "12%" : `${14 + (b.h / 9) * 86}%`, animationDelay: `${i * 22}ms`, ["--i" as string]: i }} />
      ))}
    </span>
  );
}

/** 녹음 중 실시간 파형: 마이크 크기(ln-level 이벤트)가 오른쪽에서 들어와 왼쪽으로 흐른다 */
/** 녹음 중 파형: 들어온 소리 크기를 시간 순서로 이어 그린 부드러운 물결 (위아래 대칭, 세 겹).
 *  소리가 오지 않으면(일시정지·조용함) 물결이 잔잔하게 가라앉는다. */
export function LiveWave({ loud }: { loud?: boolean }) {
  const cv = useRef<HTMLCanvasElement>(null);
  const loudRef = useRef(loud);
  loudRef.current = loud;
  useEffect(() => {
    const c = cv.current; if (!c) return;
    const ctx = c.getContext("2d"); if (!ctx) return;
    const N = 64;
    const levels = new Array<number>(N).fill(0.03);
    let target = 0.03, cur = 0.03, last = 0, raf = 0, t0 = performance.now();
    const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
    const onLevel = (e: Event) => { last = performance.now(); target = Math.max(0.03, Math.min(1, Math.sqrt((e as CustomEvent<number>).detail) * 1.25)); };
    window.addEventListener("ln-level", onLevel);
    const css = (name: string, fb: string) => getComputedStyle(c).getPropertyValue(name).trim() || fb;
    let tick = 0;
    const draw = (now: number) => {
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      const w = c.clientWidth, h = c.clientHeight;
      if (c.width !== Math.round(w * dpr)) { c.width = Math.round(w * dpr); c.height = Math.round(h * dpr); }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, w, h);
      if (now - last > 700) target = 0.04 + Math.sin(now / 900) * 0.015;   // 조용할 때는 숨 쉬듯
      cur += (target - cur) * 0.25;
      if (++tick % 3 === 0) { levels.shift(); levels.push(cur); }
      const mid = h / 2, t = (now - t0) / 1000;
      const quiet = now - last > 700;
      const main = loudRef.current ? css("--accent-record", "#E66C59") : quiet ? css("--accent-lav", "#B9A7E8") : css("--accent-2", "#E9A1A0");
      const thick = loudRef.current ? 1.6 : 1;
      const layers: [number, number, number][] = [[1, 0.9, 2.2 * thick], [0.62, 0.45, 1.4 * thick], [0.34, 0.25, 1]];
      layers.forEach(([amp, alpha, lw], k) => {
        ctx.beginPath();
        for (let x = 0; x <= w; x += 3) {
          const p = x / w, li = Math.min(N - 1, Math.floor(p * (N - 1)));
          const lv = levels[li] + (levels[Math.min(N - 1, li + 1)] - levels[li]) * ((p * (N - 1)) % 1);
          const edge = Math.sin(Math.PI * p);   // 양 끝은 가늘게
          const y = mid + Math.sin(p * 18 + t * (2.2 + k) + k) * lv * edge * (h * 0.46) * amp;
          if (x === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        }
        ctx.strokeStyle = main; ctx.globalAlpha = alpha; ctx.lineWidth = lw; ctx.lineCap = "round"; ctx.stroke();
      });
      ctx.globalAlpha = 1;
      if (!reduce) raf = requestAnimationFrame(draw);
    };
    raf = requestAnimationFrame(draw);
    return () => { window.removeEventListener("ln-level", onLevel); cancelAnimationFrame(raf); };
  }, []);
  return <canvas className={`live-wave live-canvas${loud ? " loud" : ""}`} ref={cv} aria-hidden="true" />;
}
