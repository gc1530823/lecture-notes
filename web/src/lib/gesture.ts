// 카드 넘기기 손짓: 손가락(또는 마우스)으로 카드를 옆으로 밀면 기울며 따라오고,
// 충분히 밀었다 놓으면 그 방향으로 날아가며 onLeft / onRight, 덜 밀면 제자리로 튕겨 돌아온다.
// 짧게 누르기(탭)는 그대로 click 으로 지나가므로 "눌러서 뒤집기"와 함께 쓸 수 있다.
import { useEffect, type RefObject } from "react";
import { play } from "./sound";

const THRESHOLD = 90;   // 이만큼 밀면 넘긴다 (px)
const TAP = 8;          // 이보다 덜 움직이면 탭

export function useSwipe(ref: RefObject<HTMLElement | null>, opts: { onLeft?: () => void; onRight?: () => void; enabled?: boolean; bind?: unknown }) {
  // bind: 카드 요소가 새로 그려질 때(key가 바뀔 때) 다시 붙이기 위한 값
  const { onLeft, onRight, enabled = true, bind } = opts;
  useEffect(() => {
    const el = ref.current;
    if (!el || !enabled || (!onLeft && !onRight)) return;
    let startX = 0, startY = 0, dx = 0, dragging = false, id = -1;
    const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
    const set = (x: number, animate: boolean) => {
      el.style.transition = animate ? "transform .35s cubic-bezier(.2,.8,.2,1), opacity .35s" : "none";
      el.style.transform = x ? `translateX(${x}px) rotate(${x / 18}deg)` : "";
      el.dataset.swipe = x > 30 ? "right" : x < -30 ? "left" : "";
    };
    const down = (e: PointerEvent) => {
      if ((e.target as HTMLElement).closest("input, textarea, select")) return;
      startX = e.clientX; startY = e.clientY; dx = 0; dragging = false; id = e.pointerId;
    };
    const move = (e: PointerEvent) => {
      if (e.pointerId !== id) return;
      const mx = e.clientX - startX, my = e.clientY - startY;
      if (!dragging) {
        if (Math.abs(mx) < TAP || Math.abs(my) > Math.abs(mx)) return; // 세로 스크롤은 그대로
        dragging = true;
        el.setPointerCapture(id);
      }
      dx = mx;
      if ((dx > 0 && !onRight) || (dx < 0 && !onLeft)) dx /= 4; // 갈 수 없는 쪽은 살짝만
      set(dx, false);
    };
    const up = (e: PointerEvent) => {
      if (e.pointerId !== id) return;
      id = -1;
      if (!dragging) return;
      // 끌었던 것은 클릭(뒤집기)으로 치지 않는다
      const swallow = (ev: Event) => { ev.stopPropagation(); ev.preventDefault(); };
      el.addEventListener("click", swallow, { capture: true, once: true });
      window.setTimeout(() => el.removeEventListener("click", swallow, { capture: true }), 50);
      const go = dx > THRESHOLD && onRight ? onRight : dx < -THRESHOLD && onLeft ? onLeft : null;
      if (!go) { set(0, true); return; }
      play("swish");
      if (still) { go(); return; }
      el.style.transition = "transform .28s ease-in, opacity .28s ease-in";
      el.style.transform = `translateX(${Math.sign(dx) * 520}px) rotate(${Math.sign(dx) * 22}deg)`;
      el.style.opacity = "0";
      window.setTimeout(go, 220);
    };
    el.addEventListener("pointerdown", down);
    el.addEventListener("pointermove", move);
    el.addEventListener("pointerup", up);
    el.addEventListener("pointercancel", up);
    el.style.touchAction = "pan-y";
    return () => {
      el.removeEventListener("pointerdown", down);
      el.removeEventListener("pointermove", move);
      el.removeEventListener("pointerup", up);
      el.removeEventListener("pointercancel", up);
    };
  }, [ref, onLeft, onRight, enabled, bind]);
}
