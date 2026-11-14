// 시간표: 오늘 수업을 홈 화면에 보여 주고(지금 수업은 강조), 누르면 그 과목 폴더로 간다. 여기서 바로 고친다.
import { useCallback, useEffect, useRef, useState } from "react";
import { getJSON, postJSON } from "../api/useApi";
import { Button, Icon } from "../components/ui";
import { courseTone } from "../lib/course";

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

/** slot="top": 시간표가 있을 때 홈 맨 위 (지금·다음 수업 + 오늘 수업)
 *  slot="invite": 시간표가 비었을 때 녹음 버튼 아래에 눈에 띄는 '시간표 등록' 카드 */
export function Timetable({ courses, onPick, slot = "top" }: { courses: string[]; onPick: (course: string) => void; slot?: "top" | "invite" }) {
  const [rows, setRows] = useState<ClassRow[] | null>(null);
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({ course: "", weekday: todayIndex(), start: "09:00", end: "10:15", place: "" });
  const [error, setError] = useState("");
  const [, tick] = useState(0);

  const load = useCallback(() => { getJSON<ClassRow[]>("/timetable").then(setRows).catch(() => setRows(null)); }, []);
  useEffect(load, [load]);
  useEffect(() => { window.addEventListener(CHANGED, load); return () => window.removeEventListener(CHANGED, load); }, [load]);
  useEffect(() => { const t = window.setInterval(() => tick((n) => n + 1), 60000); return () => window.clearInterval(t); }, []);

  if (rows === null) return null; // 서버가 시간표를 모르거나(옛 서버·데모) 못 불러오면 조용히 숨긴다
  // 시간표가 있으면 위(top)에, 없으면 아래 등록 카드(invite)에. 등록하는 동안에는 그 자리에 그대로 둔다
  if (slot === "top" ? rows.length === 0 : rows.length > 0 && !editing) return null;
  const now = currentClass(rows);
  const today = rows.filter((r) => r.weekday === todayIndex());

  const add = async () => {
    setError("");
    try {
      await postJSON("/timetable", form);
      setForm((f) => ({ ...f, course: "", place: "" }));
      load();
      window.dispatchEvent(new Event(CHANGED));
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  };
  const remove = async (id: number) => {
    await fetch((import.meta.env.VITE_API_URL ?? "") + `/timetable/${id}`, { method: "DELETE" });
    load();
    window.dispatchEvent(new Event(CHANGED));
  };

  return (
    <section className="timetable" aria-label="시간표">
      {now ? (
        <button className={`list-item class-now ${courseTone(now.row.course)}${now.live ? " live" : ""}`} onClick={() => onPick(now.row.course)}>
          <span className="list-item-icon is-art"><Icon name="chalkboard-teacher" art size={40} /></span>
          <span className="grow">
            <span className="class-tag">{now.live && <i />}{now.live ? "지금 수업" : "다음 수업"} · <span className="num">{now.row.start}~{now.row.end}</span></span>
            <span className="t-title-m" style={{ display: "block" }}>{now.row.course}</span>
            <span className="list-item-sub">{now.row.place ? `${now.row.place} · ` : ""}눌러서 이 과목 열기</span>
          </span>
          <span className="list-item-chev"><Icon name="caret-right" size={18} /></span>
        </button>
      ) : null}
      {slot === "invite" ? (
        <button className={`tt-invite${editing ? " open" : ""}`} onClick={() => setEditing((v) => !v)} aria-expanded={editing}>
          <span className="tt-mini" aria-hidden>
            {[0, 1, 2, 3, 4].map((d) => <span key={d}>{[0, 1, 2].map((h) => <i key={h} className={(d + h) % 3 === 0 ? `blk-${(d + h) % 8}` : undefined} />)}</span>)}
          </span>
          <span className="grow">
            <b>{editing ? "시간표를 넣어 주세요" : "시간표 등록하기"}</b>
            <small>{editing ? "다 넣었으면 닫기를 눌러요" : "에타 · 학교 시간표 캡처 한 장이면 끝. 수업 시간이 되면 그 과목이 맨 위에 떠요"}</small>
          </span>
          <span className="tt-go">{editing ? "닫기" : <>등록 <Icon name="caret-right" size={14} /></>}</span>
        </button>
      ) : (
        <button className="tt-card" onClick={() => setEditing((v) => !v)} aria-expanded={editing}>
          <span className="tt-ic"><Icon name="calendar-check" size={22} /></span>
          <span className="grow">
            <b>{today.length ? "오늘 수업" : "오늘은 수업이 없어요"}</b>
            <small>{today.length ? today.map((r) => `${r.course} ${r.start}`).join(" · ") : "푹 쉬거나 복습해요"}</small>
          </span>
          <span className="tt-btn">{editing ? "닫기" : "시간표 고치기"}</span>
        </button>
      )}
      {editing && (
        <div className="timetable-edit">
          <ImportFromImage hasRows={rows.length > 0} onSaved={() => { load(); window.dispatchEvent(new Event(CHANGED)); }} />
          <p className="tt-or">또는 한 과목씩 직접 넣기</p>
          {rows.length > 0 && <WeekGrid rows={rows} onPick={onPick} />}
          {DAYS.map((day, i) => {
            const list = rows.filter((r) => r.weekday === i);
            if (!list.length) return null;
            return (
              <div key={day} className="timetable-day">
                <b className="t-caption">{day}</b>
                {list.map((r) => (
                  <span key={r.id} className={`timetable-class t-caption ${courseTone(r.course)}`}>
                    {r.start}~{r.end} {r.course}{r.place ? ` (${r.place})` : ""}
                    <button onClick={() => void remove(r.id)} aria-label={`${r.course} 지우기`}><Icon name="x" size={14} /></button>
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
    </section>
  );
}


type Draft = Omit<ClassRow, "id">;

/** 시간표 캡처로 넣기: 에브리타임·학교 포털 캡처를 AI가 읽고 → 사람이 확인·고친 뒤 → 한 번에 저장 */
function ImportFromImage({ hasRows, onSaved }: { hasRows: boolean; onSaved: () => void }) {
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
    body.append("file", file);
    try {
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
    <div className="tt-import">
      <input ref={input} type="file" accept="image/*" hidden onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) void read(f); }} />
      {state !== "check" && state !== "saving" && (
        <button className="tt-shot" onClick={() => input.current?.click()} disabled={state === "reading"}>
          <span className="tt-shot-ic"><Icon name="camera" art size={26} /></span>
          <span className="grow">
            <b>{state === "reading" ? "시간표를 읽는 중…" : "시간표 캡처로 넣기"}</b>
            <small>{state === "reading" ? "AI가 요일·시간·과목을 옮기고 있어요 (10초쯤)" : "에브리타임 · 학교 포털 시간표 캡처나 사진"}</small>
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

const minutes = (clock: string) => Number(clock.slice(0, 2)) * 60 + Number(clock.slice(3, 5));

/** 이번 주 시간표: 요일 칸마다 과목 블록. 오늘 칸에는 지금 시각 선 */
function WeekGrid({ rows, onPick }: { rows: ClassRow[]; onPick: (course: string) => void }) {
  const days = Math.max(5, ...rows.map((r) => r.weekday + 1));
  const from = Math.floor(Math.min(...rows.map((r) => minutes(r.start))) / 60);
  const to = Math.ceil(Math.max(...rows.map((r) => minutes(r.end))) / 60);
  const hours = Math.max(1, to - from);
  const hour = Math.max(22, Math.min(40, Math.round(220 / hours))); // 한 시간의 높이(px): 전체가 너무 길어지지 않게
  const today = todayIndex();
  const nowMin = minutes(clockOf());
  const live = currentClass(rows)?.row;
  const cols = { gridTemplateColumns: `repeat(${days}, 1fr)` };
  return (
    <div className="week">
      <div className="week-head" style={cols}>
        {DAYS.slice(0, days).map((d, i) => <span key={d} className={i === today ? "today" : ""}>{d}</span>)}
      </div>
      <div className="week-body" style={{ ...cols, height: hours * hour, "--hour": `${hour}px` } as React.CSSProperties}>
        {Array.from({ length: hours + 1 }, (_, i) => <span key={i} className="week-hour" style={{ top: i * hour }}>{from + i}</span>)}
        {DAYS.slice(0, days).map((d, day) => (
          <div key={d} className={`week-col${day === today ? " today" : ""}`}>
            {day === today && nowMin >= from * 60 && nowMin <= to * 60 && <span className="week-now" style={{ top: ((nowMin - from * 60) / 60) * hour }} />}
            {rows.filter((r) => r.weekday === day).map((r, i) => (
              <button key={r.id} className={`week-block ${courseTone(r.course)}${live?.id === r.id ? " live" : ""}`} onClick={() => onPick(r.course)}
                style={{ top: ((minutes(r.start) - from * 60) / 60) * hour, height: Math.max(18, ((minutes(r.end) - minutes(r.start)) / 60) * hour - 2), animationDelay: `${day * 50 + i * 40}ms` }}
                aria-label={`${d}요일 ${r.start} ${r.course}`}>
                {r.course}{r.place && <small>{r.place}</small>}
              </button>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
