// 자료 상세: 강의(녹음) 목록과 수업 시작, 시험 예상 지도로 가는 곳
import { useRef, useState } from "react";
import { useWaves, Wave } from "../lib/wave";
import { EnglishToggle, lectureLang } from "../components/EnglishToggle";
import type { DocumentBrief } from "../api/types";
import { useApi } from "../api/useApi";
import { Chip, Empty, Icon, TopBar } from "../components/ui";
import { courseTone } from "../lib/course";
import { getJSON } from "../api/useApi";
import { useEffect } from "react";
import { back, go } from "../router";
import { subtitleOf } from "./Home";
import { askText, askYes, tell } from "../components/Dialog";

// 강의 진행 단계: 녹음 → 받아쓰기 → 정리 → 끝
const STEP: Record<string, number> = { recording: 0, transcribing: 1, processing: 2, done: 3, failed: -1 };
const STATUS: Record<string, string> = { recording: "녹음 중", transcribing: "받아쓰는 중", processing: "정리 중", done: "정리 끝", failed: "정리 실패" };
const API = import.meta.env.VITE_API_URL ?? "";

export default function DocDetail({ docId }: { docId: string }) {
  const waves = useWaves();
  // 약점 노트에 모인 수 (시험 준비 칸에 실제 숫자로)
  const [weakN, setWeakN] = useState<number | null>(null);
  useEffect(() => { getJSON<{ items?: unknown[] } | unknown[]>(`/documents/${docId}/weak`).then((r) => setWeakN(Array.isArray(r) ? r.length : (r.items?.length ?? 0))).catch(() => setWeakN(null)); }, [docId]);
  // 목록 API에 강의 목록이 같이 오므로 그것을 쓴다
  const { data: docs, error, reload: reloadDocs } = useApi<DocumentBrief[]>("/documents");
  const doc = docs?.find((d) => d.id === docId);
  const [upload, setUpload] = useState<string | null>(null);
  const [menu, setMenu] = useState(false);
  const audioInput = useRef<HTMLInputElement>(null);

  // '음성 메모' 등으로 녹음해 둔 파일 → 서버가 받아쓰고 필기·요약까지. 큰 파일이라 올라가는 정도를 보여 주려고 XHR을 쓴다
  const sendAudio = (file: File) => {
    const form = new FormData();
    form.append("document_id", docId);
    form.append("language", lectureLang(docId));
    form.append("file", file);
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API}/sessions/from-audio`);
    xhr.upload.onprogress = (e) => { if (e.lengthComputable) setUpload(`올리는 중… ${Math.round((e.loaded / e.total) * 100)}%`); };
    xhr.onload = () => {
      setUpload(null);
      if (xhr.status >= 300) return tell(`올리지 못했어요 (${xhr.status})`);
      go({ name: "lecture", docId, sessionId: JSON.parse(xhr.responseText).id });
    };
    xhr.onerror = () => { setUpload(null); tell("올리지 못했어요. 인터넷 연결을 확인해 주세요."); };
    setUpload("올리는 중…");
    xhr.send(form);
  };

  const remove = async () => {
    if (!await askYes("이 강의자료를 휴지통으로 옮길까요? 7일 안에는 설정 › 휴지통에서 되살릴 수 있어요.")) return;
    const res = await fetch(`${API}/documents/${docId}`, { method: "DELETE" });
    if (res.ok) go({ name: "home" }); else tell("지우지 못했어요");
  };

  return (
    <div className="screen">
      <TopBar title={doc?.title ?? "강의"} onBack={() => back({ name: "home" })}
        action={doc && (
          <div className="top-menu">
            <button className="top-bar-back" onClick={() => setMenu(!menu)} aria-label="더보기" aria-expanded={menu}><Icon name="dots-three-outline" /></button>
            {menu && <>
              <div className="top-menu-bg" onClick={() => setMenu(false)} />
              <div className="top-menu-list" role="menu">
                <button role="menuitem" className="danger" onClick={() => { setMenu(false); void remove(); }}><Icon name="trash" size={16} /> 휴지통으로 옮기기</button>
              </div>
            </>}
          </div>
        )} />
      <div className="screen-body">
        {error && <Empty icon="warning-circle">{error}</Empty>}
        {docs && !doc && <Empty icon="warning">자료를 찾을 수 없어요</Empty>}
        {doc && (
          <>
            <div className="row" style={{ flexWrap: "wrap", gap: 8 }}>
              <span className="t-caption muted grow">{subtitleOf(doc)}</span>
              <Chip variant="accent" onClick={async () => {
                const course = await askText("과목 이름 (비우면 과목 없음)", doc.course ?? "");
                if (course === null) return;
                await fetch(`${API}/documents/${docId}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ course }) });
                reloadDocs();
              }}>{doc.course ? doc.course : "과목 정하기"}</Chip>
            </div>
            <OcrProgress docId={docId} />
            {/* 이 자료로 할 일은 두 가지: 지금 녹음하거나, 녹음 파일을 붙이거나 */}
            <div className="record-hub two">
              <button className="record-main" onClick={() => go({ name: "lecture", docId })}>
                <span className="record-ic"><Icon name="microphone" art size={32} /></span>
                <span><b>{doc.kind === "meeting" ? "회의 기록" : "수업 녹음"}</b></span>
              </button>
              <button className="record-main alt" onClick={() => !upload && audioInput.current?.click()}>
                <span className="record-ic"><Icon name="upload-simple" art size={32} /></span>
                <span><b>녹음 파일</b>{upload && <small>{upload}</small>}</span>
              </button>
            </div>
            <EnglishToggle docId={docId} />
            <input ref={audioInput} type="file" accept="audio/*,.m4a,.mp3,.wav" hidden
              onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) sendAudio(f); }} />

            <h2 className="t-title-s section-title">강의 {doc.sessions.length}개</h2>
            {doc.sessions.length === 0 && <p className="muted">아직 녹음한 강의가 없어요. 위에서 녹음을 시작하거나 올려 주세요.</p>}
            {doc.sessions.map((s, i) => (
              <button key={s.id} className={`lec-row ${courseTone(doc.course)}`} style={{ animationDelay: `${i * 50}ms` }}
                onClick={() => go(s.status === "failed" ? { name: "lecture", docId, sessionId: s.id } : { name: "session", docId, sessionId: s.id, tab: "notes" })}>
                <span className="lec-no">{String(doc.sessions.length - i).padStart(2, "0")}</span>
                <span className="lec-main">
                  <b>{new Date(s.started_at * 1000).toLocaleString("ko-KR", { month: "long", day: "numeric", weekday: "short" })}</b>
                  <small>{new Date(s.started_at * 1000).toLocaleTimeString("ko-KR", { hour: "numeric", minute: "2-digit" })} · {STATUS[s.status] ?? s.status}</small>
                  <span className="lec-steps" aria-hidden="true">{[0, 1, 2, 3].map((k) => <i key={k} className={k <= (STEP[s.status] ?? 0) ? "on" : ""} />)}</span>
                </span>
                <Wave data={waves[s.id]} bars={14} className="lec-wave" />
              </button>
            ))}

            {doc.kind !== "meeting" && doc.sessions.length > 0 && (
              <>
                <h2 className="t-title-s section-title">시험 준비</h2>
                <div className="prep">
                  <button className="prep-main" onClick={() => go({ name: "jokbo", docId })}>
                    <b>족보 노트</b>
                    <i className="prep-go"><Icon name="arrow-right" size={18} /></i>
                  </button>
                  <button className="prep-sub quiz" onClick={() => go({ name: "quiz", docId })}><b>퀴즈</b></button>
                  <button className="prep-sub weak" onClick={() => go({ name: "weak", docId })}><b>약점 노트</b>{weakN != null && <em>{weakN ? `${weakN}개 모였어요` : "아직 없어요"}</em>}</button>
                </div>
                <button className="link-row" onClick={() => { window.location.href = `${API}/documents/${docId}/anki.txt`; }}>
                  <Icon name="export" size={16} /> Anki 로 내보내기
                </button>
              </>
            )}
          </>
        )}
      </div>
    </div>
  );
}

/** 스캔본·그림 슬라이드: 서버가 쪽마다 글자를 읽는 동안 진행을 보여 준다 */
function OcrProgress({ docId }: { docId: string }) {
  const [state, setState] = useState<{ status: string; done: number; total: number } | null>(null);
  useEffect(() => {
    let alive = true;
    let timer: number | undefined;
    const poll = () => getJSON<typeof state>(`/documents/${docId}/ocr`).then((s) => {
      if (!alive || !s) return;
      setState(s);
      if (s.status === "reading") timer = window.setTimeout(poll, 2000);
    }).catch(() => {});
    void poll();
    return () => { alive = false; window.clearTimeout(timer); };
  }, [docId]);
  if (!state || state.status !== "reading") return null;
  return <p className="t-caption" style={{ color: "var(--accent-primary)" }}><span className="spin" /> 그림으로 된 쪽의 글자를 읽는 중 {state.done}/{state.total}쪽. 다 읽으면 쪽 추적이 잘 돼요</p>;
}
