// 안드로이드 앱에만 있는 기능 (window.AndroidLive): 홈 화면 위젯에 시간표 넘기기 · 상태바 색 맞추기.
// 예전 앱(이 기능이 없는 버전)이나 브라우저에서는 조용히 넘어간다.
type Native = { saveTimetable?: (json: string) => void; statusBar?: (color: string, light: boolean) => void };
const native = () => (window as unknown as { AndroidLive?: Native }).AndroidLive;

/** 시간표를 불러올 때마다 위젯에 넘긴다 (위젯은 인터넷 없이 이것만 본다) */
export function shareTimetable(rows: { course: string; weekday: number; start: string; end: string; place: string }[]): void {
  try { native()?.saveTimetable?.(JSON.stringify(rows.map(({ course, weekday, start, end, place }) => ({ course, weekday, start, end, place })))); }
  catch { /* 예전 앱 */ }
}

/** 상태바(위) · 버튼 줄(아래)과 브라우저 주소창 색을 화면 바탕색에 맞춘다. 밝은/어두운 화면이 바뀔 때마다 */
export function followStatusBar(): void {
  const apply = () => {
    const bg = getComputedStyle(document.documentElement).getPropertyValue("--bg-paper").trim() || "#f6f5fb";
    const hex = bg.startsWith("#") && bg.length === 4 ? `#${[...bg.slice(1)].map((c) => c + c).join("")}` : bg;
    const n = parseInt(hex.slice(1, 7), 16);
    const light = ((n >> 16) & 255) * 0.3 + ((n >> 8) & 255) * 0.59 + (n & 255) * 0.11 > 140;
    document.querySelector('meta[name="theme-color"]')?.setAttribute("content", hex);
    try { native()?.statusBar?.(hex, light); } catch { /* 예전 앱 */ }
  };
  apply();
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", apply);
  new MutationObserver(apply).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
}
