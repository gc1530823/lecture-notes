// 친구 탭: 친구(추가·신청·시간표 보기·친구마다 설정) · 족보(강의자료마다 합쳐진 친구·받은 파일·공개/합치기) · 공개 설정
// 친구끼리는 같은 강의자료(같은 PDF)로 들은 강의의 족보가 저절로 합쳐진다. 녹음·받아쓰기·필기 전체는 서로 못 본다.
import { useCallback, useEffect, useState } from "react";
import { getJSON, postJSON } from "../api/useApi";
import SlidingTabs from "../components/SlidingTabs";
import { Empty, Button, Icon, TopBar } from "../components/ui";
import { go } from "../router";
import { Switch } from "./ExamPrep";
import { WeekGrid, type ClassRow } from "./Timetable";
import { askYes } from "../components/Dialog";
import { Skeleton } from "../lib/motion";

/** 받침이 있으면 '을', 없으면 '를' (운영체제를 · 자료구조를 · 컴퓨터공학을) */
const withEul = (w: string) => {
  const c = w.charCodeAt(w.length - 1);
  return w + (c >= 0xac00 && c <= 0xd7a3 && (c - 0xac00) % 28 ? "을" : "를");
};

interface Friend {
  id: string; name: string; status: string; mine: boolean; created_at: number;
  share?: boolean; merge?: boolean; their_jokbo?: boolean; their_timetable?: boolean; same_courses?: string[];
}
interface Prefs { share_jokbo: boolean; share_timetable: boolean; merge_jokbo: boolean; allow_requests: boolean; items: string[]; share_courses: string[] }
interface FriendsData { me: { name: string; code: string; prefs: Prefs; courses: string[] }; friends: Friend[]; incoming: Friend[]; outgoing: Friend[] }
interface JokboDoc { doc_id: string; title: string; course: string; friends: string[]; files: { id: number; nickname: string }[]; friend_share: boolean; friend_merge: boolean }

