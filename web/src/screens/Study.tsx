import { play } from "../lib/sound";
// 4 공부하기: 요약 · 퀴즈 · 플래시카드 · 개념 · 마인드맵 · 암기 · AI 튜터
import { useCallback, useEffect, useState, type ReactNode } from "react";
import type { ClozeItem, Concept, Flashcard, MindNode, StudyResponse, SummaryResponse, TutorReply } from "../api/types";
import { getJSON, postJSON, useApi } from "../api/useApi";
import { Button, Chip, Empty, Icon, TermCard } from "../components/ui";
import { ConfusedPane } from "./ExamPrep";

const KINDS = [["summary", "요약"], ["quiz", "퀴즈"], ["flashcards", "플래시카드"], ["concepts", "개념"], ["mindmap", "마인드맵"], ["cloze", "암기"], ["confused", "모르겠다"], ["tutor", "AI 튜터"]] as const;
type Kind = (typeof KINDS)[number][0];

export default function Study({ sessionId }: { sessionId: string }) {
  const [kind, setKind] = useState<Kind | "bilingual">("flashcards");
  // 영어 강의면 "영어 이중 노트" 탭을 맨 앞에 보여 준다
  const { data: lang } = useApi<{ english: boolean }>(`/sessions/${sessionId}/language`);
  return (
    <>
      <div className="scroll-x" role="tablist" aria-label="공부 도구">
        {lang?.english && <Chip variant={kind === "bilingual" ? "accent" : "default"} onClick={() => setKind("bilingual")}>영어 이중 노트</Chip>}
        {KINDS.map(([k, label]) => <Chip key={k} variant={kind === k ? "accent" : "default"} onClick={() => setKind(k)}>{label}</Chip>)}
      </div>
      {(kind === "summary" || kind === "quiz") && <SummaryPane sessionId={sessionId} quiz={kind === "quiz"} />}
      {kind === "flashcards" && <AIStudy<Flashcard[]> sessionId={sessionId} kind="flashcards" render={(b) => <Flashcards cards={b} />} />}
      {kind === "concepts" && <AIStudy<Concept[]> sessionId={sessionId} kind="concepts" render={(b) => (
        <>{b.map((c, i) => <TermCard key={i} term={c.term} page={c.page_no} definition={c.example ? `${c.definition}\n예) ${c.example}` : c.definition} />)}</>
      )} />}
      {kind === "mindmap" && <AIStudy<MindNode> sessionId={sessionId} kind="mindmap" render={(b) => <MindMap root={b} />} />}
      {kind === "cloze" && <Cloze sessionId={sessionId} />}
      {kind === "confused" && <ConfusedPane sessionId={sessionId} />}
      {kind === "bilingual" && <AIStudy<{ en: string; ko: string; page_no: number }[]> sessionId={sessionId} kind="bilingual" render={(b) => <Bilingual pairs={b} />} />}
      {kind === "tutor" && <Tutor sessionId={sessionId} />}
    </>
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
  if (!state) return <p className="muted">불러오는 중…</p>;
  if (state.status === "building")
    return <Empty icon="sparkle">AI가 만드는 중이에요{state.total ? ` · ${state.done}/${state.total}쪽` : "…"}</Empty>;
  if (state.status !== "ready" || state.body === null)
    return (
      <div className="banner">
        <p className="t-body">오늘 강의 내용으로 만들어 드릴게요.</p>
        <Button onClick={build} icon="magic-wand">만들기</Button>
      </div>
    );
  return (
    <>
      {state.stale && <Button variant="secondary" onClick={build} icon="clock-counter-clockwise">필기가 바뀌었어요 · 다시 만들기</Button>}
      {render(state.body)}
    </>
  );
}

function Flashcards({ cards }: { cards: Flashcard[] }) {
  const [i, setI] = useState(0);
  const [flipped, setFlipped] = useState(false);
  const [again, setAgain] = useState<number[]>([]);
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
  const next = (know: boolean) => {
    if (!know && i < cards.length) setAgain([...again, i]);
    setI(i + 1);
    setFlipped(false);
  };
  return (
    <>
      <p className="t-caption faint" style={{ textAlign: "center" }}>{index + 1} / {deck.length}{i >= cards.length ? " · 다시 보기" : ""}</p>
      <button key={`${i}-${flipped}`} className="flashcard flip-in" data-flipped={flipped} onClick={() => setFlipped(!flipped)} aria-live="polite">
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
          <strong className="t-title-s">{b.label}{b.page_no ? <span className="t-caption faint"> · {b.page_no}쪽</span> : null}</strong>
          {(b.children ?? []).map((leaf, j) => <span key={j} className="t-body muted">{leaf.label}</span>)}
        </div>
      ))}
    </div>
  );
}

