// 누를 때 짧은 진동 (안드로이드 앱 · 진동을 지원하는 폰 브라우저). 아이폰 사파리는 진동을 막아 두어 조용히 넘어간다.
// 설정에서 끌 수 있게 ln.haptic = "off" 면 울리지 않는다.
const PATTERN = { light: 8, medium: 14, heavy: [18, 40, 18] } as const;

export function haptic(kind: keyof typeof PATTERN = "light"): void {
  try {
    if (localStorage.getItem("ln.haptic") === "off") return;
    navigator.vibrate?.(PATTERN[kind] as number | number[]);
  } catch { /* 진동이 없는 기기 */ }
}
