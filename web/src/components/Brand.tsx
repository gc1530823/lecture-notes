// LUNE 브랜드: 로고(보라 그라데이션 위 L 하나 + 손글씨 필기선)와 글자 로고(Outfit 글꼴을 벡터로 바꾼 것).
// Listen. Learn. Remember.  — 앱 아이콘(android/res/drawable/ic_launcher_*.xml, web/public/icon-*.png)과 같은 모양
import { useId } from "react";

export const TAGLINE = "Listen. Learn. Remember.";
export const MARK_L = "M200 136 V336 H322";
export const MARK_PEN = "M200 386 C 236 368, 258 404, 292 386 S 340 372, 358 380";

/** 로고 (네모 아이콘) */
export function LuneMark({ size = 40, className = "" }: { size?: number; className?: string }) {
  const id = useId().replace(/:/g, "");
  return (
    <svg className={`lune-mark ${className}`} width={size} height={size} viewBox="0 0 512 512" aria-hidden="true">
      <defs>
        <linearGradient id={`bg${id}`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" style={{ stopColor: "var(--accent-deep)" }} /><stop offset=".55" style={{ stopColor: "var(--accent-primary)" }} /><stop offset="1" style={{ stopColor: "var(--accent-2)" }} />
        </linearGradient>
        <radialGradient id={`gl${id}`} cx=".25" cy=".12" r=".7">
          <stop offset="0" stopColor="#fff" stopOpacity=".18" /><stop offset="1" stopColor="#fff" stopOpacity="0" />
        </radialGradient>
      </defs>
      <rect width="512" height="512" rx="116" fill={`url(#bg${id})`} />
      <rect width="512" height="512" rx="116" fill={`url(#gl${id})`} />
      <path className="lune-l" d={MARK_L} fill="none" stroke="#fff" strokeWidth="32" strokeLinecap="round" strokeLinejoin="round" />
      <path className="lune-pen" d={MARK_PEN} fill="none" stroke="#fff" strokeOpacity=".8" strokeWidth="12" strokeLinecap="round" />
    </svg>
  );
}

/** 글자 로고 'LUNE' (글자색 = currentColor) */
export function LuneWordmark({ height = 22, className = "", gradient = false }: { height?: number; className?: string; gradient?: boolean }) {
  return (
    <svg className={`lune-word ${className}`} height={height} viewBox="0 -703 2941 703" fill={gradient ? "url(#lune-word-g)" : "currentColor"} role="img" aria-label="LUNE">
      {gradient && (
        <defs>
          <linearGradient id="lune-word-g" x1="0" x2="1" y1="0" y2="0">
            <stop offset="0" stopColor="var(--accent-primary)" />
            <stop offset="1" style={{ stopColor: "var(--accent-2)" }} />
          </linearGradient>
        </defs>
      )}
      <path d="M72 0V-703H208V0ZM172 0V-121H530V0Z M1025 10Q942 10 877.5 -26.5Q813 -63 776 -127.0Q739 -191 739 -272V-703H875.0V-268Q875 -221 894.5 -187.0Q914 -153 948.5 -134.5Q983 -116 1025 -116Q1068 -116 1101 -134.5Q1134 -153 1153.5 -187.0Q1173 -221 1173 -267V-703H1310.0V-271Q1310 -190 1273 -126.5Q1236 -63 1172.5 -26.5Q1109 10 1025 10Z M1564 0V-703H1659.0L1700 -567V0ZM2050 0 1633 -540 1659 -703 2076 -163ZM2050 0 2011 -132V-703H2148.0V0Z M2411 0V-703H2547.0V0ZM2511 0V-120H2900.0V0ZM2511 -301V-417H2865.0V-301ZM2511 -583V-703H2895.0V-583Z" />
    </svg>
  );
}
