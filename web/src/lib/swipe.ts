// 손가락으로 좌우로 밀기: 가로로 충분히(60px) 밀고 세로보다 확실히 가로일 때만 (세로 스크롤과 헷갈리지 않게).
// 안쪽에 data-swipe 가 있는 요소(예: 시간표 주 넘기기)에서 시작한 밀기는 바깥에서 무시한다.
import { useRef, type TouchEvent } from "react";

export function useSwipe(onLeft: () => void, onRight: () => void, own?: string) {
  const start = useRef<{ x: number; y: number; t: number; skip: boolean } | null>(null);
  return {
    onTouchStart: (e: TouchEvent) => {
      const el = e.target as HTMLElement;
      const inner = el.closest("[data-swipe]");
      const skip = !!el.closest("input, textarea, select, .slide-tabs.scroll, [data-noswipe]") || (inner !== null && inner.getAttribute("data-swipe") !== own);
      start.current = { x: e.touches[0].clientX, y: e.touches[0].clientY, t: Date.now(), skip };
    },
    onTouchEnd: (e: TouchEvent) => {
      const s = start.current;
      start.current = null;
      if (!s || s.skip) return;
      const dx = e.changedTouches[0].clientX - s.x;
      const dy = e.changedTouches[0].clientY - s.y;
      if (Math.abs(dx) < 60 || Math.abs(dx) < Math.abs(dy) * 1.6 || Date.now() - s.t > 800) return;
      if (dx < 0) onLeft(); else onRight();
    },
  };
}
