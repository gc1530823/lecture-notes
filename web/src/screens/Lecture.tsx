// 2·3 강의 화면 (녹음 중): 강의자료 위에 형광펜·번호 깃발, 아래에 포스트잇 필기. 노트 수업은 모눈 노트에 주제별로 써 내려간다.
// 녹음 → 서버(받아쓰기·AI 필기) → WebSocket 이벤트로 화면에 붙는다. 기존 웹앱과 같은 규약 (lib/live.ts).
import { useCallback, useEffect, useLayoutEffect, useRef, useState, type CSSProperties } from "react";
import type { Annotation, DocumentDetail, GlossaryTerm, Page } from "../api/types";
import { getJSON, postJSON } from "../api/useApi";
import { browserRecognizer, LiveSocket, startMicrophone, type Mic, type ServerEvent } from "../lib/live";
import { clock, NotesPdf, PlayerBar, TaskDetail, TaskList, usePlayer, type FullTask } from "./LectureExtras";
import { ConsentSheet } from "./ExamPrep";
import { loadPdf, renderPage, type PdfDoc } from "../lib/pdf";
import { Button, Chip, Icon, NOTE_LABEL, PostIt, TermCard, TopBar } from "../components/ui";
import { go } from "../router";

const FOLLOW_CONFIDENCE = 0.6;
const MANUAL_PAUSE_MS = 20_000;
const QUICK_QUESTIONS = ["방금 뭐라고 했어?", "쉽게 다시 설명해 줘", "예시 하나만 들어 줘", "이거 시험에 어떻게 나올까?"];
const TASK_LABEL: Record<string, string> = { in_class: "수업 중 과제", homework: "숙제", report: "레포트", exam_prep: "시험 준비" };
const STRONG_BUZZ = [220, 120, 220, 120, 220];

// 기기별 설정. 사생활 보호 모드 등에서 저장소를 못 쓰면 기본값으로 동작한다
const prefs = {
  get(key: string) { try { return localStorage.getItem(`ln.${key}`); } catch { return null; } },
  set(key: string, value: string) { try { localStorage.setItem(`ln.${key}`, value); } catch { /* 저장 못 해도 괜찮다 */ } },
};

type Note = Annotation & { preview?: boolean };
type Sheet = null | "ask" | "glossary" | "pending" | "tasks" | "pdf" | { catchUp: number } | { task: number };


