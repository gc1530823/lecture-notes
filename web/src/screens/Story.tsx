// 강의 스토리 · 수업 흐름 · 연속 공부.
// 스토리: 강의 하나를 1분 안에 넘겨 보는 카드 묶음 (시험·강조·목소리 높인 순간·막힌 곳·과제·새 용어). 눌러서 그 순간 녹음을 듣는다.
// 흐름: 1분 단위 막대. 진할수록 중요한 구간(시험 언급·필기·모르겠다·목소리). 눌러서 그 시각으로.
// 서버가 규칙만으로 만든다 (AI 호출 없음).
import { useCallback, useEffect, useRef, useState } from "react";
import { getJSON } from "../api/useApi";
import { Button, Icon } from "../components/ui";
import { Confetti, Count, Words } from "../lib/motion";
import { Mascot } from "../components/Mascot";
import { go } from "../router";

interface Card { kind: string; label: string; text: string; page_no: number | null; at_ms: number | null; quote: string; tone: string }
interface Minute { minute: number; speech: number; notes: number; exam: number; confused: number; loud: number; page: number | null; weight: number }
interface StoryData {
  title: string; started_at: number; cards: Card[];
  stats: { minutes: number; notes: number; exam: number; terms: number; confused: number; pages: number };
  flow: { duration_ms: number; minutes: Minute[] };
}

const ICON: Record<string, string> = { cover: "sparkle", exam: "target", emphasis: "megaphone", loud: "microphone", confused: "hand-palm", task: "clipboard-text", term: "book-open-text", note: "note-pencil", end: "graduation-cap" };
const CARD_MS = 6500;

const clock = (ms: number) => `${Math.floor(ms / 60000)}:${String(Math.floor(ms / 1000) % 60).padStart(2, "0")}`;

/** 그 순간으로: 강의자료 위에서 그 쪽을 열고 녹음을 그 시각부터 */
export function jumpToMoment(docId: string, sessionId: string, page: number | null, ms: number | null) {
  try {
    if (page) sessionStorage.setItem("ln.jump", String(page));
    if (ms != null) sessionStorage.setItem("ln.jumpMs", String(ms));
  } catch { /* 괜찮다 */ }
  go({ name: "lecture", docId, sessionId });
}

export function StoryEntry({ docId, sessionId }: { docId: string; sessionId: string }) {
  const [data, setData] = useState<StoryData | null>(null);
  const [open, setOpen] = useState(false);
  useEffect(() => { getJSON<StoryData>(`/sessions/${sessionId}/story`).then(setData).catch(() => setData(null)); }, [sessionId]);
  if (!data || data.cards.length <= 2) return null;
  const s = data.stats;
  return (
    <>
      <button className="story-entry" onClick={() => setOpen(true)}>
        <span className="story-ring"><Icon name="play" size={20} /></span>
        <span className="grow">
          <span className="t-title-s" style={{ display: "block" }}>1분 스토리로 보기</span>
          <span className="list-item-sub">{[s.exam ? `시험 언급 ${s.exam}번` : "", `필기 ${s.notes}개`, s.minutes ? `${s.minutes}분 수업` : ""].filter(Boolean).join(" · ")}</span>
        </span>
        <span className="story-count t-caption">{data.cards.length}장</span>
      </button>
      <FlowStrip flow={data.flow} onJump={(m) => jumpToMoment(docId, sessionId, m.page, m.minute * 60000)} />
      {open && <StoryViewer data={data} onClose={() => setOpen(false)}
        onListen={(c) => jumpToMoment(docId, sessionId, c.page_no, c.at_ms)}
        onStudy={() => { setOpen(false); go({ name: "session", docId, sessionId, tab: "study" }); }} />}
    </>
  );
}

