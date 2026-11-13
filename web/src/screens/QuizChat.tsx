// AI 퀴즈: 튜터와 대화하듯 문제를 하나씩 받고 답하면 AI가 채점한다.
// AI가 강의자료와 수업 내용을 먼저 공부한 뒤 객관식 · OX · 빈칸 · 단답 · 서술을 섞어 낸다 (server/app/quiz.py)
import { useEffect, useRef, useState } from "react";
import { getJSON, postJSON } from "../api/useApi";
import { Button, TopBar } from "../components/ui";
import { back } from "../router";
import { play } from "../lib/sound";

type Verdict = "correct" | "partial" | "wrong";
interface Result { verdict: Verdict; score: number; feedback: string; given: string }
interface Question {
  index: number; type: "mcq" | "ox" | "fill" | "short" | "essay"; type_label: string; page_no: number; topic: string;
  question: string; choices: string[]; answer?: string; explanation?: string; result?: Result;
}
interface QuizSet { id: number; title: string; questions: Question[]; score: number; answered: number }

const COUNTS = [5, 8, 12];
const VERDICT: Record<Verdict, string> = { correct: "정답", partial: "부분 정답", wrong: "오답" };
const KEY = (path: string) => `ln.quizset.${path}`;

/** 채점 표시 (벡터): 맞음 체크 · 부분 반달 · 틀림 엑스 */
function Mark({ verdict }: { verdict: Verdict }) {
  return (
    <svg className={`qc-mark ${verdict}`} viewBox="0 0 24 24" width="22" height="22" aria-hidden="true">
      <circle cx="12" cy="12" r="11" />
      {verdict === "correct" && <path d="M7 12.5l3.2 3.2L17 9" />}
      {verdict === "partial" && <path d="M7.5 12h9" />}
      {verdict === "wrong" && <path d="M8.5 8.5l7 7M15.5 8.5l-7 7" />}
    </svg>
  );
}

