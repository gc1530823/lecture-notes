// 미끄러지는 탭: 고른 탭 아래의 흰 알약이 옆으로 미끄러져 옮겨 간다 (화면 안의 탭 · 공부 도구 고르기)
import { useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { play } from "../lib/sound";

export default function SlidingTabs<K extends string>({ items, value, onChange, scroll = false, label }:
  { items: readonly (readonly [K, ReactNode])[]; value: K; onChange: (k: K) => void; scroll?: boolean; label: string }) {
  const root = useRef<HTMLDivElement>(null);
  const [pill, setPill] = useState<{ x: number; w: number } | null>(null);
  useLayoutEffect(() => {
    const el = root.current?.querySelector<HTMLElement>(`[data-key="${value}"]`);
    if (!el) return;
    setPill({ x: el.offsetLeft, w: el.offsetWidth });
    if (scroll) el.scrollIntoView({ block: "nearest", inline: "center", behavior: "smooth" });
    const ro = new ResizeObserver(() => setPill({ x: el.offsetLeft, w: el.offsetWidth }));
    ro.observe(el);
    return () => ro.disconnect();
  }, [value, scroll, items.length]);
  return (
    <div ref={root} className={`slide-tabs${scroll ? " scroll" : ""}`} role="tablist" aria-label={label}>
      {pill && <span className="slide-pill" style={{ transform: `translateX(${pill.x}px)`, width: pill.w }} aria-hidden="true" />}
      {items.map(([k, l]) => (
        <button key={k} data-key={k} role="tab" aria-selected={k === value} className={k === value ? "on" : ""}
          onClick={() => { if (k !== value) { play("tick"); onChange(k); } }}>{l}</button>
      ))}
    </div>
  );
}
