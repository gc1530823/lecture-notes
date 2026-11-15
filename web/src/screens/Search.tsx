// 전체 검색: 모든 강의의 필기 · 교수님 말 · 용어 · 슬라이드에서 찾는다 ("그 교수님이 시험 나온다고 한 거 뭐였지?")
import { useEffect, useRef, useState } from "react";
import { getJSON } from "../api/useApi";
import { Chip, Empty, Icon, NOTE_LABEL, TopBar } from "../components/ui";
import type { NoteType } from "../api/types";
import { back, go } from "../router";

interface Hit {
  kind: "note" | "term" | "speech" | "slide";
  text: string; note_type?: NoteType; start_ms?: number; page_no: number | null;
  session_id?: string; doc_id: string; title: string; course?: string; started_at: number;
}

const KIND = { note: "필기", speech: "교수님 말", term: "용어", slide: "슬라이드" } as const;

export function jumpTo(hit: { doc_id: string; session_id?: string; page_no: number | null; start_ms?: number; kind?: string }) {
  // 강의 화면이 그 쪽부터 열리게, 교수님 말이면 그 순간 녹음부터 들리게 알려 둔다
  try {
    if (hit.page_no) sessionStorage.setItem("ln.jump", String(hit.page_no));
    if (hit.session_id && hit.start_ms != null && (hit.kind === "speech" || hit.kind === "note")) sessionStorage.setItem("ln.jumpMs", String(hit.start_ms));
  } catch { /* 괜찮다 */ }
  go(hit.session_id ? { name: "lecture", docId: hit.doc_id, sessionId: hit.session_id } : { name: "doc", docId: hit.doc_id });
}

export default function Search() {
  const [q, setQ] = useState(() => { try { return sessionStorage.getItem("ln.q") ?? ""; } catch { return ""; } });
  const [hits, setHits] = useState<Hit[] | null>(null);
  const [kind, setKind] = useState<"all" | Hit["kind"]>("all");
  const [course, setCourse] = useState<string>("all");
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => {
    window.clearTimeout(timer.current);
    try { sessionStorage.setItem("ln.q", q); } catch { /* 괜찮다 */ }
    if (q.trim().length < 2) { setHits(null); return; }
    timer.current = window.setTimeout(() => {
      getJSON<{ results: Hit[] }>(`/search?q=${encodeURIComponent(q.trim())}`).then((r) => setHits(r.results)).catch(() => setHits([]));
    }, 250);
  }, [q]);

  const inCourse = (hits ?? []).filter((h) => course === "all" || (h.course || "") === course);
  const shown = inCourse.filter((h) => kind === "all" || h.kind === kind);
  const courses = [...new Set((hits ?? []).map((h) => h.course || "").filter(Boolean))];
  const mark = (text: string) => {
    const i = text.toLowerCase().indexOf(q.trim().toLowerCase());
    if (i < 0) return text;
    const from = Math.max(0, i - 40);
    return <>{from > 0 ? "…" : ""}{text.slice(from, i)}<mark>{text.slice(i, i + q.trim().length)}</mark>{text.slice(i + q.trim().length, i + 140)}</>;
  };

  return (
    <div className="screen">
      <TopBar title="찾기" onBack={() => back({ name: "home" })} />
      <div className="screen-body">
        <div className="search-box">
          <Icon name="magic-wand" size={18} />
          <input className="input" autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder="모든 강의에서 찾기 (예: 시험, 역전파)" aria-label="찾을 말" />
        </div>
        {hits && courses.length > 1 && (
          <div className="scroll-x" role="group" aria-label="과목">
            <Chip variant={course === "all" ? "selected" : "default"} onClick={() => setCourse("all")}>모든 과목</Chip>
            {courses.map((c) => (
              <Chip key={c} variant={course === c ? "selected" : "default"} onClick={() => setCourse(c)}>{c} {hits.filter((h) => h.course === c).length}</Chip>
            ))}
          </div>
        )}
        {hits && (
          <div className="scroll-x" role="group" aria-label="종류">
            {(["all", "note", "speech", "term", "slide"] as const).map((k) => (
              <Chip key={k} variant={kind === k ? "selected" : "default"} onClick={() => setKind(k)}>
                {k === "all" ? `전체 ${inCourse.length}` : `${KIND[k]} ${inCourse.filter((h) => h.kind === k).length}`}
              </Chip>
            ))}
          </div>
        )}
        {!hits && <Empty icon="book-open-text">두 글자 이상 넣으면 필기·교수님 말·용어·슬라이드에서 찾아요</Empty>}
        {hits && shown.length === 0 && <Empty icon="warning-circle">찾는 말이 없어요</Empty>}
        {shown.map((h, i) => (
          <button key={i} className="list-item search-hit" onClick={() => jumpTo(h)}>
            <span className="grow" style={{ minWidth: 0 }}>
              <span className="t-caption muted" style={{ display: "block" }}>
                {KIND[h.kind]}{h.note_type ? ` · ${NOTE_LABEL[h.note_type]}` : ""} · {h.course ? `${h.course} · ` : ""}{h.title}{h.page_no ? ` ${h.page_no}쪽` : ""}
              </span>
              <span className="t-body">{mark(h.text)}</span>
              {h.kind === "speech" && h.start_ms != null && <span className="t-caption faint" style={{ display: "block" }}><Icon name="play" size={11} /> 누르면 이 순간부터 들어요</span>}
            </span>
            <span className="list-item-chev"><Icon name="caret-right" size={18} /></span>
          </button>
        ))}
      </div>
    </div>
  );
}