function SummaryPane({ sessionId, quiz }: { sessionId: string; quiz: boolean }) {
  const { data, reload } = useApi<SummaryResponse & { quiz_status?: string }>(`/sessions/${sessionId}/summary`);
  const making = data?.quiz_status === "making";
  // AI가 퀴즈를 새로 내는 중이면 잠깐씩 다시 물어본다
  useEffect(() => {
    if (!making) return;
    const t = window.setInterval(() => reload(), 2500);
    return () => window.clearInterval(t);
  }, [making, reload]);
  const remake = async () => {
    try { await postJSON(`/sessions/${sessionId}/quiz`); setPicked({}); reload(); }
    catch (e) { alert(e instanceof Error ? e.message : String(e)); }
  };
  const { data: terms } = useApi<{ term: string }[]>(`/sessions/${sessionId}/glossary`);
  const [picked, setPicked] = useState<Record<number, number>>({});
  if (!data) return <p className="muted">불러오는 중…</p>;
  const s = data.summary;
  if (!s) return <Empty icon="clock">강의가 끝나면 요약과 퀴즈가 만들어져요</Empty>;
  if (!quiz) {
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
  const items = s.quiz ?? [];
  if (making) return <div className="quiz-making"><span className="spin" /><b>AI가 오늘 강의로 문제를 내고 있어요</b><span className="t-caption muted">외운 문장 찾기가 아니라 이해를 묻는 문제로 만들어요</span></div>;
  if (items.length === 0) return <Empty icon="list-numbers">퀴즈가 없어요</Empty>;
  return (
    <>
      <div className="row quiz-head">
        <span className="t-caption muted grow">AI가 강의 내용을 바탕으로 낸 문제 {items.length}개</span>
        <button className="chip chip-accent" onClick={() => void remake()}>새 문제 받기</button>
      </div>
      {items.map((q, qi) => {
        const answered = picked[qi] !== undefined;
        return (
          <div key={qi} className="banner">
            <span className="t-caption faint">{qi + 1}번 · {q.page_no}쪽</span>
            <strong className="t-title-s">{q.question}</strong>
            {q.choices.map((c, ci) => {
              const variant = !answered ? "secondary" : ci === q.answer_index ? "primary" : ci === picked[qi] ? "record" : "secondary";
              const fx = !answered ? "" : ci === q.answer_index ? " fx-right" : ci === picked[qi] ? " fx-wrong" : "";
              return <Button key={ci} variant={variant} block className={`quiz-choice${fx}`} disabled={answered && variant === "secondary"}
                style={{ animationDelay: `${ci * 50}ms` }}
                data-sound onClick={() => { if (answered) return; setPicked({ ...picked, [qi]: ci }); play(ci === q.answer_index ? "success" : "wrong"); navigator.vibrate?.(ci === q.answer_index ? 15 : [30, 40, 30]); }}><span className="choice-letter">{"ABCD"[ci]}</span>{c}</Button>;
            })}
            {answered && (
              <p className={`quiz-result t-body ${picked[qi] === q.answer_index ? "right" : "wrong"}`}>
                <b>{picked[qi] === q.answer_index ? "정답이에요" : "아쉬워요"}</b> {q.explanation}
              </p>
            )}
          </div>
        );
      })}
    </>
  );
}

function Cloze({ sessionId }: { sessionId: string }) {
  const { data } = useApi<StudyResponse<ClozeItem[]>>(`/sessions/${sessionId}/study/cloze`);
  const [shown, setShown] = useState<Set<number>>(new Set());
  if (!data) return <p className="muted">불러오는 중…</p>;
  const items = data.body ?? [];
  if (items.length === 0) return <Empty icon="brain">빈칸으로 낼 문장이 아직 없어요</Empty>;
  return (
    <>
      <p className="t-caption muted">빈칸을 눌러 답을 확인하세요 · 시험·강조 필기부터</p>
      {items.map((it, i) => {
        const [before, after] = it.text.split("____");
        const open = shown.has(i);
        return (
          <button key={i} className="banner" style={{ textAlign: "left" }} onClick={() => setShown(new Set(shown).add(i))}>
            <span className="t-caption faint">{it.page_no}쪽{it.important ? " · 시험에 나올 수 있어요" : ""}</span>
            <p className="t-body">{before}{open ? <span className="cloze-answer">{it.answer}</span> : <span className="cloze-blank" />}{after}</p>
          </button>
        );
      })}
    </>
  );
}

function Tutor({ sessionId }: { sessionId: string }) {
  const [messages, setMessages] = useState<{ role: "user" | "assistant"; content: string; pages?: number[] }[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);

  const send = async (text: string) => {
    if (!text.trim() || busy) return;
    const next = [...messages, { role: "user" as const, content: text.trim() }];
    setMessages(next);
    setInput("");
    setBusy(true);
    try {
      const reply = await postJSON<TutorReply>(`/sessions/${sessionId}/tutor`,
        { messages: next.map(({ role, content }) => ({ role, content })) });
      setMessages([...next, { role: "assistant", content: reply.answer, pages: reply.pages }]);
    } catch (e) {
      setMessages([...next, { role: "assistant", content: `답하지 못했어요: ${e instanceof Error ? e.message : e}` }]);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <p className="t-caption muted">오늘 강의 내용(슬라이드 · 교수님 설명 · 필기)으로만 답해요</p>
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
        <span className="t-caption muted grow">왼쪽 영어 원문 · 오른쪽 한국어 번역</span>
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
