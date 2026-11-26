// 시간표: 오늘 수업을 홈 화면에 보여 주고(지금 수업은 강조), 누르면 그 과목 폴더로 간다. 여기서 바로 고친다.
import { useCallback, useEffect, useRef, useState } from "react";
import { getJSON, postJSON } from "../api/useApi";
import { Button, Icon } from "../components/ui";
import { courseTone } from "../lib/course";
import { go } from "../router";
import { useSwipe } from "../lib/swipe";
import { shareTimetable } from "../lib/native";
import { haptic } from "../lib/haptic";
import { askYes } from "../components/Dialog";
import { Skeleton } from "../lib/motion";

export interface ClassRow { id: number; course: string; weekday: number; start: string; end: string; place: string }

const DAYS = ["월", "화", "수", "목", "금", "토", "일"];

/** 0 = 월요일 (서버와 같은 기준) */
export function todayIndex(now = new Date()): number { return (now.getDay() + 6) % 7; }
export function clockOf(now = new Date()): string { return `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}`; }

/** 오늘 수업 가운데 지금 하는 것, 없으면 다음 것 */
export function currentClass(rows: ClassRow[], now = new Date()): { row: ClassRow; live: boolean } | null {
  const clock = clockOf(now);
  const today = rows.filter((r) => r.weekday === todayIndex(now)).sort((a, b) => a.start.localeCompare(b.start));
  // 쉬는 시간에 미리 열 수 있게 시작 10분 전부터 "지금 수업"으로 본다
  const soon = clockOf(new Date(now.getTime() + 10 * 60000));
  const live = today.find((r) => r.start <= soon && clock < r.end);
  if (live) return { row: live, live: true };
  const next = today.find((r) => r.start > clock);
  return next ? { row: next, live: false } : null;
}

const CHANGED = "ln-timetable-changed";

/** 홈에 놓는 작은 시간표 카드.
 *  slot="top": 시간표가 있을 때 홈 맨 위 (지금·다음 수업 + 오늘 수업 한 줄)
 *  slot="invite": 시간표가 비었을 때 녹음 버튼 아래의 '시간표 등록하기' 카드
 *  전체 시간표와 고치기는 '일정' 탭의 시간표 화면에서 */
