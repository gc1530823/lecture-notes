// 강의 화면의 정리·공부·용어 탭 내용 (Session.tsx)
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { go } from "../router";
import type { ClozeItem, Concept, Flashcard, MindNode, StudyResponse, SummaryResponse, TutorReply } from "../api/types";
import { getJSON, postJSON, useApi } from "../api/useApi";
import { Button, Chip, Empty, Fold, Icon, TermCard } from "../components/ui";
import { ConfusedPane } from "./ExamPrep";
import QuizCards from "./QuizCards";
import { jumpToMoment } from "./Story";
import SlidingTabs from "../components/SlidingTabs";
import { useSwipe } from "../lib/gesture";
import { Skeleton } from "../lib/motion";

// 공부 탭은 세 가지만: 퀴즈(AI가 내고 채점) · 외우기(플래시카드 + 빈칸) · 질문하기(헷갈린 곳 + AI 튜터)
const KINDS = [["quiz", "퀴즈"], ["memorize", "외우기"], ["ask", "질문하기"]] as const;
type Kind = (typeof KINDS)[number][0];

export default function Study({ sessionId, docId }: { sessionId: string; docId?: string }) {
  const [kind, setKind] = useState<Kind>("quiz");
  return (
    <>
      <SlidingTabs label="공부 방법" value={kind} onChange={setKind} items={KINDS} />
      {kind === "quiz" && <QuizCards makePath={`/sessions/${sessionId}/quiz-set`} scopeLabel="이번 강의의 자료와 교수님 설명을" onPage={docId ? (p) => jumpToMoment(docId, sessionId, p, null) : undefined} />}
      {kind === "memorize" && (
        <>
          <p className="t-caption muted">카드를 넘기며 외우고, 아래 빈칸으로 한 번 더 확인해요</p>
          <AIStudy<Flashcard[]> sessionId={sessionId} kind="flashcards" render={(b) => <Flashcards cards={b} />} />
          <h3 className="t-title-s section-title">빈칸 채우기</h3>
          <Cloze sessionId={sessionId} />
        </>
      )}
      {kind === "ask" && (
        <>
          <h3 className="t-title-s section-title">헷갈렸던 곳</h3>
          <ConfusedPane sessionId={sessionId} />
          <h3 className="t-title-s section-title">질문하기</h3>
          <Tutor sessionId={sessionId} />
        </>
      )}
    </>
  );
}

/** 정리 탭: 요약 · 마인드맵 (· 영어 강의면 이중 노트) */
export function Organize({ sessionId }: { sessionId: string }) {
  const { data: lang } = useApi<{ english: boolean }>(`/sessions/${sessionId}/language`);
  return (
    <>
      <SummaryPane sessionId={sessionId} />
      <Fold title="마인드맵" sub="강의 내용을 가지로 펼쳐 보기">
        <AIStudy<MindNode> sessionId={sessionId} kind="mindmap" render={(b) => <MindMap root={b} />} />
      </Fold>
      {lang?.english && (
        <>
          <h3 className="t-title-s section-title">영어 이중 노트</h3>
          <AIStudy<{ en: string; ko: string; page_no: number }[]> sessionId={sessionId} kind="bilingual" render={(b) => <Bilingual pairs={b} />} />
        </>
      )}
    </>
  );
}

/** 용어 탭 아래: AI 개념 설명 (예시까지). 수업 중에 모인 용어 사전과 한 곳에 */
export function ConceptExplain({ sessionId }: { sessionId: string }) {
  return (
    <AIStudy<Concept[]> sessionId={sessionId} kind="concepts" render={(b) => (
      <>{b.map((c, i) => <TermCard key={i} term={c.term} page={c.page_no} definition={c.example ? `${c.definition}\n예) ${c.example}` : c.definition} />)}</>
    )} />
  );
}

