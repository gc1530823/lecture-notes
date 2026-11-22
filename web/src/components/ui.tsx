// Figma "02 디자인 시스템" 페이지의 컴포넌트와 1:1로 맞춘 기본 부품.
// 이름·속성(variant)도 Figma와 같게 두어 디자인과 코드를 오가기 쉽게 한다.
import { useState } from "react";
import type { ButtonHTMLAttributes, CSSProperties, ReactNode } from "react";
import { NoteText } from "./NoteText";
import type { NoteType } from "../api/types";

// 색 아이콘: 벡터(Phosphor duotone, MIT). 옅은 채움 + 선, 아이콘마다 정해진 색. 작은 조작 아이콘은 굵은 선 아이콘.
const DUO_ALIAS: Record<string, string> = {
  "file-pdf": "file-text", magnifier: "magnifying-glass", calendar: "calendar-check", "hand-palm": "question", "hand-waving": "chat-circle-dots",
  carrot: "fire", "list-numbers": "clipboard-text", "check-square": "clipboard-text", "clock-counter-clockwise": "clock", warning: "warning-circle",
  meeting: "users", "magnifying-glass": "magnifying-glass", "chat-dots": "chat-circle-dots",
};
const DUO = new Set(["microphone", "headphones", "notebook", "file-text", "book-open-text", "star", "target", "cards", "brain", "lightbulb", "note-pencil",
  "graduation-cap", "megaphone", "fire", "magnifying-glass", "shield-check", "calendar-check", "camera", "question", "chat-circle-dots", "chats-circle",
  "chat-teardrop-text", "clock", "timer", "trash", "clipboard-text", "check-circle", "warning-circle", "sparkle", "magic-wand", "tree-structure", "users",
  "chalkboard-teacher", "arrow-counter-clockwise", "waveform", "books", "notepad", "house", "gear", "upload-simple", "arrows-clockwise",
  "folder-simple-plus"]);
/** 아이콘마다의 색 (참고 디자인처럼: 일정은 파랑, 별은 노랑, 과녁은 빨강, 생각은 분홍…) */
const TONE: Record<string, string> = {
  microphone: "violet", headphones: "violet", waveform: "violet", notebook: "violet", "note-pencil": "violet", notepad: "violet", books: "violet",
  "file-text": "blue", "book-open-text": "blue", "calendar-check": "blue", question: "blue", "chat-circle-dots": "blue", "chats-circle": "blue",
  "chat-teardrop-text": "blue", "tree-structure": "blue", "magnifying-glass": "blue", "shield-check": "blue", users: "blue", "arrow-counter-clockwise": "blue",
  star: "yellow", lightbulb: "yellow", sparkle: "yellow", "magic-wand": "yellow", clock: "orange", timer: "orange", megaphone: "orange", fire: "orange",
  "warning-circle": "orange", "clipboard-text": "orange", target: "red", trash: "red", brain: "pink", cards: "pink", "graduation-cap": "violet",
  "check-circle": "green", "chalkboard-teacher": "green", camera: "slate", house: "violet", gear: "slate",
  "upload-simple": "blue", "arrows-clockwise": "blue", "folder-simple-plus": "green",
};

/** 색 벡터 아이콘이 있는 이름인지 */
export function hasArt(name: string): boolean { return DUO.has(DUO_ALIAS[name] ?? name); }

/** 아이콘. art = 색 벡터 아이콘(duotone). 없는 이름은 굵은 선 아이콘. 모두 public/icons.svg 스프라이트 */
export function Icon({ name, size = 22, art = false }: { name: string; size?: number; art?: boolean }) {
  if (art && hasArt(name)) {
    const id = DUO_ALIAS[name] ?? name;
    return (
      <svg className={`icon art tone-${TONE[id] ?? "violet"}`} width={size} height={size} style={{ width: size, height: size }} aria-hidden="true">
        <use href={`${import.meta.env.BASE_URL}icons.svg#dt-${id}`} />
      </svg>
    );
  }
  return (
    <svg className="icon" width={size} height={size} style={{ width: size, height: size }} aria-hidden="true">
      <use href={`${import.meta.env.BASE_URL}icons.svg#${name}`} />
    </svg>
  );
}

