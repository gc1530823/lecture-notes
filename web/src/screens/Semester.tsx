// 학기 전체: 개념 지도(2D) · 학기 튜터 · 시험 D-day
import SlidingTabs from "../components/SlidingTabs";
import { useEffect, useMemo, useState } from "react";
import type { DocumentBrief } from "../api/types";
import { getJSON, postJSON, useApi } from "../api/useApi";
import { Button, Chip, Empty, Hint, Icon, ListItem, TopBar } from "../components/ui";
import { back, go } from "../router";
import { askYes, tell } from "../components/Dialog";

interface Occurrence { doc_id: string; doc_title: string; session_id: string; page_no: number | null; start_ms: number; started_at: number }
interface Node { id: string; term: string; definition: string; occurrences: Occurrence[]; docs: string[]; count: number; links: number }
interface Edge { source: string; target: string; weight: number; reasons: string[] }

const PALETTE = ["explanation", "example", "emphasis", "exam", "notice", "tip", "qa"];

/** 가벼운 힘 배치: 이어진 용어는 당기고, 모든 용어는 밀어내고, 같은 강의자료 용어는 같은 쪽으로 */
function layout(nodes: Node[], edges: Edge[], width: number, height: number) {
  const docs = [...new Set(nodes.map((n) => n.docs[0]))];
  const anchor = new Map(docs.map((d, i) => {
    // 강의자료가 하나면 가운데, 여럿이면 둥글게 나눠 앉힌다
    const a = (i / Math.max(1, docs.length)) * Math.PI * 2, r = docs.length > 1 ? 0.28 : 0;
    return [d, { x: width / 2 + Math.cos(a) * width * r, y: height / 2 + Math.sin(a) * height * r }];
  }));
  const pos = new Map(nodes.map((n, i) => {
    const a = anchor.get(n.docs[0])!;
    return [n.id, { x: a.x + Math.cos(i * 2.4) * 30, y: a.y + Math.sin(i * 2.4) * 30 }];
  }));
  for (let step = 0; step < 220; step++) {
    const cool = 1 - step / 220;
    const force = new Map(nodes.map((n) => [n.id, { x: 0, y: 0 }]));
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const a = pos.get(nodes[i].id)!, b = pos.get(nodes[j].id)!;
        const dx = a.x - b.x, dy = a.y - b.y, d2 = Math.max(dx * dx + dy * dy, 25);
        const f = 2600 / d2;
        force.get(nodes[i].id)!.x += dx * f / Math.sqrt(d2); force.get(nodes[i].id)!.y += dy * f / Math.sqrt(d2);
        force.get(nodes[j].id)!.x -= dx * f / Math.sqrt(d2); force.get(nodes[j].id)!.y -= dy * f / Math.sqrt(d2);
      }
    }
    for (const e of edges) {
      const a = pos.get(e.source), b = pos.get(e.target);
      if (!a || !b) continue;
      const dx = b.x - a.x, dy = b.y - a.y;
      force.get(e.source)!.x += dx * 0.02 * e.weight; force.get(e.source)!.y += dy * 0.02 * e.weight;
      force.get(e.target)!.x -= dx * 0.02 * e.weight; force.get(e.target)!.y -= dy * 0.02 * e.weight;
    }
    for (const n of nodes) {
      const p = pos.get(n.id)!, f = force.get(n.id)!, a = anchor.get(n.docs[0])!;
      f.x += (a.x - p.x) * 0.01; f.y += (a.y - p.y) * 0.01;
      p.x = Math.min(width - 40, Math.max(40, p.x + Math.max(-12, Math.min(12, f.x)) * cool));
      p.y = Math.min(height - 24, Math.max(24, p.y + Math.max(-12, Math.min(12, f.y)) * cool));
    }
  }
  return { pos, docs };
}

export default function Semester({ tab }: { tab: string }) {
  return (
    <div className="screen">
      <TopBar title="학기 전체" onBack={() => back({ name: "home" })} />
      <div className="screen-body">
        <SlidingTabs label="학기 전체" items={[["map", "개념 지도"], ["tutor", "질문하기"], ["exams", "시험 D-day"]] as const}
          value={tab as "map" | "tutor" | "exams"} onChange={(k) => go({ name: "semester", tab: k })} />
        {tab === "map" && <ConceptMap />}
        {tab === "tutor" && <SemesterTutor />}
        {tab === "exams" && <Exams />}
      </div>
    </div>
  );
}

