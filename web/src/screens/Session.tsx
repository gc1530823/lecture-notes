import { useEffect, useState } from "react";
// 강의 다시 보기: 필기 → 정리 → 공부 → 용어 (공부하는 순서대로)
import type { Annotation, DocumentDetail, GlossaryTerm, SummaryResponse } from "../api/types";
import { getJSON, postJSON, useApi } from "../api/useApi";
import { Button, Chip, Empty, Fold, Hint, Icon, NoteSection, PostIt, TermCard, TopBar } from "../components/ui";
import { back, go } from "../router";
import { NotesPdf, StudyNotePdf } from "./LectureExtras";
import Study, { ConceptExplain, Organize } from "./Study";
import { StoryEntry, jumpToMoment } from "./Story";
import { Skeleton } from "../lib/motion";
import SlidingTabs from "../components/SlidingTabs";
import { askYes, tell } from "../components/Dialog";

const TABS = [["notes", "필기"], ["organize", "정리"], ["study", "공부"], ["glossary", "용어"]] as const;

export default function Session({ docId, sessionId, tab }: { docId: string; sessionId: string; tab: string }) {
  const { data: doc } = useApi<DocumentDetail>(`/documents/${docId}`);
  const title = doc?.title ?? "강의";

  return (
    <div className="screen">
      <TopBar title={title} onBack={() => back({ name: "doc", docId })} />
      <div className="screen-body">
        <SlidingTabs label="강의 보기" items={TABS} value={tab as (typeof TABS)[number][0]} onChange={(key) => go({ name: "session", docId, sessionId, tab: key })} />
        {tab === "notes" && doc && (
          <>
            <Button variant="secondary" icon={doc.kind === "notebook" ? "notebook" : "file-pdf"}
              onClick={() => go({ name: "lecture", docId, sessionId })}>{doc.kind === "meeting" ? "회의 노트로 보기" : doc.kind === "notebook" ? "노트로 보기" : "슬라이드에서 보기"}</Button>
            <Renote sessionId={sessionId} />
            <Notes doc={doc} sessionId={sessionId} />
          </>
        )}
        {tab === "organize" && doc && (
          <>
            <Organize sessionId={sessionId} />
            <h3 className="t-title-s section-title">내려받기</h3>
            <StudyNotePdf sessionId={sessionId} />
            <NotesPdf sessionId={sessionId} />
            <ExportRow sessionId={sessionId} />
            {/* 1분 스토리는 덤: 정리 탭 맨 아래 */}
            {doc.kind !== "meeting" && <Fold title="한눈에 넘겨 보기" sub="1분 만에 수업 흐름 보기"><StoryEntry docId={docId} sessionId={sessionId} /></Fold>}
          </>
        )}
        {tab === "study" && <Study sessionId={sessionId} docId={docId} />}
        {tab === "glossary" && (
          <>
            <Glossary sessionId={sessionId} />
            <h3 className="t-title-s section-title">개념 설명 <span className="t-caption faint">예시까지 더 자세히</span></h3>
            <ConceptExplain sessionId={sessionId} />
          </>
        )}
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

  const linesOf = (p: DocumentDetail["pages"][number]) => (p.text || p.blocks.map((b) => b.text).join("\n")).split("\n")
    .map((l) => l.replace(/[\uE000-\uF8FF\uFFFD]/g, "").trim()).filter(Boolean);
  const firstCount = new Map<string, number>();
  for (const p of pages) { const l = linesOf(p)[0]; if (l) firstCount.set(l, (firstCount.get(l) ?? 0) + 1); }
  return (
    <>
      {overview && <Overview text={overview} />}
      {review && review.checked > 0 && (
        <p className="t-caption review-note"><Icon name="check-circle" size={16} /> 수업 뒤 AI가 필기 {review.checked}개를 다시 확인했어요
          {[review.fixed ? `${review.fixed}개 고침` : "", review.moved ? `${review.moved}개 쪽 옮김` : "", review.deleted ? `${review.deleted}개 지움` : "", review.added ? `${review.added}개 더함` : ""].filter(Boolean).map((t) => `, ${t}`).join("")}</p>
      )}
      {beyond?.ratio ? (
        <Hint icon="sparkle">교수님 설명의 <b>{Math.round(beyond.ratio * 100)}%</b>는 슬라이드에 없던 내용이에요</Hint>
      ) : null}
      {pages.map((p) => {
        const mine = notes.filter((n) => n.page_no === p.page_no && !n.pending);
        // 쪽마다 똑같이 찍힌 머리글(강의 제목)은 건너뛰고 그 쪽만의 첫 줄을 제목으로
        const lines = linesOf(p);
        const heading = (lines.find((l) => (firstCount.get(l) ?? 0) < 3) ?? lines[0] ?? "").replace(/^[▸▶•\-\s]+/, "").slice(0, 44);
        return (
          <section key={p.id} style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <h2 className="page-title"><button className="page-jump" onClick={() => jumpToMoment(doc.id, sessionId, p.page_no, null)} aria-label={`${p.page_no}쪽 슬라이드 열기`}>{p.page_no}쪽 슬라이드 보기 →</button>{heading || `${p.page_no}쪽`}</h2>
            {pageSummary.get(p.page_no) && <p className="page-sum">{pageSummary.get(p.page_no)}</p>}
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
  // 긴 개요는 다섯 줄만 먼저 보여 준다 (나머지는 눌러서)
  const [more, setMore] = useState(false);
  const long = text.length > 180;
  return (
    <div className={`banner overview${more || !long ? " open" : ""}`}>
      <strong className="t-title-s">{title}</strong>
      <p className="t-body">{text}</p>
      {long && <button className="overview-more" onClick={() => setMore(!more)}>{more ? "접기" : "끝까지 읽기"}</button>}
    </div>
  );
}

function Glossary({ sessionId }: { sessionId: string }) {
  const { data: terms } = useApi<GlossaryTerm[]>(`/sessions/${sessionId}/glossary`);
  if (!terms) return <Skeleton />;
  if (terms.length === 0) return <Empty icon="book-open-text">수업 중에 잡힌 전문용어가 없어요</Empty>;
  return (
    <>
      <div className="meta-chips"><span className="meta-chip strong">용어 {terms.length}개</span><span className="meta-chip">수업에 나온 순서</span></div>
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
    } catch { tell("복사하지 못했어요. Markdown 받기를 써 주세요."); }
  };
  return (
    <div className="row" style={{ flexWrap: "wrap", gap: 8 }}>
      <a className="chip chip-accent" href={url} download>Markdown 받기</a>
      <Chip variant={copied ? "selected" : "accent"} onClick={copy}>{copied ? "복사했어요. 노션에 붙여 넣으세요" : "노션에 붙여 넣기용 복사"}</Chip>
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
      {items.map((d, i) => <p key={i} className="t-body jokbo-line plain-line">{d.text}</p>)}
    </section>
  );
  return (
    <>
      <p className="t-caption muted">{new Date(data.started_at * 1000).toLocaleString("ko-KR", { month: "long", day: "numeric", weekday: "short", hour: "numeric", minute: "2-digit" })}
        {data.topics.length ? `, 안건 ${data.topics.map((t) => t.title).join(", ")}` : ""}</p>
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

/** 필기 다시 만들기: AI 필기만 지우고 받아쓰기로 새로 쓴다 (내가 쓰거나 고친 필기·사진·질문은 그대로) */
function Renote({ sessionId }: { sessionId: string }) {
  const [busy, setBusy] = useState(false);
  const [snap, setSnap] = useState<{ notes: number; now: number } | null>(null);
  useEffect(() => { getJSON<typeof snap>(`/sessions/${sessionId}/snapshot`).then(setSnap).catch(() => {}); }, [sessionId]);
  const run = async () => {
    if (!await askYes("AI 필기를 처음부터 다시 만들까요?\n내가 쓰거나 고친 필기, 사진, 질문은 그대로 남아요. 지금 AI 필기는 보관해 두니 마음에 안 들면 되돌릴 수 있어요. (1~3분)")) return;
    setBusy(true);
    try {
      await postJSON(`/sessions/${sessionId}/renote`);
      window.location.hash = `#/doc/${encodeURIComponent(location.hash.split("/")[2] ?? "")}/lecture/${sessionId}`;
    } catch (e) { tell(e instanceof Error ? e.message : String(e)); setBusy(false); }
  };
  const undo = async () => {
    if (!await askYes(`다시 만들기 전 AI 필기 ${snap!.notes}개로 되돌릴까요? 지금 AI 필기 ${snap!.now}개는 지워져요. 내가 쓴 필기는 그대로예요.`)) return;
    setBusy(true);
    try { await postJSON(`/sessions/${sessionId}/undo-renote`); window.location.reload(); }
    catch (e) { tell(e instanceof Error ? e.message : String(e)); setBusy(false); }
  };
  return (
    <div className="renote-row">
      <button className="soft-link" onClick={() => void run()} disabled={busy}>
        <Icon name="arrows-clockwise" size={14} /> {busy ? "바꾸는 중…" : "필기 다시 만들기"}
      </button>
      {snap && (
        <span className={`renote-undo${snap.now < snap.notes * 0.9 ? " warn" : ""}`}>
          다시 만든 필기 {snap.now}개 (전 {snap.notes}개)
          <button className="chip chip-accent" onClick={() => void undo()} disabled={busy}><Icon name="arrow-counter-clockwise" size={13} /> 되돌리기</button>
        </span>
      )}
    </div>
  );
}
