// 1 자료 목록 (Figma "03 디자인 / 1 자료 목록")
import { useEffect, useRef, useState } from "react";
import type { DocumentBrief } from "../api/types";
import { getJSON, postJSON, useApi } from "../api/useApi";
import { android } from "../lib/live";
import { Button, Chip, Empty, Icon, ListItem } from "../components/ui";
import { ReviewBanner } from "./ExamPrep";
import { ExamBanner } from "./Semester";
import { Timetable } from "./Timetable";
import { StreakCard } from "./Story";
import { TasksCard } from "./Tasks";
import { Skeleton } from "../lib/motion";
import { courseTone } from "../lib/course";
import { useWaves, Wave } from "../lib/wave";
import { go } from "../router";


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

/** 시간대에 맞는 인사 */
function greeting(now = new Date()): string {
  const h = now.getHours();
  if (h < 6) return "늦은 밤이에요";
  if (h < 11) return "좋은 아침이에요";
  if (h < 14) return "점심은 먹었어요?";
  if (h < 18) return "오후 수업도 힘내요";
  if (h < 23) return "오늘 배운 것, 복습할까요?";
  return "오늘도 수고했어요";
}

export default function Home() {
  const { data: docs, error, loading, reload } = useApi<DocumentBrief[]>("/documents");
  useReminder();
  const waves = useWaves();
  // 처음 쓰는 사람은 소개 화면부터 (데모가 아닐 때)
  useEffect(() => {
    try { if (!localStorage.getItem("ln.onboarded") && !sessionStorage.getItem("ln.introSeen")) { sessionStorage.setItem("ln.introSeen", "1"); go({ name: "intro" }); } } catch { /* 괜찮다 */ }
  }, []);
  const line = greeting();
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

  const newNotebook = async (kind: "notebook" | "meeting" = "notebook") => {
    const title = prompt(kind === "meeting" ? "회의 이름" : "수업 이름", kind === "meeting" ? "팀 회의" : "새 노트 수업");
    if (title === null) return;
    setBusy("노트를 만드는 중…");
    try {
      const doc = await postJSON<{ id: string }>("/documents/notebook", { title, kind, course: filter !== "all" ? filter : "" });
      go({ name: "doc", docId: doc.id });
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
  const today = new Date().toLocaleDateString("ko-KR", { month: "long", day: "numeric", weekday: "long" });

  return (
    <div className="screen">
      <header className="home-head">
        <div className="row">
          <span className="t-caption muted grow">{today}</span>
          <button className="top-bar-back" onClick={() => go({ name: "intro" })} aria-label="소개 다시 보기"><Icon name="sparkle" /></button>
          <button className="top-bar-back" onClick={() => go({ name: "search" })} aria-label="모든 강의에서 찾기"><Icon name="book-open-text" /></button>
          <button className="top-bar-back" onClick={() => go({ name: "privacy" })} aria-label="개인정보와 녹음"><Icon name="shield-check" /></button>
        </div>
        <h1 className="hero-title">{line}</h1>
      </header>
      <div className="screen-body">
        <Timetable courses={courses} onPick={pick} />
        {/* 과목 고르기: 과목마다 정해진 블록 색 */}
        <div className="picks" role="group" aria-label="과목">
          <button className={`pick${filter === "all" ? " on" : ""}`} aria-pressed={filter === "all"} onClick={() => pick("all")}>전체</button>
          {courses.map((c) => (
            <button key={c} className={`pick ${courseTone(c)}${filter === c ? " on" : ""}`} aria-pressed={filter === c} onClick={() => pick(c)}><i />{c}</button>
          ))}
          {hasLoose && courses.length > 0 && <button className={`pick${filter === "" ? " on" : ""}`} aria-pressed={filter === ""} onClick={() => pick("")}>과목 없음</button>}
        </div>
        <StreakCard />
        <TasksCard />
        <ExamBanner />
        <ReviewBanner />
        <div className="row home-shortcuts">
          <Chip variant="accent" onClick={() => go({ name: "semester", tab: "map" })}>개념 지도</Chip>
          <Chip variant="accent" onClick={() => go({ name: "semester", tab: "tutor" })}>학기 튜터</Chip>
          <Chip variant="accent" onClick={() => go({ name: "semester", tab: "exams" })}>시험 D-day</Chip>
          <Chip variant="accent" onClick={() => void newNotebook("meeting")}>회의 기록</Chip>
        </div>
        {loading && !docs && <Skeleton lines={4} />}
        {error && <Empty icon="warning-circle">서버에 연결할 수 없어요<br /><span className="t-caption">{error}</span></Empty>}
        {docs && shown.length === 0 && (
          <Empty icon="chalkboard-teacher">
            <strong className="t-title-s">아직 강의가 없어요</strong><br />
            강의자료 PDF를 올리거나, 자료 없는 수업은 노트로 시작하세요.<br />녹음 파일만 있어도 돼요: 아래 "녹음"을 눌러 올리면 주제별로 정리해 드려요.
          </Empty>
        )}
        {groups.map(([course, list]) => (
          <section key={course || "-"} className="course-group">
            {(filter === "all" && courses.length > 0) && (
              <h2 className={`course-title ${courseTone(course)}`}><span>{course || "과목 없음"}</span> <small>{list.length}</small></h2>
            )}
            {list.map((doc, i) => (
              <ListItem key={doc.id} index={i} tone={courseTone(doc.course)} art={doc.sessions[0] ? <Wave data={waves[doc.sessions[0].id]} /> : undefined} icon={doc.kind === "meeting" ? "users" : doc.kind === "notebook" ? "notebook" : "file-pdf"} title={doc.title}
                subtitle={subtitleOf(doc)} onClick={() => go({ name: "doc", docId: doc.id })} />
            ))}
          </section>
        ))}
      </div>
      <div className="home-actions">
        <Button variant="secondary" icon="note-pencil" onClick={() => newNotebook()} disabled={!!busy}>노트 수업</Button>
        <Button variant="secondary" icon="headphones" onClick={() => audio.current?.click()} disabled={!!busy} aria-label="녹음 파일만 올리기">녹음 파일</Button>
        <input ref={audio} type="file" accept="audio/*,.m4a,.mp3,.wav,.aac,.ogg,.webm" hidden
          onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) uploadAudio(f); }} />
        <Button icon="tray-arrow-down" onClick={() => file.current?.click()} disabled={!!busy}>{busy ?? "강의자료"}</Button>
        <input ref={file} type="file" accept="application/pdf,.pdf,.ppt,.pptx,.key,.odp,.doc,.docx,.hwp,.hwpx" hidden
          onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) void upload(f); }} />
      </div>
    </div>
  );
}
