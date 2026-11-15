// 시험 공부 화면: 족보 노트 · 오늘의 복습(망각 곡선) · 개인정보와 녹음 동의
import { useSwipe } from "../lib/gesture";
import { AccountSecurity, OwnerAccountTools } from "./Account";
import { PREVIEW, play, setSoundOn, soundOn } from "../lib/sound";
import { useEffect, useRef, useState, type ReactNode } from "react";
import type { DocumentBrief } from "../api/types";
import { getJSON, postJSON, useApi } from "../api/useApi";
import { Button, Chip, Empty, Icon, PostIt, TermCard, TopBar } from "../components/ui";
import { android } from "../lib/live";
import { getPrefs, setPrefs, type Prefs } from "../lib/prefs";
import { back, go } from "../router";

const API = import.meta.env.VITE_API_URL ?? "";

interface Jokbo {
  title: string;
  friends: string[];
  crowd: { page_no: number; title: string; people: string[]; notes: { who: string; text: string; kind: string }[] }[];
  lectures: number;
  exam: { page_no: number; text: string; lecture: number }[];
  emphasis: { page_no: number; text: string; lecture: number }[];
  notice: { page_no: number; text: string; lecture: number }[];
  top_pages: { page_no: number; title: string; score: number; reasons: string[]; summary: string }[];
  terms: { term: string; definition: string; page_no: number | null }[];
  confused: { page_no: number; speech: string; explanation: string | null; lecture: number }[];
  predicted: { page_no: number; question: string; answer: string; reason: string }[];
}

