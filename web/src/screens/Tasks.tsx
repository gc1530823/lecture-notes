// 할 일: 모든 강의에서 받은 과제·공지를 모은다.
//   홈 카드(TasksCard): 가까운 마감 3개
//   할 일 화면(TasksScreen): 달력에 마감 날짜 점 · 날짜별 목록 · 끝낸 일 모아 보기
// 체크해도 바로 사라지지 않는다: 줄이 그어진 채 남고, 아래 '되돌리기'로 언제든 다시 살릴 수 있다.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { getJSON } from "../api/useApi";
import { Icon, TopBar } from "../components/ui";
import { courseTone } from "../lib/course";
import SlidingTabs from "../components/SlidingTabs";
import { TimetableEditor } from "./Timetable";
import { go } from "../router";
import { refreshNotices } from "../lib/notices";

export interface HomeTask {
  id: number; title: string; instructions?: string; due_text: string | null; due_on?: string | null; due_date?: string | null;
  done: boolean; kind: string; doc_id: string; doc_title: string; course: string; session_id: string; checked?: boolean;
}

const API = import.meta.env.VITE_API_URL ?? "";
const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const todayIso = () => iso(new Date());
const dayDiff = (a: string, b: string) => Math.round((Date.parse(a) - Date.parse(b)) / 86400000);

/** D-day 글자: 오늘 · 내일 · D-3 · 3일 지남 */
function dday(due: string | null | undefined): { text: string; tone: "late" | "soon" | "later" } | null {
  if (!due) return null;
  const n = dayDiff(due, todayIso());
  if (n < 0) return { text: `${-n}일 지남`, tone: "late" };
  if (n === 0) return { text: "오늘 마감", tone: "soon" };
  if (n === 1) return { text: "내일 마감", tone: "soon" };
  return { text: `D-${n}`, tone: n <= 3 ? "soon" : "later" };
}

function dueLabel(due: string) {
  const d = new Date(due + "T00:00:00");
  return d.toLocaleDateString("ko-KR", { month: "long", day: "numeric", weekday: "short" });
}

