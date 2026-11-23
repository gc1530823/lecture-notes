// 이 기기의 설정 (설정 화면). 브라우저 저장소에 두고, 앱이 켜질 때 화면에 바로 적용한다.
export interface Prefs {
  theme: "system" | "light" | "dark";   // 화면 색
  text: "normal" | "large" | "xlarge";  // 글자 크기 (1 · 1.15 · 1.3배)
  motion: "full" | "reduce";            // 움직임
  vibrate: boolean;                     // 진동
  quizCount: number;                    // 퀴즈 카드 기본 장 수
  reminder: number;                     // 복습 알림 시각 (시, 0 = 끄기) · 안드로이드 앱
  dueAlarm: boolean;                    // 할 일 마감 알림 (하루 전 저녁·당일 아침)
  classAlarm: boolean;                  // 수업 시작 5분 전 알림
}

const KEY = "ln.prefs";
export const DEFAULT_PREFS: Prefs = { theme: "system", text: "normal", motion: "full", vibrate: true, quizCount: 8, reminder: 20, dueAlarm: true, classAlarm: true };

export function getPrefs(): Prefs {
  try { return { ...DEFAULT_PREFS, ...JSON.parse(localStorage.getItem(KEY) || "{}") }; } catch { return DEFAULT_PREFS; }
}

const realVibrate = typeof navigator !== "undefined" && navigator.vibrate ? navigator.vibrate.bind(navigator) : null;

let skyTimer = 0;
export function isNight(d = new Date()): boolean { const h = d.getHours(); return h >= 19 || h < 6; }

/** 설정을 화면에 적용한다: 색 · 글자 크기 · 움직임 · 진동 */
export function applyPrefs(p: Prefs = getPrefs()) {
  const root = document.documentElement;
  // 자동: 진짜 하늘처럼 낮엔 크림, 해가 지면(저녁 7시~아침 6시) 밤하늘
  root.dataset.theme = p.theme === "system" ? (isNight() ? "dark" : "light") : p.theme;
  root.dataset.hour = isNight() ? "night" : "day";
  window.clearTimeout(skyTimer);
  skyTimer = window.setTimeout(() => applyPrefs(getPrefs()), 60_000);
  root.dataset.text = p.text;
  root.dataset.motion = p.motion;
  if (realVibrate) navigator.vibrate = p.vibrate ? realVibrate : () => false;
}

export function setPrefs(change: Partial<Prefs>): Prefs {
  const next = { ...getPrefs(), ...change };
  try { localStorage.setItem(KEY, JSON.stringify(next)); } catch { /* 괜찮다 */ }
  applyPrefs(next);
  return next;
}