function StoryViewer({ data, onClose, onListen, onStudy }: { data: StoryData; onClose: () => void; onListen: (c: Card) => void; onStudy: () => void }) {
  const [index, setIndex] = useState(0);
  const [paused, setPaused] = useState(false);
  const held = useRef(0);
  const card = data.cards[index];
  const last = index === data.cards.length - 1;

  const move = useCallback((d: number) => {
    setIndex((i) => {
      const next = i + d;
      if (next < 0) return 0;
      if (next >= data.cards.length) { onClose(); return i; }
      return next;
    });
  }, [data.cards.length, onClose]);

  // 카드마다 6.5초 뒤 다음으로 (마지막 카드는 머문다, 누르고 있으면 멈춘다)
  useEffect(() => {
    if (paused || last) return;
    const t = window.setTimeout(() => move(1), CARD_MS);
    return () => window.clearTimeout(t);
  }, [index, paused, last, move]);

  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key === "ArrowRight" || e.key === " ") move(1);
      if (e.key === "ArrowLeft") move(-1);
    };
    window.addEventListener("keydown", key);
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { window.removeEventListener("keydown", key); document.body.style.overflow = overflow; };
  }, [move, onClose]);

  const down = () => { held.current = Date.now(); setPaused(true); };
  const up = (d: number) => { setPaused(false); if (Date.now() - held.current < 250) move(d); };

  return (
    <div className={`story tone-${card.tone}`} role="dialog" aria-modal="true" aria-label="강의 스토리">
      <div className="story-bg" aria-hidden="true"><i /><i /><i /></div>
      <div className="story-bars" aria-hidden="true">
        {data.cards.map((_, i) => (
          <span key={i}><b className={i < index ? "done" : i === index ? (last ? "done" : "run") : ""} key={i === index ? `r${index}` : i}
            style={i === index && !last ? { animationDuration: `${CARD_MS}ms`, animationPlayState: paused ? "paused" : "running" } : undefined} /></span>
        ))}
      </div>
      <header className="story-head">
        <span className="grow t-caption">{data.title} · {new Date(data.started_at * 1000).toLocaleDateString("ko-KR", { month: "long", day: "numeric" })}</span>
        <button onClick={onClose} aria-label="닫기"><Icon name="x" /></button>
      </header>
      <button className="story-tap left" onPointerDown={down} onPointerUp={() => up(-1)} onPointerLeave={() => setPaused(false)} aria-label="이전 카드" />
      <button className="story-tap right" onPointerDown={down} onPointerUp={() => up(1)} onPointerLeave={() => setPaused(false)} aria-label="다음 카드" />
      <div className="story-card" key={index} aria-live="polite">
        <span className="story-label"><Icon name={ICON[card.kind] ?? "sparkle"} size={18} /> {card.label}</span>
        {card.kind === "end" ? (
          <>
            <Confetti />
            <span className="story-mascot"><Mascot mood="happy" size={92} /></span>
            <h2 className="story-text big"><Words text="오늘도 한 강의 끝!" /></h2>
            <div className="story-stats">
              <div><b><Count to={data.stats.minutes} /></b><span>분 수업</span></div>
              <div><b><Count to={data.stats.notes} /></b><span>필기</span></div>
              <div><b><Count to={data.stats.exam} /></b><span>시험 언급</span></div>
              <div><b><Count to={data.stats.terms} /></b><span>새 용어</span></div>
            </div>
          </>
        ) : (
          <>
            <h2 className={`story-text${card.text.length < 60 ? " big" : ""}`}><Words text={card.text} /></h2>
            {card.quote && <p className="story-quote">“{card.quote}”</p>}
            {(card.page_no || card.at_ms != null) && (
              <span className="story-meta t-caption">{[card.page_no ? `${card.page_no}쪽` : "", card.at_ms != null ? clock(card.at_ms) : ""].filter(Boolean).join(" · ")}</span>
            )}
          </>
        )}
      </div>
      <footer className="story-foot">
        {card.kind === "end"
          ? <Button icon="cards" onClick={onStudy}>바로 복습하기</Button>
          : card.at_ms != null && <Button variant="secondary" icon="headphones" onClick={() => onListen(card)}>이 순간 듣기</Button>}
      </footer>
    </div>
  );
}

