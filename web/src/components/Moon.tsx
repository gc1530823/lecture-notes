// 오늘의 실제 달 모양: 날짜로 달의 위상(0=삭, 0.5=보름)을 계산해 그린다. LUNE의 상징.
const SYNODIC = 29.530588853;
const NEW_MOON = Date.UTC(2000, 0, 6, 18, 14) / 86400000; // 기준 삭 (2000-01-06 18:14 UTC)

export function moonPhase(d = new Date()): number {
  const days = d.getTime() / 86400000 - NEW_MOON;
  return ((days / SYNODIC) % 1 + 1) % 1;
}

export function moonName(p: number): string {
  if (p < 0.03 || p > 0.97) return "삭";
  if (p < 0.22) return "초승달";
  if (p < 0.28) return "상현달";
  if (p < 0.47) return "차오르는 달";
  if (p < 0.53) return "보름달";
  if (p < 0.72) return "기우는 달";
  if (p < 0.78) return "하현달";
  return "그믐달";
}

/** 보름까지 며칠 (지났으면 다음 삭까지) */
export function moonNext(p: number): string {
  const toFull = Math.round(((0.5 - p + 1) % 1) * SYNODIC);
  const toNew = Math.round(((1 - p) % 1) * SYNODIC);
  if (p < 0.47) return `보름까지 ${toFull}일`;
  if (p < 0.53) return "오늘 밤 보름";
  return `그믐까지 ${toNew}일`;
}

export function Moon({ size = 64, phase = moonPhase(), className = "" }: { size?: number; phase?: number; className?: string }) {
  const r = 50;
  const k = Math.cos(2 * Math.PI * phase);   // 1: 삭, -1: 보름
  const waxing = phase < 0.5;
  // 밝은 쪽 반원 + 경계선(타원 반쪽)
  const lit = `M0 ${-r} A${r} ${r} 0 0 1 0 ${r} A${Math.abs(k) * r} ${r} 0 0 ${k > 0 ? 0 : 1} 0 ${-r}Z`;
  return (
    <svg className={`moon ${className}`} width={size} height={size} viewBox="-56 -56 112 112" role="img" aria-label={moonName(phase)}>
      <circle r={r} className="moon-dark" />
      <path d={lit} className="moon-lit" transform={waxing ? undefined : "scale(-1 1)"} />
      <circle cx={-16} cy={-14} r={6} className="moon-crater" /><circle cx={14} cy={18} r={9} className="moon-crater" /><circle cx={22} cy={-20} r={4} className="moon-crater" />
    </svg>
  );
}
