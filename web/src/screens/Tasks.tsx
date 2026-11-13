// 할 일 모아 보기: 모든 강의에서 받은 과제·공지를 홈에 한데 모은다. 체크하면 끝낸 것으로.
import { useCallback, useEffect, useState } from "react";
import { getJSON } from "../api/useApi";
import { Icon } from "../components/ui";
import { go } from "../router";

interface HomeTask { id: number; title: string; due_text: string | null; done: boolean; kind: string; doc_id: string; doc_title: string; course: string; session_id: string }

export function TasksCard() {
  const [tasks, setTasks] = useState<HomeTask[] | null>(null);
  const [all, setAll] = useState(false);
  const load = useCallback(() => { getJSON<HomeTask[]>("/tasks").then(setTasks).catch(() => setTasks(null)); }, []);
  useEffect(load, [load]);
  if (!tasks) return null;
  const open = tasks.filter((t) => !t.done);
  if (open.length === 0) return null;
  const toggle = async (t: HomeTask) => {
    setTasks((list) => list && list.map((x) => (x.id === t.id ? { ...x, done: true } : x))); // 먼저 화면에서 지우고
    navigator.vibrate?.(15);
    try {
      await fetch((import.meta.env.VITE_API_URL ?? "") + `/tasks/${t.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ done: true }) });
    } catch { load(); }
  };
  return (
    <section className="banner tasks-card" aria-label="할 일">
      <div className="row">
        <Icon name="clipboard-text" art size={30} />
        <strong className="t-title-s grow">할 일 {open.length}개</strong>
        {open.length > 3 && <button className="chip chip-accent" onClick={() => setAll(!all)}>{all ? "접기" : "모두 보기"}</button>}
      </div>
      {(all ? open : open.slice(0, 3)).map((t) => (
        <div key={t.id} className="task-row">
          <button className="task-check" onClick={() => void toggle(t)} aria-label={`${t.title} 끝냄으로 표시`}><Icon name="check" size={16} /></button>
          <button className="grow task-text" onClick={() => go({ name: "lecture", docId: t.doc_id, sessionId: t.session_id })}>
            <span className="t-body" style={{ display: "block" }}>{t.title}</span>
            <span className="t-caption muted">{[t.due_text, t.course || t.doc_title].filter(Boolean).join(" · ")}</span>
          </button>
        </div>
      ))}
    </section>
  );
}
