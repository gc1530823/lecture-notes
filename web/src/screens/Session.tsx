import { useState } from "react";
// 강의 다시 보기: 필기(쪽마다 포스트잇 / 노트 모드는 모눈 노트), 공부하기, 용어 사전
import type { Annotation, DocumentDetail, GlossaryTerm, SummaryResponse } from "../api/types";
import { useApi } from "../api/useApi";
import { Button, Chip, Empty, Icon, NoteSection, PostIt, TermCard, TopBar } from "../components/ui";
import { go } from "../router";
import { NotesPdf } from "./LectureExtras";
import Study from "./Study";
import { StoryEntry } from "./Story";
import { Skeleton } from "../lib/motion";

const TABS = [["notes", "필기"], ["study", "공부하기"], ["glossary", "용어 사전"]] as const;

export default function Session({ docId, sessionId, tab }: { docId: string; sessionId: string; tab: string }) {
  const { data: doc } = useApi<DocumentDetail>(`/documents/${docId}`);
  const title = { notes: doc?.title ?? "강의", study: "공부하기", glossary: "용어 사전" }[tab] ?? "강의";

  return (
    <div className="screen">
      <TopBar title={title} onBack={() => go({ name: "doc", docId })} />
      <div className="screen-body">
        <div className="scroll-x" role="tablist">
          {TABS.map(([key, label]) => (
            <Chip key={key} variant={tab === key ? "selected" : "default"} onClick={() => go({ name: "session", docId, sessionId, tab: key })}>
              {label}
            </Chip>
          ))}
        </div>
        {tab === "notes" && doc && (
          <>
            <Button variant="secondary" icon={doc.kind === "notebook" ? "notebook" : "file-pdf"}
              onClick={() => go({ name: "lecture", docId, sessionId })}>{doc.kind === "meeting" ? "회의 노트로 보기" : doc.kind === "notebook" ? "노트로 보기" : "강의자료 위에서 보기"}</Button>
            {doc.kind !== "meeting" && <StoryEntry docId={docId} sessionId={sessionId} />}
            <NotesPdf sessionId={sessionId} />
            <ExportRow sessionId={sessionId} />
            <Notes doc={doc} sessionId={sessionId} />
          </>
        )}
        {tab === "study" && <Study sessionId={sessionId} />}
        {tab === "glossary" && <Glossary sessionId={sessionId} />}
      </div>
    </div>
  );
}

function Notes({ doc, sessionId }: { doc: DocumentDetail; sessionId: string }) {
  const { data: notes } = useApi<Annotation[]>(`/sessions/${sessionId}/annotations`);
  const { data: summary } = useApi<SummaryResponse>(`/sessions/${sessionId}/summary`);
  const { data: beyond } = useApi<{ ratio?: number; annotation_ids?: number[] }>(`/sessions/${sessionId}/beyond-slides`);
  if (!notes) return <Skeleton lines={5} />;
  if (notes.length === 0) return <Empty icon="note-pencil">이 강의에는 아직 필기가 없어요</Empty>;

  const beyondIds = new Set(beyond?.annotation_ids ?? []);
  const pageSummary = new Map((summary?.summary?.pages ?? []).map((p) => [p.page_no, p.summary]));
  const pages = doc.pages.filter((p) => notes.some((n) => n.page_no === p.page_no && !n.pending));
  const overview = summary?.summary?.overview;
  const review = (summary as { review?: { checked: number; fixed: number; moved: number; deleted: number; added: number } | null } | undefined)?.review;

  if (doc.kind === "meeting") return <Minutes sessionId={sessionId} />;

  if (doc.kind === "notebook") {
    return (
      <>
        {overview && <Overview text={overview} />}
        <div className="note-sheet">
          {pages.map((p) => {
            const mine = notes.filter((n) => n.page_no === p.page_no && !n.pending);
            const key = mine.find((n) => n.type === "exam" || n.type === "emphasis");
            return <NoteSection key={p.id} number={p.page_no} title={p.text || `${p.page_no}번 주제`}
              highlight={pageSummary.get(p.page_no) ?? key?.text} lines={mine.filter((n) => n !== key).map((n) => n.text)} />;
          })}
        </div>
      </>
    );
  }

  return (
    <>
      {overview && <Overview text={overview} />}
      {review && review.checked > 0 && (
        <p className="t-caption review-note"><Icon name="check-circle" size={16} /> 수업 뒤 AI가 필기 {review.checked}개를 다시 확인했어요
          {[review.fixed ? `${review.fixed}개 고침` : "", review.moved ? `${review.moved}개 쪽 옮김` : "", review.deleted ? `${review.deleted}개 지움` : "", review.added ? `${review.added}개 더함` : ""].filter(Boolean).map((t) => ` · ${t}`).join("")}</p>
      )}
      {beyond?.ratio ? (
        <p className="t-caption muted">교수님 설명의 {Math.round(beyond.ratio * 100)}%는 슬라이드에 없던 내용이에요</p>
      ) : null}
      {pages.map((p) => {
        const mine = notes.filter((n) => n.page_no === p.page_no && !n.pending);
        const heading = (p.text || p.blocks[0]?.text || "").split("\n")[0].slice(0, 40);
        return (
          <section key={p.id} style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <h2 className="t-title-s section-title">{p.page_no}쪽 {heading && <span className="muted">· {heading}</span>}</h2>
            {pageSummary.get(p.page_no) && <p className="t-body muted">{pageSummary.get(p.page_no)}</p>}
            <div className="postit-grid">
              {mine.map((n, i) => (
                <PostIt key={n.id} type={n.type} number={i + 1} photo={n.photo_id ? `${import.meta.env.VITE_API_URL ?? ""}/photos/${n.photo_id}` : null} tag={beyondIds.has(n.id) ? "슬라이드에 없음" : undefined}>{n.text}</PostIt>
              ))}
            </div>
          </section>
        );
      })}
    </>
  );
}