export function Timetable({ onPick, slot = "top" }: { courses?: string[]; onPick: (course: string) => void; slot?: "top" | "invite" }) {
  const [rows, setRows] = useState<ClassRow[] | null>(null);
  const [, tick] = useState(0);
  const [next, setNext] = useState<NextMap>({});
  const load = useCallback(() => {
    getJSON<ClassRow[]>("/timetable").then((r) => { setRows(r); shareTimetable(r); }).catch(() => setRows(null));
    getJSON<NextMap>("/timetable/next").then(setNext).catch(() => {});
  }, []);
  useEffect(load, [load]);
  useEffect(() => { window.addEventListener(CHANGED, load); return () => window.removeEventListener(CHANGED, load); }, [load]);
  useEffect(() => { const t = window.setInterval(() => tick((n) => n + 1), 60000); return () => window.clearInterval(t); }, []);

  if (rows === null) return null; // 서버가 시간표를 모르거나 못 불러오면 조용히 숨긴다
  if (slot === "top" ? rows.length === 0 : rows.length > 0) return null;
  const open = () => go({ name: "timetable" });

  if (slot === "invite") return (
    <section className="timetable" aria-label="시간표">
      <button className="tt-invite" onClick={open}>
        <span className="tt-mini" aria-hidden>
          {[0, 1, 2, 3, 4].map((d) => <span key={d}>{[0, 1, 2].map((h) => <i key={h} className={(d + h) % 3 === 0 ? `blk-${(d + h) % 8}` : undefined} />)}</span>)}
        </span>
        <span className="grow">
          <b>시간표 등록</b>
        </span>
        <Icon name="caret-right" size={16} />
      </button>
    </section>
  );

  const now = currentClass(rows);
  const today = rows.filter((r) => r.weekday === todayIndex());
  // 지금·다음 수업 뒤에 남은 오늘 수업만 (이미 끝난 수업은 보여 줄 필요 없다)
  const later = now ? today.filter((r) => r.id !== now.row.id && r.start > now.row.start).sort((a, b) => a.start.localeCompare(b.start)) : [];
  return (
    <section className="timetable" aria-label="시간표">
      {now && (
        <button className={`class-now ${courseTone(now.row.course)}${now.live ? " live" : ""}`} onClick={() => onPick(now.row.course)}>
          <span className="cn-time"><small>{now.live ? "지금" : "다음"}</small><b>{now.row.start}</b><em>~{now.row.end}</em></span>
          <span className="cn-body">
            <b>{now.row.course}</b>
            {now.row.place && <span>{now.row.place}</span>}
          </span>
          <Icon name="caret-right" size={18} />
        </button>
      )}
      {now && next[now.row.course] && (
        <button className="tt-ready" onClick={() => go({ name: "lecture", docId: next[now.row.course].doc_id })}>
          <span className="tt-ready-dot"><Icon name="microphone" size={16} /></span>
          <span className="grow"><b>녹음 시작</b><small>{next[now.row.course].title}</small></span>
          <Icon name="caret-right" size={14} />
        </button>
      )}
      {now ? (
        // 지금·다음 수업 카드가 있으면 오늘 수업은 한 줄로만 (같은 것을 두 번 보여 주지 않게)
        <button className="tt-link" onClick={open}>
          <Icon name="calendar-dots" size={15} />
          <b className="tt-link-n">{later.length ? "이따가" : `오늘 ${today.length}개`}</b>
          <span className="grow tt-link-chips">
            {!later.length && <span className="tt-link-done">오늘 마지막 수업이에요</span>}
            {later.map((r) => (
              <span key={r.id} className={`tt-link-chip ${courseTone(r.course)}`}><span className="mark">{r.course}</span><em>{r.start}</em></span>
            ))}
          </span>
          <span className="tt-link-go">시간표 <Icon name="caret-right" size={12} /></span>
        </button>
      ) : (
        <button className="tt-card" onClick={open}>
          <span className="tt-ic"><Icon name="calendar-dots" size={22} /></span>
          <span className="grow">
            <b>{today.length ? "오늘 수업은 끝났어요" : "오늘은 수업이 없어요"}</b>
            <small>{today.length ? "오늘 배운 걸 복습해 볼까요?" : "푹 쉬거나 복습해요"}</small>
          </span>
          <span className="tt-btn">시간표 보기</span>
        </button>
      )}
    </section>
  );
}

/** 시간표 화면 ('일정' 탭): 이번 주 표 · 캡처로 넣기 · 직접 넣기 · 지우기 */
type NextMap = Record<string, { doc_id: string; title: string; auto: boolean }>;