/** 족보 노트: 이 자료의 모든 강의에서 시험에 필요한 것만 한 장에. 인쇄하면 A4로 나온다 */
export function JokboScreen({ docId }: { docId: string }) {
  const { data, error } = useApi<Jokbo>(`/documents/${docId}/jokbo`);
  const [showAnswers, setShowAnswers] = useState(false);

  return (
    <div className="screen jokbo">
      <TopBar title="족보 노트" onBack={() => back({ name: "doc", docId })}
        action={<button className="top-bar-back no-print" onClick={() => { const app = android(); if (app) app.print("족보 노트"); else window.print(); }} aria-label="인쇄 · PDF로 저장"><Icon name="file-pdf" /></button>} />
      <div className="screen-body">
        {error && <Empty icon="warning-circle">{error}</Empty>}
        {data && data.lectures === 0 && <Empty icon="notebook">강의를 녹음하면 시험에 필요한 것만 모아 드려요</Empty>}
        {data && data.lectures > 0 && (
          <>
            <header className="jokbo-head">
              <span className="t-caption muted">강의 {data.lectures}번 모아 보기 · AI가 새로 쓰지 않고 수업에서 나온 것만 모았어요</span>
              <h1 className="t-title-l">{data.title}</h1>
            </header>

            <ShareBox docId={docId} friends={data.friends} />

            {data.crowd.length > 0 && (
              <Section icon="users" title={`함께 본 족보 · 나와 친구 ${data.friends.length}명`} tone="exam">
                {data.crowd.slice(0, 12).map((c) => (
                  <div key={c.page_no} className="jokbo-page">
                    <div className="row">
                      <strong className="t-title-s grow">{c.page_no}쪽{c.title ? ` · ${c.title}` : ""}</strong>
                      <span className="chip chip-selected">{c.people.length}명</span>
                    </div>
                    <span className="t-caption muted">{c.people.join(", ")}이(가) 시험·강조로 적음</span>
                    {groupNotes(c.notes).slice(0, 3).map((n, i) => <p key={i} className="t-body">· {n.text} <span className="t-caption faint">({n.who.join(", ")})</span></p>)}
                  </div>
                ))}
              </Section>
            )}

            {data.exam.length > 0 && (
              <Section icon="star" title="교수님이 시험에 나온다고 한 것" tone="exam">
                {data.exam.map((n, i) => <Line key={i} page={n.page_no}>{n.text}</Line>)}
              </Section>
            )}

            {data.top_pages.length > 0 && (
              <Section icon="target" title="가장 유력한 쪽">
                {data.top_pages.map((p) => (
                  <div key={p.page_no} className="jokbo-page">
                    <strong className="t-title-s">{p.page_no}쪽{p.title ? ` · ${p.title}` : ""}</strong>
                    {p.summary && <p className="t-body">{p.summary}</p>}
                    <p className="t-caption muted">{p.reasons.join(" · ")}</p>
                  </div>
                ))}
              </Section>
            )}

            {data.emphasis.length > 0 && (
              <Section icon="warning-circle" title="강조한 것" tone="emphasis">
                {data.emphasis.map((n, i) => <Line key={i} page={n.page_no}>{n.text}</Line>)}
              </Section>
            )}

            {data.confused.length > 0 && (
              <Section icon="hand-palm" title="내가 헷갈렸던 것">
                {data.confused.map((m, i) => (
                  <div key={i} className="jokbo-page">
                    <span className="t-caption muted">{m.page_no}쪽 · {m.lecture}번째 강의</span>
                    <p className="t-body">{m.explanation ?? `"${m.speech.slice(-80)}" — 공부하기 › 모르겠다에서 설명을 만들 수 있어요`}</p>
                  </div>
                ))}
              </Section>
            )}

            {data.terms.length > 0 && (
              <Section icon="book-open-text" title={`꼭 아는 용어 ${data.terms.length}개`}>
                <div className="jokbo-terms">{data.terms.map((t, i) => <TermCard key={i} term={t.term} page={t.page_no} definition={t.definition} />)}</div>
              </Section>
            )}

            {data.predicted.length > 0 && (
              <Section icon="list-numbers" title="예상 문제" action={
                <Chip variant={showAnswers ? "selected" : "default"} onClick={() => setShowAnswers(!showAnswers)}>{showAnswers ? "답 숨기기" : "답 보기"}</Chip>
              }>
                {data.predicted.map((q, i) => (
                  <div key={i} className="jokbo-page">
                    <strong className="t-body">{i + 1}. {q.question} <span className="t-caption faint">{q.page_no}쪽</span></strong>
                    <p className={`t-body muted answer${showAnswers ? "" : " hidden-answer"}`}>{q.answer}</p>
                  </div>
                ))}
              </Section>
            )}
            {data.predicted.length === 0 && (
              <p className="t-caption muted no-print">예상 문제는 시험 예상 지도에서 "예상 문제 만들기"를 누르면 여기에 같이 나와요.</p>
            )}

            {data.notice.length > 0 && (
              <Section icon="megaphone" title="공지 (범위·일정)" tone="notice">
                {data.notice.map((n, i) => <Line key={i} page={n.page_no}>{n.text}</Line>)}
              </Section>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function Section({ icon, title, tone, action, children }: { icon: string; title: string; tone?: string; action?: ReactNode; children: ReactNode }) {
  return (
    <section className="jokbo-section" style={tone ? { borderColor: `var(--note-${tone}-ink)` } : undefined}>
      <div className="row">
        <span style={{ color: tone ? `var(--note-${tone}-ink)` : "var(--accent-primary)" }}><Icon name={icon} /></span>
        <h2 className="t-title-s grow">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  );
}

function Line({ page, children }: { page: number; children: ReactNode }) {
  return <p className="t-body jokbo-line"><span className="t-caption faint">{page}쪽</span> {children}</p>;
}

interface ReviewCard {
  card_key: string; document_id: string; title: string; source: string; front: string; back: string;
  page_no: number | null; reps: number; lapses: number; new: boolean; next?: Record<string, string>;
}
interface ReviewToday { cards: ReviewCard[]; due: number; new: number; total: number; next_due_at: number | null }

const SOURCE_LABEL: Record<string, string> = { confused: "수업 중 헷갈렸던 곳", exam: "시험 예상 문제", flashcard: "플래시카드" };
const GRADE_BUTTONS = [["again", "몰랐어요", "record"], ["hard", "어렵게 기억", "secondary"], ["good", "기억났어요", "secondary"], ["easy", "바로 알았어요", "primary"]] as const;

/** 오늘의 복습: 틀린 것은 10분 뒤 다시, 맞힌 것은 1일 → 3일 → 점점 길게 */
export function ReviewScreen() {
  const [today, setToday] = useState<ReviewToday | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [flipped, setFlipped] = useState(false);
  const [done, setDone] = useState(0);
  const [busy, setBusy] = useState(false);

  const load = () => getJSON<ReviewToday>("/review/today").then(setToday).catch((e) => setError(e.message));
  useEffect(() => { void load(); }, []);

  const answer = async (grade: string) => {
    if (!today || busy) return;
    const card = today.cards[0];
    setBusy(true);
    try {
      await postJSON(`/review/${card.card_key}`, { grade });
      const rest = today.cards.slice(1);
      // "다시"는 10분 뒤가 아니라 이번 복습 끝에 한 번 더 보여 준다
      setToday({ ...today, cards: grade === "again" ? [...rest, { ...card, new: false }] : rest });
      setDone((n) => n + 1);
      setFlipped(false);
      play(grade === "again" ? "wrong" : "success");
      if (rest.length === 0 && grade !== "again") window.setTimeout(() => play("complete"), 250);
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    setBusy(false);
  };

  const card = today?.cards[0];
  // 답을 본 뒤에는 카드를 밀어서: 왼쪽 = 몰랐어요, 오른쪽 = 기억났어요
  const cardRef = useRef<HTMLButtonElement>(null);
  useSwipe(cardRef, { onLeft: () => void answer("again"), onRight: () => void answer("good"), enabled: flipped && !busy, bind: `${card?.card_key}-${flipped}` });
  return (
    <div className="screen">
      <TopBar title="오늘의 복습" onBack={() => back({ name: "home" })} />
      <div className="screen-body">
        {error && <Empty icon="warning-circle">{error}</Empty>}
        {!today && !error && <p className="muted">카드를 모으는 중…</p>}
        {today && today.total === 0 && (
          <Empty icon="cards">
            <strong className="t-title-s">아직 복습할 카드가 없어요</strong><br />
            강의 뒤 공부하기 › 플래시카드를 만들거나, 수업 중 "모르겠어요"를 누르거나, 시험 예상 문제를 만들면 여기에 모여요.
          </Empty>
        )}
        {today && today.total > 0 && !card && (
          <Empty icon="check-circle" mood="happy">
            <strong className="t-title-s">오늘 복습 끝! {done ? `${done}장 봤어요` : ""}</strong><br />
            {today.next_due_at ? `다음 복습: ${new Date(today.next_due_at * 1000).toLocaleString("ko-KR", { month: "long", day: "numeric", hour: "numeric", minute: "2-digit" })}` : ""}
          </Empty>
        )}
        {card && (
          <>
            {done === 0 && !flipped && (
              <ol className="review-guide">
                <li>질문의 답을 머릿속으로 떠올려 보고</li>
                <li>카드를 눌러 답을 확인한 뒤</li>
                <li>얼마나 기억났는지 고르면, 잊어버릴 때쯤 다시 보여 줘요</li>
              </ol>
            )}
            <p className="t-caption muted" style={{ textAlign: "center" }}>
              남은 카드 {today!.cards.length}장 · {card.title}{card.page_no ? ` ${card.page_no}쪽` : ""}
            </p>
            <button ref={cardRef} key={`${card.card_key}-${flipped}`} className={`flashcard swipe-card ${flipped ? "flip-in" : "card-in"}`} data-flipped={flipped} onClick={() => setFlipped(!flipped)} aria-live="polite">
              <Chip variant="accent">{card.new ? "새 카드 · " : card.lapses ? `${card.lapses}번 틀림 · ` : ""}{SOURCE_LABEL[card.source] ?? card.source}</Chip>
              {flipped && <span className="review-q t-caption">Q. {card.front}</span>}
              <span className={flipped ? "t-body" : "t-title-m"} style={{ whiteSpace: "pre-wrap" }}>{flipped ? card.back : card.front}</span>
              <span className="t-caption faint">{flipped ? "얼마나 기억났는지 아래에서 골라 주세요" : "답을 떠올려 본 뒤 눌러서 확인"}</span>
            </button>
            {flipped ? (
              <>
              <div className="swipe-hint" aria-hidden="true"><span>← 몰랐어요</span><span>기억났어요 →</span></div>
              <div className="grade-row">
                {GRADE_BUTTONS.map(([grade, label, variant]) => (
                  <Button key={grade} variant={variant} onClick={() => answer(grade)} disabled={busy}>
                    <span className="grade-label">{label}<small>{grade === "again" ? "이번에 한 번 더" : card.next?.[grade] ?? ""}</small></span>
                  </Button>
                ))}
              </div>
              </>
            ) : (
              <Button block variant="secondary" onClick={() => setFlipped(true)}>답 보기</Button>
            )}
          </>
        )}
      </div>
    </div>
  );
}

/** 홈 화면 위 "오늘 복습 N장" 띠 */
export function ReviewBanner() {
  const [today, setToday] = useState<ReviewToday | null>(null);
  useEffect(() => { getJSON<ReviewToday>("/review/today").then(setToday).catch(() => {}); }, []);
  if (!today || today.total === 0) return null;
  const count = today.cards.length;
  return (
    <button className="list-item review-banner" onClick={() => go({ name: "review" })}>
      <span className="list-item-icon is-art"><Icon name="brain" art size={40} /></span>
      <span className="grow">
        <span className="t-title-s" style={{ display: "block" }}>{count ? `오늘 복습 ${count}장` : "오늘 복습 끝!"}</span>
        <span className="list-item-sub">{count ? `다시 볼 때가 된 카드 ${today.due}장 · 새 카드 ${today.new}장` : "잊어버릴 때쯤 다시 알려 드릴게요"}</span>
      </span>
      <span className="list-item-chev"><Icon name="caret-right" size={18} /></span>
    </button>
  );
}

interface Privacy { ai: string; speech: string; storage: string; training: boolean }

export function usePrivacy() {
  return useApi<Privacy>("/privacy").data;
}

/** 녹음 전 한 번: 녹음 허락 · 데이터가 어디로 가는지. 동의하면 이 기기에 기억한다 */
export function ConsentSheet({ onAgree, onCancel }: { onAgree: () => void; onCancel: () => void }) {
  const info = usePrivacy();
  const [ok, setOk] = useState(false);
  return (
    <>
      <div className="sheet-bg" onClick={onCancel} />
      <div className="sheet" role="dialog" aria-modal="true" aria-labelledby="consent-title">
        <h3 className="t-title-m" id="consent-title">녹음하기 전에</h3>
        <div className="banner">
          <p className="t-body"><b>강의 녹음은 교수님 허락을 받아 주세요.</b> 학교·수업마다 규칙이 달라요. 녹음은 본인 공부에만 쓰고 다른 사람에게 퍼뜨리지 마세요.</p>
        </div>
        <PrivacyFacts info={info} />
        <label className="row t-body"><input type="checkbox" checked={ok} onChange={(e) => setOk(e.target.checked)} /> 녹음 허락을 받았고, 위 내용을 확인했어요</label>
        <Button block variant="record" icon="microphone" disabled={!ok} onClick={onAgree}>녹음 시작</Button>
      </div>
    </>
  );
}

function PrivacyFacts({ info }: { info: Privacy | null }) {
  if (!info) return <p className="muted">확인하는 중…</p>;
  return (
    <ul className="privacy-list t-body">
      <li><b>받아쓰기</b> · {info.speech}</li>
      <li><b>필기·요약 AI</b> · {info.ai}</li>
      <li><b>저장</b> · {info.storage}</li>
      <li><b>우리 AI 학습</b> · {info.training ? "켜짐: AI 요청·답과 필기 고친 기록을 이 서버 안에 학습 데이터로 남겨요" : "꺼짐"}</li>
    </ul>
  );
}

/** 설정 한 줄: 아이콘 · 제목 · 설명 · 오른쪽 조작 */
function SettingRow({ icon, title, sub, right, onClick, danger }: { icon: string; title: string; sub?: string; right?: ReactNode; onClick?: () => void; danger?: boolean }) {
  const body = (
    <>
      <span className={`set-ic${danger ? " danger" : ""}`}><Icon name={icon} art size={24} /></span>
      <span className="grow set-text"><b>{title}</b>{sub && <small>{sub}</small>}</span>
      {right ?? (onClick && <Icon name="caret-right" size={16} />)}
    </>
  );
  return onClick ? <button className={`set-row${danger ? " danger" : ""}`} onClick={onClick}>{body}</button> : <div className="set-row">{body}</div>;
}

function Segmented<T extends string | number>({ value, options, onChange }: { value: T; options: [T, string][]; onChange: (v: T) => void }) {
  return (
    <span className="seg" role="radiogroup">
      {options.map(([v, label]) => (
        <button key={String(v)} role="radio" aria-checked={v === value} className={v === value ? "on" : ""} onClick={() => onChange(v)}>{label}</button>
      ))}
    </span>
  );
}

export function Switch({ on, onChange, label }: { on: boolean; onChange: (v: boolean) => void; label: string }) {
  return <button className={`switch${on ? " on" : ""}`} role="switch" aria-checked={on} aria-label={label} onClick={() => onChange(!on)}><i /></button>;
}

/** 설정: 계정 · 화면 · 소리와 진동 · 공부 · 녹음과 개인정보 · 앱 정보 */
export function PrivacyScreen() {
  const info = usePrivacy();
  const { data: docs, reload } = useApi<DocumentBrief[]>("/documents");
  const [busy, setBusy] = useState(false);
  const [prefs, setP] = useState<Prefs>(getPrefs());
  const [sound, setSound] = useState(soundOn());
  const [me, setMe] = useState<{ auth: boolean; user: { name: string } | null } | null>(null);
  const [showFacts, setShowFacts] = useState(false);
  useEffect(() => { getJSON<typeof me>("/auth/me").then(setMe).catch(() => {}); }, []);
  const change = (c: Partial<Prefs>) => setP(setPrefs(c));

  const wipe = async () => {
    if (!docs?.length || !confirm(`강의자료 ${docs.length}개와 그 녹음·필기·복습 기록을 모두 지울까요? 되돌릴 수 없어요.`)) return;
    setBusy(true);
    for (const d of docs) await fetch(`${API}/documents/${d.id}`, { method: "DELETE" }).catch(() => {});
    try { localStorage.removeItem("ln.consent"); } catch { /* 괜찮다 */ }
    await reload();
    setBusy(false);
  };
  const logout = async () => {
    if (!confirm("로그아웃할까요? 자료는 서버에 그대로 있어요.")) return;
    await postJSON("/auth/logout").catch(() => {});
    window.location.hash = "#/";
    window.location.reload();
  };
  const reminder = (h: number) => {
    change({ reminder: h });
    const app = android();
    if (h === 0) app?.cancelReminder?.(); else app?.setReminder?.("오늘 배운 것, 복습할 시간이에요", "눌러서 바로 복습하기", h, 0);
  };

  return (
    <div className="screen settings">
      <TopBar title="설정" onBack={() => back({ name: "home" })} />
      <div className="screen-body">
        {me?.auth && me.user && (
          <section className="set-group">
            <h3>계정</h3>
            <SettingRow icon="users" title={me.user.name} sub="내 강의·녹음·필기는 나만 볼 수 있어요"
              right={<button className="chip chip-default" onClick={() => void logout()}>로그아웃</button>} />
            <AccountSecurity />
          </section>
        )}

        <section className="set-group">
          <h3>화면</h3>
          <SettingRow icon="sparkle" title="화면 색" right={<Segmented value={prefs.theme} onChange={(v) => change({ theme: v })}
            options={[["system", "기기대로"], ["light", "밝게"], ["dark", "어둡게"]]} />} />
          <SettingRow icon="book-open-text" title="글자 크기" right={<Segmented value={prefs.text} onChange={(v) => change({ text: v })}
            options={[["normal", "보통"], ["large", "크게"]]} />} />
          <SettingRow icon="waveform" title="움직임 줄이기" sub="화면 전환·카드 효과를 끄고 바로 보여 줘요"
            right={<Switch on={prefs.motion === "reduce"} onChange={(v) => change({ motion: v ? "reduce" : "full" })} label="움직임 줄이기" />} />
        </section>

        <section className="set-group">
          <h3>소리와 진동</h3>
          <SettingRow icon="megaphone" title="효과음" sub="정답·카드 넘기기·복습 끝 같은 순간에만 작게"
            right={<Switch on={sound} onChange={(v) => { setSoundOn(v); setSound(v); }} label="효과음" />} />
          {sound && (
            <div className="set-preview">{PREVIEW.map(([name, label]) => <button key={name} className="chip chip-default" onClick={() => play(name)}>{label}</button>)}</div>
          )}
          <SettingRow icon="hand-palm" title="진동" sub="녹음 중에는 소리 대신 진동으로 알려요 (시험·공지 얘기)"
            right={<Switch on={prefs.vibrate} onChange={(v) => change({ vibrate: v })} label="진동" />} />
        </section>

        <section className="set-group">
          <h3>공부</h3>
          <SettingRow icon="brain" title="퀴즈 카드 기본 장 수" right={<Segmented value={prefs.quizCount} onChange={(v) => change({ quizCount: v })}
            options={[[5, "5"], [8, "8"], [12, "12"]]} />} />
          {android() && (
            <SettingRow icon="clock" title="복습 알림" sub="매일 이 시각에 '오늘 복습 N장'을 알려요" right={<Segmented value={prefs.reminder} onChange={reminder}
              options={[[0, "끄기"], [19, "7시"], [21, "9시"], [23, "11시"]]} />} />
          )}
        </section>

        <section className="set-group">
          <h3>녹음과 개인정보</h3>
          <SettingRow icon="shield-check" title="녹음 전 안내" sub="녹음은 교수님 허락을 받고, 본인 공부에만 써 주세요" />
          <SettingRow icon="question" title="내 녹음과 자료는 어디로 가나요?" sub={showFacts ? undefined : "받아쓰기 · AI · 저장 위치 보기"} onClick={() => setShowFacts((v) => !v)} />
          {showFacts && <div className="set-facts"><PrivacyFacts info={info} /></div>}
          <SettingRow icon="arrow-counter-clockwise" title="녹음 동의 다시 받기" sub="다음 녹음 때 안내를 다시 보여 줘요"
            onClick={() => { try { localStorage.removeItem("ln.consent"); } catch { /* 괜찮다 */ } alert("다음 녹음 때 다시 물어볼게요."); }} />
          <SettingRow icon="trash" danger title={busy ? "지우는 중…" : "내 자료 모두 지우기"} sub={docs?.length ? `강의자료 ${docs.length}개와 녹음·필기·복습 기록` : "지울 자료가 없어요"}
            onClick={busy || !docs?.length ? undefined : () => void wipe()} />
        </section>

        <section className="set-group">
          <h3>앱 정보</h3>
          <SettingRow icon="sparkle" title="LUNE · AI 강의 노트" sub="Listen. Learn. Remember." />
          <SettingRow icon="graduation-cap" title="처음 안내 다시 보기" onClick={() => go({ name: "intro" })} />
          {android() && <SettingRow icon="gear" title="서버 주소 바꾸기" sub="다른 LUNE 서버에 연결해요" onClick={() => android()?.changeServer()} />}
        </section>
        {me?.auth && <MigrateServer />}
      </div>
    </div>
  );
}

/** 공부하기 › 모르겠다: 수업 중 표시한 곳마다 설명 만들기 */
export function ConfusedPane({ sessionId }: { sessionId: string }) {
  const [marks, setMarks] = useState<{ id: number; page_no: number; at_ms: number; speech: string; explanation: string | null }[] | null>(null);
  const [busy, setBusy] = useState<number | null>(null);
  useEffect(() => { getJSON<typeof marks>(`/sessions/${sessionId}/marks`).then(setMarks).catch(() => setMarks([])); }, [sessionId]);

  const explain = async (id: number) => {
    setBusy(id);
    try {
      const m = await postJSON<NonNullable<typeof marks>[number]>(`/marks/${id}/explain`);
      setMarks((all) => all?.map((x) => (x.id === id ? m : x)) ?? null);
    } catch (e) { alert(e instanceof Error ? e.message : String(e)); }
    setBusy(null);
  };

  if (!marks) return <p className="muted">불러오는 중…</p>;
  if (marks.length === 0) return <Empty icon="hand-palm">수업 중 "모르겠어요"를 누른 곳이 여기에 모여요</Empty>;
  return (
    <>
      <p className="t-caption muted">설명을 만든 것은 오늘의 복습 카드로도 나와요</p>
      {marks.map((m) => (
        <div key={m.id} className="banner">
          <span className="t-caption faint">{m.page_no}쪽 · {Math.floor(m.at_ms / 60000)}분쯤</span>
          <p className="t-body muted">"{m.speech.slice(-140) || "(받아쓴 말 없음)"}"</p>
          {m.explanation ? <PostIt type="qa">{m.explanation}</PostIt> : (
            <Button onClick={() => explain(m.id)} disabled={busy !== null} icon="sparkle">{busy === m.id ? "설명 만드는 중…" : "쉽게 다시 설명해 줘"}</Button>
          )}
        </div>
      ))}
    </>
  );
}


/** 함께 만드는 족보: 로그인 없이 파일로. 내 족보 파일을 보내고, 친구 파일을 합치면 여럿이 표시한 쪽이 위로 */
function ShareBox({ docId, friends }: { docId: string; friends: string[] }) {
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);

  const exportFile = async () => {
    const nickname = prompt("친구에게 보일 내 이름", "") ?? "";
    const res = await fetch(`${API}/documents/${docId}/share?nickname=${encodeURIComponent(nickname)}`);
    if (!res.ok) return alert("족보 파일을 만들지 못했어요");
    const data = await res.json();
    const name = `${data.title} 족보${nickname ? ` (${nickname})` : ""}.json`;
    const app = android();
    if (app) return app.saveFile(name, "application/json", JSON.stringify(data));
    const blob = new Blob([JSON.stringify(data)], { type: "application/json" });
    const a = Object.assign(document.createElement("a"), { href: URL.createObjectURL(blob), download: `${data.title} 족보${nickname ? ` (${nickname})` : ""}.json` });
    a.click();
    URL.revokeObjectURL(a.href);
  };

  const importFile = async (file: File) => {
    setBusy(true);
    try {
      const share = JSON.parse(await file.text());
      const nickname = prompt("이 족보를 보낸 친구 이름", share.nickname || "친구") ?? "친구";
      const res = await fetch(`${API}/documents/${docId}/shared`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ nickname, share }),
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body?.detail ?? "합치지 못했어요");
      window.location.reload();
    } catch (e) { alert(e instanceof Error ? e.message : "족보 파일을 읽지 못했어요"); }
    setBusy(false);
  };

  return (
    <div className="banner no-print">
      <div className="row">
        <span className="list-item-icon is-art"><Icon name="users" art size={40} /></span>
        <span className="grow">
          <strong className="t-title-s" style={{ display: "block" }}>함께 만드는 족보</strong>
          <span className="t-caption muted">{friends.length ? `${friends.join(", ")}의 족보를 합쳤어요` : "LUNE 친구는 같은 PDF 로 들은 족보가 저절로 합쳐져요. 친구가 아니면 파일로 주고받아요"}</span>
        </span>
      </div>
      <button className="link-row" onClick={() => go({ name: "friends" })}>
        <Icon name="users" art size={20} /><span className="grow">친구 추가 · 관리</span><Icon name="caret-right" size={14} />
      </button>
      <div className="row">
        <Button className="grow" variant="secondary" onClick={exportFile}>파일로 보내기</Button>
        <Button className="grow" variant="secondary" onClick={() => input.current?.click()} disabled={busy}>{busy ? "합치는 중…" : "받은 파일 합치기"}</Button>
        <input ref={input} type="file" accept="application/json,.json" hidden onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) void importFile(f); }} />
      </div>
    </div>
  );
}

/** 같은 글(띄어쓰기·문장부호 무시)은 한 줄로 모으고 누가 적었는지만 합친다 */
function groupNotes(notes: { who: string; text: string }[]) {
  const groups = new Map<string, { text: string; who: string[] }>();
  for (const n of notes) {
    const key = n.text.replace(/[\s\p{P}]/gu, "").slice(0, 60);
    const g = groups.get(key) ?? { text: n.text, who: [] };
    if (!g.who.includes(n.who)) g.who.push(n.who);
    groups.set(key, g);
  }
  return [...groups.values()].sort((a, b) => b.who.length - a.who.length);
}

/** 효과음 켜고 끄기 (기기에 기억). 녹음 중에는 켜 둬도 소리 대신 진동만 */

/** 새 서버로 옮기기 (서버 주인만): 옮기기 코드를 받아 새 서버 설치 스크립트에 넣으면, 새 서버가 자료를 통째로 가져간다 */
function MigrateServer() {
  const [owner, setOwner] = useState(false);
  const [hint, setHint] = useState("");
  const [code, setCode] = useState<{ code: string; until: number } | null>(null);
  const [copied, setCopied] = useState(false);
  const [tools, setTools] = useState(false);
  useEffect(() => { getJSON<{ owner: boolean; owner_hint?: string }>("/admin/migrate").then((r) => { setOwner(r.owner); setHint(r.owner_hint ?? ""); }).catch(() => {}); }, []);
  if (!owner) return hint ? <p className="owner-hint">서버 주인 계정: {hint} (처음 가입한 계정이에요. 서버 설정은 그 계정에서 보여요)</p> : null;
  const make = async () => {
    if (!confirm("새 서버로 옮기기 코드를 만들까요? 2일 동안 쓸 수 있고, 이 코드를 아는 서버는 모든 자료를 가져갈 수 있어요.")) return;
    try { setCode(await postJSON("/admin/migrate")); } catch (e) { alert(e instanceof Error ? e.message : String(e)); }
  };
  const copy = async () => { try { await navigator.clipboard.writeText(code!.code); setCopied(true); } catch { /* 길게 눌러 복사 */ } };
  return (
    <section className="set-group">
      <h3>서버 (주인만 보여요)</h3>
      <SettingRow icon="envelope-simple" title="메일 · 친구 비밀번호" sub="비밀번호 찾기 메일 보내기, 친구 초기화 코드" onClick={() => setTools(!tools)} />
      {tools && <OwnerAccountTools />}
      <SettingRow icon="arrows-clockwise" title="새 서버로 옮기기" sub="더 큰 서버를 만들 때: 계정·강의·녹음을 통째로 넘겨요" onClick={() => void make()} />
      {code && (
        <div className="migrate-code">
          <small>옮기기 코드 · {new Date(code.until * 1000).toLocaleString("ko-KR", { month: "long", day: "numeric", hour: "numeric", minute: "2-digit" })}까지</small>
          <code>{code.code}</code>
          <button className="chip chip-accent" onClick={() => void copy()}>{copied ? "복사했어요" : "복사"}</button>
          <small>새 서버 설치 스크립트의 MIGRATE_CODE 에 붙여 넣으세요. 옮기는 동안에는 앱에 새로 녹음하지 마세요.</small>
        </div>
      )}
    </section>
  );
}
