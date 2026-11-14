// 1 자료 목록 (Figma "03 디자인 / 1 자료 목록")
import { useEffect, useRef, useState } from "react";
import type { DocumentBrief } from "../api/types";
import { getJSON, postJSON, useApi } from "../api/useApi";
import { android } from "../lib/live";
import { Empty, Icon, ListItem } from "../components/ui";
import { ExamBanner } from "./Semester";
import { Timetable } from "./Timetable";
import { StreakCard } from "./Story";
import { TasksCard } from "./Tasks";
import { Skeleton } from "../lib/motion";
import { courseTone } from "../lib/course";
import { useWaves, Wave } from "../lib/wave";
import { go } from "../router";
import { LuneMark, LuneWordmark } from "../components/Brand";


export function subtitleOf(doc: DocumentBrief): string {
  const lectures = doc.sessions.length ? `강의 ${doc.sessions.length}번` : "아직 강의 없음";
  const kind = doc.kind === "meeting" ? `회의 · 안건 ${doc.page_count}개` : doc.kind === "notebook" ? `노트 · 주제 ${doc.page_count}개` : `슬라이드 ${doc.page_count}쪽`;
  return `${kind} · ${lectures} · ${relativeDay(doc.created_at)}`;
}

export function relativeDay(seconds: number): string {
  const days = Math.floor((Date.now() / 1000 - seconds) / 86400);
  if (days <= 0) return "오늘";
  if (days === 1) return "어제";
  if (days < 7) return `${days}일 전`;
  return new Date(seconds * 1000).toLocaleDateString("ko-KR", { month: "long", day: "numeric" });
}

/** 안드로이드 앱: 매일 저녁 8시 복습·시험 알림 글을 최신 숫자로 맞춰 둔다 */
function useReminder() {
  useEffect(() => {
    const app = android();
    if (!app?.setReminder) return;
    Promise.all([
      getJSON<{ cards: unknown[]; total: number }>("/review/today").catch(() => null),
      getJSON<{ title: string; exam_date: string }[]>("/exams").catch(() => []),
    ]).then(([review, exams]) => {
      const today = new Date().toISOString().slice(0, 10);
      const exam = (exams ?? []).find((e) => e.exam_date >= today);
      const days = exam ? Math.round((new Date(exam.exam_date + "T00:00:00").getTime() - new Date(today + "T00:00:00").getTime()) / 86400000) : null;
      const count = review?.cards.length ?? 0;
      if (!review?.total && !exam) return;
      const title = count ? `오늘 복습 ${count}장이 기다려요` : "오늘 강의 복습할 시간이에요";
      const text = [exam ? `${exam.title} ${days === 0 ? "D-DAY" : `D-${days}`}` : "", "눌러서 바로 복습하기"].filter(Boolean).join(" · ");
      app.setReminder!(title, text, 20, 0);
    });
  }, []);
}