function Overview({ text, title = "한눈에 보는 강의" }: { text: string; title?: string }) {
  return (
    <div className="banner">
      <strong className="t-title-s">{title}</strong>
      <p className="t-body">{text}</p>
    </div>
  );
}

function Glossary({ sessionId }: { sessionId: string }) {
  const { data: terms } = useApi<GlossaryTerm[]>(`/sessions/${sessionId}/glossary`);
  if (!terms) return <Skeleton />;
  if (terms.length === 0) return <Empty icon="book-open-text">수업 중에 잡힌 전문용어가 없어요</Empty>;
  return (
    <>
      <p className="t-caption muted">수업 중에 나온 용어 {terms.length}개 · 나온 순서</p>
      {terms.map((t) => <TermCard key={t.id} term={t.term} page={t.page_no} definition={t.definition} />)}
    </>
  );
}

/** 내보내기: Markdown 파일 받기 · 노션에 붙여 넣기 (노션은 Markdown을 붙여 넣으면 제목·목록·굵은 글씨가 그대로 살아남) */
function ExportRow({ sessionId }: { sessionId: string }) {
  const url = `${import.meta.env.VITE_API_URL ?? ""}/sessions/${sessionId}/export.md`;
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      const text = await (await fetch(url)).text();
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2500);
    } catch { alert("복사하지 못했어요. Markdown 받기를 써 주세요."); }
  };
  return (
    <div className="row" style={{ flexWrap: "wrap", gap: 8 }}>
      <a className="chip chip-accent" href={url} download>Markdown 받기</a>
      <Chip variant={copied ? "selected" : "accent"} onClick={copy}>{copied ? "복사했어요 · 노션에 붙여 넣으세요" : "노션에 붙여 넣기용 복사"}</Chip>
    </div>
  );
}

interface MinutesData {
  title: string; started_at: number; summary: string;
  topics: { page_no: number; title: string }[];
  decisions: { page_no: number; text: string }[]; open: { page_no: number; text: string }[];
  notices: { page_no: number; text: string }[]; discussion: { page_no: number; text: string }[];
  actions: { id: number; owner: string; title: string; due: string; detail: string; done: boolean }[];
}

/** 회의록: 결정 · 할 일(담당자·기한) · 미결 · 일정 · 논의 요점 */
function Minutes({ sessionId }: { sessionId: string }) {
  const { data } = useApi<MinutesData>(`/sessions/${sessionId}/minutes`);
  if (!data) return <p className="muted">회의록을 만드는 중…</p>;
  const section = (title: string, icon: string, items: { text: string }[], tone: string) => items.length > 0 && (
    <section className="jokbo-section" style={{ borderColor: `var(--note-${tone}-ink)` }}>
      <div className="row"><span style={{ color: `var(--note-${tone}-ink)` }}><Icon name={icon} /></span><h2 className="t-title-s grow">{title}</h2></div>
      {items.map((d, i) => <p key={i} className="t-body jokbo-line">· {d.text}</p>)}
    </section>
  );
  return (
    <>
      <p className="t-caption muted">{new Date(data.started_at * 1000).toLocaleString("ko-KR", { month: "long", day: "numeric", weekday: "short", hour: "numeric", minute: "2-digit" })}
        {data.topics.length ? ` · 안건 ${data.topics.map((t) => t.title).join(", ")}` : ""}</p>
      {data.summary && <Overview text={data.summary} title="회의 요약" />}
      {section("결정된 것", "check-circle", data.decisions, "emphasis")}
      {data.actions.length > 0 && (
        <section className="jokbo-section" style={{ borderColor: "var(--accent-primary)" }}>
          <div className="row"><span style={{ color: "var(--accent-primary)" }}><Icon name="check-square" /></span><h2 className="t-title-s grow">할 일</h2></div>
          {data.actions.map((a) => (
            <div key={a.id} className="action-row">
              <span className="chip chip-selected">{a.owner}</span>
              <span className="grow t-body" style={{ textDecoration: a.done ? "line-through" : undefined }}>{a.title}</span>
              {a.due && <span className="t-caption muted">{a.due}</span>}
            </div>
          ))}
        </section>
      )}
      {section("아직 안 정한 것", "warning-circle", data.open, "qa")}
      {section("일정·공지", "megaphone", data.notices, "notice")}
      {section("논의 요점", "chat-teardrop-text", data.discussion, "explanation")}
    </>
  );
}
