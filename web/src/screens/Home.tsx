// 1 자료 목록 (Figma "03 디자인 / 1 자료 목록")
import { useEffect, useRef, useState } from "react";
import type { DocumentBrief } from "../api/types";
import { getJSON, postJSON, useApi } from "../api/useApi";
import { android } from "../lib/live";
import { Button, Empty, Icon, ListItem } from "../components/ui";
import { ExamBanner } from "./Semester";
import { Timetable } from "./Timetable";
import { StreakCard } from "./Story";
import { TasksCard } from "./Tasks";
import { Skeleton } from "../lib/motion";
import { courseTone } from "../lib/course";
import { useWaves, Wave } from "../lib/wave";
import { go } from "../router";
import { play } from "../lib/sound";
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
  const latestSlides = (docs ?? []).find((d) => d.kind === "slides");

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
        <HeroCarousel line={line} quizDoc={latestSlides} />
        <div className="tiles">
          <Tile icon="calendar" title="오늘의 복습" sub="망각 곡선" onClick={() => go({ name: "review" })} />
          <Tile icon="star" title="족보 노트" sub="시험 핵심 정리" onClick={() => latestSlides ? go({ name: "jokbo", docId: latestSlides.id }) : alert("강의자료를 먼저 올려 주세요")} />
          <Tile icon="hand-palm" title="시험 D-day" sub="남은 날과 계획" onClick={() => go({ name: "semester", tab: "exams" })} />
          <Tile icon="target" title="시험 예상 지도" sub="예상 문제" onClick={() => latestSlides ? go({ name: "exam", docId: latestSlides.id }) : alert("강의자료를 먼저 올려 주세요")} />
          <Tile icon="chats-circle" title="AI 튜터" sub="질문하기" onClick={() => go({ name: "semester", tab: "tutor" })} />
          <Tile icon="tree-structure" title="개념 지도" sub="학기 전체" onClick={() => go({ name: "semester", tab: "map" })} />
        </div>
        <Timetable courses={courses} onPick={pick} />
        {/* 과목 고르기: 과목마다 정해진 블록 색 */}
        <div className="picks" role="group" aria-label="과목">
          <button className={`pick${filter === "all" ? " on" : ""}`} aria-pressed={filter === "all"} onClick={() => pick("all")}>전체</button>
          {courses.map((c) => (
            <button key={c} className={`pick ${courseTone(c)}${filter === c ? " on" : ""}`} aria-pressed={filter === c} onClick={() => pick(c)}><i />{c}</button>
          ))}
          {hasLoose && courses.length > 0 && <button className={`pick${filter === "" ? " on" : ""}`} aria-pressed={filter === ""} onClick={() => pick("")}>과목 없음</button>}
        </div>
        <ExamBanner />
        <TasksCard />
        <StreakCard />
        <div className="row">
          <h2 className="section-title grow">내 강의</h2>
          <button className="chip chip-default" onClick={() => void newNotebook("meeting")}>회의 기록</button>
        </div>
        {loading && !docs && <Skeleton lines={4} />}
        {error && <Empty icon="warning-circle">서버에 연결할 수 없어요<br /><span className="t-caption">{error}</span></Empty>}
        {docs && shown.length === 0 && (
          <Empty icon="notebook">
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
              <ListItem key={doc.id} index={i} tone={courseTone(doc.course)} art={doc.sessions[0] && waves[doc.sessions[0].id]?.w ? <Wave data={waves[doc.sessions[0].id]} /> : undefined} icon={doc.kind === "meeting" ? "users" : doc.kind === "notebook" ? "notebook" : "file-pdf"} title={doc.title}
                subtitle={subtitleOf(doc)} onClick={() => go({ name: "doc", docId: doc.id })} />
            ))}
          </section>
        ))}
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
    </div>
  );
}

