// 2·3 강의 화면 (녹음 중): 강의자료 위에 형광펜·번호 깃발, 아래에 포스트잇 필기. 노트 수업은 모눈 노트에 주제별로 써 내려간다.
// 녹음 → 서버(받아쓰기·AI 필기) → WebSocket 이벤트로 화면에 붙는다. 기존 웹앱과 같은 규약 (lib/live.ts).
import { useCallback, useEffect, useLayoutEffect, useRef, useState, type CSSProperties } from "react";
import { LocalRecording, syncRecordings } from "../lib/localRec";
import { EnglishToggle, lectureLang } from "../components/EnglishToggle";
import { IosRecordWarning } from "../components/IosHint";
import type { Annotation, DocumentDetail, GlossaryTerm, NoteType, Page } from "../api/types";
import { getJSON, postJSON } from "../api/useApi";
import { LiveWave, refreshWaves } from "../lib/wave";
import { play, setRecording } from "../lib/sound";
import { android, browserRecognizer, LiveSocket, NativeLive, startFileAudio, startMicrophone, type Live, type Mic, type ServerEvent } from "../lib/live";
import { clock, LectureMore, PlayerBar, TaskDetail, TaskList, usePlayer, type FullTask } from "./LectureExtras";
import { ConsentSheet } from "./ExamPrep";
import { loadPdf, renderPage, type PdfDoc } from "../lib/pdf";
import { Button, Chip, Icon, NOTE_LABEL, PostIt, TermCard, TopBar } from "../components/ui";
import { back as goBack, go } from "../router";
import { askYes, tell } from "../components/Dialog";
import { Skeleton } from "../lib/motion";

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
type Sheet = null | "ask" | "glossary" | "pending" | "tasks" | "pdf" | "add" | { edit: number } | { catchUp: number } | { task: number } | { source: number };


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
  const [, setEstimate] = useState<number | null>(null);
  const [autoFollow, setAutoFollow] = useState(true);
  const [caption, setCaption] = useState("교수님 말이 여기에 글로 떠요");
  const [perk, setPerk] = useState(false);
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
  const [loud, setLoud] = useState(false); // 방금 문장을 목소리 높여 말했는지 (자막 옆에 표시)
  const [photoBusy, setPhotoBusy] = useState(false);
  // 발표 모드(설정)를 켠 사람에게만 '발표 시연' 링크를 보여 준다
  const presenter = (() => { try { return localStorage.getItem("ln.presenter") === "1"; } catch { return false; } })();
  // 아래 조작부 높이만큼 내용 아래에 여백을 둬서 마지막 필기가 가려지지 않게
  const footerRef = useRef<HTMLElement>(null);
  useEffect(() => {
    const el = footerRef.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => document.documentElement.style.setProperty("--footer-h", `${el.offsetHeight}px`));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const photoInput = useRef<HTMLInputElement>(null);

  // 이벤트 처리기에서 최신 값을 읽기 위한 거울
  const live = useRef<Live | null>(null);
  const mic = useRef<Mic | null>(null);
  const localRec = useRef<LocalRecording | null>(null);
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
        if (d.kind === "slides") loadPdf(docId).then((p) => alive && setPdf(p)).catch((e) => setError(e.message));
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
          // 검색에서 왔으면 그 쪽부터
          let jump: number | null = null;
          try { jump = Number(sessionStorage.getItem("ln.jump")) || null; sessionStorage.removeItem("ln.jump"); } catch { /* 괜찮다 */ }
          if (jump) { setPage(jump); return; }
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

  // 녹음 중에 앱·브라우저가 꺼져 '끝내기'를 못 누른 강의: 이어서 녹음하거나 여기서 끝낸다
  const [cut, setCut] = useState<{ ms: number; native: boolean; elsewhere: boolean } | null>(null);
  // 녹음 파일로 정리 중인 강의: 끝날 때까지 필기를 다시 받아 온다
  const [serverStatus, setServerStatus] = useState<{ status: string; progress: number | null; error?: string | null; engine?: string | null; analysis?: { done_ms: number; total_ms: number; page: number | null } | null } | null>(null);
  const [justDone, setJustDone] = useState(false); // 정리가 막 끝났을 때 잠깐 '정리 끝' 표시
  useEffect(() => {
    if (!initialSession) return;
    let alive = true;
    let timer: number | undefined;
    const poll = async () => {
      try {
        const s = await getJSON<{ status: string; progress: number | null; error?: string | null; engine?: string | null; analysis?: { done_ms: number; total_ms: number; page: number | null } | null }>(`/sessions/${initialSession}/summary`);
        if (!alive) return;
        if (s.status === "recording") {
          const got = await getJSON<{ ms: number; live?: boolean }>(`/sessions/${initialSession}/received`).catch(() => ({ ms: 0, live: false }));
          const native = !!android()?.isRecording();
          if (alive) setCut({ ms: got.ms, native, elsewhere: !native && !!got.live });
        }
        const busy = s.status === "transcribing" || s.status === "processing";
        setServerStatus((prev) => {
          if (!busy && prev && prev.status !== s.status) setRefresh((n) => n + 1); // 막 끝났으면 마지막 필기를 한 번 더 받는다
          if (!busy && prev && ["transcribing", "processing"].includes(prev.status) && s.status === "done") { setJustDone(true); window.setTimeout(() => setJustDone(false), 4500); }
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

  // 화면이 다시 켜지면 그동안 놓친 필기·과제·용어를 다시 받아 온다
  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState !== "visible" || !sessionId || phase !== "recording") return;
      Promise.all([
        getJSON<Annotation[]>(`/sessions/${sessionId}/annotations`),
        getJSON<FullTask[]>(`/sessions/${sessionId}/tasks`).catch(() => null),
        getJSON<GlossaryTerm[]>(`/sessions/${sessionId}/glossary`).catch(() => null),
        getJSON<DocumentDetail>(`/documents/${docId}`).catch(() => null),
      ]).then(([a, t, g, d]) => {
        setNotes(a);
        if (t) setTasks(t);
        if (g) setTerms(g);
        if (d) setDoc(d);
      }).catch(() => {});
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, [sessionId, phase, docId]);

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
        flash(e.annotation.id);
        play(e.annotation.type === "exam" || e.annotation.type === "notice" ? "alert" : "note"); // 녹음 중이면 진동만
        if (e.annotation.type === "exam" || e.annotation.type === "notice") {
          setPerk(true); window.setTimeout(() => setPerk(false), 2600); // 시험·공지: 파형이 빨개진다
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
        setBanner({ icon: "clipboard-text", title: `새 ${TASK_LABEL[e.task.kind] ?? "과제"}${e.task.due_text ? `, ${e.task.due_text}` : ""}`, text: e.task.title, task: e.task.id });
        if (a11yRef.current) navigator.vibrate?.(STRONG_BUZZ);
        break;
      case "heard":
        setCaption(e.text);
        setLoud(Boolean((e as { loud?: boolean }).loud));
        break;
      case "spoken":
        setCaption(e.text);
        setLines((l) => [...l, e.text].slice(-3));
        setSpoken({ page: e.page, block_id: e.block_id });
        break;
      case "notice":
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

  // '이 쪽 고정': 고정하는 동안 AI 필기는 보고 있는 쪽에 붙는다 (서버 쪽 추정보다 우선). 넘기면 고정도 따라간다
  useEffect(() => {
    if (phase !== "recording" || !live.current) return;
    live.current.send({ type: "pin", page: autoFollow ? null : page });
  }, [phase, autoFollow, page]);
  // --- 녹음 ---
  const start = async (demoFile?: File, resume?: { id: string; ms: number }) => {
    const app = demoFile ? null : android(); // 시연 파일은 앱 안에서도 웹 방식으로 보낸다
    // 마이크는 버튼을 누른 바로 그 순간에 켜야 iPhone Safari가 허락한다 (서버 응답을 기다리기 전에)
    // 안드로이드 앱 안에서는 앱이 직접 녹음한다 (화면이 꺼져도 이어진다)
    // 서버로 보내면서 폰 안에도 전부 모아 둔다 (연결이 끊겨도 녹음이 빠지지 않게 · lib/localRec.ts)
    const send = (pcm: ArrayBuffer) => { live.current?.sendAudio(pcm); localRec.current?.append(pcm); };
    const micStart = app ? Promise.resolve(null)
      : demoFile ? startFileAudio(demoFile, send, () => toast("시연 파일이 끝났어요. ■ 를 눌러 강의를 끝내세요"))
      : startMicrophone(send);
    micStart.catch(() => {}); // 실패는 아래에서 다룬다
    let id: string;
    try {
      // 끊긴 강의를 이어 녹음하면 같은 강의에 붙인다 (서버가 녹음 조각과 받아쓰기 시각을 앞 조각에 이어 매긴다)
      id = resume?.id ?? (await postJSON<{ id: string }>("/sessions", { document_id: docId, language: lectureLang(docId) })).id;
    } catch (e) {
      micStart.then((m) => m?.stop()).catch(() => {});
      return toast(e instanceof Error ? e.message : String(e));
    }
    const began = Date.now() - (resume?.ms ?? 0);
    if (!app) localRec.current = new LocalRecording(id);
    setSessionId(id);
    setStartedAt(began);
    setNow(began);
    play("start");
    setRecording(true);
    setPhase("recording");
    window.history.replaceState(null, "", `#/doc/${docId}/lecture/${id}`);
    const socket: Live = app ? new NativeLive(app, id, (e) => handleRef.current(e)) : new LiveSocket(id, (e) => handleRef.current(e), () => pageRef.current);
    live.current = socket;
    socket.connect();
    try {
      mic.current = await micStart;
      if (app) app.keepScreenOn(false); // 앱은 화면을 꺼도 되니 켜 둘 필요가 없다
    } catch {
      // 마이크 소리를 직접 못 받는 브라우저: 내장 음성 인식으로 대신한다
      const rec = browserRecognizer(
        (text, s, e) => socket.send({ type: "transcript_final", text, start_ms: s, end_ms: e }),
        (interim) => setCaption(interim || "교수님 말이 여기에 글로 떠요"),
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
    setRecording(false);
    play("stop");
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
    // 폰에 모아 둔 녹음: 서버가 다 받았으면 지우고, 빠진 곳이 있으면 전체 녹음을 올려 처음부터 다시 정리
    const rec = localRec.current;
    localRec.current = null;
    if (rec) void rec.finish().then(syncRecordings).then((n) => { if (n) toast("연결이 끊겼던 부분까지 전체 녹음을 올렸어요. 처음부터 다시 정리해요."); });
    setPhase(sessionId || finish ? "ended" : "idle");
  };

  const handleRef = useRef(handle);
  handleRef.current = handle;

  // 강의가 끝나면: 녹음 다시 듣기, 슬라이드에 없던 설명 표시
  const player = usePlayer(sessionId, phase === "ended");
  useEffect(() => () => setRecording(false), []); // 강의 화면을 벗어나면 효과음 금지를 푼다
  useEffect(() => { if (phase === "ended") refreshWaves(); }, [phase]); // 새 강의의 소리 무늬를 목록에서 다시 받게
  // 스토리·수업 흐름에서 "이 순간 듣기"로 왔으면 녹음을 그 시각부터 튼다
  const playFromRef = useRef(player.playFrom);
  playFromRef.current = player.playFrom;
  useEffect(() => {
    if (!player.hasAudio) return;
    let ms: number | null = null;
    try { const raw = sessionStorage.getItem("ln.jumpMs"); sessionStorage.removeItem("ln.jumpMs"); ms = raw === null ? null : Number(raw); } catch { /* 괜찮다 */ }
    if (ms !== null && !Number.isNaN(ms)) playFromRef.current(ms + 3000);
  }, [player.hasAudio]);

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
      toast("표시했어요, 끝나고 쉽게 설명해 드릴게요");
    } catch (e) { toast(e instanceof Error ? e.message : String(e)); }
  };

  // 칠판·화이트보드 사진: 찍으면 AI가 읽어 지금 쪽에 필기로 붙인다
  const sendPhoto = async (file: File) => {
    if (!sessionId) return;
    setPhotoBusy(true);
    try {
      const form = new FormData();
      form.append("page_no", String(page));
      form.append("file", file);
      const res = await fetch(`${import.meta.env.VITE_API_URL ?? ""}/sessions/${sessionId}/photo`, { method: "POST", body: form });
      const note = await res.json();
      if (!res.ok) throw new Error(note?.detail ?? "사진을 올리지 못했어요");
      setNotes((n) => [...n, note]);
      flash(note.id);
      toast("칠판 사진을 필기로 붙였어요");
    } catch (e) { toast(e instanceof Error ? e.message : String(e)); }
    setPhotoBusy(false);
  };

  // 확인 필요 필기가 맞다고 확인 (틀렸으면 길게 눌러 고치거나 지운다) → 우리 AI 학습에 확인된 정답으로
  const confirmNote = async (n: Note) => {
    try {
      const res = await fetch(`${import.meta.env.VITE_API_URL ?? ""}/annotations/${n.id}`, {
        method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ confirm: true }),
      });
      if (!res.ok) throw new Error("확인하지 못했어요");
      const updated = await res.json();
      setNotes((all) => all.map((x) => (x.id === n.id ? updated : x)));
      toast("확인했어요, 우리 AI가 배워요");
    } catch (e) { toast(e instanceof Error ? e.message : String(e)); }
  };

  // ⭐ 여기 중요: 방금 설명한 문장을 강조 필기로 (시험 예상 지도·족보에 들어간다)
  const starHere = async () => {
    if (!sessionId) return;
    try {
      const note = await postJSON<Annotation>(`/sessions/${sessionId}/star`, { page_no: page });
      setNotes((n) => [...n, note]);
      flash(note.id);
      navigator.vibrate?.(15);
      toast("중요 표시했어요 ⭐");
    } catch (e) { toast(e instanceof Error ? e.message : String(e)); }
  };

  // 내 필기: 지금 쪽에 직접 쓴다
  const addMyNote = async (text: string, type: string) => {
    if (!sessionId || !text.trim()) return;
    try {
      const note = await postJSON<Annotation>(`/sessions/${sessionId}/annotations`, { page_no: page, text, type });
      setNotes((n) => [...n, note]);
      setSheet(null);
      flash(note.id);
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

  const editNote = (note: Note) => { if (!note.preview) setSheet({ edit: note.id }); };
  const deleteNote = async (note: Note) => {
    if (!await askYes("이 필기를 지울까요?")) return;
    try {
      await fetch(`${import.meta.env.VITE_API_URL ?? ""}/annotations/${note.id}`, { method: "DELETE" });
      setNotes((n) => n.filter((x) => x.id !== note.id));
      setSelected(null);
      setSheet(null);
    } catch (e) { toast(e instanceof Error ? e.message : String(e)); }
  };
  const saveNote = async (note: Note, text: string, type: NoteType = note.type) => {
    if (!text.trim()) return deleteNote(note);
    try {
      const res = await fetch(`${import.meta.env.VITE_API_URL ?? ""}/annotations/${note.id}`, {
        method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: text === note.text ? undefined : text, type: type === note.type ? undefined : type }),
      });
      if (!res.ok) throw new Error("저장하지 못했어요");
      const updated = await res.json();
      setNotes((n) => n.map((x) => (x.id === note.id ? updated : x)));
      setSheet(null);
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
  if (error) return <div className="screen"><TopBar title="강의" onBack={() => goBack({ name: "doc", docId })} /><p className="screen-body muted">{error}</p></div>;
  if (!doc) return <div className="screen"><TopBar title="" onBack={() => goBack({ name: "doc", docId })} /><div className="screen-body"><Skeleton lines={5} /></div></div>;

  const recording = phase === "recording";
  const notebook = doc.kind === "notebook" || doc.kind === "meeting";
  const all = [...notes, ...previews];
  const visible = all.filter((n) => n.page_no === page && !n.pending);
  const pending = notes.filter((n) => n.pending);
  const pageInfo = doc.pages[page - 1];

  const back = async () => {
    if (recording && !await askYes("녹음을 멈추고 나갈까요?")) return;
    // 뒤로 = 들어온 화면으로 (끝난 강의에서 필기 화면으로 '앞으로' 보내면 두 화면 사이를 끝없이 오가서 홈으로 못 갔다)
    goBack({ name: "doc", docId });
  };

  return (
    <div className={`screen lecture${recording ? " night-rec" : ""}${!recording && serverStatus?.status && ["transcribing", "processing"].includes(serverStatus.status) ? " analyzing" : ""}${!recording && serverStatus?.analysis?.page === page ? " analyzing-here" : ""}${justDone ? " just-done" : ""}`}>
      <TopBar title={doc.title} onBack={back} home={false} action={
        <div className="row" style={{ gap: 0 }}>
          <button className="top-bar-back" aria-label={`용어 사전 ${terms.length}개`} onClick={() => setSheet("glossary")} style={{ position: "relative" }}>
            <Icon name="book-open-text" />
            {terms.length > 0 && <span className="badge">{terms.length}</span>}
            <small className="top-icon-label">용어</small>
          </button>
          <button className={`top-bar-back${a11y ? " on" : ""}`} aria-label="자막 모드 (크게 보기·중요할 때 진동)" aria-pressed={a11y} onClick={toggleA11y}>
            <Icon name="closed-captioning" />
            <small className="top-icon-label">자막</small>
          </button>
          {sessionId && phase === "ended" && (
            <button className="top-bar-back" aria-label="더보기: 정리 노트 PDF, 강의 지우기" onClick={() => setSheet("pdf")}><Icon name="dots-three-outline" /></button>
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
                <Chip variant={autoFollow ? "default" : "selected"} onClick={() => setAutoFollow(!autoFollow)}>
                  {autoFollow ? <><Icon name="lock-simple" size={13} /> 이 쪽 고정</> : <><Icon name="lock-simple" size={13} /> {page}쪽 고정 풀기</>}
                </Chip>
              )}
            </div>
        )}
        {!notebook && (
          <>
            {visible.length === 0 ? (
              <p className="muted lecture-empty">{recording ? "교수님 설명을 듣고 있어요. 필기가 여기에 붙어요." : "이 쪽에는 아직 필기가 없어요"}</p>
            ) : (
              <div key={page} className="postit-grid page-turn">
                {visible.map((n, i) => (
                  <div key={n.id} className={`postit-slot${!n.preview && !n.edited_by_user && (n.confidence ?? 1) < 0.6 ? " unsure" : ""}${n.id === selected ? " sel" : ""}${n.id === fresh ? " fresh" : ""}${n.preview ? " preview" : ""}`}
                    onClick={() => setSelected(selected === n.id ? null : n.id)}
                    onContextMenu={(e) => { e.preventDefault(); editNote(n); }}>
                    <PostIt type={n.type} number={i + 1} photo={n.photo_id ? `${import.meta.env.VITE_API_URL ?? ""}/photos/${n.photo_id}` : null}
                      tag={n.preview ? "정리하는 중…" : beyond.has(n.id) ? "슬라이드에 없는 설명" : n.edited_by_user ? "직접 씀·고침" : undefined}>{n.text}</PostIt>
                    {n.id === selected && !n.preview && (
                      <div className="note-actions" onClick={(e) => e.stopPropagation()}>
                        {/* AI 가 엉뚱한 쪽에 붙였을 때: 옆 쪽으로 한 번에 옮기기 */}
                        {page > 1 && <button onClick={() => void place(n, page - 1)} aria-label="이 필기를 앞 쪽으로 옮기기"><Icon name="caret-left" size={16} />앞 쪽으로</button>}
                        {page < doc.pages.length && <button onClick={() => void place(n, page + 1)} aria-label="이 필기를 다음 쪽으로 옮기기">다음 쪽으로<Icon name="caret-right" size={16} /></button>}
                        <button onClick={() => editNote(n)}><Icon name="note-pencil" size={16} />수정</button>
                        <button className="danger" onClick={() => void deleteNote(n)}><Icon name="trash" size={16} />삭제</button>
                      </div>
                    )}
                    {!n.preview && !n.edited_by_user && (n.confidence ?? 1) < 0.6 && (
                      <button className="confirm-chip" onClick={(e) => { e.stopPropagation(); void confirmNote(n); }}
                        aria-label="AI가 쪽을 확신하지 못한 필기예요. 맞으면 눌러 주세요">이 쪽이 맞아요</button>
                    )}
                    {n.id === selected && !n.preview && (
                      <button className="source-chip" onClick={(e) => { e.stopPropagation(); setSheet({ source: n.id }); }}>
                        <Icon name="chat-teardrop-text" size={14} /> 근거 보기
                      </button>
                    )}
                    {player.hasAudio && !n.preview && (
                      <button className="play-chip" onClick={(e) => { e.stopPropagation(); player.playFrom(n.start_ms, n.type === "emphasis" || n.type === "exam" ? 15 : 3); }} aria-label="이 필기 때 녹음 듣기">
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

      <footer ref={footerRef} className={`bottom-bar${recording ? " rec" : ""}`}>
        {player.open && (
          <>
            {replayLine && <p className="caption-line t-body" aria-live="polite"><Icon name="closed-captioning" size={16} /> {replayLine}</p>}
            <PlayerBar audio={player.audio.current} speech={player.speech} onClose={() => { player.close(); setReplayLine(null); }} />
            <div className="row" style={{ gap: 8 }}>
              <Chip variant={replayFollow ? "accent" : "default"} onClick={() => setReplayFollow(!replayFollow)}>
                {replayFollow ? "쪽 따라가기 켜짐" : "쪽 따라가기 꺼짐"}
              </Chip>
            </div>
          </>
        )}
        {!player.open && player.hasAudio && phase === "ended" && (
          <button className="replay-start t-caption" onClick={() => player.playFrom(3000)}>
            <Icon name="play" size={16} /> 처음부터 다시 보기 (녹음에 맞춰 쪽과 필기, 자막이 따라와요)
          </button>
        )}
        {recording && (
          <>
            <div className="rec-clock" aria-live="off"><i />{clock(now - startedAt)}</div>
            <LiveWave loud={loud || perk} />
            <span className="rec-pill"><i />{perk ? "시험·공지 얘기가 나왔어요" : "실시간 받아쓰기 중…"}</span>
          </>
        )}
        {!recording && phase !== "idle" && ((serverStatus?.status && ["transcribing", "processing"].includes(serverStatus.status)) || justDone) && (() => {
          // AI가 지금 무엇을 하는지: 받아쓰기(몇 %) → 쪽마다 필기로 옮기기(몇 분 중 몇 분, 지금 몇 쪽) → 요약 → 끝
          const st = justDone ? "done" : serverStatus!.status;
          const an = serverStatus?.analysis;
          const mm = (ms: number) => `${Math.floor(ms / 60000)}:${String(Math.floor(ms / 1000) % 60).padStart(2, "0")}`;
          const pct = st === "done" ? 1 : st === "transcribing" ? (serverStatus?.progress ?? 0) * 0.4 : an?.total_ms ? 0.4 + (an.done_ms / an.total_ms) * 0.5 : 0.92;
          const notedPages = new Set(notes.filter((n) => !n.pending).map((n) => n.page_no));
          const nowPage = an?.page ?? null;
          return (
            <div className={`ai-work${st === "done" ? " finished" : ""}`} role="status">
              <div className="aw-top">
                {st === "done" ? <span className="aw-check" aria-hidden="true"><Icon name="check" size={16} /></span> : (
                  <span className="aw-flow" aria-hidden="true">
                    <span className="aw-wave">{Array.from({ length: 7 }, (_, i) => <i key={i} style={{ animationDelay: `${i * 0.09}s` }} />)}</span>
                    <span className="aw-arrow" />
                    <span className="aw-lines"><i /><i /><i /></span>
                  </span>
                )}
                <span className="aw-text">
                  <b>{st === "done" ? "정리 끝" : st === "transcribing" ? "교수님 말을 받아쓰는 중" : an ? "쪽마다 필기로 옮기는 중" : "요약과 퀴즈를 만드는 중"}</b>
                  <small>{st === "done" ? `필기가 ${notedPages.size}쪽에 붙었어요` : st === "transcribing" ? `${Math.round((serverStatus?.progress ?? 0) * 100)}%` : an ? `${mm(an.done_ms)} / ${mm(an.total_ms)} 분석${nowPage ? `, 지금 ${nowPage}쪽` : ""}` : "거의 다 됐어요"}</small>
                </span>
                <span className="aw-pct">{Math.round(pct * 100)}<small>%</small></span>
              </div>
              <span className="aw-bar"><i style={{ transform: `scaleX(${pct})` }} /></span>
              {/* 쪽마다 상태: 끝(필기 있음) · 지금 · 기다림. 누르면 그 쪽으로 */}
              {!notebook && (
                <div className="aw-pages" aria-label="쪽마다 정리 상태">
                  {doc.pages.map((p) => {
                    const state = p.page_no === nowPage && st !== "done" ? "now" : notedPages.has(p.page_no) ? "done" : "wait";
                    return <button key={p.id} className={`aw-p ${state}${p.page_no === page ? " here" : ""}`} style={{ ["--k" as string]: p.page_no }} onClick={() => goTo(p.page_no)}
                      aria-label={`${p.page_no}쪽, ${state === "done" ? "정리 끝" : state === "now" ? "정리 중" : "기다리는 중"}`} />;
                  })}
                </div>
              )}
            </div>
          );
        })()}
        {!recording && phase === "ended" && sessionId && cut && (
          <div className="cut-banner" role="alert">
            <span className="cut-ic"><Icon name="warning-circle" size={20} /></span>
            <div className="grow">
              <b>{cut.native ? "앱이 아직 녹음하고 있어요" : cut.elsewhere ? "다른 기기에서 녹음하고 있어요" : "녹음이 중간에 끊겼어요"}</b>
              <small>{cut.native ? "화면만 다시 열렸어요. 수업이 끝났으면 녹음을 끝내 주세요."
                : cut.elsewhere ? "녹음하는 기기에서 끝내 주세요. 그 기기를 잃어버렸으면 여기서 끝내도 돼요."
                : `${clock(cut.ms)}까지 저장돼 있어요. 수업이 아직이면 이어서 녹음해요.`}</small>
              <div className="row">
                {!cut.native && !cut.elsewhere && <button className="chip chip-accent" onClick={() => { const c = cut; setCut(null); void start(undefined, { id: sessionId, ms: c.ms }); }}>
                  <Icon name="microphone" size={14} /> 이어서 녹음</button>}
                <button className="chip chip-default" onClick={async () => {
                  if (cut.native) android()?.stop();
                  try { await postJSON(`/sessions/${sessionId}/end`); window.location.reload(); }
                  catch (e) { toast(e instanceof Error ? e.message : String(e)); }
                }}>여기서 끝내고 정리하기</button>
              </div>
            </div>
          </div>
        )}
        {!recording && sessionId && serverStatus?.status === "failed" && (
          <div className="listen-row retry-row">
            <span className="t-caption muted grow">정리하지 못했어요. 녹음은 저장돼 있어요.{serverStatus.error && <><br /><span className="retry-why">{serverStatus.error}</span></>}</span>
            <button className="chip chip-accent" onClick={async () => {
              try { await postJSON(`/sessions/${sessionId}/retry`); window.location.reload(); }
              catch (e) { tell(e instanceof Error ? e.message : String(e)); }
            }}>다시 정리하기</button>
          </div>
        )}
        {recording && !a11y && (
          <p className="caption-line t-caption" aria-live="polite">
            <span className="rec-dot" />
            {loud && <span className="loud-tag">목소리 높임</span>}<span className={`caption-text${perk ? " hot" : ""}`} key={caption.slice(0, 12)}>{caption}</span>
          </p>
        )}
        {recording && a11y && (
          <div className="caption-big" aria-live="polite">
            {(lines.length ? lines : [caption]).map((l, i, arr) => <p key={i} className={i === arr.length - 1 ? "now" : ""}>{l}</p>)}
          </div>
        )}
        <div className="row">
          <div className="grow">
            {notebook ? (
              <span className="t-title-s">{page}번 주제{pageInfo?.text ? `, ${pageInfo.text}` : ""}</span>
            ) : (
              <div className="pager">
                <button onClick={() => goTo(page - 1)} aria-label="이전 쪽"><Icon name="caret-left" size={18} /></button>
                <span className="t-title-s">{page} / {doc.pages.length}</span>
                <button onClick={() => goTo(page + 1)} aria-label="다음 쪽"><Icon name="caret-right" size={18} /></button>
              </div>
            )}
            <span className="t-caption muted" style={{ display: "block" }}>
              {recording ? (notebook ? `필기 쓰는 중, ${page}번 주제` : "필기 쓰는 중") : phase === "ending" ? "마지막 필기를 받는 중…" : phase === "ended" ? (cut ? "녹음이 끊긴 강의예요" : serverStatus?.status === "transcribing" ? `녹음 파일 받아쓰는 중${serverStatus.progress ? ` ${Math.round(serverStatus.progress * 100)}%` : "…"}${serverStatus.engine === "local" ? ", Groq 가 막혀 서버에서 받아쓰는 중이라 느려요" : ""}`
                : serverStatus?.status === "processing" ? "필기·요약 정리 중…" : serverStatus?.status === "failed" ? "정리하지 못했어요" : "강의가 끝났어요") : "버튼을 누르면 녹음을 시작해요"}
            </span>
          </div>
          {sessionId && phase !== "idle" && (
            <button className="round round-soft" onClick={() => setSheet("add")} disabled={photoBusy} aria-label="내 필기 쓰기, 칠판 사진">
              {photoBusy ? <span className="spin" /> : <Icon name="note-pencil" art size={30} />}<span className="tool-label">내 필기</span>
            </button>
          )}
          <input ref={photoInput} type="file" accept="image/*" capture="environment" hidden
            onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) void sendPhoto(f); }} />
          {sessionId && (recording || phase === "ending") && (
            <button className="round round-soft star-btn" onClick={starHere} aria-label="여기 중요 ⭐">
              <Icon name="star" art size={30} /><span className="tool-label">중요</span>
            </button>
          )}
          {recording && (
            <button className="round round-soft confused-btn" onClick={markConfused} aria-label="모르겠어요 (표시만 하고 끝나고 설명)">
              <Icon name="hand-palm" art size={30} />{confused > 0 && <span className="badge">{confused}</span>}<span className="tool-label">모르겠어요</span>
            </button>
          )}
          {sessionId && (recording || phase === "ending") && (
            <button className="round round-soft" onClick={() => setSheet("ask")} disabled={asking} aria-label="방금 뭐라고?">
              {asking ? <span className="spin" /> : <Icon name="chat-circle-dots" art size={30} />}<span className="tool-label">질문</span>
            </button>
          )}
          {phase === "idle" && (
            <div className="idle-lang">
              <EnglishToggle docId={docId} /><IosRecordWarning />
              {presenter && <label className="demo-file">
                <input type="file" accept="audio/*,.m4a,.mp3,.wav,.aac,.ogg,.webm" hidden
                  onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) void start(f); }} />
                <Icon name="play" size={12} /> 발표 시연: 녹음 파일을 실시간 강의처럼 틀기
              </label>}
            </div>
          )}
          {phase === "idle" && <button className="round round-record" onClick={startWithConsent} aria-label="녹음 시작"><Icon name="microphone" art size={46} /><span className="tool-label rec-label">녹음 시작</span></button>}
          {recording && <button className="round round-record on" onClick={() => void stop()} aria-label="강의 끝내기"><span className="stop" /><span className="tool-label rec-label">끝내기</span></button>}
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
            {sheet === "add" && (
              <AddSheet page={page} onSave={addMyNote} onPhoto={() => { setSheet(null); photoInput.current?.click(); }} />
            )}
            {typeof sheet === "object" && "source" in sheet && sessionId && (() => {
              const n = notes.find((x) => x.id === sheet.source);
              return n ? <SourceSheet sessionId={sessionId} note={n} canPlay={player.hasAudio}
                onPlay={() => { setSheet(null); player.playFrom(n.start_ms, n.type === "emphasis" || n.type === "exam" ? 15 : 3); }} /> : null;
            })()}
            {typeof sheet === "object" && "task" in sheet && (() => {
              const t = tasks.find((x) => x.id === sheet.task);
              return t ? <TaskDetail task={t} toast={toast} onChange={(u) => setTasks((all) => all.map((x) => (x.id === u.id ? u : x)))} /> : null;
            })()}
            {sheet === "pdf" && sessionId && <LectureMore sessionId={sessionId} onDeleted={() => go({ name: "doc", docId })} />}
            {typeof sheet === "object" && "edit" in sheet && (() => {
              const n = notes.find((x) => x.id === sheet.edit);
              return n ? <EditNoteSheet note={n} onSave={(t, k) => void saveNote(n, t, k)} onDelete={() => void deleteNote(n)} /> : null;
            })()}
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
              return <p key={i} style={important ? { color: "var(--note-exam-ink)", fontWeight: 700 } : undefined} className="t-body plain-line">{p.replace(/^\[중요\]\s*/, "")}</p>;
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
  // 쪽을 넘긴 방향 (앞으로/뒤로): 그 방향에서 미끄러져 들어오는 모션에 쓴다
  const lastPage = useRef(page?.page_no ?? 1);
  const dir = (page?.page_no ?? 1) >= lastPage.current ? "next" : "prev";
  useEffect(() => { lastPage.current = page?.page_no ?? 1; }, [page?.page_no]);

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
    <div className={`slide turn-${dir}-${page.page_no % 2}`} ref={box} style={{ aspectRatio: `${page.width} / ${page.height}` }}
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
  const meeting = doc.kind === "meeting";
  const MARK: Record<string, string> = meeting
    ? { explanation: "-", example: "근거)", emphasis: "결정)", exam: "!", notice: "일정)", tip: "(+)", qa: "미결)" }
    : { explanation: "-", example: "예)", emphasis: "!", exam: "★", notice: "공지)", tip: "(+)", qa: "Q." };
  return (
    <div className="notebook">
      <header className={`notebook-band${meeting ? " meeting" : ""}`}>
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
              {mine.length === 0 && <p className="t-note faint">{recording && current ? (meeting ? "회의를 듣고 있어요. 결정·할 일이 여기에 써져요." : "교수님 설명을 듣고 있어요. 필기가 여기에 써져요.") : "아직 필기가 없어요"}</p>}
              {mine.map((n) => (
                <p key={n.id} ref={n.id === fresh ? freshRef : undefined} onClick={() => onSelect(selected === n.id ? null : n.id)}
                  className={`t-note nb-line${n.type === "exam" || n.type === "emphasis" ? " note-hl" : ""}${n.preview ? " preview" : ""}${n.id === fresh ? " fresh" : ""}`}>
                  <span className="nb-mark" style={{ color: `var(--note-${n.type}-ink)` }}>{MARK[n.type] ?? "-"}</span> {n.text}
                  {n.photo_id && <img className="nb-photo" src={`${import.meta.env.VITE_API_URL ?? ""}/photos/${n.photo_id}`} alt="칠판 사진" loading="lazy" />}
                </p>
              ))}
            </section>
          );
        })}
      </div>
    </div>
  );
}

/** ＋: 지금 쪽에 내 필기 쓰기, 또는 칠판 사진 */
function AddSheet({ page, onSave, onPhoto }: { page: number; onSave: (text: string, type: string) => void; onPhoto: () => void }) {
  const [text, setText] = useState("");
  const [type, setType] = useState("explanation");
  const kinds = [["explanation", "메모"], ["emphasis", "중요"], ["exam", "시험"], ["example", "예시"], ["qa", "질문"]] as const;
  return (
    <>
      <h3 className="t-title-m">{page}쪽에 내 필기</h3>
      <div className="scroll-x" role="radiogroup" aria-label="필기 종류">
        {kinds.map(([k, label]) => <Chip key={k} variant={type === k ? "selected" : "default"} onClick={() => setType(k)}>{label}</Chip>)}
      </div>
      <textarea className="input draft" style={{ minHeight: 120 }} value={text} onChange={(e) => setText(e.target.value)}
        placeholder="여기에 직접 적어요. AI 필기와 같은 자리에 붙어요" aria-label="내 필기" autoFocus />
      <Button block onClick={() => onSave(text, type)} disabled={!text.trim()}>붙이기</Button>
      <Button block variant="secondary" icon="camera" onClick={onPhoto}>칠판 사진 찍어 붙이기</Button>
    </>
  );
}

/** 근거 보기: 이 필기를 쓸 무렵 교수님이 실제로 한 말 (AI가 지어냈는지 바로 확인) */
function SourceSheet({ sessionId, note, canPlay, onPlay }: { sessionId: string; note: Note; canPlay: boolean; onPlay: () => void }) {
  const [segments, setSegments] = useState<{ start_ms: number; end_ms: number; text: string; page_no: number | null }[] | null>(null);
  useEffect(() => {
    getJSON<NonNullable<typeof segments>>(`/sessions/${sessionId}/transcript`).then(setSegments).catch(() => setSegments([]));
  }, [sessionId]);
  // 필기는 설명이 끝날 무렵 붙으므로 그 앞 40초 ~ 뒤 5초의 말을 보여 준다
  const near = (segments ?? []).filter((s) => s.end_ms >= note.start_ms - 40_000 && s.start_ms <= note.start_ms + 5_000);
  const words = new Set(note.text.replace(/[^\p{L}\p{N}\s]/gu, " ").split(/\s+/).filter((w) => w.length >= 2));
  return (
    <>
      <h3 className="t-title-m">근거 보기</h3>
      <PostIt type={note.type}>{note.text}</PostIt>
      <span className="t-caption muted">이 필기 무렵 교수님이 한 말 {note.edited_by_user ? "· 직접 쓰거나 고친 필기예요" : ""}</span>
      {!segments && <Skeleton />}
      {segments && near.length === 0 && <p className="muted">이 무렵 받아쓴 말이 없어요.</p>}
      <div className="source-list">
        {near.map((s, i) => (
          <p key={i} className="t-body">
            <span className="t-caption faint">{clock(s.start_ms)} </span>
            {s.text.split(/(\s+)/).map((w, j) => words.has(w.replace(/[^\p{L}\p{N}]/gu, "")) ? <mark key={j}>{w}</mark> : w)}
          </p>
        ))}
      </div>
      {canPlay && <Button block variant="secondary" icon="play" onClick={onPlay}>이 부분 녹음 듣기</Button>}
    </>
  );
}

/** 필기 고치기·지우기 */
const KINDS: NoteType[] = ["explanation", "example", "emphasis", "exam", "notice", "tip", "qa"];

/** 필기 고치기: 종류(색) 고르기 · 꾸미기(제목·굵게·형광펜·번호·나열) · 바로 미리 보기 */
function EditNoteSheet({ note, onSave, onDelete }: { note: Note; onSave: (text: string, type: NoteType) => void; onDelete: () => void }) {
  const [text, setText] = useState(note.text);
  const [type, setType] = useState<NoteType>(note.type);
  const box = useRef<HTMLTextAreaElement>(null);
  // 고른 글자를 감싸거나, 고른 줄 앞에 붙인다
  const wrap = (left: string, right = left, empty = "글자") => {
    const el = box.current; if (!el) return;
    const { selectionStart: a, selectionEnd: b } = el;
    const picked = text.slice(a, b) || empty;
    const next = text.slice(0, a) + left + picked + right + text.slice(b);
    setText(next);
    requestAnimationFrame(() => { el.focus(); el.setSelectionRange(a + left.length, a + left.length + picked.length); });
  };
  const lines = (make: (line: string, i: number) => string) => {
    const el = box.current; if (!el) return;
    const start = text.lastIndexOf("\n", el.selectionStart - 1) + 1;
    const endAt = text.indexOf("\n", el.selectionEnd);
    const end = endAt < 0 ? text.length : endAt;
    const block = text.slice(start, end).split("\n").map((l) => l.replace(/^(?:\d+\.\s|·\s)/, "")).map(make).join("\n");
    setText(text.slice(0, start) + block + text.slice(end));
    requestAnimationFrame(() => el.focus());
  };
  const title = () => {
    const first = text.split("\n")[0];
    if (/^[^:\n]{1,28}:\s/.test(first)) return; // 이미 제목이 있다
    setText(text.includes("\n") ? text.replace("\n", ":\n") : `제목: ${text}`);
  };
  const changed = text !== note.text || type !== note.type;
  return (
    <>
      <h3 className="t-title-m">필기 고치기</h3>
      <div className="kind-pick" role="radiogroup" aria-label="필기 종류">
        {KINDS.map((k) => (
          <button key={k} role="radio" aria-checked={type === k} className={`kind-chip${type === k ? " on" : ""}`}
            style={{ "--paper": `var(--note-${k}-paper)`, "--ink": `var(--note-${k}-ink)` } as CSSProperties} onClick={() => setType(k)}>
            {NOTE_LABEL[k]}
          </button>
        ))}
      </div>
      <div className="fmt-bar" aria-label="꾸미기">
        <button onClick={title}><b>제목</b></button>
        <button onClick={() => wrap("**")}><b>굵게</b></button>
        <button onClick={() => wrap("==")}><mark>형광펜</mark></button>
        <button onClick={() => lines((l, i) => `${i + 1}. ${l}`)}>1. 번호</button>
        <button onClick={() => lines((l) => `· ${l}`)}>· 나열</button>
      </div>
      <textarea ref={box} className="input" rows={5} value={text} onChange={(e) => setText(e.target.value)} style={{ padding: 12, resize: "vertical" }} autoFocus />
      <span className="t-caption muted">미리 보기. "제목: 내용"이면 제목이 굵게, 줄마다 "1." 이면 번호 목록이 돼요</span>
      <div className="edit-preview"><PostIt type={type}>{text || " "}</PostIt></div>
      <div className="row">
        <Button className="grow" variant="record" icon="trash" onClick={onDelete}>지우기</Button>
        <Button className="grow" onClick={() => onSave(text, type)} disabled={!text.trim() || !changed}>저장</Button>
      </div>
    </>
  );
}