function ConceptMap() {
  const { data, error } = useApi<{ nodes: Node[]; edges: Edge[] }>("/semester/concepts");
  const [picked, setPicked] = useState<string | null>(null);
  const W = 360, H = 420;
  const nodes = useMemo(() => (data?.nodes ?? []).slice(0, 60), [data]);
  const edges = useMemo(() => (data?.edges ?? []).filter((e) => nodes.some((n) => n.id === e.source) && nodes.some((n) => n.id === e.target)), [data, nodes]);
  const { pos, docs } = useMemo(() => layout(nodes, edges, W, H), [nodes, edges]);

  if (error) return <Empty icon="warning-circle">{error}</Empty>;
  if (!data) return <p className="muted">용어를 모으는 중…</p>;
  if (nodes.length === 0) return (
    <Empty icon="tree-structure" action={{ label: "첫 수업 녹음하기", icon: "microphone", onClick: () => go({ name: "home" }) }}>
      <strong className="t-title-s">아직 별자리가 비어 있어요</strong>
    </Empty>
  );

  const node = nodes.find((n) => n.id === picked);
  const neighbors = new Set(edges.filter((e) => e.source === picked || e.target === picked).flatMap((e) => [e.source, e.target]));
  const docColor = (d: string) => `var(--note-${PALETTE[docs.indexOf(d) % PALETTE.length]}-ink)`;
  const titles = new Map(nodes.flatMap((n) => n.occurrences.map((o) => [o.doc_id, o.doc_title] as const)));

  return (
    <>
      <Hint icon="tree-structure">용어 <b>{data.nodes.length}개</b>예요. 함께 설명됐거나 뜻에 서로 나오면 이어요. 누르면 그 강의 그 순간으로 갈 수 있어요.</Hint>
      <div className="scroll-x" style={{ flexWrap: "wrap" }}>
        {docs.map((d) => <span key={d} className="chip chip-default"><span className="dot" style={{ background: docColor(d) }} /> {titles.get(d)}</span>)}
      </div>
      <svg className="concept-map" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="학기 개념 지도">
        {edges.map((e, i) => {
          const a = pos.get(e.source)!, b = pos.get(e.target)!;
          const on = picked && (e.source === picked || e.target === picked);
          return <line key={i} x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="var(--text-tertiary)" strokeOpacity={on ? 0.9 : picked ? 0.12 : 0.35} strokeWidth={Math.min(4, e.weight) * (on ? 1.2 : 0.8)} />;
        })}
        {nodes.map((n) => {
          const p = pos.get(n.id)!;
          const dim = picked && n.id !== picked && !neighbors.has(n.id);
          const r = 6 + Math.min(10, n.count * 2 + n.links);
          return (
            <g key={n.id} transform={`translate(${p.x},${p.y})`} opacity={dim ? 0.25 : 1} onClick={() => setPicked(picked === n.id ? null : n.id)} style={{ cursor: "pointer" }}>
              <circle r={r} fill={docColor(n.docs[0])} fillOpacity={0.85} stroke={n.id === picked ? "var(--text-primary)" : "var(--bg-card)"} strokeWidth={2} />
              <text y={r + 12} textAnchor="middle" className="concept-label">{n.term.length > 12 ? n.term.slice(0, 11) + "…" : n.term}</text>
            </g>
          );
        })}
      </svg>
      {node ? (
        <div className="banner">
          <strong className="t-title-m">{node.term}</strong>
          <p className="t-body">{node.definition}</p>
          {neighbors.size > 1 && (
            <div className="scroll-x" style={{ flexWrap: "wrap" }}>
              {[...neighbors].filter((id) => id !== node.id).map((id) => (
                <Chip key={id} variant="accent" onClick={() => setPicked(id)}>{nodes.find((n) => n.id === id)?.term}</Chip>
              ))}
            </div>
          )}
          <span className="t-caption muted">나온 곳 {node.occurrences.length}번</span>
          {node.occurrences.map((o, i) => (
            <ListItem key={i} icon="play" title={`${o.doc_title}${o.page_no ? `, ${o.page_no}쪽` : ""}`}
              subtitle={`${new Date(o.started_at * 1000).toLocaleDateString("ko-KR", { month: "long", day: "numeric" })} 강의, ${Math.floor(o.start_ms / 60000)}분쯤`}
              onClick={() => go({ name: "lecture", docId: o.doc_id, sessionId: o.session_id })} />
          ))}
        </div>
      ) : (
        <div className="term-list">
          {nodes.slice(0, 12).map((n) => (
            <button key={n.id} className="chip chip-accent" onClick={() => setPicked(n.id)}>{n.term} <span className="faint">{n.count}</span></button>
          ))}
        </div>
      )}
    </>
  );
}