/** 강의자료 미리 연결: 과목마다 다음 수업에 쓸 자료를 골라 두면, 수업 시간에 홈에서 바로 녹음한다 */
function NextDocs({ courses }: { courses: string[] }) {
  const [next, setNext] = useState<NextMap>({});
  const [docs, setDocs] = useState<{ id: string; title: string; course?: string }[]>([]);
  useEffect(() => {
    getJSON<NextMap>("/timetable/next").then(setNext).catch(() => {});
    getJSON<typeof docs>("/documents").then(setDocs).catch(() => {});
  }, []);
  const withDocs = courses.filter((c) => docs.some((d) => (d.course || "") === c));
  const without = courses.filter((c) => !withDocs.includes(c));
  const pick = async (course: string, docId: string) => {
    const r = await fetch((import.meta.env.VITE_API_URL ?? "") + "/timetable/next", {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ course, doc_id: docId || null }) });
    if (r.ok) { setNext(await r.json()); window.dispatchEvent(new Event(CHANGED)); }
  };
  return (
    <section className="next-docs" aria-label="다음 수업 자료">
      <div className="next-head">
        <b className="grow">다음 수업 자료</b>
        <span className="next-count">{withDocs.length}<i>/{courses.length}</i></span>
      </div>
      {withDocs.map((c) => {
        const mine = docs.filter((d) => (d.course || "") === c);
        const cur = next[c];
        return (
          <label key={c} className={`next-row ${courseTone(c)}`}>
            <i />
            <span className="next-course">{c}</span>
            <select className="input" value={cur && !cur.auto ? cur.doc_id : ""} onChange={(e) => void pick(c, e.target.value)} aria-label={`${c} 다음 수업 자료`}>
              <option value="">{cur?.auto ? `자동: ${cur.title}` : "자동 (새로 올린 자료)"}</option>
              {mine.map((d) => <option key={d.id} value={d.id}>{d.title}</option>)}
            </select>
          </label>
        );
      })}
      {without.length > 0 && (
        <div className="next-missing">
          {withDocs.length > 0 && <span className="next-missing-label">자료 없음</span>}
          <div className="mark-row">
            {without.map((c) => <span key={c} className={`mark ${courseTone(c)}`}>{c}</span>)}
          </div>
          <p className="next-tip">자료를 올릴 때 과목을 맞춰 두면 여기 붙어요</p>
        </div>
      )}
    </section>
  );
}

