// 1 자료 목록 (Figma "03 디자인 / 1 자료 목록")
import { useEffect, useRef, useState } from "react";
import { EnglishToggle, lectureLang, setLectureLang } from "../components/EnglishToggle";
import type { DocumentBrief } from "../api/types";
import { getJSON, postJSON, useApi } from "../api/useApi";
import { android } from "../lib/live";
import { Empty, Icon, ListItem } from "../components/ui";
import { Moon, moonNext, moonPhase } from "../components/Moon";
import { ExamBanner } from "./Semester";
import { Timetable } from "./Timetable";
import { StreakBadge } from "./Story";
import { TasksCard } from "./Tasks";
import { IosInstallHint } from "../components/IosHint";
import { Skeleton } from "../lib/motion";
import { courseTone } from "../lib/course";
import { useWaves, Wave } from "../lib/wave";
import { go } from "../router";
import { getPrefs } from "../lib/prefs";
import { refreshNotices } from "../lib/notices";
import { LuneMark, LuneWordmark } from "../components/Brand";
import { askText, tell } from "../components/Dialog";


export function subtitleOf(doc: DocumentBrief): string {
  const kind = doc.kind === "meeting" ? `회의, 안건 ${doc.page_count}개` : doc.kind === "notebook" ? `노트, 주제 ${doc.page_count}개` : `슬라이드 ${doc.page_count}쪽`;
  return `${doc.kind === "meeting" || doc.kind === "notebook" ? kind : `${doc.page_count}쪽`} · ${doc.sessions.length ? `${doc.sessions.length}강` : "녹음 전"} · ${relativeDay(doc.created_at)}`;
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
  useEffect(() => { void refreshNotices(); }, []);   // 마감·수업 알림도 앱을 열 때마다 새로
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
      const text = [exam ? `${exam.title} ${days === 0 ? "D-DAY" : `D-${days}`}` : "", "눌러서 바로 복습하기"].filter(Boolean).join(". ");
      const hour = getPrefs().reminder;
      if (hour) app.setReminder!(title, text, hour, 0);
    });
  }, []);
}