/** 수업 흐름: 1분에 막대 하나. 높이·진하기 = 중요도, 빨강 = 시험 언급, 점 = 모르겠다 */
export function FlowStrip({ flow, onJump }: { flow: StoryData["flow"]; onJump: (m: Minute) => void }) {
  const [picked, setPicked] = useState<Minute | null>(null);
  if (flow.minutes.length < 3) return null;
  const top = [...flow.minutes].sort((a, b) => b.weight - a.weight)[0];
  const info = picked ?? top;
  return (
    <section className="flow" aria-label="수업 흐름">
      <div className="row">
        <h2 className="t-title-s grow">수업 흐름</h2>
        <span className="t-caption muted">진할수록 중요한 구간</span>
      </div>
      <div className="flow-bars" style={{ gridTemplateColumns: `repeat(${flow.minutes.length}, 1fr)` }}>
        {flow.minutes.map((m, i) => (
          <button key={m.minute} className={`flow-bar${m.exam ? " exam" : ""}${info === m ? " on" : ""}`}
            style={{ "--h": `${12 + m.weight * 88}%`, "--o": 0.25 + m.weight * 0.75, animationDelay: `${Math.min(i * 14, 700)}ms` } as React.CSSProperties}
            onClick={() => setPicked(m)} aria-label={`${m.minute}분${m.exam ? " 시험 언급" : ""}${m.confused ? " 모르겠다 표시" : ""}`}>
            {m.confused > 0 && <i />}
          </button>
        ))}
      </div>
      <button className="flow-info" onClick={() => onJump(info)}>
        <span className="grow t-caption">
          <b>{info.minute}분쯤{info.page ? ` · ${info.page}쪽` : ""}</b>{" "}
          {[info.exam ? "시험에 나온다고 한 구간" : "", info.confused ? "모르겠다고 표시" : "", info.loud ? "목소리를 높임" : "", info.notes ? `필기 ${info.notes}개` : ""].filter(Boolean).join(" · ") || "조용히 지나간 구간"}
        </span>
        <span className="t-caption flow-go"><Icon name="play" size={14} /> 여기부터 듣기</span>
      </button>
    </section>
  );
}

interface Streak { streak: number; best: number; today: boolean; week: { date: string; done: boolean }[]; days: number }

function Carrot() {
  return (
    <svg className="carrot" viewBox="0 0 26 34" aria-hidden="true">
      <path className="c-leaf" d="M13 11 C9 5 9 2 12 1 C14 3 14 6 13 11 Z M13 11 C17 5 20 4 22 6 C21 9 17 10 13 11 Z M13 11 C8 8 5 8 4 10 C6 12 9 12 13 11 Z" />
      <path className="c-body" d="M7 12 Q13 8 19 12 Q20 22 13 33 Q6 22 7 12 Z" />
    </svg>
  );
}

/** 당근 모으기: 강의를 듣거나 복습한 날마다 쫑긋에게 당근 하나 (며칠째 이어 가는지) */
export function StreakCard() {
  const [data, setData] = useState<Streak | null>(null);
  useEffect(() => { getJSON<Streak>(`/streak?tz=${-new Date().getTimezoneOffset()}`).then(setData).catch(() => setData(null)); }, []);
  if (!data || data.days === 0) return null;
  const names = ["일", "월", "화", "수", "목", "금", "토"];
  return (
    <div className="carrots">
      <span>
        <b><Count to={data.streak} /><small>일째</small></b>
        <span className="list-item-sub">{data.today ? "오늘 당근 받았어요" : data.streak > 0 ? "오늘도 하면 당근 하나" : `최고 ${data.best}일`}</span>
      </span>
      <span className="carrot-row" aria-label="이번 주 당근">
        {data.week.map((d, i) => (
          <span key={d.date} className={`${d.done ? "done" : ""}${i === data.week.length - 1 ? " today" : ""}`} style={{ "--i": i } as React.CSSProperties}>
            <Carrot />{names[new Date(d.date + "T00:00:00").getDay()]}
          </span>
        ))}
      </span>
    </div>
  );
}