export function TimetableEditor({ onPick }: { onPick: (course: string) => void }) {
  const [rows, setRows] = useState<ClassRow[] | null>(null);
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({ course: "", weekday: todayIndex(), start: "09:00", end: "10:15", place: "" });
  const [error, setError] = useState("");
  const [courses, setCourses] = useState<string[]>([]);
  const load = useCallback(() => { getJSON<ClassRow[]>("/timetable").then((r) => { setRows(r); shareTimetable(r); }).catch(() => setRows([])); }, []);
  useEffect(load, [load]);
  useEffect(() => {
    getJSON<{ course?: string }[]>("/documents").then((d) => setCourses([...new Set(d.map((x) => x.course || "").filter(Boolean))])).catch(() => {});
  }, []);
  const changed = () => { load(); window.dispatchEvent(new Event(CHANGED)); };

  const add = async () => {
    setError("");
    try {
      await postJSON("/timetable", form);
      setForm((f) => ({ ...f, course: "", place: "" }));
      changed();
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  };
  const remove = async (r: ClassRow) => {
    if (!await askYes(`${DAYS[r.weekday]}요일 ${r.start} ${r.course}을(를) 시간표에서 뺄까요?`)) return;
    await fetch((import.meta.env.VITE_API_URL ?? "") + `/timetable/${r.id}`, { method: "DELETE" });
    changed();
  };
  if (!rows) return <Skeleton />;

  return (
    <div className="tt-screen">
      {rows.length > 0 ? <><WeekGrid rows={rows} onPick={onPick} dated /><NextClassCard rows={rows} onPick={onPick} /></> : (
        <p className="tasks-empty">아직 시간표가 없어요</p>
      )}
      {rows.length > 0 && <NextDocs courses={[...new Set(rows.map((r) => r.course))]} />}
      {rows.length > 0 ? (
        <section className="tt-tools" aria-label="시간표 고치기">
          <b className="tt-tools-title">시간표 고치기</b>
          <div className="tt-tools-grid">
            <ImportFromImage hasRows onSaved={changed} compact />
            <button className={`tt-tile${adding ? " on" : ""}`} onClick={() => setAdding(!adding)} aria-expanded={adding}>
              <span className="tt-tile-ic edit"><Icon name="note-pencil" size={20} /></span>
              <b>직접 고치기</b>
              <small>한 과목씩 넣고 빼기</small>
            </button>
          </div>
        </section>
      ) : (
        <>
          <ImportFromImage hasRows={false} onSaved={changed} />
          <button className="tt-fold" onClick={() => setAdding(!adding)} aria-expanded={adding}>
            <Icon name="plus" size={16} /><span className="grow">한 과목씩 직접 넣기</span><Icon name={adding ? "caret-up" : "caret-down"} size={14} />
          </button>
        </>
      )}
      {adding && (
        <div className="timetable-edit">
          {DAYS.map((day, i) => {
            const list = rows.filter((r) => r.weekday === i);
            if (!list.length) return null;
            return (
              <div key={day} className="timetable-day">
                <b className="t-caption">{day}</b>
                {list.map((r) => (
                  <span key={r.id} className={`timetable-class t-caption ${courseTone(r.course)}`}>
                    {r.start}~{r.end} {r.course}{r.place ? ` (${r.place})` : ""}
                    <button onClick={() => void remove(r)} aria-label={`${r.course} 빼기`}><Icon name="x" size={14} /></button>
                  </span>
                ))}
              </div>
            );
          })}
          <div className="timetable-form">
            <input className="input" placeholder="과목 이름" list="timetable-courses" value={form.course}
              onChange={(e) => setForm({ ...form, course: e.target.value })} aria-label="과목 이름" />
            <datalist id="timetable-courses">{courses.map((c) => <option key={c} value={c} />)}</datalist>
            <div className="row">
              <select className="input" value={form.weekday} onChange={(e) => setForm({ ...form, weekday: Number(e.target.value) })} aria-label="요일">
                {DAYS.map((d, i) => <option key={d} value={i}>{d}요일</option>)}
              </select>
              <input className="input" type="time" value={form.start} onChange={(e) => setForm({ ...form, start: e.target.value })} aria-label="시작 시간" />
              <input className="input" type="time" value={form.end} onChange={(e) => setForm({ ...form, end: e.target.value })} aria-label="끝나는 시간" />
            </div>
            <div className="row">
              <input className="input" placeholder="강의실 (안 적어도 돼요)" value={form.place} onChange={(e) => setForm({ ...form, place: e.target.value })} aria-label="강의실" />
              <Button onClick={() => void add()} disabled={!form.course.trim()}>넣기</Button>
            </div>
            {error && <p className="t-caption" style={{ color: "var(--note-exam-ink)" }}>{error}</p>}
          </div>
        </div>
      )}
    </div>
  );
}

type Draft = Omit<ClassRow, "id">;

/** WebP·HEIC 같은 사진은 서버가 못 열 수 있어서, 폰 브라우저가 열어서 PNG 로 바꿔 보낸다 (PNG·JPEG 는 그대로) */
async function asPng(file: File): Promise<Blob> {
  if (/^image\/(png|jpe?g)$/.test(file.type)) return file;
  const url = URL.createObjectURL(file);
  try {
    const img = new Image();
    img.src = url;
    await img.decode();
    const canvas = document.createElement("canvas");
    canvas.width = img.naturalWidth; canvas.height = img.naturalHeight;
    canvas.getContext("2d")!.drawImage(img, 0, 0);
    const blob = await new Promise<Blob | null>((ok) => canvas.toBlob(ok, "image/png"));
    if (!blob) throw new Error();
    return new File([blob], "timetable.png", { type: "image/png" });
  } catch {
    throw new Error("이 사진 형식은 열 수 없어요. 시간표를 스크린샷으로 찍어서 올려 주세요.");
  } finally { URL.revokeObjectURL(url); }
}

/** 시간표 캡처로 넣기: 에브리타임·학교 포털 캡처를 AI가 읽고 → 사람이 확인·고친 뒤 → 한 번에 저장 */
function ImportFromImage({ hasRows, onSaved, compact = false }: { hasRows: boolean; onSaved: () => void; compact?: boolean }) {
  const input = useRef<HTMLInputElement>(null);
  const [state, setState] = useState<"idle" | "reading" | "check" | "saving">("idle");
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [replace, setReplace] = useState(hasRows);
  const [error, setError] = useState("");
  const [preview, setPreview] = useState<string | null>(null);
  const [note, setNote] = useState("");

  const read = async (file: File) => {
    setError(""); setState("reading");
    setPreview(URL.createObjectURL(file));
    const body = new FormData();
    try {
      body.append("file", await asPng(file));
      const r = await fetch((import.meta.env.VITE_API_URL ?? "") + "/timetable/from-image", { method: "POST", body });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(data.detail ?? "시간표를 읽지 못했어요");
      setDrafts(data.classes); setNote(data.note ?? ""); setState("check");
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); setState("idle"); }
  };
  const save = async () => {
    setError(""); setState("saving");
    try {
      await postJSON("/timetable/bulk", { classes: drafts, replace });
      setDrafts([]); setState("idle"); setPreview(null); onSaved();
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); setState("check"); }
  };
  const edit = (i: number, change: Partial<Draft>) => setDrafts((d) => d.map((x, j) => (j === i ? { ...x, ...change } : x)));

  return (
    <div className={`tt-import${state === "check" || state === "saving" ? " open" : ""}`}>
      <input ref={input} type="file" accept="image/*" hidden onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) void read(f); }} />
      {compact && state !== "check" && state !== "saving" && (
        <button className="tt-tile" onClick={() => input.current?.click()} disabled={state === "reading"}>
          <span className="tt-tile-ic shot">{state === "reading" ? <span className="spin" aria-hidden /> : <Icon name="camera" size={20} />}</span>
          <b>{state === "reading" ? "읽는 중…" : "캡처로 넣기"}</b>
          <small>{state === "reading" ? "10초쯤 걸려요" : "에타나 포털 시간표 사진"}</small>
        </button>
      )}
      {!compact && state !== "check" && state !== "saving" && (
        <button className="tt-shot" onClick={() => input.current?.click()} disabled={state === "reading"}>
          <span className="tt-shot-ic"><Icon name="camera" art size={26} /></span>
          <span className="grow">
            <b>{state === "reading" ? "시간표를 읽는 중…" : "시간표 캡처로 넣기"}</b>
            <small>{state === "reading" ? "AI가 요일·시간·과목을 옮기고 있어요 (10초쯤)" : "에브리타임이나 학교 포털 시간표 캡처"}</small>
          </span>
          {state === "reading" ? <span className="spin" aria-hidden /> : <Icon name="caret-right" size={16} />}
        </button>
      )}
      {(state === "check" || state === "saving") && (
        <div className="tt-check">
          <div className="row">
            {preview && <img src={preview} alt="올린 시간표" className="tt-thumb" />}
            <span className="grow"><b>{drafts.length}개 수업을 찾았어요</b><small>틀린 곳은 눌러서 고치고, 아니면 지워 주세요</small></span>
          </div>
          {note && <p className="tt-note">{note}</p>}
          {drafts.map((d, i) => (
            <div key={i} className={`tt-draft ${courseTone(d.course)}`}>
              <input className={`input${d.course.trim() ? "" : " need"}`} value={d.course} placeholder={`${DAYS[d.weekday]} ${d.start} 수업 이름`}
                onChange={(e) => edit(i, { course: e.target.value })} aria-label="과목 이름" />
              <div className="row">
                <select className="input" value={d.weekday} onChange={(e) => edit(i, { weekday: Number(e.target.value) })} aria-label="요일">
                  {DAYS.map((day, j) => <option key={day} value={j}>{day}</option>)}
                </select>
                <input className="input" type="time" value={d.start} onChange={(e) => edit(i, { start: e.target.value })} aria-label="시작" />
                <input className="input" type="time" value={d.end} onChange={(e) => edit(i, { end: e.target.value })} aria-label="끝" />
                <button className="round" onClick={() => setDrafts((x) => x.filter((_, j) => j !== i))} aria-label={`${d.course} 빼기`}><Icon name="x" size={14} /></button>
              </div>
            </div>
          ))}
          {hasRows && (
            <label className="tt-replace"><input type="checkbox" checked={replace} onChange={(e) => setReplace(e.target.checked)} /> 지금 시간표를 지우고 이것으로 바꾸기</label>
          )}
          <div className="row">
            <Button variant="secondary" onClick={() => { setState("idle"); setDrafts([]); setPreview(null); }}>다시 고르기</Button>
            <Button onClick={() => void save()} disabled={!drafts.length || state === "saving" || drafts.some((d) => !d.course.trim())}>
              {state === "saving" ? "넣는 중…" : drafts.some((d) => !d.course.trim()) ? "이름을 채워 주세요" : `${drafts.length}개 넣기`}
            </Button>
          </div>
        </div>
      )}
      {error && <p className="t-caption" style={{ color: "var(--note-exam-ink)" }}>{error}</p>}
    </div>
  );
}