/** 처음 쓰는 사람 안내: 가입 → 강의자료 → 첫 녹음. 다 하면(또는 닫으면) 사라진다 */
function FirstSteps({ docs, onDoc, onRecord }: { docs: DocumentBrief[]; onDoc: () => void; onRecord: () => void }) {
  const [hide, setHide] = useState(() => { try { return localStorage.getItem("ln.firstSteps") === "off"; } catch { return false; } });
  const hasDoc = docs.length > 0;
  const hasRec = docs.some((d) => d.sessions.length > 0);
  if (hide || (hasDoc && hasRec)) return null;
  const close = () => { try { localStorage.setItem("ln.firstSteps", "off"); } catch { /* 괜찮다 */ } setHide(true); };
  const steps: [string, string, boolean, (() => void) | null][] = [
    ["가입하기", "끝났어요", true, null],
    ["강의자료 올리기", "PDF, PPT, 한글 파일", hasDoc, onDoc],
    ["첫 수업 녹음", "들으면서 쪽마다 필기가 붙어요", hasRec, onRecord],
  ];
  const next = steps.findIndex(([, , done]) => !done);
  return (
    <section className="first-steps" aria-label="시작하기">
      <div className="row"><b className="grow">LUNE 시작하기 <small>{steps.filter(([, , d]) => d).length}/3</small></b>
        <button className="ios-hint-x" aria-label="안내 닫기" onClick={close}><Icon name="x" size={16} /></button></div>
      <ol>
        {steps.map(([title, sub, done, act], i) => (
          <li key={title} className={done ? "done" : i === next ? "now" : ""}>
            <button disabled={done || !act} onClick={act ?? undefined}>
              <span className="fs-num">{done ? <Icon name="check" size={14} /> : i + 1}</span>
              <span className="grow"><b>{title}</b><small>{sub}</small></span>
              {!done && i === next && <Icon name="caret-right" size={14} />}
            </button>
          </li>
        ))}
      </ol>
    </section>
  );
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
      tell(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  // 강의자료 없이 녹음 파일만: 노트 수업을 만들고 받아쓰기 → 주제별 필기 → 요약까지 서버가 한다
  const audio = useRef<HTMLInputElement>(null);
  const uploadAudio = (f: File) => {
    const form = new FormData();
    form.append("file", f);
    form.append("language", lectureLang(null));
    if (filter !== "all" && filter) form.append("course", filter);
    const xhr = new XMLHttpRequest();
    xhr.open("POST", (import.meta.env.VITE_API_URL ?? "") + "/documents/from-audio");
    xhr.upload.onprogress = (e) => { if (e.lengthComputable) setBusy(`녹음 올리는 중 ${Math.round((e.loaded / e.total) * 100)}%`); };
    xhr.onload = () => {
      setBusy(null);
      if (xhr.status >= 300) { tell(`올리지 못했어요 (${xhr.status})`); return; }
      const made = JSON.parse(xhr.responseText) as { document_id: string; session_id: string };
      go({ name: "lecture", docId: made.document_id, sessionId: made.session_id });
    };
    xhr.onerror = () => { setBusy(null); tell("올리지 못했어요. 인터넷 연결을 확인해 주세요."); };
    setBusy("녹음 올리는 중…");
    xhr.send(form);
  };

  // 강의자료에 녹음 파일 붙이기: 그 자료로 강의를 하나 만들고 받아쓰기 → 필기 → 요약
  const uploadToDoc = (docId: string, f: File) => {
    const form = new FormData();
    form.append("document_id", docId);
    form.append("language", lectureLang(docId));
    form.append("file", f);
    const xhr = new XMLHttpRequest();
    xhr.open("POST", (import.meta.env.VITE_API_URL ?? "") + "/sessions/from-audio");
    xhr.upload.onprogress = (e) => { if (e.lengthComputable) setBusy(`녹음 올리는 중 ${Math.round((e.loaded / e.total) * 100)}%`); };
    xhr.onload = () => {
      setBusy(null);
      if (xhr.status >= 300) { tell(`올리지 못했어요 (${xhr.status})`); return; }
      const made = JSON.parse(xhr.responseText) as { id: string };
      go({ name: "lecture", docId, sessionId: made.id });
    };
    xhr.onerror = () => { setBusy(null); tell("올리지 못했어요. 인터넷 연결을 확인해 주세요."); };
    setBusy("녹음 올리는 중…");
    xhr.send(form);
  };

  // 녹음 시작 / 녹음 올리기 → 어느 강의자료에? (자료 없이도 돼요)
  const [picker, setPicker] = useState<null | "record" | "upload">(null);
  const target = useRef<string | null>(null);
  const audioToDoc = useRef<HTMLInputElement>(null);
  const pickEn = useRef(lectureLang(null) === "en");
  const choose = (docId: string | null) => {
    const mode = picker;
    setPicker(null);
    setLectureLang(docId, pickEn.current);   // 이 시트에서 고른 '영어 강의'를 그 자료에 기억
    if (mode === "record") {
      if (docId) go({ name: "lecture", docId }); else void newNotebook("notebook", true);
    } else if (mode === "upload") {
      target.current = docId;
      (docId ? audioToDoc : audio).current?.click();
    }
  };

  const newNotebook = async (kind: "notebook" | "meeting" = "notebook", startNow = false) => {
    const title = await askText(kind === "meeting" ? "회의 이름" : "수업 이름", kind === "meeting" ? "팀 회의" : "새 노트 수업");
    if (title === null) return;
    setBusy("노트를 만드는 중…");
    try {
      const doc = await postJSON<{ id: string }>("/documents/notebook", { title, kind, course: filter !== "all" ? filter : "" });
      go(startNow ? { name: "lecture", docId: doc.id } : { name: "doc", docId: doc.id });
    } catch (e) {
      tell(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const courses = [...new Set((docs ?? []).map((d) => d.course ?? "").filter(Boolean))].sort((a, b) => a.localeCompare(b, "ko"));
  const hasLoose = (docs ?? []).some((d) => !d.course);
  const [showAll, setShowAll] = useState(false);
  const [going, setGoing] = useState(false); // 녹음 판을 누르면 물결이 솟고 마이크 원이 커진 뒤 강의자료 고르기가 열린다
  const matched = (docs ?? []).filter((d) => filter === "all" || (d.course ?? "") === filter);
  // 홈에는 최근 강의 5개만, 나머지는 '전체 보기'로 (과목이 늘어도 홈이 길어지지 않게)
  const LIMIT = 5;
  const shown = showAll ? matched : matched.slice(0, LIMIT);
  // 전체 보기에서는 과목별로 묶어 보여 준다
  const groups: [string, DocumentBrief[]][] = filter === "all"
    ? [...courses.map((c) => [c, shown.filter((d) => d.course === c)] as [string, DocumentBrief[]]), ["", shown.filter((d) => !d.course)] as [string, DocumentBrief[]]]
        .filter(([, list]) => list.length > 0)
    : [[filter, shown]];

  return (
    <div className="screen">
      <HomeHead />
      <div className="home-search-wrap">
        <button className="home-search" onClick={() => go({ name: "search" })}>
          <Icon name="magnifying-glass" size={17} /><span>검색</span>
        </button>
      </div>
      <div className="screen-body">
        <Timetable courses={courses} onPick={pick} />

        {docs && <FirstSteps docs={docs} onDoc={() => file.current?.click()} onRecord={() => setPicker("record")} />}
        {/* 이 앱의 중심: 강의자료에 녹음을 붙인다 (지금 녹음하거나, 녹음 파일을 올리거나) */}
        <section className="record-hub" aria-label="강의 녹음">
          <button className={`record-main sig${going ? " go" : ""}`} disabled={!!busy} onClick={() => { if (going) return; setGoing(true); navigator.vibrate?.(10); window.setTimeout(() => { setGoing(false); setPicker("record"); }, matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 480); }}>
            <svg className="sig-wave" viewBox="0 0 400 120" preserveAspectRatio="none" aria-hidden="true">
              <path className="w1" d="M0 70 C 60 40, 120 100, 200 66 S 330 30, 400 64 V120 H0Z">
                <animate attributeName="d" dur="7s" repeatCount="indefinite" values="M0 70 C 60 40, 120 100, 200 66 S 330 30, 400 64 V120 H0Z;M0 62 C 70 92, 140 36, 210 72 S 320 96, 400 58 V120 H0Z;M0 70 C 60 40, 120 100, 200 66 S 330 30, 400 64 V120 H0Z" />
              </path>
              <path className="w2" d="M0 86 C 80 70, 150 104, 220 84 S 340 70, 400 90 V120 H0Z">
                <animate attributeName="d" dur="5s" repeatCount="indefinite" values="M0 86 C 80 70, 150 104, 220 84 S 340 70, 400 90 V120 H0Z;M0 92 C 70 104, 160 70, 230 92 S 330 104, 400 82 V120 H0Z;M0 86 C 80 70, 150 104, 220 84 S 340 70, 400 90 V120 H0Z" />
              </path>
            </svg>
            <span className="grow sig-copy"><b>수업 녹음</b></span>
            <span className="sig-moon" aria-hidden="true"><Moon size={190} phase={moonPhase()} /></span>
            <span className="sig-mic"><i /><i /><Icon name="microphone" size={26} /></span>
          </button>
          <div className="record-sub">
            <button onClick={() => setPicker("upload")} disabled={!!busy}><Icon name="upload-simple" size={17} />녹음 파일</button>
            <button onClick={() => file.current?.click()} disabled={!!busy}><Icon name="plus" size={17} />강의자료</button>
          </div>
          {busy && <p className="record-busy"><span className="spin" /> {busy}</p>}
        </section>
        <Timetable courses={courses} onPick={pick} slot="invite" />
        <input ref={file} type="file" accept="application/pdf,.pdf,.ppt,.pptx,.key,.odp,.doc,.docx,.hwp,.hwpx" hidden
          onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) void upload(f); }} />
        <input ref={audio} type="file" accept="audio/*,.m4a,.mp3,.wav,.aac,.ogg,.webm" hidden
          onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) uploadAudio(f); }} />
        <input ref={audioToDoc} type="file" accept="audio/*,.m4a,.mp3,.wav,.aac,.ogg,.webm" hidden
          onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f && target.current) uploadToDoc(target.current, f); }} />

        <IosInstallHint />
        <ExamBanner />
        <TasksCard />

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
          <section key={course || "-"} className={`course-group ${courseTone(course)}`}>
            {(filter === "all" && courses.length > 0) && (
              <h3 className={`course-title ${courseTone(course)}`}><span>{course || "과목 없음"}</span> <small>{list.length}</small></h3>
            )}
            {list.map((doc, i) => (
              <ListItem key={doc.id} index={i} tone={courseTone(doc.course)} art={doc.sessions[0] && waves[doc.sessions[0].id]?.w ? <Wave data={waves[doc.sessions[0].id]} /> : undefined} icon={doc.kind === "meeting" ? "users" : doc.kind === "notebook" ? "notebook" : "file-pdf"} title={doc.title}
                subtitle={subtitleOf(doc)} onClick={() => go({ name: "doc", docId: doc.id })} />
            ))}
          </section>
        ))}

        {matched.length > LIMIT && (
          <button className="show-all" onClick={() => setShowAll(!showAll)}>
            {showAll ? "접기" : `강의 ${matched.length}개 전체 보기`} <Icon name={showAll ? "caret-up" : "caret-down"} size={14} />
          </button>
        )}
        {/* 학기 전체로 가는 길은 가볍게 한 줄 (홈은 오늘 녹음, D-day, 할 일 위주) */}
        <div className="home-links" role="group" aria-label="학기 전체">
          <button onClick={() => go({ name: "semester", tab: "exams" })}><Icon name="target" art size={26} /><span>시험 준비</span></button>
          <button onClick={() => go({ name: "semester", tab: "tutor" })}><Icon name="chats-circle" art size={26} /><span>질문하기</span></button>
          <button onClick={() => go({ name: "semester", tab: "map" })}><Icon name="tree-structure" art size={26} /><span>개념 지도</span></button>
        </div>

        {picker && (
          <>
            <div className="sheet-bg" onClick={() => setPicker(null)} />
            <div className="sheet" role="dialog" aria-modal="true" aria-label="강의자료 고르기">
              <h3 className="t-title-m">{picker === "record" ? "어느 강의자료로 녹음할까요?" : "어느 강의자료에 녹음을 붙일까요?"}</h3>
              <p className="t-caption muted">강의자료를 고르면 필기가 그 쪽 옆에 붙어요</p>
              <EnglishToggle docId={null} onChange={(v) => { pickEn.current = v; }} />
              {(docs ?? []).filter((d) => d.kind !== "meeting").map((d) => (
                <ListItem key={d.id} icon={d.kind === "notebook" ? "notebook" : "file-pdf"} title={d.title} subtitle={subtitleOf(d)} onClick={() => choose(d.id)} />
              ))}
              {picker === "record" && (
                <ListItem icon="upload-simple" title="강의자료 먼저 올리기" subtitle="PDF, PPT, 한글 파일을 올리고 그 위에서 녹음해요" onClick={() => { setPicker(null); file.current?.click(); }} />
              )}
              <ListItem icon="note-pencil" title="강의자료 없이" subtitle="주제가 바뀔 때마다 노트를 나눠서 정리해요" onClick={() => choose(null)} />

            </div>
          </>
        )}
      </div>
    </div>
  );
}