/** AI가 만드는 공부 재료: 없으면 만들기 버튼, 만드는 중이면 진행률, 끝나면 그린다 */
function AIStudy<T>({ sessionId, kind, render }: { sessionId: string; kind: string; render: (body: T) => ReactNode }) {
  const path = `/sessions/${sessionId}/study/${kind}`;
  const [state, setState] = useState<StudyResponse<T> | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try { setState(await getJSON<StudyResponse<T>>(path)); } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  }, [path]);
  useEffect(() => { setState(null); setError(null); void load(); }, [load]);
  useEffect(() => {
    if (state?.status !== "building") return;
    const t = setTimeout(load, 1500);
    return () => clearTimeout(t);
  }, [state, load]);

  const build = async () => {
    setError(null);
    try { setState(await postJSON<StudyResponse<T>>(path)); } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  };

  if (error) return <Empty icon="warning-circle">{error}</Empty>;
  if (!state) return <Skeleton />;
  if (state.status === "building")
    return <Empty icon="sparkle">만드는 중이에요{state.total ? ` (${state.done}/${state.total}쪽)` : "…"}</Empty>;
  if (state.status !== "ready" || state.body === null)
    return (
      <div className="banner">
        <p className="t-body">오늘 강의 내용으로 만들어 드릴게요.</p>
        <Button onClick={build} icon="magic-wand">만들기</Button>
      </div>
    );
  return (
    <>
      {state.stale && <Button variant="secondary" onClick={build} icon="clock-counter-clockwise">필기가 바뀌었어요. 다시 만들기</Button>}
      {render(state.body)}
    </>
  );
}

function Flashcards({ cards }: { cards: Flashcard[] }) {
  const [i, setI] = useState(0);
  const [flipped, setFlipped] = useState(false);
  const [again, setAgain] = useState<number[]>([]);
  const cardRef = useRef<HTMLButtonElement>(null);
  const next = useCallback((know: boolean) => {
    if (!know && i < cards.length) setAgain((a) => [...a, i]);
    setI((n) => n + 1);
    setFlipped(false);
  }, [i, cards.length]);
  const onLeft = useCallback(() => next(false), [next]);
  const onRight = useCallback(() => next(true), [next]);
  useSwipe(cardRef, { onLeft, onRight, bind: `${i}-${flipped}` });
  if (cards.length === 0) return <Empty icon="cards">만들 카드가 없었어요</Empty>;
  const deck = i < cards.length ? cards : again.map((n) => cards[n]);
  const index = i < cards.length ? i : i - cards.length;
  if (index >= deck.length) {
    return (
      <Empty icon="check-circle">
        <strong className="t-title-s">다 봤어요!</strong><br />다시 볼 카드 {again.length}장
        <div style={{ marginTop: 16 }}><Button onClick={() => { setI(0); setAgain([]); setFlipped(false); }}>처음부터</Button></div>
      </Empty>
    );
  }
  const card = deck[index];
  return (
    <>
      <p className="t-caption faint" style={{ textAlign: "center" }}>{index + 1} / {deck.length}{i >= cards.length ? ", 다시 보기" : ""}</p>
      <div className="swipe-hint" aria-hidden="true"><span>← 다시 볼래요</span><span>알아요 →</span></div>
      <button ref={cardRef} key={`${i}-${flipped}`} className="flashcard flip-in swipe-card" data-flipped={flipped} onClick={() => setFlipped(!flipped)} aria-live="polite">
        <Chip variant="accent">{card.page_no}쪽</Chip>
        <span className={flipped ? "t-body" : "t-title-m"}>{flipped ? card.back : card.front}</span>
        <span className="t-caption faint">{flipped ? "질문으로 돌아가기" : "눌러서 답 보기"}</span>
      </button>
      <div className="row">
        <Button className="grow" variant="secondary" onClick={() => next(false)}>다시 볼래요</Button>
        <Button className="grow" onClick={() => next(true)}>알아요</Button>
      </div>
    </>
  );
}

