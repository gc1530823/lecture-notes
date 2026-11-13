// 과목 블록 색: 과목 이름으로 여덟 색 가운데 하나가 정해진다 (어느 화면에서든 같은 과목은 같은 색).
export function courseTone(course: string | null | undefined): string {
  if (!course) return "blk-none";
  let hash = 0;
  for (const ch of course) hash = (hash * 31 + ch.codePointAt(0)!) >>> 0;
  return `blk-${hash % 8}`;
}