const short = (clock: string) => clock.replace(/^0/, "");   // 09:00 → 9:00 (좁은 칸에 시간이 한 줄로 들어가게)
const minutes = (clock: string) => Number(clock.slice(0, 2)) * 60 + Number(clock.slice(3, 5));

/** 이번 주 시간표: 위에 주 넘기기와 날짜 띠, 아래에 요일 칸마다 과목 블록. 지금 시각은 보라 선과 '지금' 알약 */
export function WeekGrid({ rows, onPick, dated = false }: { rows: ClassRow[]; onPick: (course: string) => void; dated?: boolean }) {
  const [week, setWeek] = useState(0);   // 0 = 이번 주, -1 = 지난주 … (수업은 매주 같고 날짜만 바뀐다)
  const days = Math.max(5, ...rows.map((r) => r.weekday + 1));
  // 보통 9시~6시를 보여 주고, 그보다 이르거나 늦은 수업이 있으면 넓힌다
  const from = Math.min(9, Math.floor(Math.min(...rows.map((r) => minutes(r.start))) / 60));
  const to = Math.max(18, Math.ceil(Math.max(...rows.map((r) => minutes(r.end))) / 60));
  const hours = Math.max(1, to - from);
  const hour = 58; // 한 시간 높이(px): 과목 이름 · 장소 · 시간이 들어가게
  const thisWeek = week === 0;
  const today = thisWeek ? todayIndex() : -1;
  const nowMin = minutes(clockOf());
  const now = currentClass(rows);
  const live = thisWeek && now?.live ? now.row : null;
  // 과목마다 다른 색: 나온 순서대로 8가지를 돌려 쓴다 (겹치지 않게)
  const courses = [...new Set([...rows].sort((a, b) => a.weekday - b.weekday || a.start.localeCompare(b.start)).map((r) => r.course))];
  const colorOf = (course: string) => courses.indexOf(course) % 8;
  const cols = { gridTemplateColumns: `28px repeat(${days}, 1fr)` };
  const monday = new Date();
  monday.setHours(0, 0, 0, 0);
  monday.setDate(monday.getDate() - todayIndex() + week * 7);
  const dateOf = (i: number) => { const d = new Date(monday); d.setDate(monday.getDate() + i); return d; };
  const mid = dateOf(3);
  const busy = new Set(rows.map((r) => r.weekday));
  const showNow = thisWeek && today < days && nowMin >= from * 60 && nowMin <= to * 60;
  const [dir, setDir] = useState<"" | "next" | "prev">("");
  const move = (by: number) => { setDir(by > 0 ? "next" : "prev"); setWeek((w) => (by === 0 ? 0 : w + by)); haptic("light"); };
  const swipe = useSwipe(() => move(1), () => move(-1), "week");
  return (
    <div className="tt-wrap" {...(dated ? { ...swipe, "data-swipe": "week" } : {})}>
      {dated && (
        <>
          <div className="tt-nav">
            <button className="tt-arrow" onClick={() => move(-1)} aria-label="지난주"><Icon name="caret-left" size={18} /></button>
            <b className="tt-month">{mid.getFullYear()}년 {mid.getMonth() + 1}월</b>
            <button className={`tt-today-btn${thisWeek ? " on" : ""}`} onClick={() => { setDir(week > 0 ? "prev" : "next"); setWeek(0); haptic("light"); }} disabled={thisWeek}>오늘</button>
            <button className="tt-arrow" onClick={() => move(1)} aria-label="다음 주"><Icon name="caret-right" size={18} /></button>
          </div>
          <div key={week} className={`tt-dates ${dir}`} style={{ gridTemplateColumns: `repeat(${days}, 1fr)` }}>
            {DAYS.slice(0, days).map((d, i) => (
              <span key={d} className={`tt-date${i === today ? " today" : ""}`}>
                <small>{d}</small><b>{dateOf(i).getDate()}</b>
                <i className={busy.has(i) ? "dot" : ""} />
              </span>
            ))}
          </div>
        </>
      )}
      <div className="tt-grid" role="table" aria-label="이번 주 시간표">
        {!dated && (
          <div className="tt-head" style={cols} role="row">
            <span />
            {DAYS.slice(0, days).map((d, i) => <span key={d} role="columnheader" className={i === today ? "today" : ""}>{d}</span>)}
          </div>
        )}
        <div className="tt-body" style={{ ...cols, height: hours * hour, "--hour": `${hour}px` } as React.CSSProperties}>
          <div className="tt-hours">
            {Array.from({ length: hours }, (_, i) => <span key={i} style={{ height: hour }}>{String(from + i).padStart(2, "0")}</span>)}
          </div>
          {DAYS.slice(0, days).map((d, day) => (
            <div key={d} className={`tt-col${day === today ? " today" : ""}`}>
              {rows.filter((r) => r.weekday === day).map((r, i) => {
                const h = ((minutes(r.end) - minutes(r.start)) / 60) * hour;
                return (
                  <button key={r.id} className={`tt-block tt-c${colorOf(r.course)}${live?.id === r.id ? " live" : ""}`}
                    onClick={() => onPick(r.course)}
                    style={{ top: ((minutes(r.start) - from * 60) / 60) * hour, height: Math.max(22, h - 2), animationDelay: `${day * 50 + i * 40}ms` }}
                    aria-label={`${d}요일 ${r.start}~${r.end} ${r.course}${r.place ? ` ${r.place}` : ""}`}>
                    <b>{r.course}</b>
                    {r.place && h > 44 && <small>{r.place}</small>}
                    {h > 70 && <small className="tt-time">{short(r.start)}–{short(r.end)}</small>}
                  </button>
                );
              })}
            </div>
          ))}
          {showNow && (
            <div className="tt-now" style={{ top: ((nowMin - from * 60) / 60) * hour }} aria-hidden>
              <span>지금</span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/** 시간표 아래 '다음 수업' 카드: 지금 하는 수업, 없으면 오늘 · 다음 날들 가운데 가장 가까운 수업 */
export function NextClassCard({ rows, onPick }: { rows: ClassRow[]; onPick: (course: string) => void }) {
  const now = currentClass(rows);
  let found: { row: ClassRow; when: string; live: boolean } | null = now
    ? { row: now.row, when: `오늘 ${now.row.start}`, live: now.live } : null;
  if (!found && rows.length) {
    const t = todayIndex();
    for (let k = 1; k <= 7 && !found; k++) {
      const day = (t + k) % 7;
      const first = rows.filter((r) => r.weekday === day).sort((a, b) => a.start.localeCompare(b.start))[0];
      if (first) found = { row: first, when: `${k === 1 ? "내일" : `${DAYS[day]}요일`} ${first.start}`, live: false };
    }
  }
  if (!found) return null;
  return (
    <button className="tt-next" onClick={() => onPick(found!.row.course)}>
      <span className="tt-next-ic"><Icon name="calendar-dots" size={24} /></span>
      <span className="grow">
        <small>{found.live ? "지금 수업" : "다음 수업"}</small>
        <b>{found.row.course}</b>
        <span>{found.when}{found.row.place ? `, ${found.row.place}` : ""}</span>
      </span>
      <Icon name="caret-right" size={18} />
    </button>
  );
}
