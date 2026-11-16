// 강의 화면 보조 기능: 과제(목록·상세·AI 초안), 정리 PDF, 녹음 다시 듣기 플레이어
import { useEffect, useRef, useState } from "react";
import { PdfViewer } from "../components/PdfViewer";
import { getJSON, postJSON } from "../api/useApi";
import type { Task } from "../lib/live";
import { Button, Chip, Icon } from "../components/ui";
import { askYes, tell } from "../components/Dialog";

const API = import.meta.env.VITE_API_URL ?? "";

export const TASK_KINDS: Record<string, { label: string; icon: string; color: string }> = {
  in_class: { label: "수업 중 과제", icon: "timer", color: "var(--accent-record)" },
  homework: { label: "숙제", icon: "house-line", color: "var(--accent-primary)" },
  report: { label: "레포트", icon: "file-text", color: "var(--note-tip-ink)" },
  exam_prep: { label: "시험 준비", icon: "graduation-cap", color: "var(--note-emphasis-ink)" },
};

export interface TaskDraft { checklist: string[]; outline: string[]; draft: string; sources: number[] }
export type FullTask = Task & { page_no?: number | null; draft?: TaskDraft | null };

export const clock = (ms: number) => {
  const s = Math.max(0, Math.floor(ms / 1000));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  return `${h ? `${h}:${String(m).padStart(2, "0")}` : m}:${String(sec).padStart(2, "0")}`;
};

export function TaskList({ tasks, onOpen }: { tasks: FullTask[]; onOpen: (id: number) => void }) {
  return (
    <>
      <h3 className="t-title-m">이번 강의 과제</h3>
      {tasks.length === 0 && <p className="muted">교수님이 과제를 말하면 여기에 모여요.</p>}
      {tasks.map((t) => {
        const k = TASK_KINDS[t.kind] ?? TASK_KINDS.homework;
        return (
          <button key={t.id} className="list-item" onClick={() => onOpen(t.id)}>
            <span className="list-item-icon" style={{ color: t.done ? "var(--note-example-ink)" : k.color }}><Icon name={t.done ? "check-circle" : k.icon} /></span>
            <span className="grow">
              <span className="t-title-s" style={{ display: "block", textDecoration: t.done ? "line-through" : undefined }}>{t.title}</span>
              <span className="list-item-sub">{k.label}{t.due_text ? ` · ${t.due_text}` : ""}{t.draft ? " · 초안 있음" : ""}</span>
            </span>
            <span className="list-item-chev"><Icon name="caret-right" size={18} /></span>
          </button>
        );
      })}
    </>
  );
}