/** 보라 배너: 인사 + 오늘의 복습 (참고 디자인의 "오늘도 수고했어요!") */
/** 맨 위 배너: 옆으로 밀어 넘기는 카드 (복습 · 시험 D-day · AI 퀴즈). 가만히 두면 6초마다 저절로 넘어간다 */
function HeroCarousel({ line, quizDoc }: { line: string; quizDoc?: DocumentBrief }) {
  const [count, setCount] = useState<number | null>(null);
  const [exam, setExam] = useState<{ title: string; days: number } | null>(null);
  const [at, setAt] = useState(0);
  const track = useRef<HTMLDivElement>(null);
  const touched = useRef(false);
  useEffect(() => {
    getJSON<{ cards: unknown[] }>("/review/today").then((t) => setCount(t.cards.length)).catch(() => setCount(null));
    getJSON<{ title: string; exam_date: string }[]>("/exams").then((list) => {
      const today = new Date().toISOString().slice(0, 10);
      const next = list.filter((e) => e.exam_date >= today).sort((a, b) => a.exam_date.localeCompare(b.exam_date))[0];
      if (next) setExam({ title: next.title, days: Math.round((new Date(next.exam_date + "T00:00:00").getTime() - new Date(today + "T00:00:00").getTime()) / 86400000) });
    }).catch(() => {});
  }, []);
  const slides = [
    { key: "review", tone: "violet", icon: "graduation-cap", title: line,
      sub: count ? `오늘의 복습 ${count}장을 시작해 볼까요?` : count === 0 ? "오늘 복습은 다 했어요. 새 강의를 들어 볼까요?" : "강의를 듣고 나면 복습 카드가 쌓여요",
      go: () => go({ name: "review" }) },
    ...(exam ? [{ key: "exam", tone: "rose", icon: "target", title: `${exam.title} ${exam.days === 0 ? "D-DAY" : `D-${exam.days}`}`,
      sub: exam.days === 0 ? "오늘이에요! 족보 노트로 마지막 정리" : "남은 날에 맞춘 오늘의 공부 계획 보기", go: () => go({ name: "semester", tab: "exams" }) }] : []),
    ...(quizDoc ? [{ key: "quiz", tone: "sky", icon: "brain", title: "AI 퀴즈 카드",
      sub: `${quizDoc.title}, AI가 낸 문제로 실력 확인`, go: () => go({ name: "quiz", docId: quizDoc.id }) }] : []),
  ];
  // 저절로 넘기기 (손대면 멈춘다)
  useEffect(() => {
    if (slides.length < 2 || matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const t = window.setInterval(() => {
      if (touched.current || document.hidden) return;
      const el = track.current;
      if (!el) return;
      const next = (Math.round(el.scrollLeft / el.clientWidth) + 1) % slides.length;
      el.scrollTo({ left: next * el.clientWidth, behavior: "smooth" });
    }, 6000);
    return () => window.clearInterval(t);
  }, [slides.length]);
  const onScroll = () => {
    const el = track.current;
    if (!el) return;
    const n = Math.round(el.scrollLeft / el.clientWidth);
    if (n !== at) { setAt(n); if (touched.current) play("slide"); }
  };
  return (
    <div className="hero-carousel">
      <div ref={track} className="hero-track" onScroll={onScroll} onPointerDown={() => { touched.current = true; }}>
        {slides.map((s, i) => (
          <button key={s.key} className={`hero-card tone-${s.tone}${i === at ? " on" : ""}`} onClick={s.go}>
            <b>{s.title}</b>
            <span>{s.sub}</span>
            <svg className="hero-art" aria-hidden="true"><use href={`${import.meta.env.BASE_URL}icons.svg#dt-${s.icon}`} /></svg>
          </button>
        ))}
      </div>
      {slides.length > 1 && (
        <div className="hero-dots" aria-hidden="true">
          {slides.map((s, i) => <i key={s.key} className={i === at ? "on" : ""} />)}
        </div>
      )}
    </div>
  );
}

function Tile({ icon, title, sub, onClick }: { icon: string; title: string; sub: string; onClick: () => void }) {
  return (
    <button className="tile" onClick={onClick}>
      <Icon name={icon} art size={30} />
      <span><b>{title}</b><small>{sub}</small></span>
    </button>
  );
}
