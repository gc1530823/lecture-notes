// 자료 상세: 강의(녹음) 목록과 수업 시작, 시험 예상 지도로 가는 곳
import { useRef, useState } from "react";
import { EnglishToggle, lectureLang } from "../components/EnglishToggle";
import type { DocumentBrief } from "../api/types";
import { useApi } from "../api/useApi";
import { Chip, Empty, Icon, ListItem, TopBar } from "../components/ui";
import { courseTone } from "../lib/course";
import { useWaves, Wave } from "../lib/wave";
import { getJSON } from "../api/useApi";
import { useEffect } from "react";
import { back, go } from "../router";
import { subtitleOf } from "./Home";

const STATUS: Record<string, string> = { recording: "녹음 중", transcribing: "받아쓰는 중", processing: "정리 중", done: "정리 끝", failed: "정리 실패" };
const API = import.meta.env.VITE_API_URL ?? "";

export default function DocDetail({ docId }: { docId: string }) {
  // 목록 API에 강의 목록이 같이 오므로 그것을 쓴다
  const { data: docs, error, reload: reloadDocs } = useApi<DocumentBrief[]>("/documents");
  const waves = useWaves();
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
      if (xhr.status >= 300) return alert(`올리지 못했어요 (${xhr.status})`);
      go({ name: "lecture", docId, sessionId: JSON.parse(xhr.responseText).id });
    };
    xhr.onerror = () => { setUpload(null); alert("올리지 못했어요. 인터넷 연결을 확인해 주세요."); };
    setUpload("올리는 중…");
    xhr.send(form);
  };

  const remove = async () => {
    if (!confirm("이 강의자료와 지난 강의 필기를 모두 지울까요? 되돌릴 수 없어요.")) return;
    const res = await fetch(`${API}/documents/${docId}`, { method: "DELETE" });
    if (res.ok) go({ name: "home" }); else alert("지우지 못했어요");
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
                <button role="menuitem" className="danger" onClick={() => { setMenu(false); void remove(); }}><Icon name="trash" size={16} /> 강의자료와 강의 모두 지우기</button>
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
                const course = prompt("과목 이름 (비우면 과목 없음)", doc.course ?? "");
                if (course === null) return;
                await fetch(`${API}/documents/${docId}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ course }) });
                reloadDocs();
              }}>{doc.course ? `과목 · ${doc.course}` : "과목 정하기"}</Chip>
            </div>
            <OcrProgress docId={docId} />
            {/* 이 자료로 할 일은 두 가지: 지금 녹음하거나, 녹음 파일을 붙이거나 */}
            <div className="record-hub two">
              <button className="record-main" onClick={() => go({ name: "lecture", docId })}>
                <span className="record-ic"><Icon name="microphone" art size={32} /></span>
                <span><b>{doc.kind === "meeting" ? "회의 기록 시작" : "수업 녹음 시작"}</b><small>필기가 이 자료 위에 붙어요</small></span>
              </button>
              <button className="record-main alt" onClick={() => !upload && audioInput.current?.click()}>
                <span className="record-ic"><Icon name="upload-simple" art size={32} /></span>
                <span><b>녹음 파일 올리기</b><small>{upload ?? "녹음한 수업을 정리해요"}</small></span>
              </button>
            </div>
            <EnglishToggle docId={docId} />
            <input ref={audioInput} type="file" accept="audio/*,.m4a,.mp3,.wav" hidden
              onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) sendAudio(f); }} />

            <h2 className="t-title-s section-title">강의 {doc.sessions.length}개</h2>
            {doc.sessions.length === 0 && <p className="muted">아직 녹음한 강의가 없어요. 위에서 녹음을 시작하거나 올려 주세요.</p>}
            {doc.sessions.map((s, i) => (
              <ListItem key={s.id} icon="headphones" tone={courseTone(doc.course)} art={waves[s.id]?.w ? <Wave data={waves[s.id]} /> : undefined}
                title={new Date(s.started_at * 1000).toLocaleString("ko-KR", { month: "long", day: "numeric", weekday: "short", hour: "numeric", minute: "2-digit" })}
                subtitle={`${doc.sessions.length - i}번째 강의 · ${STATUS[s.status] ?? s.status}`}
                onClick={() => go(s.status === "failed" ? { name: "lecture", docId, sessionId: s.id } : { name: "session", docId, sessionId: s.id, tab: "notes" })} />
            ))}

            {doc.kind !== "meeting" && doc.sessions.length > 0 && (
              <>
                <h2 className="t-title-s section-title">시험 준비 <span className="t-caption faint">이 자료의 모든 강의로</span></h2>
                <ListItem icon="star" title="족보 노트" subtitle="시험에 나온다고 한 것 · 유력한 쪽 · 헷갈린 것 · 예상 문제를 한 장에"
                  onClick={() => go({ name: "jokbo", docId })} />
                <ListItem icon="brain" title="AI 퀴즈" subtitle="AI 가 이 자료와 강의를 공부하고 문제를 내요 · 바로 채점"
                  onClick={() => go({ name: "quiz", docId })} />
                <ListItem icon="target" title="약점 노트" subtitle="퀴즈에서 틀린 문제 · 수업 중 헷갈린 곳 · 복습에서 자주 틀린 것"
                  onClick={() => go({ name: "weak", docId })} />
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
  return <p className="t-caption" style={{ color: "var(--accent-primary)" }}><span className="spin" /> 그림으로 된 쪽의 글자를 읽는 중 {state.done}/{state.total}쪽 · 다 읽으면 쪽 추적이 잘 돼요</p>;
}
