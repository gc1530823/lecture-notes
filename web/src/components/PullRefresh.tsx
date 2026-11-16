// 당겨서 새로고침: 화면 맨 위에서 아래로 당기면 위에 보라 동그라미가 내려오고, 충분히 당겼다 놓으면 화면을 새로 불러온다.
// 녹음 화면처럼 새로 그리면 안 되는 곳은 enabled=false 로 끈다.
import { useEffect, useRef, useState } from "react";
import { haptic } from "../lib/haptic";
import { Icon } from "./ui";

const LIMIT = 72;   // 이만큼(화면에서 보이는 거리) 당기면 새로고침

export function PullRefresh({ enabled, onRefresh }: { enabled: boolean; onRefresh: () => void }) {
  const [pull, setPull] = useState(0);
  const [spinning, setSpinning] = useState(false);
  const start = useRef<{ x: number; y: number } | null>(null);
  const armed = useRef(false);
  useEffect(() => {
    if (!enabled) return;
    const down = (e: TouchEvent) => {
      const el = e.target as HTMLElement;
      if (window.scrollY > 0 || document.querySelector(".sheet, .sheet-back") || el.closest("input, textarea, select, [data-noswipe], .pdf-viewer")) { start.current = null; return; }
      start.current = { x: e.touches[0].clientX, y: e.touches[0].clientY };
      armed.current = false;
    };
    const move = (e: TouchEvent) => {
      if (!start.current) return;
      const dy = e.touches[0].clientY - start.current.y;
      const dx = Math.abs(e.touches[0].clientX - start.current.x);
      if (dy <= 0 || dx > dy || window.scrollY > 0) { setPull(0); return; }
      const shown = Math.min(110, dy * 0.45);
      setPull(shown);
      if (shown >= LIMIT && !armed.current) { armed.current = true; haptic("light"); }
      if (shown < LIMIT) armed.current = false;
    };
    const up = () => {
      if (!start.current) return;
      start.current = null;
      if (armed.current) {
        setSpinning(true);
        setPull(LIMIT * 0.8);
        window.setTimeout(() => { onRefresh(); }, 120);
        window.setTimeout(() => { setSpinning(false); setPull(0); }, 700);
      } else setPull(0);
      armed.current = false;
    };
    document.addEventListener("touchstart", down, { passive: true });
    document.addEventListener("touchmove", move, { passive: true });
    document.addEventListener("touchend", up);
    document.addEventListener("touchcancel", up);
    return () => {
      document.removeEventListener("touchstart", down);
      document.removeEventListener("touchmove", move);
      document.removeEventListener("touchend", up);
      document.removeEventListener("touchcancel", up);
    };
  }, [enabled, onRefresh]);
  if (!pull && !spinning) return null;
  const ready = pull >= LIMIT || spinning;
  return (
    <div className={`pull-refresh${spinning ? " spinning" : ""}${ready ? " ready" : ""}`} style={{ transform: `translate(-50%, ${pull - 44}px)` }} aria-hidden>
      <span style={{ transform: spinning ? undefined : `rotate(${pull * 4}deg)` }}><Icon name="arrows-clockwise" size={20} /></span>
    </div>
  );
}