/** 보라 배너: 인사 + 오늘의 복습 (참고 디자인의 "오늘도 수고했어요!") */

/** 홈 머리: 작은 로고 → 날짜 · 인사(이름) → 오늘 한 줄 요약 (수업 · 할 일) */
function HomeHead() {
  const [name, setName] = useState("");
  const [sum, setSum] = useState<{ classes: number; due: number } | null>(null);
  useEffect(() => {
    getJSON<{ user: { name: string } | null }>("/auth/me").then((m) => setName(m.user?.name ?? "")).catch(() => {});
    const today = (new Date().getDay() + 6) % 7;
    const iso = new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 10);
    Promise.all([
      getJSON<{ weekday: number }[]>("/timetable").catch(() => []),
      getJSON<{ done: boolean; due_date?: string | null }[]>("/tasks").catch(() => []),
    ]).then(([rows, tasks]) => setSum({
      classes: rows.filter((r) => r.weekday === today).length,
      due: tasks.filter((t) => !t.done && t.due_date && t.due_date <= iso).length,
    }));
  }, []);
  const h = new Date().getHours();
  const hello = h < 5 ? "늦은 밤이에요" : h < 11 ? "좋은 아침이에요" : h < 17 ? "좋은 오후예요" : h < 22 ? "좋은 저녁이에요" : "오늘도 수고했어요";
  // 글은 두 단계만: 작은 날짜 한 줄 + 큰 한 줄(오늘 제일 중요한 것 하나, 숫자만 달빛색으로 강조)
  const now = new Date();
  const caption = `${now.toLocaleDateString("ko-KR", { month: "long", day: "numeric", weekday: "long" })} · ${moonNext(moonPhase())}`;
  const big = !sum ? <>{hello}</>
    : sum.due ? <>오늘 마감 <em>{sum.due}개</em></>
    : sum.classes ? <>오늘 수업 <em>{sum.classes}개</em></>
    : <>{hello}{name ? <>, <em>{name}</em>님</> : ""}</>;
  return (
    <header className="home-head">
      <span className="home-bigmoon" aria-hidden="true"><Moon size={230} phase={moonPhase()} /></span>
      <div className="home-top">
        <span className="home-brand"><LuneMark size={22} /><LuneWordmark height={12} /></span>
        <span className="home-top-right">
          <StreakBadge />
          <button className="home-me" onClick={() => go({ name: "privacy" })} aria-label="설정"><Icon name="gear" size={18} /></button>
        </span>
      </div>
      <div className="home-hello">
        <p className="home-cap">{caption}</p>
        <h1 className="home-big">{big}</h1>
      </div>
    </header>
  );
}
