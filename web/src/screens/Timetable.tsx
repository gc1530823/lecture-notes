// 시간표: 오늘 수업을 홈 화면에 보여 주고(지금 수업은 강조), 누르면 그 과목 폴더로 간다. 여기서 바로 고친다.
import { useCallback, useEffect, useState } from "react";
import { getJSON, postJSON } from "../api/useApi";
import { Button, Chip, Icon } from "../components/ui";

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

export function Timetable({ courses, onPick }: { courses: string[]; onPick: (course: string) => void }) {
  const [rows, setRows] = useState<ClassRow[] | null>(null);
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({ course: "", weekday: todayIndex(), start: "09:00", end: "10:15", place: "" });
  const [error, setError] = useState("");
  const [, tick] = useState(0);

  const load = useCallback(() => { getJSON<ClassRow[]>("/timetable").then(setRows).catch(() => setRows(null)); }, []);
  useEffect(load, [load]);
  useEffect(() => { const t = window.setInterval(() => tick((n) => n + 1), 60000); return () => window.clearInterval(t); }, []);

  if (rows === null) return null; // 서버가 시간표를 모르거나(옛 서버·데모) 못 불러오면 조용히 숨긴다
  const now = currentClass(rows);
  const today = rows.filter((r) => r.weekday === todayIndex());

  const add = async () => {
    setError("");
    try {
      await postJSON("/timetable", form);
      setForm((f) => ({ ...f, course: "", place: "" }));
      load();
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  };
  const remove = async (id: number) => {
    await fetch((import.meta.env.VITE_API_URL ?? "") + `/timetable/${id}`, { method: "DELETE" });
    load();
  };

  return (
    <section className="timetable" aria-label="시간표">
      {now ? (
        <button className={`list-item class-now${now.live ? " live" : ""}`} onClick={() => onPick(now.row.course)}>
          <span className="list-item-icon"><Icon name="chalkboard-teacher" /></span>
          <span className="grow">
            <span className="t-title-s" style={{ display: "block" }}>{now.live ? "지금 수업" : "다음 수업"} · {now.row.course}</span>
            <span className="list-item-sub">{now.row.start}~{now.row.end}{now.row.place ? ` · ${now.row.place}` : ""} · 눌러서 이 과목 열기</span>
          </span>
          <span className="list-item-chev"><Icon name="caret-right" size={18} /></span>
        </button>
      ) : null}
      <div className="row timetable-row">
        <span className="t-caption muted grow">
          {rows.length === 0 ? "시간표를 넣으면 수업 시간에 맞춰 과목을 바로 열어 줘요"
            : today.length ? `오늘 ${today.map((r) => `${r.course} ${r.start}`).join(" · ")}` : "오늘은 수업이 없어요"}
        </span>
        <Chip onClick={() => setEditing((v) => !v)}>{editing ? "닫기" : rows.length ? "시간표" : "시간표 넣기"}</Chip>
      </div>
      {editing && (
        <div className="timetable-edit">
          {DAYS.map((day, i) => {
            const list = rows.filter((r) => r.weekday === i);
            if (!list.length) return null;
            return (
              <div key={day} className="timetable-day">
                <b className="t-caption">{day}</b>
                {list.map((r) => (
                  <span key={r.id} className="timetable-class t-caption">
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
              <Button icon="plus" onClick={() => void add()} disabled={!form.course.trim()}>넣기</Button>
            </div>
            {error && <p className="t-caption" style={{ color: "var(--note-exam-ink)" }}>{error}</p>}
          </div>
        </div>
      )}
    </section>
  );
}