export default function Home() {
  const { data: docs, error, loading, reload } = useApi<DocumentBrief[]>("/documents");
  useReminder();
  const waves = useWaves();
  // 처음 쓰는 사람은 소개 화면부터 (데모가 아닐 때)
  useEffect(() => {
    try { if (!localStorage.getItem("ln.onboarded") && !sessionStorage.getItem("ln.introSeen")) { sessionStorage.setItem("ln.introSeen", "1"); go({ name: "intro" }); } } catch { /* 괜찮다 */ }
  }, []);
  // 과목 폴더: "all" = 전체, "" = 과목 없음, 그 밖에는 과목 이름 (기기에 기억)
  const [filter, setFilter] = useState<string>(() => { try { return localStorage.getItem("ln.course") ?? "all"; } catch { return "all"; } });
  const pick = (c: string) => { setFilter(c); try { localStorage.setItem("ln.course", c); } catch { /* 괜찮다 */ } };
  const [busy, setBusy] = useState<string | null>(null);
  const file = useRef<HTMLInputElement>(null);

  const upload = async (f: File) => {
    setBusy("강의자료를 읽는 중…");
    try {
      const form = new FormData();
      form.append("file", f);
      if (filter !== "all" && filter) form.append("course", filter); // 지금 보는 과목 폴더에 넣는다
      const res = await fetch((import.meta.env.VITE_API_URL ?? "") + "/documents", { method: "POST", body: form });
      const data = await res.json();
      if (!res.ok) throw new Error(data?.detail ?? "올리지 못했어요");
      await reload();
      go({ name: "doc", docId: data.id });
    } catch (e) {
      alert(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  // 강의자료 없이 녹음 파일만: 노트 수업을 만들고 받아쓰기 → 주제별 필기 → 요약까지 서버가 한다
  const audio = useRef<HTMLInputElement>(null);
  const uploadAudio = (f: File) => {
    const form = new FormData();
    form.append("file", f);
    if (filter !== "all" && filter) form.append("course", filter);
    const xhr = new XMLHttpRequest();
    xhr.open("POST", (import.meta.env.VITE_API_URL ?? "") + "/documents/from-audio");
    xhr.upload.onprogress = (e) => { if (e.lengthComputable) setBusy(`녹음 올리는 중 ${Math.round((e.loaded / e.total) * 100)}%`); };
    xhr.onload = () => {
      setBusy(null);
      if (xhr.status >= 300) { alert(`올리지 못했어요 (${xhr.status})`); return; }
      const made = JSON.parse(xhr.responseText) as { document_id: string; session_id: string };
      go({ name: "lecture", docId: made.document_id, sessionId: made.session_id });
    };
    xhr.onerror = () => { setBusy(null); alert("올리지 못했어요. 인터넷 연결을 확인해 주세요."); };
    setBusy("녹음 올리는 중…");
    xhr.send(form);
  };

  // 강의자료에 녹음 파일 붙이기: 그 자료로 강의를 하나 만들고 받아쓰기 → 필기 → 요약
  const uploadToDoc = (docId: string, f: File) => {
    const form = new FormData();
    form.append("document_id", docId);
    form.append("file", f);
    const xhr = new XMLHttpRequest();
    xhr.open("POST", (import.meta.env.VITE_API_URL ?? "") + "/sessions/from-audio");
    xhr.upload.onprogress = (e) => { if (e.lengthComputable) setBusy(`녹음 올리는 중 ${Math.round((e.loaded / e.total) * 100)}%`); };
    xhr.onload = () => {
      setBusy(null);
      if (xhr.status >= 300) { alert(`올리지 못했어요 (${xhr.status})`); return; }
      const made = JSON.parse(xhr.responseText) as { id: string };
      go({ name: "lecture", docId, sessionId: made.id });
    };
    xhr.onerror = () => { setBusy(null); alert("올리지 못했어요. 인터넷 연결을 확인해 주세요."); };
    setBusy("녹음 올리는 중…");
    xhr.send(form);
  };

  // 녹음 시작 / 녹음 올리기 → 어느 강의자료에? (자료 없이도 돼요)
  const [picker, setPicker] = useState<null | "record" | "upload">(null);
  const target = useRef<string | null>(null);
  const audioToDoc = useRef<HTMLInputElement>(null);
  const choose = (docId: string | null) => {
    const mode = picker;
    setPicker(null);
    if (mode === "record") {
      if (docId) go({ name: "lecture", docId }); else void newNotebook("notebook", true);
    } else if (mode === "upload") {
      target.current = docId;
      (docId ? audioToDoc : audio).current?.click();
    }
  };

  const newNotebook = async (kind: "notebook" | "meeting" = "notebook", startNow = false) => {
    const title = prompt(kind === "meeting" ? "회의 이름" : "수업 이름", kind === "meeting" ? "팀 회의" : "새 노트 수업");
    if (title === null) return;
    setBusy("노트를 만드는 중…");
    try {
      const doc = await postJSON<{ id: string }>("/documents/notebook", { title, kind, course: filter !== "all" ? filter : "" });
      go(startNow ? { name: "lecture", docId: doc.id } : { name: "doc", docId: doc.id });
    } catch (e) {
      alert(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const courses = [...new Set((docs ?? []).map((d) => d.course ?? "").filter(Boolean))].sort((a, b) => a.localeCompare(b, "ko"));
  const hasLoose = (docs ?? []).some((d) => !d.course);
  const shown = (docs ?? []).filter((d) => filter === "all" || (d.course ?? "") === filter);
  // 전체 보기에서는 과목별로 묶어 보여 준다
  const groups: [string, DocumentBrief[]][] = filter === "all"
    ? [...courses.map((c) => [c, shown.filter((d) => d.course === c)] as [string, DocumentBrief[]]), ["", shown.filter((d) => !d.course)] as [string, DocumentBrief[]]]
        .filter(([, list]) => list.length > 0)
    : [[filter, shown]];

  return (
    <div className="screen">
      <header className="home-head">
        <div className="row">
          <span className="home-brand grow"><LuneMark size={30} /><LuneWordmark height={19} /></span>
          <button className="top-bar-back" onClick={() => go({ name: "search" })} aria-label="모든 강의에서 찾기"><Icon name="magnifying-glass" /></button>
          <button className="top-bar-back" onClick={() => go({ name: "privacy" })} aria-label="설정"><Icon name="gear" /></button>
        </div>
      </header>
      <div className="screen-body">
        <Timetable courses={courses} onPick={pick} />

        {/* 이 앱의 중심: 강의자료에 녹음을 붙인다 (지금 녹음하거나, 녹음 파일을 올리거나) */}
        <section className="record-hub" aria-label="강의 녹음">
          <button className="record-main" onClick={() => setPicker("record")} disabled={!!busy}>
            <span className="record-ic"><Icon name="microphone" art size={34} /></span>
            <span><b>수업 녹음 시작</b><small>들으면서 강의자료에 필기가 붙어요</small></span>
          </button>
          <button className="record-main alt" onClick={() => setPicker("upload")} disabled={!!busy}>
            <span className="record-ic"><Icon name="upload-simple" art size={34} /></span>
            <span><b>녹음 파일 올리기</b><small>{busy ?? "이미 녹음한 수업을 정리해요"}</small></span>
          </button>
          <button className="record-add" onClick={() => file.current?.click()} disabled={!!busy}>
            <Icon name="plus" size={16} /> 강의자료 올리기 <small>PDF · PPT · 한글</small>
          </button>
        </section>
        <input ref={file} type="file" accept="application/pdf,.pdf,.ppt,.pptx,.key,.odp,.doc,.docx,.hwp,.hwpx" hidden
          onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) void upload(f); }} />
        <input ref={audio} type="file" accept="audio/*,.m4a,.mp3,.wav,.aac,.ogg,.webm" hidden
          onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) uploadAudio(f); }} />
        <input ref={audioToDoc} type="file" accept="audio/*,.m4a,.mp3,.wav,.aac,.ogg,.webm" hidden
          onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f && target.current) uploadToDoc(target.current, f); }} />

        <h2 className="section-title">내 강의</h2>
        {courses.length > 0 && (
          <div className="picks" role="group" aria-label="과목">
            <button className={`pick${filter === "all" ? " on" : ""}`} aria-pressed={filter === "all"} onClick={() => pick("all")}>전체</button>
            {courses.map((c) => (
              <button key={c} className={`pick ${courseTone(c)}${filter === c ? " on" : ""}`} aria-pressed={filter === c} onClick={() => pick(c)}><i />{c}</button>
            ))}
            {hasLoose && <button className={`pick${filter === "" ? " on" : ""}`} aria-pressed={filter === ""} onClick={() => pick("")}>과목 없음</button>}
          </div>
        )}
        {loading && !docs && <Skeleton lines={4} />}
        {error && <Empty icon="warning-circle">서버에 연결할 수 없어요<br /><span className="t-caption">{error}</span></Empty>}
        {docs && shown.length === 0 && (
          <Empty icon="notebook">
            <strong className="t-title-s">아직 강의가 없어요</strong><br />
            위에서 강의자료를 올리고 수업을 녹음해 보세요.<br />녹음 파일만 있어도 돼요.
          </Empty>
        )}
        {groups.map(([course, list]) => (
          <section key={course || "-"} className="course-group">
            {(filter === "all" && courses.length > 0) && (
              <h3 className={`course-title ${courseTone(course)}`}><span>{course || "과목 없음"}</span> <small>{list.length}</small></h3>
            )}
            {list.map((doc, i) => (
              <ListItem key={doc.id} index={i} tone={courseTone(doc.course)} art={doc.sessions[0] && waves[doc.sessions[0].id]?.w ? <Wave data={waves[doc.sessions[0].id]} /> : undefined} icon={doc.kind === "meeting" ? "users" : doc.kind === "notebook" ? "notebook" : "file-pdf"} title={doc.title}
                subtitle={subtitleOf(doc)} onClick={() => go({ name: "doc", docId: doc.id })} />
            ))}
          </section>
        ))}

        <h2 className="section-title">공부 · 시험</h2>
        <div className="tiles">
          <Tile icon="calendar" title="오늘의 복습" sub="잊기 전에 다시" onClick={() => go({ name: "review" })} />
          <Tile icon="target" title="시험 준비" sub="D-day · 족보 노트" onClick={() => go({ name: "semester", tab: "exams" })} />
          <Tile icon="chats-circle" title="AI에게 묻기" sub="모든 강의에서" onClick={() => go({ name: "semester", tab: "tutor" })} />
          <Tile icon="tree-structure" title="학기 전체" sub="개념 지도" onClick={() => go({ name: "semester", tab: "map" })} />
        </div>
        <ExamBanner />
        <TasksCard />
        <StreakCard />

        {picker && (
          <>
            <div className="sheet-bg" onClick={() => setPicker(null)} />
            <div className="sheet" role="dialog" aria-modal="true" aria-label="강의자료 고르기">
              <h3 className="t-title-m">{picker === "record" ? "어느 강의자료로 녹음할까요?" : "어느 강의자료에 녹음을 붙일까요?"}</h3>
              <p className="t-caption muted">강의자료를 고르면 필기가 그 쪽 옆에 붙어요</p>
              {(docs ?? []).filter((d) => d.kind !== "meeting").map((d) => (
                <ListItem key={d.id} icon={d.kind === "notebook" ? "notebook" : "file-pdf"} title={d.title} subtitle={subtitleOf(d)} onClick={() => choose(d.id)} />
              ))}
              <ListItem icon="note-pencil" title="강의자료 없이" subtitle="주제가 바뀔 때마다 노트를 나눠서 정리해요" onClick={() => choose(null)} />
              {picker === "record" && (
                <ListItem icon="users" title="회의 기록" subtitle="결정·할 일·일정을 회의록으로" onClick={() => { setPicker(null); void newNotebook("meeting", true); }} />
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

/** 보라 배너: 인사 + 오늘의 복습 (참고 디자인의 "오늘도 수고했어요!") */
function Tile({ icon, title, sub, onClick }: { icon: string; title: string; sub: string; onClick: () => void }) {
  return (
    <button className="tile" onClick={onClick}>
      <Icon name={icon} art size={30} />
      <span><b>{title}</b><small>{sub}</small></span>
    </button>
  );
}
