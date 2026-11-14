// 필기 글을 '노트처럼' 보여 준다: 제목(굵게·필기 색) → 내용 → 항목(번호·칩). 글 자체는 바꾸지 않고 모양만 나눈다.
//   "교착 상태 네 조건: 상호 배제·점유와 대기·비선점·순환 대기" → 제목 + 칩 4개
//   "Q. …\nA. … (1) … (2) … 이 네 조건이…" → 질문 제목 + 답 + 번호 목록 + 마무리 문장
import type { ReactNode } from "react";

export interface NoteParts { q: boolean; title: string; intro: string; items: string[]; chips: boolean; outro: string }

const ENUM = /\s*(?:\((\d{1,2})\)|([①-⑳])|(?:^|\s)(\d{1,2})\)|(?:^|\s)(\d{1,2})\.\s)\s*/g;

/** 글을 제목 · 앞 문장 · 항목 · 뒤 문장으로 나눈다 (못 나누면 앞 문장에 전부) */
export function splitNote(raw: string): NoteParts {
  let text = raw.replace(/\r/g, "").trim();
  let title = "";
  let q = false;
  // 질문 필기: "Q. 질문\nA. 답"
  const qa = text.match(/^Q[.:]\s*([^\n]+)\n+\s*(?:A[.:]\s*)?([\s\S]*)$/);
  if (qa) { q = true; title = qa[1].trim(); text = qa[2].trim(); }
  else {
    // "제목: 내용" (시각 09:00 같은 것은 빼고, 제목이 짧을 때만)
    const m = text.match(/^([^:=\n]{2,28}?)\s*(?:[:：]|\s=)\s+([\s\S]+)$/);
    if (m && !/[.!?다요]$/.test(m[1].trim()) && !/\d$/.test(m[1])) { title = m[1].trim(); text = m[2].trim(); }
    else if (!text.includes("\n") && text.length <= 34 && !/[.!?]$/.test(text)) { title = text; text = ""; }
  }

  // 줄머리표 목록: "- 가\n- 나"
  const lines = text.split("\n").map((l) => l.trim()).filter(Boolean);
  const bullet = /^(?:[-•·▶→*]|\d{1,2}[.)])\s*/;
  if (lines.length >= 2 && lines.filter((l) => bullet.test(l)).length >= 2) {
    const first = bullet.test(lines[0]) ? "" : lines.shift()!;
    const items: string[] = [];
    const rest: string[] = [];
    for (const l of lines) {
      if (bullet.test(l) && !rest.length) items.push(l.replace(bullet, "")); else rest.push(l);
    }
    return { q, title, intro: first, items, chips: false, outro: rest.join(" ") };
  }

  // 글 안의 번호: "(1) … (2) …", "① … ②"
  const marks = [...text.matchAll(ENUM)];
  if (marks.length >= 2) {
    const intro = text.slice(0, marks[0].index).trim().replace(/[:：]$/, "");
    const items: string[] = [];
    for (let i = 0; i < marks.length; i++) {
      const start = marks[i].index! + marks[i][0].length;
      const end = i + 1 < marks.length ? marks[i + 1].index! : text.length;
      items.push(text.slice(start, end).trim().replace(/[,，]$/, ""));
    }
    // 마지막 항목 뒤에 이어지는 문장(". 이 네 조건이…")은 마무리 문장으로
    let outro = "";
    const last = items[items.length - 1];
    const cut = last.search(/[.。]\s+\S/);
    if (cut > 0) { outro = last.slice(cut + 1).trim(); items[items.length - 1] = last.slice(0, cut).trim(); }
    return { q, title, intro, items: items.filter(Boolean), chips: false, outro };
  }

  // 짧은 낱말 나열: "상호 배제·점유와 대기·비선점·순환 대기"
  const parts = text.split(/\s*[·∙]\s*|\s*,\s*/).map((p) => p.trim()).filter(Boolean);
  if (!text.includes("\n") && parts.length >= 3 && parts.every((p) => p.length <= 16 && !/[.!?]$/.test(p))) {
    return { q, title, intro: "", items: parts, chips: true, outro: "" };
  }
  return { q, title, intro: text, items: [], chips: false, outro: "" };
}

/** 글 안의 강조: **굵게**, ‘따옴표’, 날짜·마감, 영어 이름 (Deadlock) */
function inline(text: string): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /\*\*([^*]+)\*\*|[‘'“"]([^’'”"]{1,24})[’'”"]|((?:다음\s?주|이번\s?주)\s?\S{1,3}요일(?:까지)?|\d{1,2}월\s?\d{1,2}일(?:까지)?|\d{1,2}\/\d{1,2}(?:까지)?)|\(([A-Za-z][A-Za-z0-9 '’.-]{1,40})\)/g;
  let at = 0;
  let k = 0;
  for (const m of text.matchAll(re)) {
    if (m.index! > at) out.push(text.slice(at, m.index));
    if (m[1]) out.push(<strong key={k++}>{m[1]}</strong>);
    else if (m[2]) out.push(<strong key={k++}>{m[2]}</strong>);
    else if (m[3]) out.push(<mark key={k++} className="note-due">{m[3]}</mark>);
    else if (m[4]) out.push(<span key={k++} className="note-en">{m[4]}</span>);
    at = m.index! + m[0].length;
  }
  if (at < text.length) out.push(text.slice(at));
  return out;
}

/** 항목: "… 할 수 있는 상호 배제" 처럼 끝에 개념 이름이 오면 그 이름을 굵게, "이름: 설명"·"이름 — 설명"도 굵게 */
function item(text: string): ReactNode {
  const named = text.match(/^(.{1,18}?)\s*(?:[:：]|—|–|-|=)\s+(.+)$/);
  if (named) return <><strong>{named[1]}</strong> <span className="note-sub">{inline(named[2])}</span></>;
  const tail = text.match(/^(.*\S(?:는|은|인|한|된|진|운|른|던|할|일))\s+([가-힣A-Za-z]{1,8}(?:\s[가-힣A-Za-z]{1,6})?)$/);
  if (tail && tail[1].length >= 4) return <><span className="note-sub">{inline(tail[1])}</span> <strong>{tail[2]}</strong></>;
  return inline(text);
}

export function NoteText({ text }: { text: string }) {
  const n = splitNote(text);
  return (
    <div className="note-text">
      {n.title && (
        <p className={`note-title${n.q ? " q" : ""}`}>{n.q && <span className="note-q">Q</span>}<span>{inline(n.title)}</span></p>
      )}
      {n.intro && <p className={`note-body${n.title ? "" : " solo"}`}>{inline(n.intro)}</p>}
      {n.items.length > 0 && (n.chips ? (
        <div className="note-chips">{n.items.map((x, i) => <span key={i}>{inline(x)}</span>)}</div>
      ) : (
        <ol className="note-list">{n.items.map((x, i) => <li key={i}><i>{i + 1}</i><span>{item(x)}</span></li>)}</ol>
      ))}
      {n.outro && <p className="note-outro">{inline(n.outro)}</p>}
    </div>
  );
}