type ButtonStyle = "primary" | "secondary" | "record";
export function Button({ variant = "primary", block, icon, children, className = "", ...rest }:
  ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonStyle; block?: boolean; icon?: string }) {
  return (
    <button className={`btn btn-${variant}${block ? " btn-block" : ""} ${className}`} {...rest}>
      {icon && <Icon name={icon} size={20} />}
      {children}
    </button>
  );
}

type ChipStyle = "default" | "accent" | "selected";
export function Chip({ variant = "default", children, onClick }: { variant?: ChipStyle; children: ReactNode; onClick?: () => void }) {
  if (!onClick) return <span className={`chip chip-${variant}`}>{children}</span>;
  return (
    <button className={`chip chip-${variant}`} onClick={onClick} aria-pressed={variant === "selected"}>
      {children}
    </button>
  );
}

/** 화면 맨 위 안내: 회색 작은 글 대신 💡 연보라 상자 */
export function Hint({ children, icon = "lightbulb" }: { children: ReactNode; icon?: string }) {
  return <p className="hint"><Icon name={icon} size={16} /><span>{children}</span></p>;
}

// 근거 한 줄을 칩으로: 무엇인지 아이콘 + 짧은 말 + 숫자 (시험 예상 지도 · 족보)
const REASON: [RegExp, string, string, (m: RegExpMatchArray) => string][] = [
  [/시험에 나온다고 함 (\d+)번/, "fire", "hot", (m) => `시험 언급 ${m[1]}번`],
  [/시험 필기 (\d+)개/, "star", "exam", (m) => `시험 필기 ${m[1]}`],
  [/강조 (\d+)번/, "megaphone", "em", (m) => `강조 ${m[1]}번`],
  [/수업 중 질문 (\d+)개/, "question", "qa", (m) => `질문 ${m[1]}`],
  [/목소리 높여 말함 (\d+)번/, "speaker-high", "em", (m) => `목소리 높임 ${m[1]}`],
  [/설명 (.+)/, "clock", "time", (m) => m[1]],
  [/강의 (\d+)번에서 다룸/, "arrows-clockwise", "time", (m) => `강의 ${m[1]}번`],
];
export function ReasonChips({ reasons }: { reasons: string[] }) {
  if (!reasons.length) return <span className="reason-chips"><span className="reason-chip">언급 적음</span></span>;
  return (
    <span className="reason-chips">
      {reasons.map((r) => {
        const hit = REASON.map(([re, icon, tone, label]) => { const m = r.match(re); return m ? { icon, tone, text: label(m) } : null; }).find(Boolean);
        return <span key={r} className={`reason-chip ${hit?.tone ?? ""}`}>{hit && <Icon name={hit.icon} size={12} />}{hit?.text ?? r}</span>;
      })}
    </span>
  );
}

export function ListItem({ icon, title, subtitle, onClick, index, tone, art }: { icon: string; title: string; subtitle?: ReactNode; onClick?: () => void; index?: number; tone?: string; art?: ReactNode }) {
  // index: 목록에서 몇 번째인지 → 차례로 올라오는 모션의 늦춤
  const style = index === undefined ? undefined : { animationDelay: `${Math.min(index, 8) * 45}ms` } as CSSProperties;
  const inner = (
    <>
      <span className={`list-item-icon${art ? " has-art" : hasArt(icon) ? " is-art" : ""}`}>{art ?? <Icon name={icon} art size={40} />}</span>
      <span className="grow">
        <span className="t-title-s" style={{ display: "block" }}>{title}</span>
        {subtitle && <span className="list-item-sub">{subtitle}</span>}
      </span>
      {onClick && <span className="list-item-chev"><Icon name="caret-right" size={18} /></span>}
    </>
  );
  // 누를 곳이 없으면 버튼이 아닌 그냥 카드로 (화면 읽기 프로그램이 버튼으로 읽지 않게)
  const cls = `list-item${index === undefined ? "" : " stagger"}${tone ? ` ${tone}` : ""}`;
  return onClick ? <button className={cls} style={style} onClick={onClick}>{inner}</button> : <div className={cls} style={style}>{inner}</div>;
}