export function TaskDetail({ task, onChange, toast }: { task: FullTask; onChange: (t: FullTask) => void; toast: (m: string) => void }) {
  const [busy, setBusy] = useState(false);
  const [text, setText] = useState(task.draft?.draft ?? "");
  const k = TASK_KINDS[task.kind] ?? TASK_KINDS.homework;

  const toggle = async () => {
    try {
      const res = await fetch(`${API}/tasks/${task.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ done: !task.done }) });
      if (!res.ok) throw new Error("바꾸지 못했어요");
      onChange({ ...task, ...(await res.json()) });
    } catch (e) { toast(e instanceof Error ? e.message : String(e)); }
  };

  const draft = async () => {
    setBusy(true);
    try {
      const updated = await postJSON<FullTask>(`/tasks/${task.id}/draft`);
      onChange({ ...task, ...updated });
      setText(updated.draft?.draft ?? "");
    } catch (e) { toast(e instanceof Error ? e.message : String(e)); }
    setBusy(false);
  };

  return (
    <>
      <div className="banner">
        <span className="t-caption" style={{ color: k.color, fontWeight: 700 }}>{k.label}{task.due_text ? ` · ${task.due_text}` : ""}</span>
        <h3 className="t-title-m">{task.title}</h3>
        <p className="t-body muted">{task.instructions}</p>
        <Chip variant={task.done ? "selected" : "default"} onClick={toggle}>{task.done ? "완료함" : "완료 표시"}</Chip>
      </div>
      {!task.draft && (
        <Button block icon="sparkle" onClick={draft} disabled={busy}>{busy ? "오늘 강의 내용으로 만드는 중…" : "AI와 바로 하기"}</Button>
      )}
      {task.draft && (
        <>
          <h3 className="t-title-s section-title">요구사항 체크리스트</h3>
          <div className="banner">
            {task.draft.checklist.map((c, i) => <label key={i} className="row t-body"><input type="checkbox" /> <span>{c}</span></label>)}
          </div>
          <h3 className="t-title-s section-title">개요</h3>
          <div className="banner">
            {task.draft.outline.map((o, i) => <div key={i} className="row t-body" style={{ alignItems: "flex-start" }}><span className="note-num">{i + 1}</span><span>{o}</span></div>)}
          </div>
          <div className="row section-title">
            <h3 className="t-title-s grow">초안 (바로 고쳐 쓰세요)</h3>
            <Chip variant="accent" onClick={async () => {
              try { await navigator.clipboard.writeText(text); toast("복사했어요"); } catch { toast("복사하지 못했어요"); }
            }}>복사</Chip>
          </div>
          <textarea className="input draft" value={text} onChange={(e) => setText(e.target.value)} rows={10} aria-label="초안" />
          <p className="t-caption" style={{ color: "var(--accent-primary)" }}>근거: {task.draft.sources.map((s) => `${s}쪽`).join(", ")}</p>
          <p className="t-caption muted">AI가 만든 초안이에요. 수업마다 AI 사용 규칙이 다르니 확인하고, 본인 말로 고쳐서 제출하세요.</p>
        </>
      )}
    </>
  );
}

/** 정리 PDF: 만들기 → 진행률 → 내려받기. 필기를 고친 뒤 다시 만들 수 있다 */
export function NotesPdf({ sessionId }: { sessionId: string }) {
  const [state, setState] = useState<{ status: string; done: number; total: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const path = `/sessions/${sessionId}/notes-pdf`;

  useEffect(() => { getJSON<typeof state>(`${path}/status`).then(setState).catch((e) => setError(e.message)); }, [path]);
  useEffect(() => {
    if (state?.status !== "building") return;
    const t = window.setTimeout(() => getJSON<typeof state>(`${path}/status`).then(setState).catch(() => {}), 1500);
    return () => window.clearTimeout(t);
  }, [state, path]);

  const build = async () => {
    setError(null);
    try { setState(await postJSON<typeof state>(path)); } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  };

  return (
    <div className="banner">
      <div className="row">
        <span className="list-item-icon is-art"><Icon name="file-pdf" art size={40} /></span>
        <span className="grow">
          <strong className="t-title-s" style={{ display: "block" }}>필기 붙은 슬라이드 PDF</strong>
          <span className="t-caption muted">슬라이드에 형광펜과 필기를 붙인 그대로, 끝에 과제와 용어 사전</span>
        </span>
      </div>
      {error && <p className="t-caption" style={{ color: "var(--accent-record)" }}>{error}</p>}
      {state?.status === "building" ? (
        <Button block disabled><span className="spin" /> 만드는 중{state.total ? ` ${state.done}/${state.total}쪽` : "…"}</Button>
      ) : state?.status === "ready" ? (
        <PdfActions url={`${API}${path}`} title="필기 붙은 슬라이드" onRebuild={build} />
      ) : (
        <Button block onClick={build} disabled={!state}>만들기</Button>
      )}
    </div>
  );
}

/** 만든 PDF: 앱 안에서 열기 · 폰에 내려받기 · 다시 만들기 */
function PdfActions({ url, title, onRebuild }: { url: string; title: string; onRebuild: () => void }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <div className="row pdf-actions">
        <Button className="grow" icon="book-open-text" onClick={() => setOpen(true)}>열기</Button>
        <a className="btn btn-secondary grow" href={`${url}?download=1`} download><Icon name="download-simple" size={16} /> 내려받기</a>
        <button className="round" onClick={onRebuild} aria-label="다시 만들기" title="다시 만들기"><Icon name="arrows-clockwise" size={16} /></button>
      </div>
      {open && <PdfViewer url={url} title={title} onClose={() => setOpen(false)} />}
    </>
  );
}

/** AI 정리 노트 PDF: AI 가 배운 내용을 주제별로 새로 정리한 노트 (핵심·설명·예시·시험 포인트·용어·확인 문제) */
export function StudyNotePdf({ sessionId }: { sessionId: string }) {
  const [state, setState] = useState<{ status: string; error?: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const path = `/sessions/${sessionId}/study-pdf`;
  useEffect(() => { getJSON<typeof state>(`${path}/status`).then(setState).catch((e) => setError(e.message)); }, [path]);
  useEffect(() => {
    if (state?.status !== "building") return;
    const t = window.setTimeout(() => getJSON<typeof state>(`${path}/status`).then(setState).catch(() => {}), 2000);
    return () => window.clearTimeout(t);
  }, [state, path]);
  const build = async () => {
    setError(null);
    try { setState(await postJSON<typeof state>(path)); } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  };
  return (
    <div className="banner study-pdf">
      <div className="row">
        <span className="list-item-icon is-art"><Icon name="notebook" art size={40} /></span>
        <span className="grow">
          <strong className="t-title-s" style={{ display: "block" }}>AI 정리 노트 PDF</strong>
          <span className="t-caption muted">AI 가 오늘 배운 내용을 공부해서 주제별로 새로 정리해요 · 핵심, 설명, 예시, 시험 포인트, 용어, 확인 문제</span>
        </span>
      </div>
      {(error || state?.error) && <p className="t-caption" style={{ color: "var(--accent-record)" }}>{error || state?.error}</p>}
      {state?.status === "building" ? (
        <Button block disabled><span className="spin" /> AI 가 정리하는 중… (1분쯤)</Button>
      ) : state?.status === "ready" ? (
        <PdfActions url={`${API}${path}`} title="AI 정리 노트" onRebuild={build} />
      ) : (
        <Button block onClick={build} disabled={!state}>만들기</Button>
      )}
    </div>
  );
}

/** 강의 화면 › 더보기: 정리 PDF 두 가지와 이 강의 지우기 */
export function LectureMore({ sessionId, onDeleted }: { sessionId: string; onDeleted: () => void }) {
  const [busy, setBusy] = useState(false);
  const remove = async () => {
    if (!await askYes("이 강의를 지울까요? 녹음, 받아쓰기, 필기, 요약, 퀴즈가 모두 지워져요. 강의자료(PDF)는 남아요. 되돌릴 수 없어요.")) return;
    setBusy(true);
    try {
      const res = await fetch(`${API}/sessions/${sessionId}`, { method: "DELETE" });
      if (!res.ok && res.status !== 204) throw new Error("지우지 못했어요");
      onDeleted();
    } catch (e) { tell(e instanceof Error ? e.message : String(e)); setBusy(false); }
  };
  const redo = async () => {
    if (!await askYes("녹음부터 다시 받아쓸까요? AI 필기·요약도 새로 만들어요. 내가 쓴 필기는 남아요.")) return;
    setBusy(true);
    try {
      await postJSON(`/sessions/${sessionId}/retranscribe`);
      window.location.reload();
    } catch (e) { tell(e instanceof Error ? e.message : String(e)); setBusy(false); }
  };
  return (
    <>
      <h3 className="t-title-m">더보기</h3>
      <StudyNotePdf sessionId={sessionId} />
      <NotesPdf sessionId={sessionId} />
      <Button block variant="secondary" icon="arrows-clockwise" onClick={() => void redo()} disabled={busy}>녹음부터 다시 받아쓰기</Button>
      <span className="t-caption muted">받아쓰기가 이상할 때 (예: 한국어 강의가 영어로 나왔을 때). 내가 쓴 필기는 그대로예요.</span>
      <Button block variant="record" icon="trash" onClick={() => void remove()} disabled={busy}>{busy ? "지우는 중…" : "이 강의 지우기"}</Button>
    </>
  );
}

/** 필기를 누르면 그 필기 무렵의 녹음을 들려준다. 서버에 녹음이 있을 때만 보인다 */
export function usePlayer(sessionId: string | null, enabled: boolean) {
  const [hasAudio, setHasAudio] = useState(false);
  const [open, setOpen] = useState(false);
  const audio = useRef<HTMLAudioElement | null>(null);

  useEffect(() => {
    if (!sessionId || !enabled) return;
    // 녹음이 있는지 앞 1바이트만 받아 본다
    fetch(`${API}/sessions/${sessionId}/audio`, { headers: { Range: "bytes=0-0" } })
      .then((r) => setHasAudio(r.ok)).catch(() => setHasAudio(false));
  }, [sessionId, enabled]);

  useEffect(() => () => { audio.current?.pause(); }, []);

  const [speech, setSpeech] = useState<[number, number][]>([]);   // 말소리 구간 (초) — 무음 건너뛰기용
  const playFrom = (ms: number, before = 3) => {
    if (!sessionId) return;
    if (!audio.current) {
      audio.current = new Audio(`${API}/sessions/${sessionId}/audio`);
      audio.current.playbackRate = savedRate();
      fetch(`${API}/sessions/${sessionId}/transcript`).then((r) => r.ok ? r.json() : [])
        .then((rows: { start_ms: number; end_ms: number }[]) => setSpeech(rows.map((r) => [r.start_ms / 1000, r.end_ms / 1000])))
        .catch(() => {});
    }
    const a = audio.current;
    setOpen(true);
    // 필기는 설명이 끝날 즈음 붙으므로 조금 앞에서부터 들려준다 (중요 표시는 더 앞에서)
    const start = Math.max(0, ms / 1000 - before);
    const go = () => { a.currentTime = start; void a.play().catch(() => {}); };
    if (a.readyState >= 1) go(); else a.addEventListener("loadedmetadata", go, { once: true });
  };
  const close = () => { audio.current?.pause(); setOpen(false); };
  return { hasAudio: hasAudio && enabled, open, audio, playFrom, close, speech };
}

const RATES = [1, 1.2, 1.5, 2];
function savedRate(): number { try { return Number(localStorage.getItem("ln.rate")) || 1; } catch { return 1; } }

export function PlayerBar({ audio, onClose, speech = [] }: { audio: HTMLAudioElement | null; onClose: () => void; speech?: [number, number][] }) {
  const [, tick] = useState(0);
  const [skip, setSkip] = useState(() => { try { return localStorage.getItem("ln.skip") === "1"; } catch { return false; } });
  useEffect(() => {
    if (!audio) return;
    const on = () => tick((n) => n + 1);
    ["timeupdate", "play", "pause", "loadedmetadata", "ratechange"].forEach((e) => audio.addEventListener(e, on));
    return () => ["timeupdate", "play", "pause", "loadedmetadata", "ratechange"].forEach((e) => audio.removeEventListener(e, on));
  }, [audio]);
  // 무음 건너뛰기: 받아쓴 말 사이가 2초 넘게 비면 다음 말 바로 앞으로
  useEffect(() => {
    if (!audio || !skip || !speech.length) return;
    const jump = () => {
      const t = audio.currentTime;
      if (speech.some(([s, e]) => t >= s - 0.3 && t <= e + 0.6)) return;
      const next = speech.find(([s]) => s > t);
      if (next && next[0] - t > 2) audio.currentTime = next[0] - 0.3;
    };
    audio.addEventListener("timeupdate", jump);
    return () => audio.removeEventListener("timeupdate", jump);
  }, [audio, skip, speech]);
  if (!audio) return null;
  const pct = audio.duration ? (audio.currentTime / audio.duration) * 100 : 0;
  const rate = audio.playbackRate || 1;
  const nextRate = () => {
    const r = RATES[(RATES.indexOf(rate) + 1) % RATES.length] ?? 1;
    audio.playbackRate = r;
    try { localStorage.setItem("ln.rate", String(r)); } catch { /* 괜찮다 */ }
  };
  const toggleSkip = () => { const v = !skip; setSkip(v); try { localStorage.setItem("ln.skip", v ? "1" : "0"); } catch { /* 괜찮다 */ } };
  return (
    <div className="player">
      <div className="row">
        <button className="round round-soft" onClick={() => (audio.paused ? audio.play() : audio.pause())} aria-label={audio.paused ? "재생" : "일시정지"}>
          <Icon name={audio.paused ? "play" : "pause"} />
        </button>
        <span className="t-caption muted">{clock(audio.currentTime * 1000)}</span>
        <input className="grow" type="range" min={0} max={100} step={0.1} value={pct} aria-label="재생 위치"
          onChange={(e) => { if (audio.duration) audio.currentTime = (Number(e.target.value) / 100) * audio.duration; }} />
        <button onClick={onClose} aria-label="닫기"><Icon name="x" /></button>
      </div>
      <div className="player-tools">
        <button onClick={() => { audio.currentTime = Math.max(0, audio.currentTime - 10); }} aria-label="10초 뒤로">−10초</button>
        <button onClick={() => { audio.currentTime = audio.currentTime + 10; }} aria-label="10초 앞으로">+10초</button>
        <button className="on" onClick={nextRate} aria-label="재생 속도">{rate}배</button>
        <button className={skip ? "on" : ""} aria-pressed={skip} onClick={toggleSkip} disabled={!speech.length}>무음 건너뛰기</button>
      </div>
    </div>
  );
}
