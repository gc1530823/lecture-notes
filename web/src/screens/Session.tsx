// 강의 다시 보기: 필기(쪽마다 포스트잇 / 노트 모드는 모눈 노트), 공부하기, 용어 사전
import type { Annotation, DocumentDetail, GlossaryTerm, SummaryResponse } from "../api/types";
import { useApi } from "../api/useApi";
import { Button, Chip, Empty, NoteSection, PostIt, TermCard, TopBar } from "../components/ui";
import { go } from "../router";
import Study from "./Study";

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
              onClick={() => go({ name: "lecture", docId, sessionId })}>{doc.kind === "notebook" ? "노트로 보기" : "강의자료 위에서 보기"}</Button>
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
  if (!notes) return <p className="muted">불러오는 중…</p>;
  if (notes.length === 0) return <Empty icon="note-pencil">이 강의에는 아직 필기가 없어요</Empty>;

  const beyondIds = new Set(beyond?.annotation_ids ?? []);
  const pageSummary = new Map((summary?.summary?.pages ?? []).map((p) => [p.page_no, p.summary]));
  const pages = doc.pages.filter((p) => notes.some((n) => n.page_no === p.page_no && !n.pending));
  const overview = summary?.summary?.overview;

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
                <PostIt key={n.id} type={n.type} number={i + 1} tag={beyondIds.has(n.id) ? "슬라이드에 없음" : undefined}>{n.text}</PostIt>
              ))}
            </div>
          </section>
        );
      })}
    </>
  );
}

function Overview({ text }: { text: string }) {
  return (
    <div className="banner">
      <strong className="t-title-s">한눈에 보는 강의</strong>
      <p className="t-body">{text}</p>
    </div>
  );
}

function Glossary({ sessionId }: { sessionId: string }) {
  const { data: terms } = useApi<GlossaryTerm[]>(`/sessions/${sessionId}/glossary`);
  if (!terms) return <p className="muted">불러오는 중…</p>;
  if (terms.length === 0) return <Empty icon="book-open-text">수업 중에 잡힌 전문용어가 없어요</Empty>;
  return (
    <>
      <p className="t-caption muted">수업 중에 나온 용어 {terms.length}개 · 나온 순서</p>
      {terms.map((t) => <TermCard key={t.id} term={t.term} page={t.page_no} definition={t.definition} />)}
    </>
  );
}