export function TopBar({ title, onBack, action, home = true }: { title: string; onBack?: () => void; action?: ReactNode; home?: boolean }) {
  return (
    <header className="top-bar">
      {onBack && (
        <button className="top-bar-back" onClick={onBack} aria-label="뒤로">
          <Icon name="caret-left" />
        </button>
      )}
      {onBack && home && (
        // 어디서든 한 번에 홈으로
        <button className="top-bar-back top-bar-home" onClick={() => { window.location.hash = "#/"; }} aria-label="홈으로">
          <Icon name="house" />
        </button>
      )}
      <h1 className="top-bar-title t-title-m">{title}</h1>
      {action}
    </header>
  );
}

export const NOTE_LABEL: Record<NoteType, string> = {
  explanation: "보충설명", example: "예시", emphasis: "강조", exam: "시험", notice: "공지", tip: "팁", qa: "질문",
};

// 회의 모드에서는 같은 종류를 회의록의 이름으로 보여 준다
export const MEETING_LABEL: Partial<Record<NoteType, string>> = {
  emphasis: "결정", explanation: "논의", example: "근거", notice: "일정", qa: "미결",
};

export function PostIt({ type, number, children, tag, photo, meeting }: {
  type: NoteType; number?: number; children: ReactNode; tag?: string; photo?: string | null; meeting?: boolean;
}) {
  const style = { "--paper": `var(--note-${type}-paper)`, "--ink": `var(--note-${type}-ink)` } as CSSProperties;
  return (
    <article className={`postit postit-${type}`} style={style}>
      {type === "exam" && !meeting && <span className="exam-stamp" aria-hidden="true">시험</span>}
      <div className="postit-head">
        <span>{(meeting && MEETING_LABEL[type]) || NOTE_LABEL[type] || type}</span>
        {number !== undefined && <span className="postit-badge">{number}</span>}
      </div>
      {photo && <img className="postit-photo" src={photo} alt="칠판 사진" loading="lazy" />}
      {typeof children === "string" ? <NoteText text={children} /> : <p className="t-note" style={{ whiteSpace: "pre-wrap" }}>{children}</p>}
      {tag && <span className="postit-tag">{tag}</span>}
    </article>
  );
}

export function TermCard({ term, page, definition }: { term: string; page?: number | null; definition: string }) {
  return (
    <article className="term-card">
      <div className="row" style={{ gap: 8 }}>
        <strong className="t-title-s grow">{term}</strong>
        {page ? <span className="t-caption faint">{page}쪽</span> : null}
      </div>
      <p className="t-body muted">{definition}</p>
    </article>
  );
}

export function NoteSection({ number, title, highlight, lines }: { number: number; title: string; highlight?: string; lines: string[] }) {
  return (
    <section className="note-section">
      <div className="row" style={{ gap: 8 }}>
        <span className="note-num">{number}</span>
        <h3 className="t-title-s">{title}</h3>
      </div>
      {highlight && <p className="note-hl t-note">{highlight}</p>}
      {lines.map((l, i) => <p key={i} className="t-note note-line">{l}</p>)}
    </section>
  );
}

/** 빈 화면: 그 내용에 맞는 3D 사물 그림 + 안내 글 */
export function Empty({ icon, children, action }: { icon: string; children: ReactNode; mood?: string; action?: { label: string; onClick: () => void; icon?: string } }) {
  return (
    <div className="empty">
      <span className="empty-art"><Icon name={icon} art size={96} /></span>
      <div>{children}</div>
      {/* 빈 화면에서 끝나지 않게: 다음에 할 일 하나 */}
      {action && <button className="btn btn-primary empty-action" onClick={action.onClick}>{action.icon && <Icon name={action.icon} size={18} />}{action.label}</button>}
    </div>
  );
}

/** 접어 두는 칸: 제목 줄을 누르면 펼친다 (펼치기 전에는 안의 것을 불러오지 않는다) */
export function Fold({ title, sub, children, defaultOpen = false }: { title: string; sub?: string; children: ReactNode; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <section className={`fold${open ? " open" : ""}`}>
      <button className="fold-head" onClick={() => setOpen(!open)} aria-expanded={open}>
        <span className="grow"><b>{title}</b>{sub && <small>{sub}</small>}</span>
        <Icon name={open ? "caret-up" : "caret-down"} size={16} />
      </button>
      {open && <div className="fold-body">{children}</div>}
    </section>
  );
}
