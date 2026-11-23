// AI 퀴즈 카드: 플래시카드처럼 한 장씩 넘기며 푼다.
// AI가 강의자료와 수업 내용을 먼저 공부한 뒤 객관식 · OX · 빈칸 · 단답 · 서술 카드를 섞어 낸다 (server/app/quiz.py)
// 카드 앞면에서 답하면 AI가 채점하고 카드가 뒤집혀 결과 · 모범 답안 · 해설을 보여 준다.
// 다 풀면 틀린 카드만 모아 보통 플래시카드처럼(눌러서 답 보기) 다시 넘겨 볼 수 있다.
import { useCallback, useEffect, useRef, useState } from "react";
import { getJSON, postJSON } from "../api/useApi";
import { Button, Chip, TopBar } from "../components/ui";
import { back } from "../router";
import { play } from "../lib/sound";
import { useSwipe } from "../lib/gesture";
import { getPrefs } from "../lib/prefs";

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

/** 채점 표시 (벡터): 맞음 체크 · 부분 가로선 · 틀림 엑스 */
function Mark({ verdict, size = 26 }: { verdict: Verdict; size?: number }) {
  return (
    <svg className={`qz-mark ${verdict}`} viewBox="0 0 24 24" width={size} height={size} aria-hidden="true">
      <circle cx="12" cy="12" r="11" />
      {verdict === "correct" && <path d="M7 12.5l3.2 3.2L17 9" />}
      {verdict === "partial" && <path d="M7.5 12h9" />}
      {verdict === "wrong" && <path d="M8.5 8.5l7 7M15.5 8.5l-7 7" />}
    </svg>
  );
}

function CardHead({ q, total }: { q: Question; total: number }) {
  return (
    <div className="qz-head">
      <Chip variant="accent">{q.page_no}쪽{q.topic ? `, ${q.topic}` : ""}</Chip>
      <span className={`qz-type t-${q.type}`}>{q.type_label}</span>
      <span className="qz-no">{q.index + 1}/{total}</span>
    </div>
  );
}