function SemesterTutor() {
  type Msg = { role: "user" | "assistant"; content: string; sources?: { doc_id: string; doc_title: string; session_id: string; page_no: number }[] };
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const send = async (text: string) => {
    if (!text.trim() || busy) return;
    const next: Msg[] = [...messages, { role: "user", content: text.trim() }];
    setMessages(next); setInput(""); setBusy(true);
    try {
      const r = await postJSON<{ answer: string; sources: Msg["sources"] }>("/semester/tutor", { messages: next.map(({ role, content }) => ({ role, content })) });
      setMessages([...next, { role: "assistant", content: r.answer, sources: r.sources }]);
    } catch (e) {
      setMessages([...next, { role: "assistant", content: `답하지 못했어요: ${e instanceof Error ? e.message : e}` }]);
    }
    setBusy(false);
  };
  return (
    <>
      <Hint icon="chats-circle">들은 강의 전체에서 찾아 답해요</Hint>
      {messages.length === 0 && (
        <div className="scroll-x" style={{ flexWrap: "wrap" }}>
          {["지금까지 배운 것 한 번에 정리해 줘", "앞 강의랑 이번 강의가 어떻게 이어져?", "시험 범위에서 제일 중요한 개념 3개는?"].map((q) => (
            <Chip key={q} variant="accent" onClick={() => send(q)}>{q}</Chip>
          ))}
        </div>
      )}
      <div className="chat" aria-live="polite">
        {messages.map((m, i) => (
          <div key={i} className={`bubble ${m.role === "user" ? "bubble-me" : "bubble-ai"}`}>
            {m.content}
            {m.sources?.length ? (
              <div className="scroll-x" style={{ flexWrap: "wrap", marginTop: 8 }}>
                {m.sources.map((s, j) => (
                  <Chip key={j} variant="default" onClick={() => go({ name: "lecture", docId: s.doc_id, sessionId: s.session_id })}>{s.doc_title} {s.page_no}쪽</Chip>
                ))}
              </div>
            ) : null}
          </div>
        ))}
        {busy && <div className="bubble bubble-ai muted">찾아보는 중…</div>}
      </div>
      <form className="row" onSubmit={(e) => { e.preventDefault(); void send(input); }}>
        <input className="input" value={input} onChange={(e) => setInput(e.target.value)} placeholder="여러 강의에 걸친 질문도 돼요" aria-label="질문" />
        <Button type="submit" disabled={busy || !input.trim()} aria-label="보내기" icon="chats-circle" />
      </form>
    </>
  );
}

export interface Exam { id: number; title: string; exam_date: string; doc_ids: string[] }
interface PlanDay { date: string; d: number; pages: { doc_id: string; doc_title: string; page_no: number; title: string; reasons: string[] }[]; todo: string[] }

export const dday = (date: string) => {
  const ms = new Date(date + "T00:00:00").getTime() - new Date(new Date().toDateString()).getTime();
  const d = Math.round(ms / 86400000);
  return d > 0 ? `D-${d}` : d === 0 ? "D-DAY" : `D+${-d}`;
};

