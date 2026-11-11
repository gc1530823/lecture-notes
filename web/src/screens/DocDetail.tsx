// 자료 상세: 강의(녹음) 목록과 수업 시작, 시험 예상 지도로 가는 곳
import { useRef, useState } from "react";
import type { DocumentBrief } from "../api/types";
import { useApi } from "../api/useApi";
import { Button, Chip, Empty, Icon, ListItem, TopBar } from "../components/ui";
import { getJSON } from "../api/useApi";
import { useEffect } from "react";
import { go } from "../router";
import { subtitleOf } from "./Home";

const STATUS: Record<string, string> = { recording: "녹음 중", transcribing: "받아쓰는 중", processing: "정리 중", done: "정리 끝", failed: "정리 실패" };
const API = import.meta.env.VITE_API_URL ?? "";

export default function DocDetail({ docId }: { docId: string }) {
  // 목록 API에 강의 목록이 같이 오므로 그것을 쓴다
  const { data: docs, error, reload: reloadDocs } = useApi<DocumentBrief[]>("/documents");
  const doc = docs?.find((d) => d.id === docId);
  const [upload, setUpload] = useState<string | null>(null);
  const audioInput = useRef<HTMLInputElement>(null);

  // '음성 메모' 등으로 녹음해 둔 파일 → 서버가 받아쓰고 필기·요약까지. 큰 파일이라 올라가는 정도를 보여 주려고 XHR을 쓴다
  const sendAudio = (file: File) => {
    const form = new FormData();
    form.append("document_id", docId);
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
      <TopBar title={doc?.title ?? "강의"} onBack={() => go({ name: "home" })}
        action={doc && <button className="top-bar-back" onClick={remove} aria-label="강의자료 지우기"><Icon name="trash" /></button>} />
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
            <Button block variant="record" icon="microphone" onClick={() => go({ name: "lecture", docId })}>
              {doc.kind === "meeting" ? "회의 기록 시작" : "수업 시작"}
            </Button>
            <ListItem icon="headphones" title={upload ?? "녹음 파일로 정리하기"}
              subtitle="'음성 메모'로 녹음한 파일을 올리면 화면을 꺼 둔 수업도 필기·요약·퀴즈로 만들어요"
              onClick={() => !upload && audioInput.current?.click()} />
            <input ref={audioInput} type="file" accept="audio/*,.m4a,.mp3,.wav" hidden
              onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) sendAudio(f); }} />
            {doc.kind !== "meeting" && <>
            <ListItem icon="cards" title="Anki로 내보내기" subtitle="플래시카드·예상 문제·용어를 Anki 앱에서 가져올 수 있는 파일로 (파일 › 가져오기)"
              onClick={() => { window.location.href = `${API}/documents/${docId}/anki.txt`; }} />
            <ListItem icon="star" title="족보 노트" subtitle="모든 강의에서 시험에 나온다고 한 것·유력한 쪽·헷갈린 것·예상 문제를 한 장에"
              onClick={() => go({ name: "jokbo", docId })} />
            </>}
            {doc.kind === "slides" && (
              <ListItem icon="target" title="시험 예상 지도" subtitle="여러 강의에서 교수님이 강조한 쪽을 모아 봐요"
                onClick={() => go({ name: "exam", docId })} />
            )}
            <h2 className="t-title-s section-title">지난 강의</h2>
            {doc.sessions.length === 0 && <p className="muted">아직 녹음한 강의가 없어요.</p>}
            {doc.sessions.map((s, i) => (
              <ListItem key={s.id} icon="headphones"
                title={new Date(s.started_at * 1000).toLocaleString("ko-KR", { month: "long", day: "numeric", weekday: "short", hour: "numeric", minute: "2-digit" })}
                subtitle={`${doc.sessions.length - i}번째 강의 · ${STATUS[s.status] ?? s.status}`}
                onClick={() => go({ name: "session", docId, sessionId: s.id, tab: "notes" })} />
            ))}
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