const API = import.meta.env.VITE_API_URL ?? "";
const ITEMS: [string, string][] = [["exam", "시험 표시"], ["emphasis", "강조"], ["notice", "공지"], ["terms", "용어"], ["predicted", "예상 문제"], ["confused", "모르겠어요 설명"]];
const patch = (path: string, body: object) =>
  fetch(API + path, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
    .then((r) => { if (!r.ok) throw new Error("저장하지 못했어요"); return r.json(); });

type Tab = "friends" | "jokbo" | "privacy";

const toMin = (t: string) => Number(t.slice(0, 2)) * 60 + Number(t.slice(3, 5));
const toClock = (m: number) => `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;

/** 같이 비는 시간 (공강): 평일 9시~18시에서 둘 다 수업이 없는 1시간 이상 */
function freeTogether(a: { weekday: number; start: string; end: string }[], b: typeof a, from = 9 * 60, to = 18 * 60, min = 60) {
  const out: { weekday: number; start: string; end: string; all: boolean }[] = [];
  for (let d = 0; d < 5; d++) {
    const busy = [...a, ...b].filter((c) => c.weekday === d).map((c) => [toMin(c.start), toMin(c.end)]).sort((x, y) => x[0] - y[0]);
    let t = from;
    for (const [s, e] of [...busy, [to, to]]) {
      if (Math.min(s, to) - t >= min) out.push({ weekday: d, start: toClock(t), end: toClock(Math.min(s, to)), all: !busy.length });
      t = Math.max(t, e);
    }
  }
  return out;
}

const RANGE_KEY = "ln.freeRange";
function FreeTogether({ name, mine, theirs }: { name: string; mine: ClassRow[]; theirs: ClassRow[] }) {
  // 볼 시간대와 최소 길이는 사람마다 다르다 (아침 수업·저녁 동아리) → 고르고 기기에 기억
  const [range, setRange] = useState<[number, number, number]>(() => {
    try { const r = JSON.parse(localStorage.getItem(RANGE_KEY) ?? "null"); if (Array.isArray(r) && r.length === 3) return r as [number, number, number]; } catch { /* 기본값 */ }
    return [9, 18, 60];
  });
  const pick = (r: [number, number, number]) => { setRange(r); try { localStorage.setItem(RANGE_KEY, JSON.stringify(r)); } catch { /* 괜찮다 */ } };
  const [from, to, min] = range;
  const slots = freeTogether(mine, theirs, from * 60, to * 60, min);
  return (
    <div className="free-together">
      <b><Icon name="clock" size={16} /> {name}님과 같이 비는 시간</b>
      <div className="free-range">
        <select value={from} onChange={(e) => pick([Number(e.target.value), Math.max(to, Number(e.target.value) + 1), min])} aria-label="시작 시각">
          {Array.from({ length: 15 }, (_, i) => i + 7).map((h) => <option key={h} value={h}>{h}시</option>)}
        </select>
        <span>~</span>
        <select value={to} onChange={(e) => pick([Math.min(from, Number(e.target.value) - 1), Number(e.target.value), min])} aria-label="끝 시각">
          {Array.from({ length: 15 }, (_, i) => i + 9).map((h) => <option key={h} value={h}>{h}시</option>)}
        </select>
        <span>· 최소</span>
        <select value={min} onChange={(e) => pick([from, to, Number(e.target.value)])} aria-label="최소 길이">
          {[30, 60, 90, 120].map((m) => <option key={m} value={m}>{m < 60 ? `${m}분` : `${m / 60}시간`}</option>)}
        </select>
      </div>
      {slots.length ? (
        <div className="free-days">
          {[0, 1, 2, 3, 4].filter((d) => slots.some((f) => f.weekday === d)).map((d) => (
            <div key={d} className="free-day">
              <i>{"월화수목금"[d]}</i>
              {slots.filter((f) => f.weekday === d).map((f, j) => <span key={j} className="free-chip">{f.all ? "종일" : `${f.start}~${f.end}`}</span>)}
            </div>
          ))}
        </div>
      ) : <small>평일 {from}시~{to}시에 같이 비는 {min < 60 ? `${min}분` : `${min / 60}시간`}이 없어요</small>}
    </div>
  );
}

export function FriendsScreen() {
  const [tab, setTab] = useState<Tab>("friends");
  const [data, setData] = useState<FriendsData | null>(null);
  const [error, setError] = useState("");
  const [askShare, setAskShare] = useState<string | null>(null);   // 친구가 된 직후: 공유할 과목 고르기
  const load = useCallback(() => {
    getJSON<FriendsData>("/friends").then(setData).catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);
  useEffect(load, [load]);

  return (
    <div className="screen friends">
      <TopBar title="친구" />
      <div className="screen-body">
        <SlidingTabs label="친구 메뉴" value={tab} onChange={setTab}
          items={[["friends", `친구${data?.incoming.length ? ` ${data.incoming.length}` : ""}`], ["jokbo", "족보"], ["privacy", "공개 설정"]] as const} />
        {error && <p className="muted">{error}</p>}
        <div key={tab} className="pane-in">
        {data && tab === "friends" && <FriendsTab data={data} reload={load} onSettings={() => setTab("privacy")}
          onBecameFriends={(name) => { if (!data.me.prefs.share_courses?.length) setAskShare(name); }} />}
        {data && tab === "jokbo" && <JokboTab prefs={data.me.prefs} onSettings={() => setTab("privacy")} />}
        {data && tab === "privacy" && <PrivacyTab prefs={data.me.prefs} courses={data.me.courses} onSaved={setData} />}
        </div>
      </div>
      {data && askShare !== null && (
        <div className="sheet-back" onClick={() => setAskShare(null)}>
          <div className="friend-table share-ask" onClick={(e) => e.stopPropagation()} role="dialog" aria-label="공유할 과목 고르기">
            <b className="admin-title">{askShare}님과 친구가 됐어요</b>
            <p className="t-caption muted" style={{ margin: 0 }}>아직 아무것도 공유하지 않아요. 족보를 함께 볼 과목만 골라 주세요. 나중에 공개 설정에서 바꿀 수 있어요.</p>
            <ShareCourses prefs={data.me.prefs} courses={data.me.courses} onSaved={(d) => { setData(d); }} />
            <Button block onClick={() => setAskShare(null)}>다 골랐어요</Button>
          </div>
        </div>
      )}
    </div>
  );
}

/* ── 친구 ── */
function FriendsTab({ data, reload, onSettings, onBecameFriends }: { data: FriendsData; reload: () => void; onSettings: () => void; onBecameFriends: (name: string) => void }) {
  const [code, setCode] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  const [table, setTable] = useState<{ name: string; classes: ClassRow[]; mine?: ClassRow[] } | null>(null);

  const add = async () => {
    setMsg(""); setBusy(true);
    try {
      const r = await postJSON<{ status: string; name: string }>("/friends", { code });
      setMsg(r.status === "accepted" ? `${r.name}님과 친구가 됐어요!` : `${r.name}님에게 친구 신청을 보냈어요. 수락하면 친구가 돼요.`);
      if (r.status === "accepted") onBecameFriends(r.name);
      setCode(""); reload();
    } catch (e) { setMsg(e instanceof Error ? e.message : String(e)); }
    setBusy(false);
  };
  const accept = async (f: Friend) => {
    await postJSON(`/friends/${f.id}/accept`).catch(() => {}); navigator.vibrate?.(15); reload(); onBecameFriends(f.name);
  };
  const remove = async (f: Friend, ask: string) => {
    if (ask && !await askYes(ask)) return;
    await fetch(`${API}/friends/${f.id}`, { method: "DELETE" }).catch(() => {});
    setOpen(null); reload();
  };
  const pair = async (f: Friend, change: object) => { await patch(`/friends/${f.id}/settings`, change).catch(() => {}); reload(); };
  const showTable = async (f: Friend) => {
    try {
      const [theirs, mine] = await Promise.all([getJSON<{ name: string; classes: ClassRow[] }>(`/friends/${f.id}/timetable`),
        getJSON<ClassRow[]>("/timetable").catch(() => [] as ClassRow[])]);
      setTable({ ...theirs, mine });
    }
    catch (e) { setMsg(e instanceof Error ? e.message : String(e)); }
  };
  const shareCode = async () => {
    const text = `LUNE에서 친구 추가해 줘! 내 친구 코드: ${data.me.code}\n${window.location.origin}`;
    try {
      if (navigator.share) await navigator.share({ text });
      else { await navigator.clipboard.writeText(data.me.code); setMsg("내 코드를 복사했어요. 카톡에 붙여 넣어 보내세요."); }
    } catch { /* 닫음 */ }
  };

  const addCard = (
    <section className="set-group add-card">
      <h3>친구 추가</h3>
      <div className="my-code-line">
        <span className="grow"><small>내 친구 코드</small><b className="code">{data.me.code}</b></span>
        <Button variant="secondary" icon="export" onClick={() => void shareCode()}>보내기</Button>
      </div>
      {!data.me.prefs.allow_requests && <p className="friend-msg">지금은 친구 신청을 받지 않아요 (공개 설정)</p>}
      <div className="add-friend">
        <input className="input" value={code} maxLength={8} placeholder="친구 코드 6자리" autoCapitalize="characters"
          onChange={(e) => setCode(e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, ""))} aria-label="친구 코드"
          onKeyDown={(e) => { if (e.key === "Enter" && code.length >= 6) void add(); }} />
        <Button onClick={() => void add()} disabled={code.length < 6 || busy}>신청</Button>
      </div>
      {msg && <p className="friend-msg">{msg}</p>}
    </section>
  );
  return (
    <>
      {/* 친구가 없으면 추가부터, 있으면 받은 신청, 내 친구가 먼저 */}
      {data.friends.length === 0 && addCard}
      {data.incoming.length > 0 && (
        <section className="set-group">
          <h3>받은 신청 {data.incoming.length}</h3>
          {data.incoming.map((f) => (
            <div key={f.id} className="set-row">
              <span className="avatar">{f.name.slice(0, 1)}</span>
              <span className="grow set-text"><b>{f.name}</b><small>친구 신청을 보냈어요</small></span>
              <button className="chip chip-default" onClick={() => void remove(f, "")}>거절</button>
              <button className="chip chip-accent" onClick={() => void accept(f)}>수락</button>
            </div>
          ))}
        </section>
      )}

      <section className="set-group">
        <h3>내 친구 {data.friends.length}</h3>
        {data.friends.some((f) => f.same_courses?.length) && (
          <div className="same-course">
            {data.friends.filter((f) => f.same_courses?.length).map((f) => (
              <div key={f.id} className="same-row">
                <span className="avatar">{f.name.slice(0, 1)}</span>
                <span className="grow">
                  <b>{f.name}님도 {withEul(f.same_courses!.join(", "))} 들어요</b>
                  <small>{f.their_jokbo && f.merge !== false ? "족보가 내 족보에 자동으로 합쳐져요" : f.their_jokbo ? "이 친구 족보 합치기를 켜면 같이 볼 수 있어요" : "친구가 족보를 공개하면 합쳐져요"}</small>
                </span>
                {f.their_jokbo && f.merge === false && <button className="chip chip-accent" onClick={() => void pair(f, { merge: true })}>합치기</button>}
              </div>
            ))}
          </div>
        )}
        {data.friends.length === 0 && <Empty icon="users"><strong className="t-title-s">아직 친구가 없어요</strong><br />위에서 친구 코드를 입력해 보세요</Empty>}
        {data.friends.map((f) => (
          <div key={f.id} className={`friend-card${open === f.id ? " open" : ""}`}>
            <button className="set-row" onClick={() => setOpen(open === f.id ? null : f.id)} aria-expanded={open === f.id}>
              <span className="avatar">{f.name.slice(0, 1)}</span>
              <span className="grow set-text">
                <b>{f.name}</b>
                <small>{[f.same_courses?.length ? `같이 듣는 과목 ${f.same_courses.length}` : "", f.their_timetable ? "시간표 공개" : "시간표 비공개", f.their_jokbo ? "족보 공개" : "족보 비공개",
                  f.share === false ? "내 것 숨김" : ""].filter(Boolean).join(", ")}</small>
              </span>
              <Icon name={open === f.id ? "caret-up" : "caret-down"} size={14} />
            </button>
            {open === f.id && (
              <div className="friend-more">
                <Button block variant="secondary" icon="calendar-check" disabled={!f.their_timetable} onClick={() => void showTable(f)}>
                  {f.their_timetable ? `${f.name}님 시간표 보기` : "시간표를 비공개로 해 뒀어요"}
                </Button>
                <label className="set-line"><span className="grow">이 친구에게 내 족보·시간표 보여 주기</span>
                  <Switch on={f.share !== false} onChange={(v) => void pair(f, { share: v })} label="이 친구에게 보여 주기" /></label>
                <label className="set-line"><span className="grow">이 친구 족보를 내 족보에 합치기</span>
                  <Switch on={f.merge !== false} onChange={(v) => void pair(f, { merge: v })} label="이 친구 족보 합치기" /></label>
                <div className="row">
                  <button className="chip chip-default" onClick={onSettings}>전체 공개 설정</button>
                  <span className="grow" />
                  <button className="chip chip-default danger" onClick={() => void remove(f, `${f.name}님과 친구를 끊을까요? 족보도 더 이상 합쳐지지 않아요.`)}>친구 끊기</button>
                </div>
              </div>
            )}
          </div>
        ))}
        {data.outgoing.map((f) => (
          <div key={f.id} className="set-row">
            <span className="avatar wait">{f.name.slice(0, 1)}</span>
            <span className="grow set-text"><b>{f.name}</b><small>수락을 기다리는 중</small></span>
            <button className="chip chip-default" onClick={() => void remove(f, "")}>취소</button>
          </div>
        ))}
      </section>
      {data.friends.length > 0 && addCard}

      {table && (
        <div className="sheet-back" onClick={() => setTable(null)}>
          <div className="friend-table" onClick={(e) => e.stopPropagation()} role="dialog" aria-label={`${table.name} 시간표`}>
            <div className="row"><b className="grow">{table.name}님 시간표</b>
              <button className="top-bar-back" onClick={() => setTable(null)} aria-label="닫기"><Icon name="x" /></button></div>
            {table.classes.length ? (
              <>
                {table.mine?.length ? <FreeTogether name={table.name} mine={table.mine} theirs={table.classes} /> : null}
                <WeekGrid rows={table.classes.map((c, i) => ({ ...c, id: i }))} onPick={() => {}} />
                <ul className="friend-classes">
                  {table.classes.map((c, i) => <li key={i}><b>{"월화수목금토일"[c.weekday]}</b> {c.start}~{c.end}, {c.course}{c.place ? ` (${c.place})` : ""}</li>)}
                </ul>
              </>
            ) : <p className="muted">아직 시간표를 넣지 않았어요.</p>}
          </div>
        </div>
      )}
    </>
  );
}

/* ── 족보 ── */
function JokboTab({ prefs, onSettings }: { prefs: Prefs; onSettings: () => void }) {
  const [docs, setDocs] = useState<JokboDoc[] | null>(null);
  const load = useCallback(() => { getJSON<{ docs: JokboDoc[] }>("/friends/jokbo").then((d) => setDocs(d.docs)).catch(() => setDocs([])); }, []);
  useEffect(load, [load]);
  const flag = async (d: JokboDoc, change: object) => { await patch(`/documents/${d.doc_id}/friends`, change).catch(() => {}); load(); };
  const dropFile = async (id: number, who: string) => {
    if (!await askYes(`${who}에게 받은 족보 파일을 뺄까요?`)) return;
    await fetch(`${API}/shared/${id}`, { method: "DELETE" }).catch(() => {});
    load();
  };
  return (
    <>
      {(!prefs.share_jokbo || !prefs.merge_jokbo) && (
        <div className="jokbo-status-card">
          <Icon name="shield-check" size={18} />
          <span className="grow">
            {!prefs.share_jokbo ? "내 족보 비공개 중" : "친구 족보 합치기 꺼짐"}
          </span>
          <button className="chip chip-accent" onClick={onSettings}>공개 설정</button>
        </div>
      )}
      {!docs && <Skeleton />}
      {docs && docs.length === 0 && <Empty icon="notebook"><strong className="t-title-s">아직 녹음한 강의가 없어요</strong></Empty>}
      {docs?.map((d) => (
        <section key={d.doc_id} className="jokbo-doc">
          <div className="row">
            <span className="grow">
              <b>{d.title}</b>
              <small>{d.friends.length || d.files.length ? `${[...d.friends, ...d.files.map((f) => f.nickname)].join(", ")}의 족보가 합쳐져 있어요` : "합쳐진 친구 족보가 없어요"}</small>
            </span>
            <button className="chip chip-accent" onClick={() => go({ name: "jokbo", docId: d.doc_id })}>족보 열기</button>
          </div>
          {d.files.map((f) => (
            <div key={f.id} className="row jokbo-file">
              <Icon name="file-text" size={15} /><span className="grow">{f.nickname}님에게 파일로 받은 족보</span>
              <button className="chip chip-default" onClick={() => void dropFile(f.id, f.nickname)}>빼기</button>
            </div>
          ))}
          <label className="set-line"><span className="grow">이 자료 족보를 친구에게 공개</span>
            <Switch on={d.friend_share} onChange={(v) => void flag(d, { share: v })} label="이 자료 족보 공개" /></label>
          <label className="set-line"><span className="grow">친구 족보를 여기에 합치기</span>
            <Switch on={d.friend_merge} onChange={(v) => void flag(d, { merge: v })} label="친구 족보 합치기" /></label>
        </section>
      ))}
    </>
  );
}

/* ── 공개 설정 ── */
function PrivacyTab({ prefs, courses, onSaved }: { prefs: Prefs; courses: string[]; onSaved: (d: FriendsData) => void }) {
  const [p, setP] = useState(prefs);
  const save = async (change: Partial<Prefs>) => {
    setP({ ...p, ...change });
    try { onSaved(await patch("/friends/settings", change)); } catch { setP(p); }
  };
  const toggleItem = (k: string) => void save({ items: p.items.includes(k) ? p.items.filter((x) => x !== k) : [...p.items, k] });
  const Row = ({ title, sub, on, k }: { title: string; sub?: string; on: boolean; k: keyof Prefs }) => (
    <div className="set-row">
      <span className="grow set-text"><b>{title}</b>{sub && <small>{sub}</small>}</span>
      <Switch on={on} onChange={(v) => void save({ [k]: v })} label={title} />
    </div>
  );
  return (
    <>
      <section className="set-group">
        <h3>족보를 공유할 과목</h3>
        <ShareCourses prefs={p} courses={courses} onSaved={(d) => { setP(d.me.prefs); onSaved(d); }} hideTimetable />
      </section>
      <section className="set-group">
        <h3>친구에게 공개</h3>
        <Row k="share_timetable" on={p.share_timetable} title="내 시간표 공개" />
      </section>
      {p.share_jokbo && (
        <section className="set-group">
          <h3>족보에서 친구에게 보일 것</h3>
          <div className="item-picks">
            {ITEMS.map(([k, label]) => (
              <button key={k} className={`pick${p.items.includes(k) ? " on" : ""}`} aria-pressed={p.items.includes(k)} onClick={() => toggleItem(k)}>
                {p.items.includes(k) && <Icon name="check" size={12} />} {label}
              </button>
            ))}
          </div>
        </section>
      )}
      <section className="set-group">
        <h3>받기</h3>
        <Row k="merge_jokbo" on={p.merge_jokbo} title="친구 족보 합치기" />
        <Row k="allow_requests" on={p.allow_requests} title="친구 신청 받기" />
      </section>
    </>
  );
}

/** 족보를 공유할 과목 고르기 (기본은 아무것도 공유 안 함) + 시간표 공개 */
function ShareCourses({ prefs, courses, onSaved, hideTimetable }: { prefs: Prefs; courses: string[]; onSaved: (d: FriendsData) => void; hideTimetable?: boolean }) {
  const [chosen, setChosen] = useState<string[]>(prefs.share_courses ?? []);
  const [timetable, setTimetable] = useState(prefs.share_timetable);
  const save = async (change: object) => { try { onSaved(await patch("/friends/settings", change)); } catch { /* 그대로 */ } };
  const flip = (c: string) => {
    const next = chosen.includes(c) ? chosen.filter((x) => x !== c) : [...chosen, c];
    setChosen(next); void save({ share_courses: next });
  };
  return (
    <div className="share-courses">
      {courses.length === 0 ? (
        <Empty icon="folder-simple-plus"><strong className="t-title-s">과목이 정해진 강의자료가 없어요</strong></Empty>
      ) : (
        <div className="item-picks">
          {courses.map((c) => (
            <button key={c} className={`pick${chosen.includes(c) ? " on" : ""}`} aria-pressed={chosen.includes(c)} onClick={() => flip(c)}>
              {chosen.includes(c) && <Icon name="check" size={12} />} {c}
            </button>
          ))}
        </div>
      )}
      {!hideTimetable && (
        <label className="set-line"><span className="grow">내 시간표도 보여 주기</span>
          <Switch on={timetable} onChange={(v) => { setTimetable(v); void save({ share_timetable: v }); }} label="시간표 공개" /></label>
      )}
    </div>
  );
}