function Exams() {
  const { data: exams, reload } = useApi<Exam[]>("/exams");
  const { data: docs } = useApi<DocumentBrief[]>("/documents");
  const [open, setOpen] = useState<number | null>(null);
  const [form, setForm] = useState({ title: "중간고사", date: "", docs: [] as string[] });

  useEffect(() => { if (open === null && exams?.length) setOpen(exams.find((e) => e.exam_date >= new Date().toISOString().slice(0, 10))?.id ?? null); }, [exams, open]);

  const create = async () => {
    try {
      const e = await postJSON<Exam>("/exams", { title: form.title, exam_date: form.date, doc_ids: form.docs });
      await reload();
      setOpen(e.id);
      setForm({ title: "중간고사", date: "", docs: [] });
    } catch (err) { tell(err instanceof Error ? err.message : String(err)); }
  };
  const remove = async (id: number) => {
    if (!await askYes("이 시험 계획을 지울까요?")) return;
    await fetch(`${import.meta.env.VITE_API_URL ?? ""}/exams/${id}`, { method: "DELETE" });
    setOpen(null);
    await reload();
  };

  return (
    <>
      {exams?.map((e) => (
        <div key={e.id}>
          <button className="list-item" onClick={() => setOpen(open === e.id ? null : e.id)}>
            <span className="list-item-icon dday">{dday(e.exam_date)}</span>
            <span className="grow">
              <span className="t-title-s" style={{ display: "block" }}>{e.title}</span>
              <span className="list-item-sub">{e.exam_date}, 범위 {e.doc_ids.length}개 자료</span>
            </span>
            <span className="list-item-chev"><Icon name={open === e.id ? "caret-left" : "caret-right"} size={18} /></span>
          </button>
          {open === e.id && <Plan exam={e} onDelete={() => remove(e.id)} />}
        </div>
      ))}
      <div className="banner">
        <strong className="t-title-s">시험 추가</strong>
        <input className="input" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} aria-label="시험 이름" placeholder="시험 이름" />
        <input className="input" type="date" value={form.date} onChange={(e) => setForm({ ...form, date: e.target.value })} aria-label="시험 날짜" />
        <span className="t-caption muted">시험 범위</span>
        <div className="scroll-x" style={{ flexWrap: "wrap" }}>
          {docs?.map((d) => (
            <Chip key={d.id} variant={form.docs.includes(d.id) ? "selected" : "default"}
              onClick={() => setForm({ ...form, docs: form.docs.includes(d.id) ? form.docs.filter((x) => x !== d.id) : [...form.docs, d.id] })}>{d.title}</Chip>
          ))}
        </div>
        <Button onClick={create} disabled={!form.date || form.docs.length === 0} icon="timer">계획 만들기</Button>
      </div>
    </>
  );
}

function Plan({ exam, onDelete }: { exam: Exam; onDelete: () => void }) {
  const [plan, setPlan] = useState<{ days_left: number; days: PlanDay[] } | null>(null);
  useEffect(() => { getJSON<typeof plan>(`/exams/${exam.id}/plan`).then(setPlan).catch(() => {}); }, [exam.id]);
  if (!plan) return <p className="muted">계획을 짜는 중…</p>;
  if (plan.days_left < 0) return <div className="banner"><p className="t-body">이미 지난 시험이에요.</p><Button variant="secondary" onClick={onDelete}>지우기</Button></div>;
  return (
    <div className="plan">
      {plan.days.map((day, i) => (
        <div key={day.date} className={`plan-day${i === 0 ? " today" : ""}`}>
          <div className="row">
            <strong className="t-title-s grow">{i === 0 ? "오늘" : new Date(day.date + "T00:00:00").toLocaleDateString("ko-KR", { month: "short", day: "numeric", weekday: "short" })}</strong>
            <span className="t-caption faint">{day.d === 0 ? "시험날" : `D-${day.d}`}</span>
          </div>
          {day.todo.map((t, j) => <p key={j} className="t-body plain-line">{t}</p>)}
          {day.pages.length > 0 && (
            <div className="scroll-x" style={{ flexWrap: "wrap" }}>
              {day.pages.map((p, j) => (
                <Chip key={j} variant="accent" onClick={() => go({ name: "jokbo", docId: p.doc_id })}>{p.doc_title} {p.page_no}쪽{p.title ? ` ${p.title.slice(0, 10)}` : ""}</Chip>
              ))}
            </div>
          )}
          {i === 0 && <Button block variant="secondary" icon="brain" onClick={() => go({ name: "review" })}>오늘의 복습 시작</Button>}
        </div>
      ))}
      <button className="t-caption muted" onClick={onDelete} style={{ alignSelf: "flex-end" }}>이 시험 지우기</button>
    </div>
  );
}

/** 홈: 가장 가까운 시험 D-day 띠 */
export function ExamBanner() {
  const [exam, setExam] = useState<Exam | null>(null);
  useEffect(() => {
    getJSON<Exam[]>("/exams").then((all) => setExam(all.find((e) => e.exam_date >= new Date().toISOString().slice(0, 10)) ?? null)).catch(() => {});
  }, []);
  if (!exam) return null;
  return (
    <button className="list-item exam-banner" onClick={() => go({ name: "semester", tab: "exams" })}>
      <span className="list-item-icon dday">{dday(exam.exam_date)}</span>
      <span className="grow">
        <span className="t-title-s" style={{ display: "block" }}>{exam.title}</span>
        <span className="list-item-sub">오늘 할 것 보기 ({exam.exam_date})</span>
      </span>
      <span className="list-item-chev"><Icon name="caret-right" size={18} /></span>
    </button>
  );
}