export default function QuizCards({ makePath, scopeLabel }: { makePath: string; scopeLabel: string }) {
  const [set, setSet] = useState<QuizSet | null>(null);
  const [count, setCount] = useState(getPrefs().quizCount);
  const [making, setMaking] = useState(false);
  const [grading, setGrading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [at, setAt] = useState(0);            // 지금 보고 있는 카드
  const [review, setReview] = useState<number | null>(null); // 틀린 카드 다시 보기: 몇 번째
  const [shown, setShown] = useState(false);  // 다시 보기 카드 뒤집힘
  // 채점된 카드는 옆으로 밀어서 다음 카드로
  const backRef = useRef<HTMLDivElement>(null);
  const toNext = useCallback(() => setAt((n) => n + 1), []);
  const graded = !!set?.questions[at]?.result;
  useSwipe(backRef, { onLeft: toNext, onRight: toNext, enabled: graded, bind: at });

  // 풀던 퀴즈가 있으면 이어서
  useEffect(() => {
    let saved: string | null = null;
    try { saved = localStorage.getItem(KEY(makePath)); } catch { /* 괜찮다 */ }
    if (saved) getJSON<QuizSet>(`/quiz-sets/${saved}`).then((s) => { setSet(s); setAt(Math.min(s.answered, s.questions.length)); }).catch(() => {});
  }, [makePath]);

  const start = async () => {
    setMaking(true); setError(null); setReview(null);
    try {
      const made = await postJSON<QuizSet>(makePath, { count });
      setSet(made); setAt(0); setDraft("");
      try { localStorage.setItem(KEY(makePath), String(made.id)); } catch { /* 괜찮다 */ }
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    setMaking(false);
  };

  const send = async (answer: string) => {
    if (!set || grading || !answer.trim()) return;
    const q = set.questions[at];
    setGrading(true); setError(null);
    try {
      const graded = await postJSON<Question & { done: boolean }>(`/quiz-sets/${set.id}/grade`, { index: q.index, answer });
      const questions = set.questions.map((x) => x.index === q.index ? graded : x);
      setSet({ ...set, questions, answered: set.answered + 1, score: questions.reduce((s, x) => s + (x.result?.score ?? 0), 0) });
      setDraft("");
      play(graded.result!.verdict === "wrong" ? "wrong" : "success");
      navigator.vibrate?.(graded.result!.verdict === "wrong" ? [25, 40, 25] : 15);
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    setGrading(false);
  };

  // 시작: 큰 빈 카드 대신, 문제 수를 크게 고르고 바로 푸는 화면
  if (!set || making) {
    return (
      <div className={`qz qz-start${making ? " making" : ""}`}>
        <span className="qz-kick">{making ? "문제를 고르는 중" : "Quiz"}</span>
        <h2 className="qz-hero">{making ? <>강의를 다시 읽고<br />시험에 낼 곳을 찾고 있어요</> : <>{scopeLabel}<br />바탕으로 문제를 내요</>}</h2>
        {making ? (
          <div className="qz-build" aria-hidden="true">{[0, 1, 2, 3, 4].map((k) => <i key={k} style={{ animationDelay: `${k * 0.18}s` }} />)}</div>
        ) : (
          <>
            <div className="qz-count" role="radiogroup" aria-label="문제 수">
              {COUNTS.map((n) => <button key={n} role="radio" aria-checked={n === count} className={n === count ? "on" : ""} onClick={() => setCount(n)}><b>{n}</b><small>문제</small></button>)}
            </div>
            <p className="qz-kinds-line">객관식, OX, 빈칸, 단답, 서술이 섞여 나와요. 답하면 바로 채점하고 해설을 보여 줘요.</p>
            <Button block onClick={() => void start()}>{count}문제 풀기</Button>
          </>
        )}
        {error && <p className="qz-error">{error}</p>}
      </div>
    );
  }

  const total = set.questions.length;
  const missed = set.questions.filter((q) => q.result && q.result.verdict !== "correct");
  const right = set.questions.filter((q) => q.result?.verdict === "correct").length;
  const dots = (
    <div className="qz-progress" aria-label={`${set.answered}/${total}장 풀었고 ${right}장 맞았어요`}>
      <div className="qz-progress-top"><b>{Math.min(at + 1, total)}<small> / {total}</small></b><span>맞힌 카드 {right}장</span></div>
      <div className="qz-bar">{set.questions.map((q) => <i key={q.index} className={`${q.result?.verdict ?? ""}${q.index === at && review === null ? " now" : ""}`} />)}</div>
    </div>
  );

  // 틀린 카드 다시 보기: 보통 플래시카드처럼 눌러서 답 보기
  if (review !== null) {
    if (review >= missed.length) {
      return (
        <div className="qz">
          <div className="flashcard qz-card qz-end card-in">
            <strong className="t-title-m">다시 보기 끝!</strong>
            <span className="t-caption muted">틀린 카드 {missed.length}장을 모두 봤어요</span>
          </div>
          <div className="row"><Button className="grow" variant="secondary" onClick={() => { setReview(0); setShown(false); }}>한 번 더</Button><Button className="grow" onClick={() => void start()}>새 카드 받기</Button></div>
        </div>
      );
    }
    const q = missed[review];
    return (
      <div className="qz">
        <p className="t-caption faint" style={{ textAlign: "center" }}>틀린 카드 다시 보기, {review + 1} / {missed.length}</p>
        <button key={`${review}-${shown}`} className="flashcard qz-card flip-in" data-flipped={shown} onClick={() => setShown(!shown)}>
          <CardHead q={q} total={total} />
          {!shown ? (
            <>
              <strong className="qz-q">{q.question}</strong>
              {q.type === "mcq" && <ol className="qz-plain">{q.choices.map((c, i) => <li key={i}><b>{"ABCD"[i]}</b> {c}</li>)}</ol>}
              <span className="t-caption faint">눌러서 답 보기</span>
            </>
          ) : (
            <>
              <p className="qz-model"><span>모범 답안</span>{q.answer}</p>
              {q.explanation && <p className="qz-why">{q.explanation}</p>}
              <span className="t-caption faint">내 답: {q.result?.given}</span>
            </>
          )}
        </button>
        <div className="row">
          <Button className="grow" variant="secondary" disabled={review === 0} onClick={() => { setReview(review - 1); setShown(false); }}>이전</Button>
          <Button className="grow" onClick={() => { setReview(review + 1); setShown(false); }}>다음</Button>
        </div>
      </div>
    );
  }

  // 다 풀었으면 점수 카드
  if (at >= total) {
    const pct = Math.round((set.score / total) * 100);
    return (
      <div className="qz">
        {dots}
        <div className="flashcard qz-card qz-end card-in">
          <svg className="qz-ring" viewBox="0 0 120 120" width="120" height="120" aria-hidden="true">
            <circle cx="60" cy="60" r="50" className="track" />
            <circle cx="60" cy="60" r="50" className="fill" style={{ strokeDasharray: `${(pct / 100) * 314} 314` }} />
          </svg>
          <strong className="qz-score">{set.score % 1 ? set.score.toFixed(1) : set.score} / {total}</strong>
          <span className="t-caption muted">{pct >= 80 ? "아주 잘했어요. 이 강의는 거의 다 이해했어요" : pct >= 50 ? "절반 넘게 맞았어요. 틀린 카드를 다시 넘겨 보세요" : "틀린 카드의 해설을 읽고 한 번 더 풀어 봐요"}</span>
          {missed.length > 0 && (
            <div className="qz-weak">
              <span>다시 볼 개념</span>
              <ul>{[...new Map(missed.map((m) => [m.topic || `${m.page_no}쪽`, m])).values()].slice(0, 4).map((m) => <li key={m.index}><b>{m.topic || "이 쪽 내용"}</b><small>{m.page_no}쪽</small></li>)}</ul>
            </div>
          )}
        </div>
        <div className="row">
          {missed.length > 0 && <Button className="grow" variant="secondary" onClick={() => { setReview(0); setShown(false); }}>틀린 카드 {missed.length}장 다시 보기</Button>}
          <Button className="grow" onClick={() => void start()}>새 카드 받기</Button>
        </div>
      </div>
    );
  }

  const q = set.questions[at];
  const r = q.result;
  const pickedIndex = r && q.type === "mcq" ? "ABCD".indexOf(r.given) : -1;
  return (
    <div className="qz">
      {dots}
      <div className="qz-stack">
        {at + 1 < total && <div className="qz-under" aria-hidden="true" />}
        {r && (q.type === "mcq" || q.type === "ox") ? (
          // 고르는 문제: 카드는 그대로, 고른 칸과 정답 칸이 색으로 바뀌고 해설이 아래로 펼쳐진다
          <div ref={backRef} key={`a${at}`} className={`flashcard qz-card qz-answered swipe-card ${r.verdict}`}>
            <CardHead q={q} total={total} />
            <strong className="qz-q">{q.question}</strong>
            {q.type === "mcq" ? (
              <div className="qz-choices done">
                {q.choices.map((c, i) => {
                  const key = "ABCD"[i]; const isAns = (q.answer ?? "").trim().toUpperCase().startsWith(key) || (r.verdict === "correct" && r.given === key);
                  return <div key={i} className={`qz-choice${isAns ? " ans" : ""}${r.given === key && !isAns ? " miss" : ""}`} style={{ animationDelay: `${i * 40}ms` }}><b>{key}</b>{c}{isAns && <Mark verdict="correct" size={20} />}{r.given === key && !isAns && <Mark verdict="wrong" size={20} />}</div>;
                })}
              </div>
            ) : (
              <div className="qz-ox done">{["O", "X"].map((k) => {
                const isAns = (q.answer ?? "").trim().toUpperCase().startsWith(k) || (r.verdict === "correct" && r.given === k);
                return <div key={k} className={`qz-choice${isAns ? " ans" : ""}${r.given === k && !isAns ? " miss" : ""}`}><b>{k}</b></div>;
              })}</div>
            )}
            <div className="qz-explain">
              <b className="qz-verdict"><Mark verdict={r.verdict} />{r.verdict === "correct" ? "맞았어요" : "다시 볼 부분이 있어요"}</b>
              {r.verdict !== "correct" && <p className="qz-concept"><span>핵심 개념</span>{q.topic || "이 쪽 내용"}<small>{q.page_no}쪽에서 다시 보기</small></p>}
              {q.explanation && <p className="qz-why">{q.explanation}</p>}
            </div>
          </div>
        ) : !r ? (
          // 앞면: 문제와 답하기
          <div key={`f${at}`} className="flashcard qz-card card-in">
            <CardHead q={q} total={total} />
            <strong className="qz-q">{q.question}</strong>
            {q.type === "mcq" && (
              <div className="qz-choices">
                {q.choices.map((c, i) => (
                  <button key={i} disabled={grading} onClick={() => void send("ABCD"[i])}><b>{"ABCD"[i]}</b>{c}</button>
                ))}
              </div>
            )}
            {q.type === "ox" && (
              <div className="qz-ox">
                <button disabled={grading} onClick={() => void send("O")} aria-label="O, 맞다"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="7.5" /></svg></button>
                <button disabled={grading} onClick={() => void send("X")} aria-label="X, 틀리다"><svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18" /></svg></button>
              </div>
            )}
            {q.type !== "mcq" && q.type !== "ox" && (
              <form className="qz-write" onSubmit={(e) => { e.preventDefault(); void send(draft); }}>
                <textarea value={draft} rows={q.type === "essay" ? 4 : 2} disabled={grading}
                  placeholder={q.type === "essay" ? "2~4문장으로 설명해 보세요" : q.type === "fill" ? "빈칸에 들어갈 말 (여러 칸이면 쉼표로)" : "답을 적어 주세요"}
                  onChange={(e) => setDraft(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey && q.type !== "essay") { e.preventDefault(); void send(draft); } }} />
                <Button block disabled={grading || !draft.trim()}>{grading ? "채점하는 중…" : "채점 받기"}</Button>
              </form>
            )}
            {grading && q.type !== "fill" && q.type !== "short" && q.type !== "essay" && <span className="t-caption faint"><span className="spin" /> 채점하는 중…</span>}
          </div>
        ) : (
          // 뒷면: 채점 결과
          <div ref={backRef} key={`b${at}`} className={`flashcard qz-card qz-back flip-in swipe-card ${r.verdict}`} data-flipped="true">
            <CardHead q={q} total={total} />
            <b className="qz-verdict"><Mark verdict={r.verdict} />{VERDICT[r.verdict]}</b>
            <p className="qz-given"><span>내 답</span>{q.type === "mcq" ? `${r.given}. ${q.choices[pickedIndex] ?? ""}` : r.given}</p>
            {r.feedback && <p className="qz-feedback">{r.feedback}</p>}
            {r.verdict !== "correct" && q.answer && <p className="qz-model"><span>모범 답안</span>{q.answer}</p>}
            {q.explanation && <p className="qz-why">{q.explanation}</p>}
          </div>
        )}
      </div>
      {r && <Button block onClick={() => setAt(at + 1)}>{at + 1 < total ? "다음 카드" : "결과 보기"}</Button>}
      {r && <p className="t-caption faint" style={{ textAlign: "center", margin: 0 }}>카드를 옆으로 밀어도 넘어가요</p>}
      {error && <p className="qz-error">{error}</p>}
    </div>
  );
}

/** 강의자료 전체로 푸는 AI 퀴즈 카드 (자료 상세 › AI 퀴즈) */
export function QuizScreen({ docId }: { docId: string }) {
  return (
    <div className="screen">
      <TopBar title="퀴즈" onBack={() => back({ name: "doc", docId })} />
      <div className="screen-body">
        <QuizCards makePath={`/documents/${docId}/quiz-set`} scopeLabel="이 강의자료와 지금까지 들은 강의를" />
      </div>
    </div>
  );
}