function MindMap({ root }: { root: MindNode }) {
  return (
    <div className="banner">
      <strong className="t-title-m" style={{ textAlign: "center" }}>{root.label}</strong>
      {(root.children ?? []).map((b, i) => (
        <div key={i} className="mind-branch">
          <strong className="t-title-s">{b.label}{b.page_no ? <span className="t-caption faint"> {b.page_no}쪽</span> : null}</strong>
          {(b.children ?? []).map((leaf, j) => <span key={j} className="t-body muted">{leaf.label}</span>)}
        </div>
      ))}
    </div>
  );
}

function SummaryPane({ sessionId }: { sessionId: string }) {
  const { data } = useApi<SummaryResponse>(`/sessions/${sessionId}/summary`);
  const { data: terms } = useApi<{ term: string }[]>(`/sessions/${sessionId}/glossary`);
  if (!data) return <Skeleton />;
  const s = data.summary;
  if (!s) return <Empty icon="clock">강의가 끝나면 요약이 만들어져요</Empty>;
  return (
    <>
      <section className="summary-block">
        <h3><Icon name="file-text" art size={22} /> 강의 요약</h3>
        <p className="t-body">{s.overview}</p>
      </section>
      {terms && terms.length > 0 && (
        <section className="summary-block">
          <h3><Icon name="clipboard-text" art size={22} /> 핵심 키워드</h3>
          <div className="keywords">{terms.slice(0, 8).map((t) => <span key={t.term}>{t.term}</span>)}</div>
        </section>
      )}
      {s.pages.map((p) => (
        <div key={p.page_no} className="banner">
          <span className="t-caption faint">{p.page_no}쪽</span>
          <p className="t-body">{p.summary}</p>
        </div>
      ))}
    </>
  );
}

function Cloze({ sessionId }: { sessionId: string }) {
  const { data } = useApi<StudyResponse<ClozeItem[]>>(`/sessions/${sessionId}/study/cloze`);
  const [shown, setShown] = useState<Set<number>>(new Set());
  if (!data) return <Skeleton />;
  const items = data.body ?? [];
  if (items.length === 0) return <Empty icon="brain">빈칸으로 낼 문장이 아직 없어요</Empty>;
  return (
    <>
      <p className="t-caption muted">빈칸을 누르면 답이 보여요. 시험에 나온다고 한 것부터 나와요</p>
      {items.map((it, i) => {
        const [before, after] = it.text.split("____");
        const open = shown.has(i);
        return (
          <button key={i} className="banner" style={{ textAlign: "left" }} onClick={() => setShown(new Set(shown).add(i))}>
            <span className="t-caption faint">{it.page_no}쪽{it.important ? ", 시험에 나올 수 있어요" : ""}</span>
            <p className="t-body">{before}{open ? <span className="cloze-answer">{it.answer}</span> : <span className="cloze-blank" />}{after}</p>
          </button>
        );
      })}
    </>
  );
}

type Scope = "lecture" | "course" | "all";
const SCOPES: [Scope, string, string][] = [
  ["lecture", "이 강의", "오늘 강의의 슬라이드와 교수님 설명, 필기로만 답해요"],
  ["course", "이 과목", "같은 과목의 모든 강의에서 가까운 부분을 찾아 답해요"],
  ["all", "학기 전체", "지금까지 들은 모든 강의에서 찾아 답해요"],
];