/** 할 일 불러오기 + 체크(되돌리기 포함) + 마감일 고치기 */
function useTasks() {
  const [tasks, setTasks] = useState<HomeTask[] | null>(null);
  const [undo, setUndo] = useState<HomeTask | null>(null);
  const timer = useRef<number>(0);
  const load = useCallback(() => { getJSON<HomeTask[]>("/tasks").then(setTasks).catch(() => setTasks(null)); }, []);
  useEffect(load, [load]);
  useEffect(() => () => window.clearTimeout(timer.current), []);

  const patch = async (id: number, body: object) => {
    try {
      const r = await fetch(`${API}/tasks/${id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      if (!r.ok) throw new Error();
      void refreshNotices();   // 마감 알림도 바뀐 대로
    } catch { load(); }
  };
  const setDone = (t: HomeTask, done: boolean) => {
    setTasks((list) => list && list.map((x) => (x.id === t.id ? { ...x, done } : x)));
    navigator.vibrate?.(done ? 15 : 8);
    void patch(t.id, { done });
    window.clearTimeout(timer.current);
    if (done) {
      setUndo(t);
      timer.current = window.setTimeout(() => setUndo(null), 6000);
    } else setUndo(null);
  };
  const setDue = (t: HomeTask, due: string) => {
    setTasks((list) => list && list.map((x) => (x.id === t.id ? { ...x, due_on: due || null, due_date: due || null, checked: true } : x)));
    void patch(t.id, { due_on: due }).then(() => { if (!due) load(); }); // 지우면 강의에서 들은 날짜로 돌아간다
  };
  // AI 가 찾은 과제 확인: 맞아요 / 이름 고치기 / 지우기
  const check = (t: HomeTask, title?: string) => {
    setTasks((list) => list && list.map((x) => (x.id === t.id ? { ...x, checked: true, title: title || x.title } : x)));
    void patch(t.id, title ? { title } : { checked: true });
  };
  const remove = (t: HomeTask) => {
    if (!confirm(`'${t.title}'을(를) 할 일에서 지울까요? AI가 잘못 찾은 과제일 때 지워 주세요.`)) return;
    setTasks((list) => list && list.filter((x) => x.id !== t.id));
    void fetch(`${API}/tasks/${t.id}`, { method: "DELETE" });
  };
  return { tasks, setDone, setDue, undo, load, check, remove };
}

function UndoBar({ task, onUndo }: { task: HomeTask | null; onUndo: (t: HomeTask) => void }) {
  if (!task) return null;
  return (
    <div className="undo-bar" role="status">
      <Icon name="check-circle" size={18} />
      <span className="grow">‘{task.title.length > 16 ? task.title.slice(0, 16) + "…" : task.title}’ 끝냈어요</span>
      <button onClick={() => onUndo(task)}><Icon name="arrow-counter-clockwise" size={15} /> 되돌리기</button>
    </div>
  );
}

function TaskRow({ t, onDone, onDue, open, onOpen, onCheck, onRemove }: {
  t: HomeTask; onDone: (t: HomeTask, done: boolean) => void; onDue?: (t: HomeTask, due: string) => void; open?: boolean; onOpen?: () => void;
  onCheck?: (t: HomeTask, title?: string) => void; onRemove?: (t: HomeTask) => void;
}) {
  const d = t.done ? null : dday(t.due_date);
  const [name, setName] = useState(t.title);
  const ai = !t.checked && !t.done;
  return (
    <div className={`task-item${t.done ? " done" : ""}${open ? " open" : ""}`}>
      <div className="task-line">
        <button className={`task-box${t.done ? " on" : ""}`} onClick={() => onDone(t, !t.done)}
          aria-label={t.done ? `${t.title} 다시 할 일로` : `${t.title} 끝냄으로 표시`} aria-pressed={t.done}>
          <Icon name="check" size={14} />
        </button>
        <button className="grow task-main" onClick={onOpen ?? (() => go({ name: "lecture", docId: t.doc_id, sessionId: t.session_id }))}>
          <span className="task-title">{t.title}{ai && <em className="ai-found">AI가 찾음</em>}</span>
          <span className="task-meta">
            <i className={`task-dot ${courseTone(t.course)}`} />{t.course || t.doc_title}
            {t.due_text ? ` · ${t.due_text}` : ""}
          </span>
        </button>
        {d && <span className={`dday ${d.tone}`}>{d.text}</span>}
      </div>
      {open && (
        <div className="task-more">
          {t.instructions && <p>{t.instructions}</p>}
          {ai && onCheck && (
            <div className="ai-check">
              <small>강의에서 AI가 찾은 과제예요. 맞는지 한 번 확인해 주세요.</small>
              <div className="row">
                <input className="input grow" value={name} onChange={(e) => setName(e.target.value)} aria-label="과제 이름" />
                <button className="chip chip-accent" onClick={() => onCheck(t, name.trim() !== t.title ? name.trim() : undefined)}>{name.trim() !== t.title ? "고쳐서 저장" : "맞아요"}</button>
                {onRemove && <button className="chip chip-default danger" onClick={() => onRemove(t)}>지우기</button>}
              </div>
            </div>
          )}
          {onDue && (
            <label className="task-due">
              <Icon name="calendar-dots" size={16} />
              <span className="grow">마감일</span>
              <input type="date" className="input" value={t.due_date ?? ""} onChange={(e) => onDue(t, e.target.value)} />
            </label>
          )}
          <button className="link-row" onClick={() => go({ name: "lecture", docId: t.doc_id, sessionId: t.session_id })}>
            <Icon name="headphones" art size={20} /><span className="grow">이 과제를 말한 강의 보기</span><Icon name="caret-right" size={14} />
          </button>
        </div>
      )}
    </div>
  );
}

/** 홈 카드: 가까운 마감 순으로 3개 + 달력으로 */
export function TasksCard() {
  const { tasks, setDone, undo } = useTasks();
  const [kept] = useState(() => new Set<number>()); // 이 화면에서 방금 체크한 것은 줄 그은 채 남긴다
  if (!tasks) return null;
  const list = tasks.filter((t) => !t.done || kept.has(t.id))
    .sort((a, b) => (a.due_date ?? "9999").localeCompare(b.due_date ?? "9999"));
  const left = tasks.filter((t) => !t.done).length;
  if (list.length === 0 && !undo) return null;
  const toggle = (t: HomeTask, done: boolean) => { kept.add(t.id); setDone(t, done); };
  // 알림이 없는 웹·아이폰에서도 놓치지 않게: 오늘 마감·마감 지남을 맨 위에 눈에 띄게
  const today = todayIso();
  const urgent = tasks.filter((t) => !t.done && t.due_date && t.due_date <= today);
  const late = urgent.filter((t) => t.due_date! < today).length;
  return (
    <section className={`banner tasks-card${urgent.length ? " urgent" : ""}`} aria-label="할 일">
      {urgent.length > 0 && (
        <p className="tasks-urgent"><Icon name="warning-circle" size={15} />
          {[urgent.length - late ? `오늘 마감 ${urgent.length - late}개` : "", late ? `마감 지남 ${late}개` : ""].filter(Boolean).join(" · ")}</p>
      )}
      <div className="row">
        <Icon name="clipboard-text" art size={30} />
        <strong className="t-title-s grow">할 일 {left}개</strong>
        <button className="chip chip-accent" onClick={() => go({ name: "tasks" })}><Icon name="calendar-dots" size={14} /> 달력으로 보기</button>
      </div>
      {list.slice(0, 3).map((t) => <TaskRow key={t.id} t={t} onDone={toggle} />)}
      <UndoBar task={undo} onUndo={(t) => setDone(t, false)} />
    </section>
  );
}

const WEEK = ["일", "월", "화", "수", "목", "금", "토"];

/** 할 일 화면: 달력 + 목록 + 끝낸 일 */
function TasksPane() {
  const { tasks, setDone, setDue, undo, check, remove } = useTasks();
  const [month, setMonth] = useState(() => { const d = new Date(); return new Date(d.getFullYear(), d.getMonth(), 1); });
  const [day, setDay] = useState<string | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  const [showDone, setShowDone] = useState(false);
  // 달력은 이번 주 한 줄로 접어 두고, 할 일 목록이 먼저 보이게 (펼치면 한 달)
  const [calOpen, setCalOpen] = useState(false);
  const [kept] = useState(() => new Set<number>());
  const today = todayIso();

  const byDay = useMemo(() => {
    const m = new Map<string, HomeTask[]>();
    for (const t of tasks ?? []) if (t.due_date) m.set(t.due_date, [...(m.get(t.due_date) ?? []), t]);
    return m;
  }, [tasks]);

  if (!tasks) return (
    <p className="muted">불러오는 중…</p>
  );

  const toggle = (t: HomeTask, done: boolean) => { kept.add(t.id); setDone(t, done); };
  const active = tasks.filter((t) => !t.done || kept.has(t.id));
  const finished = tasks.filter((t) => t.done && !kept.has(t.id));
  const left = tasks.filter((t) => !t.done).length;

  // 달력 칸: 그 달 1일의 요일만큼 비우고 시작
  const first = month.getDay();
  const days = new Date(month.getFullYear(), month.getMonth() + 1, 0).getDate();
  const cells: (string | null)[] = [...Array(first).fill(null),
    ...Array.from({ length: days }, (_, i) => iso(new Date(month.getFullYear(), month.getMonth(), i + 1)))];
  const shift = (n: number) => { setMonth(new Date(month.getFullYear(), month.getMonth() + n, 1)); setDay(null); };
  const focus = cells.indexOf(day ?? today);
  const row = focus >= 0 ? Math.floor(focus / 7) : 0;
  const visible = calOpen ? cells : cells.slice(row * 7, row * 7 + 7);

  // 목록 묶음
  const sorted = [...active].sort((a, b) => (a.due_date ?? "9999").localeCompare(b.due_date ?? "9999"));
  const groups: [string, HomeTask[]][] = day
    ? [[dueLabel(day), sorted.filter((t) => t.due_date === day)]]
    : [
      ["마감 지남", sorted.filter((t) => t.due_date && t.due_date < today)],
      ["오늘", sorted.filter((t) => t.due_date === today)],
      ["이번 주", sorted.filter((t) => t.due_date && t.due_date > today && dayDiff(t.due_date, today) <= 7)],
      ["그다음", sorted.filter((t) => t.due_date && dayDiff(t.due_date, today) > 7)],
      ["마감일 모름", sorted.filter((t) => !t.due_date)],
    ];

  return (
    <div className="tasks-screen">
      <div>
        <section className="cal" aria-label="마감 달력">
          <div className="cal-head">
            <button className="round" onClick={() => shift(-1)} aria-label="지난달"><Icon name="caret-left" size={16} /></button>
            <b className="grow">{month.getFullYear()}년 {month.getMonth() + 1}월</b>
            <button className="cal-today" onClick={() => { const d = new Date(); setMonth(new Date(d.getFullYear(), d.getMonth(), 1)); setDay(null); }}>오늘</button>
            <button className="round" onClick={() => shift(1)} aria-label="다음 달"><Icon name="caret-right" size={16} /></button>
          </div>
          <div className="cal-grid">
            {WEEK.map((w, i) => <span key={w} className={`cal-w${i === 0 ? " sun" : i === 6 ? " sat" : ""}`}>{w}</span>)}
            {visible.map((c, i) => {
              if (!c) return <span key={`e${i}`} />;
              const list = byDay.get(c) ?? [];
              const openList = list.filter((t) => !t.done);
              const late = c < today && openList.length > 0;
              return (
                <button key={c} className={`cal-day${c === today ? " today" : ""}${c === day ? " sel" : ""}${late ? " late" : ""}${list.length && !openList.length ? " cleared" : ""}`}
                  onClick={() => setDay(c === day ? null : c)} aria-label={`${dueLabel(c)}${list.length ? `, 할 일 ${openList.length}개` : ""}`}>
                  <span className="n">{Number(c.slice(8))}</span>
                  <span className="dots">{list.slice(0, 3).map((t) => <i key={t.id} className={`${courseTone(t.course)}${t.done ? " done" : ""}`} />)}</span>
                </button>
              );
            })}
          </div>
          <button className="cal-fold" onClick={() => setCalOpen(!calOpen)} aria-expanded={calOpen}>
            {calOpen ? "이번 주만 보기" : "한 달 보기"} <Icon name={calOpen ? "caret-up" : "caret-down"} size={13} />
          </button>
        </section>

        <div className="row tasks-sum">
          <strong className="grow">{day ? dueLabel(day) : `남은 할 일 ${left}개`}</strong>
          {day && <button className="chip chip-default" onClick={() => setDay(null)}>전체 보기</button>}
        </div>

        {groups.every(([, l]) => l.length === 0) && (
          <p className="tasks-empty">{day ? "이날 마감인 할 일이 없어요" : tasks.length ? "남은 할 일이 없어요. 잘했어요!" : "강의에서 과제·공지를 들으면 여기에 모여요"}</p>
        )}
        {groups.map(([label, list]) => list.length > 0 && (
          <section key={label} className="task-group">
            {!day && <h3 className={label === "마감 지남" ? "late" : ""}>{label} <span>{list.length}</span></h3>}
            {list.map((t) => <TaskRow key={t.id} t={t} onDone={toggle} onDue={setDue} open={open === t.id} onOpen={() => setOpen(open === t.id ? null : t.id)} onCheck={check} onRemove={remove} />)}
          </section>
        ))}

        {finished.length > 0 && (
          <section className="task-group finished">
            <button className="task-fold" onClick={() => setShowDone(!showDone)} aria-expanded={showDone}>
              <Icon name="check-circle" size={18} /><span className="grow">끝낸 일 {finished.length}개</span>
              <Icon name={showDone ? "caret-up" : "caret-down"} size={14} />
            </button>
            {showDone && <>
              <p className="t-caption muted">잘못 체크했으면 네모를 다시 누르면 할 일로 돌아가요.</p>
              {finished.map((t) => <TaskRow key={t.id} t={t} onDone={toggle} />)}
            </>}
          </section>
        )}
      </div>
      <UndoBar task={undo} onUndo={(t) => setDone(t, false)} />
    </div>
  );
}

/** '일정' 탭: 시간표 · 할 일 (아래 탭 하나로 묶었다) */
export function ScheduleScreen({ view }: { view: "timetable" | "tasks" }) {
  const [tab, setTab] = useState(view);
  return (
    <div className="screen schedule">
      <TopBar title="일정" />
      <div className="screen-body">
        <SlidingTabs label="일정 보기" value={tab} onChange={setTab} items={[["timetable", "시간표"], ["tasks", "할 일"]] as const} />
        <div key={tab} className="pane-in">{tab === "timetable"
          ? <TimetableEditor onPick={(course) => { try { localStorage.setItem("ln.course", course); } catch { /* 괜찮다 */ } go({ name: "home" }); }} />
          : <TasksPane />}</div>
      </div>
    </div>
  );
}
