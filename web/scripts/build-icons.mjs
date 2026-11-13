// 작은 조작 아이콘(뒤로·닫기·재생 같은 것) 스프라이트를 만든다: Phosphor 아이콘(MIT)의 굵은(bold) 모양.
// 컨셉이 둥글고 통통해서 가는 선보다 굵은 선이 어울린다. 큰 아이콘은 AI로 그린 그림(public/art)이 맡는다.
//   node scripts/build-icons.mjs   → public/icons.svg
import { readFileSync, writeFileSync, existsSync } from "node:fs";

const out = "public/icons.svg";
const old = readFileSync(out, "utf8");
const ids = [...old.matchAll(/<symbol id="([^"]+)"/g)].map((m) => m[1]).filter((id) => !id.startsWith("dt-"));
for (const extra of ["plus", "magnifying-glass", "stop", "arrow-right", "check", "carrot"]) if (!ids.includes(extra)) ids.push(extra);
let symbols = ids.map((id) => {
  const file = `node_modules/@phosphor-icons/core/assets/bold/${id}-bold.svg`;
  if (!existsSync(file)) { // Phosphor에 없는 이름은 예전 모양 그대로
    const kept = old.match(new RegExp(`<symbol id="${id}"[\\s\\S]*?</symbol>`));
    return kept ? kept[0] : "";
  }
  const inner = readFileSync(file, "utf8").replace(/^[\s\S]*?<svg[^>]*>/, "").replace(/<\/svg>\s*$/, "");
  return `<symbol id="${id}" viewBox="0 0 256 256" fill="currentColor">${inner}</symbol>`;
});
// 색 아이콘: Phosphor duotone(옅은 채움 + 선). 화면에서 아이콘마다 색을 입힌다 (components/ui.tsx 의 TONE)
const DUO = ["microphone", "headphones", "notebook", "file-text", "book-open-text", "star", "target", "cards", "brain", "lightbulb", "note-pencil",
  "graduation-cap", "megaphone", "fire", "magnifying-glass", "shield-check", "calendar-check", "camera", "question", "chat-circle-dots", "chats-circle",
  "chat-teardrop-text", "clock", "timer", "trash", "clipboard-text", "check-circle", "warning-circle", "sparkle", "magic-wand", "tree-structure", "users",
  "chalkboard-teacher", "arrow-counter-clockwise", "waveform", "books", "notepad", "house", "gear", "file-pdf", "hand-palm"];
for (const id of DUO) {
  const inner = readFileSync(`node_modules/@phosphor-icons/core/assets/duotone/${id}-duotone.svg`, "utf8").replace(/^[\s\S]*?<svg[^>]*>/, "").replace(/<\/svg>\s*$/, "");
  symbols.push(`<symbol id="dt-${id}" viewBox="0 0 256 256" fill="currentColor">${inner}</symbol>`);
}
for (const extra of ["house", "notepad", "dots-three-outline", "gear", "pause", "magnifying-glass", "export", "sliders-horizontal", "speaker-high"]) {
  const file = `node_modules/@phosphor-icons/core/assets/bold/${extra}-bold.svg`;
  if (!ids.includes(extra) && existsSync(file)) {
    const inner = readFileSync(file, "utf8").replace(/^[\s\S]*?<svg[^>]*>/, "").replace(/<\/svg>\s*$/, "");
    symbols.push(`<symbol id="${extra}" viewBox="0 0 256 256" fill="currentColor">${inner}</symbol>`);
  }
}
writeFileSync(out, `<svg xmlns="http://www.w3.org/2000/svg" style="display:none">\n${symbols.filter(Boolean).join("\n")}\n</svg>\n`);
console.log(`${symbols.filter(Boolean).length}개 아이콘 → ${out}`);