export default function QuizChat({ makePath, scopeLabel }: { makePath: string; scopeLabel: string }) {
  const [set, setSet] = useState<QuizSet | null>(null);
  const [count, setCount] = useState(8);
  const [making, setMaking] = useState(false);
  const [grading, setGrading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const end = useRef<HTMLDivElement>(null);

  // 풀던 퀴즈가 있으면 이어서
  useEffect(() => {
    let saved: string | null = null;
    try { saved = localStorage.getItem(KEY(makePath)); } catch { /* 괜찮다 */ }
    if (saved) getJSON<QuizSet>(`/quiz-sets/${saved}`).then(setSet).catch(() => {});
  }, [makePath]);

  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [set, grading, making]);

  const start = async () => {
    setMaking(true); setError(null); setSet(null);
    try {
      const made = await postJSON<QuizSet>(makePath, { count });
      setSet(made);
      try { localStorage.setItem(KEY(makePath), String(made.id)); } catch { /* 괜찮다 */ }
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    setMaking(false);
  };

  const send = async (answer: string) => {
    if (!set || grading || !answer.trim()) return;
    const q = set.questions[set.answered];
    setGrading(true); setError(null);
    // 내 답을 먼저 말풍선으로
    setSet({ ...set, questions: set.questions.map((x) => x.index === q.index ? { ...x, result: { verdict: "wrong", score: -1, feedback: "", given: answer } } : x) });
    try {
      const graded = await postJSON<Question & { done: boolean }>(`/quiz-sets/${set.id}/grade`, { index: q.index, answer });
      const questions = set.questions.map((x) => x.index === q.index ? graded : x);
      const next = { ...set, questions, answered: set.answered + 1, score: questions.reduce((s, x) => s + (x.result?.score ?? 0), 0) };
      setSet(next);
      setDraft("");
      play(graded.result!.verdict === "wrong" ? "wrong" : "success");
      navigator.vibrate?.(graded.result!.verdict === "wrong" ? [25, 40, 25] : 15);
      if (graded.done) window.setTimeout(() => play("complete"), 700);
    } catch (e) {
      setSet(set);
      setError(e instanceof Error ? e.message : String(e));
    }
    setGrading(false);
  };

  if (!set) {
    return (
      <div className="qc-start">
        <div className="qc-bubble ai">
          <b>AI 퀴즈</b>
          <p>{scopeLabel} 제가 먼저 공부한 다음, 시험처럼 문제를 하나씩 낼게요. 답하면 바로 채점하고 해설해 드려요.</p>
          <div className="qc-kinds">{["객관식", "OX", "빈칸", "단답", "서술"].map((k) => <span key={k}>{k}</span>)}</div>
        </div>
        {making ? (
          <div className="qc-bubble ai typing"><i /><i /><i /><span>강의를 공부하고 문제를 고르는 중…</span></div>
        ) : (
          <div className="qc-setup">
            <span className="t-caption muted">문제 수</span>
            <div className="qc-counts">{COUNTS.map((n) => <button key={n} className={n === count ? "on" : ""} onClick={() => setCount(n)}>{n}문제</button>)}</div>
            <Button block onClick={() => void start()}>퀴즈 시작</Button>
          </div>
        )}
        {error && <p className="qc-error">{error}</p>}
      </div>
    );
  }

  const total = set.questions.length;
  const current = set.answered < total ? set.questions[set.answered] : null;
  const pending = current?.result?.score === -1;
  const shown = set.questions.slice(0, set.answered + 1);
  const pct = Math.round((set.score / total) * 100);

  return (
    <div className="qc">
      <div className="qc-progress" aria-label={`${set.answered}/${total}문제`}>
        <span style={{ width: `${(set.answered / total) * 100}%` }} />
      </div>
      {shown.map((q) => (
        <div key={q.index} className="qc-turn">
          <div className="qc-bubble ai">
            <span className="qc-tag">Q{q.index + 1} · {q.page_no}쪽{q.topic ? ` ${q.topic}` : ""} · {q.type_label}</span>
            <p className="qc-q">{q.question}</p>
            {q.type === "mcq" && (
              <ol className="qc-choices">
                {q.choices.map((c, i) => {
                  const picked = q.result && q.result.score >= 0 && q.result.given === "ABCD"[i];
                  const right = q.answer !== undefined && c === q.answer;
                  return (
                    <li key={i}>
                      <button disabled={!!q.result || grading} className={right ? "right" : picked ? "picked" : ""} onClick={() => void send("ABCD"[i])}>
                        <span className="choice-letter">{"ABCD"[i]}</span>{c}
                      </button>
                    </li>
                  );
                })}
              </ol>
            )}
          </div>
          {q.result && <div className="qc-bubble me">{q.type === "mcq" ? `${q.result.given}. ${q.choices["ABCD".indexOf(q.result.given)] ?? ""}` : q.result.given}</div>}
          {pending && q === current && <div className="qc-bubble ai typing"><i /><i /><i /><span>채점하는 중…</span></div>}
          {q.result && q.result.score >= 0 && (
            <div className={`qc-bubble ai grade ${q.result.verdict}`}>
              <b className="qc-verdict"><Mark verdict={q.result.verdict} />{VERDICT[q.result.verdict]}</b>
              {q.result.feedback && <p>{q.result.feedback}</p>}
              {q.result.verdict !== "correct" && q.answer && <p className="qc-model"><span>모범 답안</span>{q.answer}</p>}
              {q.explanation && <p className="qc-why">{q.explanation}</p>}
            </div>
          )}
        </div>
      ))}
      {!current && (
        <div className="qc-score">
          <svg viewBox="0 0 120 120" width="112" height="112" aria-hidden="true">
            <circle cx="60" cy="60" r="50" className="track" />
            <circle cx="60" cy="60" r="50" className="fill" style={{ strokeDasharray: `${(pct / 100) * 314} 314` }} />
          </svg>
          <strong>{set.score % 1 ? set.score.toFixed(1) : set.score} / {total}</strong>
          <span className="t-caption muted">{pct >= 80 ? "아주 잘했어요. 이 강의는 거의 다 이해했어요" : pct >= 50 ? "절반 넘게 맞았어요. 틀린 문제의 해설을 다시 보세요" : "해설을 읽고 한 번 더 풀어 봐요"}</span>
          <Button block onClick={() => void start()}>새 문제로 다시</Button>
        </div>
      )}
      {error && <p className="qc-error">{error}</p>}
      <div ref={end} />
      {current && !current.result && current.type !== "mcq" && (
        <div className="qc-composer">
          {current.type === "ox" ? (
            <div className="qc-ox">
              <button disabled={grading} onClick={() => void send("O")} aria-label="O, 맞다"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="7.5" /></svg></button>
              <button disabled={grading} onClick={() => void send("X")} aria-label="X, 틀리다"><svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18" /></svg></button>
            </div>
          ) : (
            <form onSubmit={(e) => { e.preventDefault(); void send(draft); }}>
              <textarea value={draft} rows={current.type === "essay" ? 3 : 1} disabled={grading}
                placeholder={current.type === "essay" ? "2~4문장으로 설명해 보세요" : current.type === "fill" ? "빈칸에 들어갈 말 (여러 칸이면 쉼표로)" : "답을 적어 주세요"}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey && current.type !== "essay") { e.preventDefault(); void send(draft); } }} />
              <button type="submit" disabled={grading || !draft.trim()} aria-label="보내기">
                <svg viewBox="0 0 24 24"><path d="M5 12h13M13 6l6 6-6 6" /></svg>
              </button>
            </form>
          )}
        </div>
      )}
    </div>
  );
}

/** 강의자료 전체로 푸는 AI 퀴즈 (자료 상세 › AI 퀴즈) */
export function QuizScreen({ docId }: { docId: string }) {
  return (
    <div className="screen">
      <TopBar title="AI 퀴즈" onBack={() => back({ name: "doc", docId })} />
      <div className="screen-body">
        <QuizChat makePath={`/documents/${docId}/quiz-set`} scopeLabel="이 강의자료와 지금까지 들은 강의를 모두" />
      </div>
    </div>
  );
}