export default function Lecture({ docId, sessionId: initialSession }: { docId: string; sessionId?: string }) {
  const [doc, setDoc] = useState<DocumentDetail | null>(null);
  const [pdf, setPdf] = useState<PdfDoc | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [notes, setNotes] = useState<Note[]>([]);
  const [previews, setPreviews] = useState<Note[]>([]);
  const [tasks, setTasks] = useState<FullTask[]>([]);
  const [terms, setTerms] = useState<GlossaryTerm[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [fresh, setFresh] = useState<number | null>(null);
  const [sessionId, setSessionId] = useState(initialSession ?? null);
  const [phase, setPhase] = useState<"idle" | "recording" | "ending" | "ended">(initialSession ? "ended" : "idle");
  const [startedAt, setStartedAt] = useState(0);
  const [now, setNow] = useState(Date.now());
  const [estimate, setEstimate] = useState<number | null>(null);
  const [autoFollow, setAutoFollow] = useState(true);
  const [caption, setCaption] = useState("듣고 있어요…");
  const [toastTerms, setToastTerms] = useState<GlossaryTerm[]>([]);
  const [banner, setBanner] = useState<{ icon: string; title: string; text: string; task?: number } | null>(null);
  // 자막 모드: 최근 문장 3줄을 크게, 지금 설명하는 문단 표시, 시험·공지·과제 때 강하게 진동 (청각장애 학생·시끄러운 강의실)
  const [a11y, setA11y] = useState(() => prefs.get("a11y") === "1");
  const [lines, setLines] = useState<string[]>([]);
  const [spoken, setSpoken] = useState<{ page: number; block_id: number | null } | null>(null);
  const [beyond, setBeyond] = useState<Set<number>>(new Set());
  const [sheet, setSheet] = useState<Sheet>(null);
  const [asking, setAsking] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0); // 서버 정리가 끝나면 다시 불러오기
  const [confused, setConfused] = useState(0); // 이번 강의에서 "모르겠어요"를 누른 수
  const [askConsent, setAskConsent] = useState(false);

  // 이벤트 처리기에서 최신 값을 읽기 위한 거울
  const live = useRef<LiveSocket | null>(null);
  const mic = useRef<Mic | null>(null);
  const recognizer = useRef<{ stop(): void } | null>(null);
  const wakeLock = useRef<{ release(): Promise<void> } | null>(null);
  const pageRef = useRef(page);
  const followRef = useRef(autoFollow);
  const lastManual = useRef(0);
  const previewSeq = useRef(-1);
  const previewIds = useRef(new Map<string | number, number>());
  const freshTimer = useRef<number | undefined>(undefined);
  const notesRef = useRef<Note[]>([]);
  notesRef.current = notes;
  const a11yRef = useRef(a11y);
  a11yRef.current = a11y;
  pageRef.current = page;
  followRef.current = autoFollow;

  const toast = useCallback((text: string) => {
    setMessage(text);
    window.setTimeout(() => setMessage((m) => (m === text ? null : m)), 3500);
  }, []);

  // --- 불러오기 ---
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const d = await getJSON<DocumentDetail>(`/documents/${docId}`);
        if (!alive) return;
        setDoc(d);
        if (d.kind !== "notebook") loadPdf(docId).then((p) => alive && setPdf(p)).catch((e) => setError(e.message));
        if (initialSession) {
          const [a, t, g] = await Promise.all([
            getJSON<Annotation[]>(`/sessions/${initialSession}/annotations`),
            getJSON<FullTask[]>(`/sessions/${initialSession}/tasks`).catch(() => []),
            getJSON<GlossaryTerm[]>(`/sessions/${initialSession}/glossary`).catch(() => []),
          ]);
          if (!alive) return;
          setNotes(a);
          setTasks(t);
          setTerms(g);
          // 다시 볼 때 1쪽에 필기가 없으면 필기가 있는 첫 쪽부터 연다
          const first = a.filter((n) => !n.pending).map((n) => n.page_no).sort((x, y) => x - y)[0];
          if (first && !a.some((n) => n.page_no === pageRef.current && !n.pending)) setPage(first);
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => { alive = false; };
  }, [docId, initialSession, refresh]);

  // 녹음 파일로 정리 중인 강의: 끝날 때까지 필기를 다시 받아 온다
  const [serverStatus, setServerStatus] = useState<{ status: string; progress: number | null } | null>(null);
  useEffect(() => {
    if (!initialSession) return;
    let alive = true;
    let timer: number | undefined;
    const poll = async () => {
      try {
        const s = await getJSON<{ status: string; progress: number | null }>(`/sessions/${initialSession}/summary`);
        if (!alive) return;
        const busy = s.status === "transcribing" || s.status === "processing";
        setServerStatus((prev) => {
          if (!busy && prev && prev.status !== s.status) setRefresh((n) => n + 1); // 막 끝났으면 마지막 필기를 한 번 더 받는다
          return s;
        });
        if (busy) {
          const [a, t, g] = await Promise.all([
            getJSON<Annotation[]>(`/sessions/${initialSession}/annotations`),
            getJSON<FullTask[]>(`/sessions/${initialSession}/tasks`).catch(() => []),
            getJSON<GlossaryTerm[]>(`/sessions/${initialSession}/glossary`).catch(() => []),
          ]);
          if (!alive) return;
          setNotes(a); setTasks(t); setTerms(g);
          timer = window.setTimeout(poll, 3000);
        }
      } catch { /* 다음에 다시 */ }
    };
    void poll();
    return () => { alive = false; window.clearTimeout(timer); };
  }, [initialSession]);

  // 화면을 떠나면 녹음을 멈춘다
  useEffect(() => () => {
    mic.current?.stop();
    recognizer.current?.stop();
    live.current?.close();
    wakeLock.current?.release().catch(() => {});
  }, []);

  useEffect(() => {
    if (phase !== "recording") return;
    const t = window.setInterval(() => setNow(Date.now()), 500);
    return () => window.clearInterval(t);
  }, [phase]);

  const flash = useCallback((id: number) => {
    setFresh(id);
    window.clearTimeout(freshTimer.current);
    freshTimer.current = window.setTimeout(() => setFresh(null), 5000);
  }, []);

  const goTo = useCallback((no: number, manual = true) => {
    const total = doc?.pages.length ?? 0;
    if (no < 1 || no > total || no === pageRef.current) return;
    setPage(no);
    setSelected(null);
    if (manual) {
      lastManual.current = Date.now();
      live.current?.send({ type: "page_view", page: no }); // 직접 넘긴 쪽을 서버에 알린다
    }
  }, [doc]);

  // --- 서버 이벤트 ---
  const handle = useCallback((e: ServerEvent) => {
    switch (e.type) {
      case "annotation_preview": {
        const id = previewSeq.current--;
        previewIds.current.set(e.preview.id, id);
        setPreviews((p) => [...p, { ...(e.preview as unknown as Annotation), id, preview: true }]);
        flash(id);
        break;
      }
      case "previews_resolved": {
        const ids = new Set(e.ids.map((k) => previewIds.current.get(k)));
        setPreviews((p) => p.filter((n) => !ids.has(n.id)));
        break;
      }
      case "annotation_added":
        setNotes((n) => (n.some((x) => x.id === e.annotation.id) ? n : [...n, e.annotation]));
        navigator.vibrate?.(15);
        flash(e.annotation.id);
        if (e.annotation.type === "exam" || e.annotation.type === "notice") {
          setBanner(e.annotation.type === "exam"
            ? { icon: "star", title: "시험에 나온다고 했어요", text: e.annotation.text }
            : { icon: "megaphone", title: "공지", text: e.annotation.text });
          if (a11yRef.current) navigator.vibrate?.(STRONG_BUZZ);
        }
        break;
      case "term":
        setTerms((t) => (t.some((x) => x.id === e.term.id) ? t : [...t, e.term]));
        setToastTerms((t) => [e.term, ...t].slice(0, 2));
        window.setTimeout(() => setToastTerms((t) => t.filter((x) => x.id !== e.term.id)), 7000);
        break;
      case "page_added":
        setDoc((d) => (d ? { ...d, pages: [...d.pages, e.page] } : d));
        if (followRef.current) { setPage(e.page.page_no); setSelected(null); }
        break;
      case "page_title":
        setDoc((d) => (d ? { ...d, pages: d.pages.map((p) => (p.page_no === e.page ? { ...p, text: e.title } : p)) } : d));
        break;
      case "page_estimate": {
        setEstimate(e.page);
        const canFollow = followRef.current && Date.now() - lastManual.current > MANUAL_PAUSE_MS;
        if (canFollow && e.confidence >= FOLLOW_CONFIDENCE && e.page !== pageRef.current) { setPage(e.page); setSelected(null); }
        break;
      }
      case "task_added":
        setTasks((t) => [...t, e.task]);
        setBanner({ icon: "clipboard-text", title: `새 ${TASK_LABEL[e.task.kind] ?? "과제"}${e.task.due_text ? ` · ${e.task.due_text}` : ""}`, text: e.task.title, task: e.task.id });
        if (a11yRef.current) navigator.vibrate?.(STRONG_BUZZ);
        break;
      case "heard":
        setCaption(e.text);
        break;
      case "spoken":
        setCaption(e.text);
        setLines((l) => [...l, e.text].slice(-3));
        setSpoken({ page: e.page, block_id: e.block_id });
        break;
      case "error":
        toast(e.message);
        break;
    }
  }, [flash, toast]);

  useEffect(() => {
    if (!banner) return;
    const t = window.setTimeout(() => setBanner(null), 8000);
    return () => window.clearTimeout(t);
  }, [banner]);

  // --- 녹음 ---
  const start = async () => {
    // 마이크는 버튼을 누른 바로 그 순간에 켜야 iPhone Safari가 허락한다 (서버 응답을 기다리기 전에)
    const micStart = startMicrophone((pcm) => live.current?.sendAudio(pcm));
    micStart.catch(() => {}); // 실패는 아래에서 다룬다
    let id: string;
    try {
      id = (await postJSON<{ id: string }>("/sessions", { document_id: docId })).id;
    } catch (e) {
      micStart.then((m) => m.stop()).catch(() => {});
      return toast(e instanceof Error ? e.message : String(e));
    }
    const began = Date.now();
    setSessionId(id);
    setStartedAt(began);
    setNow(began);
    setPhase("recording");
    window.history.replaceState(null, "", `#/doc/${docId}/lecture/${id}`);
    const socket = new LiveSocket(id, (e) => handleRef.current(e), () => pageRef.current);
    live.current = socket;
    socket.connect();
    try {
      mic.current = await micStart;
    } catch {
      // 마이크 소리를 직접 못 받는 브라우저: 내장 음성 인식으로 대신한다
      const rec = browserRecognizer(
        (text, s, e) => socket.send({ type: "transcript_final", text, start_ms: s, end_ms: e }),
        (interim) => setCaption(interim || "듣고 있어요…"),
        () => { toast("마이크·음성 인식 권한을 허용해 주세요"); void stop(false); },
        began,
      );
      if (!rec) { toast("마이크를 쓸 수 없어요. 브라우저 설정에서 마이크 권한을 허용해 주세요."); return stop(false); }
      recognizer.current = rec;
    }
    // 수업 중 화면이 꺼지면 받아쓰기가 멈추므로 화면을 켜 둔다
    try {
      wakeLock.current = await (navigator as unknown as { wakeLock?: { request(t: string): Promise<{ release(): Promise<void> }> } })
        .wakeLock?.request("screen") ?? null;
    } catch { /* 지원하지 않는 브라우저 */ }
  };

  const stop = async (finish = true) => {
    mic.current?.stop();
    mic.current = null;
    recognizer.current?.stop();
    recognizer.current = null;
    wakeLock.current?.release().catch(() => {});
    if (finish && live.current && sessionId) {
      setPhase("ending");
      // 마지막 받아쓰기의 필기를 받을 시간을 준다
      live.current.send({ type: "flush" });
      await new Promise((r) => setTimeout(r, 6000));
      try { await postJSON(`/sessions/${sessionId}/end`); } catch (e) { toast(e instanceof Error ? e.message : String(e)); }
      if (doc?.kind === "notebook") {
        // 마지막 주제의 제목은 조금 늦게 붙으므로 다시 받아 온다
        window.setTimeout(() => { getJSON<DocumentDetail>(`/documents/${docId}`).then(setDoc).catch(() => {}); }, 4000);
      }
    }
    live.current?.close();
    live.current = null;
    setPhase(sessionId || finish ? "ended" : "idle");
  };

  const handleRef = useRef(handle);
  handleRef.current = handle;

  // 강의가 끝나면: 녹음 다시 듣기, 슬라이드에 없던 설명 표시
  const player = usePlayer(sessionId, phase === "ended");

  // 타임라인 다시 보기: 녹음을 틀면 그때 설명하던 쪽으로 넘어가고, 그 무렵 필기를 펼치고, 받아쓰기를 자막으로
  const [segments, setSegments] = useState<{ start_ms: number; end_ms: number; text: string; page_no: number | null }[]>([]);
  const [replayLine, setReplayLine] = useState<string | null>(null);
  const [replayFollow, setReplayFollow] = useState(true);
  const replayFollowRef = useRef(replayFollow);
  replayFollowRef.current = replayFollow;
  useEffect(() => {
    if (!player.open || !sessionId) return;
    getJSON<typeof segments>(`/sessions/${sessionId}/transcript`).then(setSegments).catch(() => {});
  }, [player.open, sessionId]);
  useEffect(() => {
    const audio = player.audio.current;
    if (!player.open || !audio || segments.length === 0) return;
    let lastNote: number | null = null;
    const onTime = () => {
      const t = audio.currentTime * 1000;
      let seg = null;
      for (const s of segments) { if (s.start_ms <= t) seg = s; else break; }
      setReplayLine(seg && t - seg.end_ms < 4000 ? seg.text : null);
      if (seg?.page_no && replayFollowRef.current && seg.page_no !== pageRef.current) { setPage(seg.page_no); setSelected(null); }
      // 그 무렵(8초 안) 붙은 필기를 자료 위에 펼친다
      const near = notesRef.current.filter((n) => !n.pending && n.start_ms <= t && t - n.start_ms < 8000).pop();
      if (near && near.id !== lastNote) { lastNote = near.id; setFresh(near.id); }
    };
    audio.addEventListener("timeupdate", onTime);
    return () => audio.removeEventListener("timeupdate", onTime);
  }, [player.open, player.audio, segments]);
  useEffect(() => {
    if (phase !== "ended" || !sessionId) return;
    getJSON<{ annotation_ids?: number[] }>(`/sessions/${sessionId}/beyond-slides`)
      .then((r) => setBeyond(new Set(r.annotation_ids ?? []))).catch(() => {});
  }, [phase, sessionId]);

  const toggleA11y = () => {
    const on = !a11y;
    setA11y(on);
    prefs.set("a11y", on ? "1" : "0");
    toast(on ? "자막 모드: 지금 설명하는 곳을 표시하고, 시험·공지·과제 때 진동으로 알려요" : "자막 모드를 껐어요");
  };

  // --- 모르겠어요: 수업 흐름을 끊지 않게 표시만 하고, 설명은 끝난 뒤 공부하기 › 모르겠다에서 ---
  const markConfused = async () => {
    if (!sessionId) return;
    try {
      await postJSON(`/sessions/${sessionId}/confused`, { page_no: page });
      setConfused((n) => n + 1);
      navigator.vibrate?.(15);
      toast("표시했어요 · 끝나고 쉽게 설명해 드릴게요");
    } catch (e) { toast(e instanceof Error ? e.message : String(e)); }
  };

  // 녹음 전 한 번: 교수님 허락 · 데이터가 어디로 가는지 확인 (이 기기에 기억)
  const startWithConsent = () => {
    let agreed = false;
    try { agreed = localStorage.getItem("ln.consent") === "1"; } catch { /* 저장소를 못 쓰면 매번 묻는다 */ }
    if (agreed) void start(); else setAskConsent(true);
  };

  // --- 방금 뭐라고? / 따라잡기 ---
  const ask = async (question: string) => {
    if (!sessionId) return;
    setSheet(null);
    setAsking(true);
    try {
      const note = await postJSON<Annotation>(`/sessions/${sessionId}/ask`, { question, page_no: page });
      setNotes((n) => [...n, note]);
      if (note.page_no !== page) goTo(note.page_no);
      flash(note.id);
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e));
    } finally {
      setAsking(false);
    }
  };

  const editNote = async (note: Note) => {
    if (note.preview) return;
    const text = prompt("필기 수정 (비우면 삭제)", note.text);
    if (text === null) return;
    try {
      if (!text.trim()) {
        await fetch(`${import.meta.env.VITE_API_URL ?? ""}/annotations/${note.id}`, { method: "DELETE" });
        setNotes((n) => n.filter((x) => x.id !== note.id));
      } else {
        const res = await fetch(`${import.meta.env.VITE_API_URL ?? ""}/annotations/${note.id}`, {
          method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }),
        });
        const updated = await res.json();
        setNotes((n) => n.map((x) => (x.id === note.id ? updated : x)));
      }
    } catch (e) { toast(e instanceof Error ? e.message : String(e)); }
  };

  const place = async (note: Note, no: number) => {
    const res = await fetch(`${import.meta.env.VITE_API_URL ?? ""}/annotations/${note.id}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ page_no: no }),
    });
    if (!res.ok) return toast("옮기지 못했어요");
    const placed = await res.json();
    setNotes((n) => n.map((x) => (x.id === note.id ? placed : x)));
    setSheet(null);
    goTo(no);
    flash(note.id);
  };

  // --- 그리기 ---
  if (error) return <div className="screen"><TopBar title="강의" onBack={() => go({ name: "doc", docId })} /><p className="screen-body muted">{error}</p></div>;
  if (!doc) return <div className="screen"><TopBar title="불러오는 중…" onBack={() => go({ name: "doc", docId })} /></div>;

  const recording = phase === "recording";
  const notebook = doc.kind === "notebook";
  const all = [...notes, ...previews];
  const visible = all.filter((n) => n.page_no === page && !n.pending);
  const pending = notes.filter((n) => n.pending);
  const pageInfo = doc.pages[page - 1];
  const elsewhere = estimate !== null && estimate !== page;

  const back = () => {
    if (recording && !confirm("녹음을 멈추고 나갈까요?")) return;
    go(sessionId && phase === "ended" ? { name: "session", docId, sessionId, tab: "notes" } : { name: "doc", docId });
  };

  return (
    <div className="screen lecture">
      <TopBar title={doc.title} onBack={back} action={
        <div className="row" style={{ gap: 0 }}>
          <button className="top-bar-back" aria-label={`용어 사전 ${terms.length}개`} onClick={() => setSheet("glossary")} style={{ position: "relative" }}>
            <Icon name="book-open-text" />
            {terms.length > 0 && <span className="badge">{terms.length}</span>}
          </button>
          <button className={`top-bar-back${a11y ? " on" : ""}`} aria-label="자막 모드 (크게 보기·중요할 때 진동)" aria-pressed={a11y} onClick={toggleA11y}>
            <Icon name="closed-captioning" />
          </button>
          {sessionId && phase === "ended" && (
            <button className="top-bar-back" aria-label="강의 정리 PDF" onClick={() => setSheet("pdf")}><Icon name="file-pdf" /></button>
          )}
        </div>
      } />

      {banner && (
        <button className="live-banner" role="alert" onClick={() => { if (banner.task) setSheet({ task: banner.task }); setBanner(null); }}>
          <Icon name={banner.icon} /><span className="grow"><b className="t-caption">{banner.title}</b><span className="t-body">{banner.text}</span></span>
        </button>
      )}

      <div className="screen-body lecture-body">
        {notebook ? (
          <NotebookSheet doc={doc} notes={all} page={page} recording={recording} fresh={fresh} startedAt={startedAt} onSelect={setSelected} selected={selected} />
        ) : (
          <SlideView pdf={pdf} page={pageInfo} notes={visible} selected={selected} fresh={fresh}
            here={a11y && spoken?.page === page ? spoken.block_id : null}
            onSelect={(id) => setSelected((s) => (s === id ? null : id))} onSwipe={(d) => goTo(page + d)} />
        )}

        {(!notebook || tasks.length > 0 || pending.length > 0) && (
            <div className="row lecture-head">
              <h2 className="t-title-s grow">{notebook ? "" : <>{page}쪽 필기 <span className="faint">{visible.length}</span></>}</h2>
              {tasks.length > 0 && <Chip variant="accent" onClick={() => setSheet("tasks")}>과제 {tasks.filter((t) => !t.done).length}</Chip>}
              {pending.length > 0 && <Chip variant="default" onClick={() => setSheet("pending")}>보류 {pending.length}</Chip>}
              {recording && !notebook && (
                <Chip variant={autoFollow ? "accent" : "default"} onClick={() => setAutoFollow(!autoFollow)}>
                  {autoFollow ? "자동 넘김" : elsewhere ? `지금 ${estimate}쪽 설명 중` : "직접 넘김"}
                </Chip>
              )}
            </div>
        )}
        {!notebook && (
          <>
            {visible.length === 0 ? (
              <p className="muted lecture-empty">{recording ? "교수님 설명을 듣고 있어요. 필기가 여기에 붙어요." : "이 쪽에는 아직 필기가 없어요"}</p>
            ) : (
              <div className="postit-grid">
                {visible.map((n, i) => (
                  <div key={n.id} className={`postit-slot${n.id === selected ? " sel" : ""}${n.id === fresh ? " fresh" : ""}${n.preview ? " preview" : ""}`}
                    onClick={() => setSelected(selected === n.id ? null : n.id)}
                    onContextMenu={(e) => { e.preventDefault(); void editNote(n); }}>
                    <PostIt type={n.type} number={i + 1}
                      tag={n.preview ? "AI가 정리 중…" : beyond.has(n.id) ? "슬라이드에 없는 설명" : n.edited_by_user ? "직접 수정함" : undefined}>{n.text}</PostIt>
                    {player.hasAudio && !n.preview && (
                      <button className="play-chip" onClick={(e) => { e.stopPropagation(); player.playFrom(n.start_ms); }} aria-label="이 필기 때 녹음 듣기">
                        <Icon name="play" size={14} /> {clock(n.start_ms)}
                      </button>
                    )}
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </div>

      {toastTerms.length > 0 && (
        <div className="term-stack">
          {toastTerms.map((t) => (
            <button key={t.id} className="term-toast" onClick={() => setSheet("glossary")}>
              <TermCard term={t.term} page={t.page_no} definition={t.definition} />
            </button>
          ))}
        </div>
      )}

      {message && <div className="toast" role="status">{message}</div>}

      <footer className="bottom-bar">
        {player.open && (
          <>
            {replayLine && <p className="caption-line t-body" aria-live="polite"><Icon name="closed-captioning" size={16} /> {replayLine}</p>}
            <PlayerBar audio={player.audio.current} onClose={() => { player.close(); setReplayLine(null); }} />
            <div className="row" style={{ gap: 8 }}>
              <Chip variant={replayFollow ? "accent" : "default"} onClick={() => setReplayFollow(!replayFollow)}>
                {replayFollow ? "쪽 따라가기 켜짐" : "쪽 따라가기 꺼짐"}
              </Chip>
            </div>
          </>
        )}
        {!player.open && player.hasAudio && phase === "ended" && (
          <button className="replay-start t-caption" onClick={() => player.playFrom(3000)}>
            <Icon name="play" size={16} /> 처음부터 다시 보기 · 녹음에 맞춰 쪽·필기·자막이 따라와요
          </button>
        )}
        {recording && !a11y && <p className="caption-line t-caption" aria-live="polite"><span className="rec-dot" />{caption}</p>}
        {recording && a11y && (
          <div className="caption-big" aria-live="polite">
            {(lines.length ? lines : [caption]).map((l, i, arr) => <p key={i} className={i === arr.length - 1 ? "now" : ""}>{l}</p>)}
          </div>
        )}
        <div className="row">
          <div className="grow">
            {notebook ? (
              <span className="t-title-s">{page}번 주제{pageInfo?.text ? ` · ${pageInfo.text}` : ""}</span>
            ) : (
              <div className="pager">
                <button onClick={() => goTo(page - 1)} aria-label="이전 쪽"><Icon name="caret-left" size={18} /></button>
                <span className="t-title-s">{page} / {doc.pages.length}</span>
                <button onClick={() => goTo(page + 1)} aria-label="다음 쪽"><Icon name="caret-right" size={18} /></button>
              </div>
            )}
            <span className="t-caption muted" style={{ display: "block" }}>
              {recording ? `녹음 중 ${clock(now - startedAt)}` : phase === "ending" ? "마지막 필기를 받는 중…" : phase === "ended" ? (serverStatus?.status === "transcribing" ? `녹음 파일 받아쓰는 중${serverStatus.progress ? ` ${Math.round(serverStatus.progress * 100)}%` : "…"}`
                : serverStatus?.status === "processing" ? "필기·요약 정리 중…" : serverStatus?.status === "failed" ? "정리하지 못했어요" : "강의가 끝났어요") : "버튼을 누르면 녹음을 시작해요"}
            </span>
          </div>
          {recording && (
            <button className="round round-soft confused-btn" onClick={markConfused} aria-label="모르겠어요 (표시만 하고 끝나고 설명)">
              <Icon name="hand-palm" />{confused > 0 && <span className="badge">{confused}</span>}
            </button>
          )}
          {sessionId && phase !== "idle" && (
            <button className="round round-soft" onClick={() => setSheet("ask")} disabled={asking} aria-label="방금 뭐라고?">
              {asking ? <span className="spin" /> : <Icon name="hand-waving" />}
            </button>
          )}
          {phase === "idle" && <button className="round round-record" onClick={startWithConsent} aria-label="녹음 시작"><Icon name="microphone" size={28} /></button>}
          {recording && <button className="round round-record on" onClick={() => void stop()} aria-label="강의 끝내기"><span className="stop" /></button>}
          {phase === "ending" && <span className="round round-soft"><span className="spin" /></span>}
          {phase === "ended" && sessionId && (
            <Button icon="graduation-cap" onClick={() => go({ name: "session", docId, sessionId, tab: "study" })}>공부하기</Button>
          )}
        </div>
      </footer>

      {askConsent && (
        <ConsentSheet onCancel={() => setAskConsent(false)} onAgree={() => {
          try { localStorage.setItem("ln.consent", "1"); } catch { /* 괜찮다 */ }
          setAskConsent(false);
          void start();
        }} />
      )}

      {sheet && (
        <>
          <div className="sheet-bg" onClick={() => setSheet(null)} />
          <div className="sheet" role="dialog" aria-modal="true">
            {sheet === "tasks" && <TaskList tasks={tasks} onOpen={(id) => setSheet({ task: id })} />}
            {typeof sheet === "object" && "task" in sheet && (() => {
              const t = tasks.find((x) => x.id === sheet.task);
              return t ? <TaskDetail task={t} toast={toast} onChange={(u) => setTasks((all) => all.map((x) => (x.id === u.id ? u : x)))} /> : null;
            })()}
            {sheet === "pdf" && sessionId && <NotesPdf sessionId={sessionId} />}
            {sheet === "ask" && (
              <AskSheet page={page} onAsk={ask} onCatchUp={(m) => setSheet({ catchUp: m })} />
            )}
            {typeof sheet === "object" && "catchUp" in sheet && sessionId && (
              <CatchUp sessionId={sessionId} minutes={sheet.catchUp} onGo={(no) => { setSheet(null); goTo(no); }} />
            )}
            {sheet === "glossary" && (
              <>
                <h3 className="t-title-m">용어 사전 <span className="faint t-caption">{terms.length}개</span></h3>
                {terms.length === 0 && <p className="muted">강의 중에 전문용어가 나오면 여기에 모여요.</p>}
                {terms.map((t) => <TermCard key={t.id} term={t.term} page={t.page_no} definition={t.definition} />)}
              </>
            )}
            {sheet === "pending" && (
              <>
                <h3 className="t-title-m">보류함</h3>
                <p className="muted">AI가 어느 쪽 이야기인지 확신하지 못한 필기예요. 붙일 쪽을 골라 주세요.</p>
                {pending.map((n) => (
                  <div key={n.id} style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                    <PostIt type={n.type}>{n.text}</PostIt>
                    <div className="scroll-x" style={{ flexWrap: "wrap" }}>
                      {doc.pages.map((p) => <Chip key={p.page_no} variant="accent" onClick={() => void place(n, p.page_no)}>{p.page_no}쪽</Chip>)}
                    </div>
                  </div>
                ))}
              </>
            )}
          </div>
        </>
      )}
    </div>
  );
}

function AskSheet({ page, onAsk, onCatchUp }: { page: number; onAsk: (q: string) => void; onCatchUp: (m: number) => void }) {
  const [q, setQ] = useState("");
  return (
    <>
      <h3 className="t-title-m">방금 뭐라고?</h3>
      <p className="muted">최근 2분 설명과 {page}쪽 자료를 보고 답해서, 관련 문단 옆에 붙여 줘요.</p>
      <div className="scroll-x" style={{ flexWrap: "wrap" }}>
        {QUICK_QUESTIONS.map((x) => <Chip key={x} variant="accent" onClick={() => onAsk(x)}>{x}</Chip>)}
      </div>
      <form className="row" onSubmit={(e) => { e.preventDefault(); if (q.trim()) onAsk(q.trim()); }}>
        <input className="input" value={q} onChange={(e) => setQ(e.target.value)} placeholder="궁금한 걸 적어도 돼요" aria-label="질문" />
        <Button type="submit" disabled={!q.trim()}>묻기</Button>
      </form>
      <h3 className="t-title-s section-title">딴생각했어요</h3>
      <div className="scroll-x">
        {[1, 3, 5].map((m) => <Chip key={m} variant="default" onClick={() => onCatchUp(m)}>최근 {m}분 따라잡기</Chip>)}
      </div>
    </>
  );
}

function CatchUp({ sessionId, minutes, onGo }: { sessionId: string; minutes: number; onGo: (page: number) => void }) {
  const [res, setRes] = useState<{ points: string[]; pages: number[]; from_ms: number; to_ms: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    postJSON<typeof res>(`/sessions/${sessionId}/catch-up`, { minutes }).then(setRes).catch((e) => setError(e.message));
  }, [sessionId, minutes]);
  return (
    <>
      <h3 className="t-title-m">최근 {minutes}분 따라잡기</h3>
      {error && <p className="muted">{error}</p>}
      {!res && !error && <p className="muted"><span className="spin" /> 놓친 설명을 정리하는 중…</p>}
      {res && res.points.length === 0 && <p className="muted">그동안 받아쓴 설명이 없어요.</p>}
      {res && res.points.length > 0 && (
        <>
          <p className="t-caption muted">{clock(res.from_ms)} ~ {clock(res.to_ms)} 사이에 교수님이 한 설명이에요.</p>
          <div className="banner">
            {res.points.map((p, i) => {
              const important = p.startsWith("[중요]");
              return <p key={i} className="t-body" style={important ? { color: "var(--note-exam-ink)", fontWeight: 700 } : undefined}>· {p.replace(/^\[중요\]\s*/, "")}</p>;
            })}
          </div>
          <div className="scroll-x">{res.pages.map((no) => <Chip key={no} variant="accent" onClick={() => onGo(no)}>{no}쪽 보기</Chip>)}</div>
        </>
      )}
    </>
  );
}

/** 강의자료 한 쪽 + 형광펜(필기가 붙은 문단) + 번호 깃발 + 방금 들어온/고른 필기를 자료 위에 펼친 쪽지 */
function SlideView({ pdf, page, notes, selected, fresh, here, onSelect, onSwipe }: {
  pdf: PdfDoc | null; page: Page | undefined; notes: Note[]; selected: number | null; fresh: number | null; here: number | null;
  onSelect: (id: number | null) => void; onSwipe: (dir: 1 | -1) => void;
}) {
  const box = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const [width, setWidth] = useState(0);
  const touchX = useRef<number | null>(null);

  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setWidth((w) => (Math.abs(el.clientWidth - w) > 4 ? el.clientWidth : w)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    if (pdf && page && canvas.current && width) void renderPage(pdf, page.page_no, canvas.current, width);
  }, [pdf, page, width]);

  if (!page) return null;
  const blocks = new Map(page.blocks.map((b) => [b.id, b]));
  const spot = notes.find((n) => n.id === (selected ?? fresh));
  const spotBlock = spot?.block_id != null ? blocks.get(spot.block_id) : undefined;
  let loose = 0;

  return (
    <div className="slide" ref={box} style={{ aspectRatio: `${page.width} / ${page.height}` }}
      onTouchStart={(e) => { touchX.current = e.touches[0].clientX; }}
      onTouchEnd={(e) => {
        if (touchX.current === null) return;
        const dx = e.changedTouches[0].clientX - touchX.current;
        touchX.current = null;
        if (Math.abs(dx) > 50) onSwipe(dx < 0 ? 1 : -1);
      }}>
      <canvas ref={canvas} />
      {!pdf && <span className="slide-loading muted t-caption">자료를 그리는 중…</span>}
      <div className="marks">
        {page.blocks.map((b) => {
          const last = [...notes].reverse().find((n) => n.block_id === b.id);
          if (!last) return null;
          const strong = notes.some((n) => n.block_id === b.id && n.id === selected);
          return <div key={b.id} className="hl" style={{
            left: `calc(${b.x * 100}% - 4px)`, top: `${(b.y + b.h * 0.1) * 100}%`, width: `calc(${b.w * 100}% + 8px)`, height: `${b.h * 90}%`,
            background: `var(--note-${last.type}-ink)`, opacity: strong ? 0.36 : 0.22,
          }} />;
        })}
        {notes.map((n, i) => {
          const b = n.block_id != null ? blocks.get(n.block_id) : undefined;
          let left: string, top: string;
          if (b) {
            const before = notes.slice(0, i).filter((m) => m.block_id === n.block_id).length;
            left = `min(calc(${Math.min(b.x + b.w, 1) * 100}% + ${20 + before * 30}px), calc(100% - 18px))`;
            top = `max(${(b.y + b.h / 2) * 100}%, 16px)`;
          } else {
            left = `min(${26 + loose++ * 34}px, calc(100% - 20px))`;
            top = "calc(100% - 18px)";
          }
          return (
            <button key={n.id} className={`flag${n.id === selected ? " sel" : ""}${n.preview ? " preview" : ""}`}
              style={{ left, top, background: `var(--note-${n.type}-paper)`, "--ink": `var(--note-${n.type}-ink)` } as CSSProperties}
              onClick={() => onSelect(n.id)} aria-label={`${i + 1}번 필기`}>{i + 1}</button>
          );
        })}
        {here != null && blocks.get(here) && (() => {
          const b = blocks.get(here)!;
          return <div className="here" style={{ left: `calc(${b.x * 100}% - 6px)`, top: `calc(${b.y * 100}% - 4px)`, width: `calc(${b.w * 100}% + 12px)`, height: `calc(${b.h * 100}% + 8px)` }}><span>지금 여기</span></div>;
        })()}
        {spot && (
          <button className="callout" onClick={() => onSelect(null)} style={{
            left: spotBlock ? `clamp(8px, ${spotBlock.x * 100}%, calc(38% - 8px))` : "4%",
            ...(spotBlock && spotBlock.y + spotBlock.h < 0.62
              ? { top: `calc(${(spotBlock.y + spotBlock.h) * 100}% + 6px)` }
              : { bottom: `calc(${spotBlock ? (1 - spotBlock.y) * 100 : 8}% + 6px)` }),
            background: `var(--note-${spot.type}-paper)`,
          }}>
            <span className="t-caption" style={{ color: `var(--note-${spot.type}-ink)`, display: "block" }}>{NOTE_LABEL[spot.type]}</span>
            {spot.text}
          </button>
        )}
      </div>
    </div>
  );
}

/** 노트 수업: 색 머리띠 + 모눈 종이에 주제마다 번호·제목, 그 아래로 필기가 한 줄씩 */
function NotebookSheet({ doc, notes, page, recording, fresh, selected, onSelect, startedAt }: {
  doc: DocumentDetail; notes: Note[]; page: number; recording: boolean; fresh: number | null; selected: number | null;
  onSelect: (id: number | null) => void; startedAt: number;
}) {
  const freshRef = useRef<HTMLParagraphElement>(null);
  useEffect(() => { freshRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" }); }, [fresh]);
  const date = new Date(startedAt || Date.now());
  const MARK: Record<string, string> = { explanation: "-", example: "예)", emphasis: "!", exam: "★", notice: "공지)", tip: "(+)", qa: "Q." };
  return (
    <div className="notebook">
      <header className="notebook-band">
        <span className="t-caption">{date.toLocaleDateString("ko-KR", { month: "long", day: "numeric", weekday: "short" })}</span>
        <strong className="t-title-m">{doc.title}</strong>
      </header>
      <div className="note-sheet">
        {doc.pages.map((p) => {
          const mine = notes.filter((n) => n.page_no === p.page_no && !n.pending);
          const current = p.page_no === page;
          return (
            <section key={p.page_no} className={`note-section${current ? " now" : ""}`}>
              <div className="row" style={{ gap: 8 }}>
                <span className="note-num">{p.page_no}</span>
                <h3 className="t-title-s">{p.text || <span className="faint">{recording && current ? "주제를 듣는 중…" : "제목 없음"}</span>}</h3>
              </div>
              {mine.length === 0 && <p className="t-note faint">{recording && current ? "교수님 설명을 듣고 있어요. 필기가 여기에 써져요." : "아직 필기가 없어요"}</p>}
              {mine.map((n) => (
                <p key={n.id} ref={n.id === fresh ? freshRef : undefined} onClick={() => onSelect(selected === n.id ? null : n.id)}
                  className={`t-note nb-line${n.type === "exam" || n.type === "emphasis" ? " note-hl" : ""}${n.preview ? " preview" : ""}${n.id === fresh ? " fresh" : ""}`}>
                  <span className="nb-mark" style={{ color: `var(--note-${n.type}-ink)` }}>{MARK[n.type] ?? "-"}</span> {n.text}
                </p>
              ))}
            </section>
          );
        })}
      </div>
    </div>
  );
}
