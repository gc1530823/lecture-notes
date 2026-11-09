// Figma "02 디자인 시스템" 페이지의 컴포넌트와 1:1로 맞춘 기본 부품.
// 이름·속성(variant)도 Figma와 같게 두어 디자인과 코드를 오가기 쉽게 한다.
import type { ButtonHTMLAttributes, CSSProperties, ReactNode } from "react";
import type { NoteType } from "../api/types";

/** Phosphor 아이콘 (MIT, public/icons.svg 스프라이트) */
export function Icon({ name, size = 22 }: { name: string; size?: number }) {
  return (
    <svg className="icon" width={size} height={size} aria-hidden="true">
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

export function ListItem({ icon, title, subtitle, onClick }: { icon: string; title: string; subtitle?: string; onClick?: () => void }) {
  const inner = (
    <>
      <span className="list-item-icon"><Icon name={icon} /></span>
      <span className="grow">
        <span className="t-title-s" style={{ display: "block" }}>{title}</span>
        {subtitle && <span className="list-item-sub">{subtitle}</span>}
      </span>
      {onClick && <span className="list-item-chev"><Icon name="caret-right" size={18} /></span>}
    </>
  );
  // 누를 곳이 없으면 버튼이 아닌 그냥 카드로 (화면 읽기 프로그램이 버튼으로 읽지 않게)
  return onClick ? <button className="list-item" onClick={onClick}>{inner}</button> : <div className="list-item">{inner}</div>;
}

export function TopBar({ title, onBack, action }: { title: string; onBack?: () => void; action?: ReactNode }) {
  return (
    <header className="top-bar">
      {onBack && (
        <button className="top-bar-back" onClick={onBack} aria-label="뒤로">
          <Icon name="caret-left" />
        </button>
      )}
      <h1 className="top-bar-title t-title-m">{title}</h1>
      {action}
    </header>
  );
}

export const NOTE_LABEL: Record<NoteType, string> = {
  explanation: "보충설명", example: "예시", emphasis: "강조", exam: "시험", notice: "공지", tip: "AI 팁", qa: "질문",
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
    <article className="postit" style={style}>
      <div className="postit-head">
        <span>{(meeting && MEETING_LABEL[type]) || NOTE_LABEL[type] || type}</span>
        {number !== undefined && <span className="postit-badge">{number}</span>}
      </div>
      {photo && <img className="postit-photo" src={photo} alt="칠판 사진" loading="lazy" />}
      <p className="t-note" style={{ whiteSpace: "pre-wrap" }}>{children}</p>
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
      {lines.map((l, i) => <p key={i} className="t-note">· {l}</p>)}
    </section>
  );
}

export function Empty({ icon, children }: { icon: string; children: ReactNode }) {
  return <div className="empty"><Icon name={icon} size={36} /><div>{children}</div></div>;
}