/** AI 튜터 (하나로): 범위만 골라서 묻는다 — 이 강의 · 이 과목 · 학기 전체 */
function Tutor({ sessionId }: { sessionId: string }) {
  type Src = { doc_id: string; doc_title: string; session_id: string; page_no: number };
  const [messages, setMessages] = useState<{ role: "user" | "assistant"; content: string; pages?: number[]; sources?: Src[]; scope?: Scope }[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [scope, setScope] = useState<Scope>("lecture");

  const send = async (text: string) => {
    if (!text.trim() || busy) return;
    const next = [...messages, { role: "user" as const, content: text.trim() }];
    setMessages(next);
    setInput("");
    setBusy(true);
    try {
      const reply = await postJSON<TutorReply & { sources?: Src[] }>(`/sessions/${sessionId}/tutor`,
        { scope, messages: next.map(({ role, content }) => ({ role, content })) });
      setMessages([...next, { role: "assistant", content: reply.answer, pages: reply.pages, sources: reply.sources, scope }]);
    } catch (e) {
      setMessages([...next, { role: "assistant", content: `답하지 못했어요: ${e instanceof Error ? e.message : e}` }]);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <div className="tutor-scope" role="radiogroup" aria-label="물어볼 범위">
        {SCOPES.map(([k, label]) => (
          <button key={k} role="radio" aria-checked={scope === k} className={scope === k ? "on" : ""} onClick={() => setScope(k)}>{label}</button>
        ))}
      </div>
      <p className="t-caption muted">{SCOPES.find(([k]) => k === scope)![2]}</p>
      {messages.length === 0 && (
        <div className="scroll-x" style={{ flexWrap: "wrap" }}>
          {["오늘 강의 핵심이 뭐야?", "시험에 나올 만한 거 알려줘", "제일 어려운 개념 쉽게 설명해 줘"].map((q) => (
            <Chip key={q} variant="accent" onClick={() => send(q)}>{q}</Chip>
          ))}
        </div>
      )}
      <div className="chat" aria-live="polite">
        {messages.map((m, i) => (
          <div key={i} className={`bubble ${m.role === "user" ? "bubble-me" : "bubble-ai"}`}>
            {m.content}
            {m.pages?.length ? <div className="t-caption faint" style={{ marginTop: 6 }}>근거: {m.pages.join(", ")}쪽</div> : null}
            {m.sources?.length ? (
              <div className="scroll-x" style={{ flexWrap: "wrap", marginTop: 8 }}>
                {m.sources.map((src, j) => (
                  <Chip key={j} variant="default" onClick={() => go({ name: "lecture", docId: src.doc_id, sessionId: src.session_id })}>{src.doc_title} {src.page_no}쪽</Chip>
                ))}
              </div>
            ) : null}
          </div>
        ))}
        {busy && <div className="bubble bubble-ai muted">생각하는 중…</div>}
      </div>
      <form className="row" onSubmit={(e) => { e.preventDefault(); void send(input); }}>
        <input className="input" value={input} onChange={(e) => setInput(e.target.value)} placeholder="궁금한 것을 물어보세요" aria-label="질문" />
        <Button type="submit" disabled={busy || !input.trim()} aria-label="보내기" icon="chats-circle" />
      </form>
    </>
  );
}

/** 영어 이중 노트: 쪽마다 교수님 영어 문장과 한국어 번역을 나란히. 번역 가리고 읽기 연습도 */
function Bilingual({ pairs }: { pairs: { en: string; ko: string; page_no: number }[] }) {
  const [hideKo, setHideKo] = useState(false);
  if (pairs.length === 0) return <Empty icon="chats-circle">번역할 영어 문장이 없었어요</Empty>;
  const pages = [...new Set(pairs.map((p) => p.page_no))];
  return (
    <>
      <div className="row">
        <span className="t-caption muted grow">왼쪽은 영어 원문, 오른쪽은 한국어 번역</span>
        <Chip variant={hideKo ? "selected" : "default"} onClick={() => setHideKo(!hideKo)}>{hideKo ? "번역 보기" : "번역 가리기"}</Chip>
      </div>
      {pages.map((no) => (
        <section key={no} className="banner">
          <span className="t-caption faint">{no}쪽</span>
          {pairs.filter((p) => p.page_no === no).map((p, i) => (
            <div key={i} className="bi-row">
              <p className="t-body" lang="en">{p.en}</p>
              <p className={`t-body muted${hideKo ? " hidden-answer" : ""}`}>{p.ko}</p>
            </div>
          ))}
        </section>
      ))}
    </>
  );
}
