// 친구 탭: 친구(추가·신청·시간표 보기·친구마다 설정) · 족보(강의자료마다 합쳐진 친구·받은 파일·공개/합치기) · 공개 설정
// 친구끼리는 같은 강의자료(같은 PDF)로 들은 강의의 족보가 저절로 합쳐진다. 녹음·받아쓰기·필기 전체는 서로 못 본다.
import { useCallback, useEffect, useState } from "react";
import { getJSON, postJSON } from "../api/useApi";
import SlidingTabs from "../components/SlidingTabs";
import { Button, Icon, TopBar } from "../components/ui";
import { back, go } from "../router";
import { Switch } from "./ExamPrep";
import { WeekGrid, type ClassRow } from "./Timetable";

interface Friend {
  id: string; name: string; status: string; mine: boolean; created_at: number;
  share?: boolean; merge?: boolean; their_jokbo?: boolean; their_timetable?: boolean;
}
interface Prefs { share_jokbo: boolean; share_timetable: boolean; merge_jokbo: boolean; allow_requests: boolean; items: string[] }
interface FriendsData { me: { name: string; code: string; prefs: Prefs }; friends: Friend[]; incoming: Friend[]; outgoing: Friend[] }
interface JokboDoc { doc_id: string; title: string; course: string; friends: string[]; files: { id: number; nickname: string }[]; friend_share: boolean; friend_merge: boolean }

const API = import.meta.env.VITE_API_URL ?? "";
const ITEMS: [string, string][] = [["exam", "시험 표시"], ["emphasis", "강조"], ["notice", "공지"], ["terms", "용어"], ["predicted", "예상 문제"], ["confused", "모르겠어요 설명"]];
const patch = (path: string, body: object) =>
  fetch(API + path, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
    .then((r) => { if (!r.ok) throw new Error("저장하지 못했어요"); return r.json(); });

type Tab = "friends" | "jokbo" | "privacy";

export function FriendsScreen() {
  const [tab, setTab] = useState<Tab>("friends");
  const [data, setData] = useState<FriendsData | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(() => {
    getJSON<FriendsData>("/friends").then(setData).catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);
  useEffect(load, [load]);

  return (
    <div className="screen friends">
      <TopBar title="친구" onBack={() => back({ name: "home" })} />
      <div className="screen-body">
        <SlidingTabs label="친구 메뉴" value={tab} onChange={setTab}
          items={[["friends", `친구${data?.incoming.length ? ` · ${data.incoming.length}` : ""}`], ["jokbo", "족보"], ["privacy", "공개 설정"]] as const} />
        {error && <p className="muted">{error}</p>}
        <div key={tab} className="pane-in">
        {data && tab === "friends" && <FriendsTab data={data} reload={load} onSettings={() => setTab("privacy")} />}
        {data && tab === "jokbo" && <JokboTab prefs={data.me.prefs} onSettings={() => setTab("privacy")} />}
        {data && tab === "privacy" && <PrivacyTab prefs={data.me.prefs} onSaved={setData} />}
        </div>
      </div>
    </div>
  );
}

/* ── 친구 ── */
function FriendsTab({ data, reload, onSettings }: { data: FriendsData; reload: () => void; onSettings: () => void }) {
  const [code, setCode] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  const [table, setTable] = useState<{ name: string; classes: ClassRow[] } | null>(null);

  const add = async () => {
    setMsg(""); setBusy(true);
    try {
      const r = await postJSON<{ status: string; name: string }>("/friends", { code });
      setMsg(r.status === "accepted" ? `${r.name}님과 친구가 됐어요!` : `${r.name}님에게 친구 신청을 보냈어요. 수락하면 친구가 돼요.`);
      setCode(""); reload();
    } catch (e) { setMsg(e instanceof Error ? e.message : String(e)); }
    setBusy(false);
  };
  const accept = async (f: Friend) => { await postJSON(`/friends/${f.id}/accept`).catch(() => {}); navigator.vibrate?.(15); reload(); };
  const remove = async (f: Friend, ask: string) => {
    if (ask && !confirm(ask)) return;
    await fetch(`${API}/friends/${f.id}`, { method: "DELETE" }).catch(() => {});
    setOpen(null); reload();
  };
  const pair = async (f: Friend, change: object) => { await patch(`/friends/${f.id}/settings`, change).catch(() => {}); reload(); };
  const showTable = async (f: Friend) => {
    try { setTable(await getJSON(`/friends/${f.id}/timetable`)); }
    catch (e) { setMsg(e instanceof Error ? e.message : String(e)); }
  };
  const shareCode = async () => {
    const text = `LUNE에서 친구 추가해 줘! 내 친구 코드: ${data.me.code}\n${window.location.origin}`;
    try {
      if (navigator.share) await navigator.share({ text });
      else { await navigator.clipboard.writeText(data.me.code); setMsg("내 코드를 복사했어요. 카톡에 붙여 넣어 보내세요."); }
    } catch { /* 닫음 */ }
  };

  return (
    <>
      <section className="my-code">
        <span className="t-caption">내 친구 코드</span>
        <b className="code">{data.me.code}</b>
        <span className="t-caption">{data.me.prefs.allow_requests ? "친구에게 이 코드를 알려 주세요" : "지금은 친구 신청을 받지 않아요 (공개 설정)"}</span>
        <div className="row"><Button className="grow" variant="secondary" icon="export" onClick={() => void shareCode()}>코드 보내기</Button></div>
      </section>

      <section className="set-group">
        <h3>친구 추가</h3>
        <div className="add-friend">
          <input className="input" value={code} maxLength={8} placeholder="친구 코드 6자리" autoCapitalize="characters"
            onChange={(e) => setCode(e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, ""))} aria-label="친구 코드"
            onKeyDown={(e) => { if (e.key === "Enter" && code.length >= 6) void add(); }} />
          <Button onClick={() => void add()} disabled={code.length < 6 || busy}>신청</Button>
        </div>
        {msg && <p className="friend-msg">{msg}</p>}
      </section>

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
        {data.friends.length === 0 && <p className="friend-empty">아직 친구가 없어요. 같은 수업 듣는 친구의 코드를 넣어 보세요.</p>}
        {data.friends.map((f) => (
          <div key={f.id} className={`friend-card${open === f.id ? " open" : ""}`}>
            <button className="set-row" onClick={() => setOpen(open === f.id ? null : f.id)} aria-expanded={open === f.id}>
              <span className="avatar">{f.name.slice(0, 1)}</span>
              <span className="grow set-text">
                <b>{f.name}</b>
                <small>{[f.their_timetable ? "시간표 공개" : "시간표 비공개", f.their_jokbo ? "족보 공개" : "족보 비공개",
                  f.share === false ? "내 것 숨김" : ""].filter(Boolean).join(" · ")}</small>
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

      {table && (
        <div className="sheet-back" onClick={() => setTable(null)}>
          <div className="friend-table" onClick={(e) => e.stopPropagation()} role="dialog" aria-label={`${table.name} 시간표`}>
            <div className="row"><b className="grow">{table.name}님 시간표</b>
              <button className="top-bar-back" onClick={() => setTable(null)} aria-label="닫기"><Icon name="x" /></button></div>
            {table.classes.length ? (
              <>
                <WeekGrid rows={table.classes.map((c, i) => ({ ...c, id: i }))} onPick={() => {}} />
                <ul className="friend-classes">
                  {table.classes.map((c, i) => <li key={i}><b>{"월화수목금토일"[c.weekday]}</b> {c.start}~{c.end} · {c.course}{c.place ? ` (${c.place})` : ""}</li>)}
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
    if (!confirm(`${who}에게 받은 족보 파일을 뺄까요?`)) return;
    await fetch(`${API}/shared/${id}`, { method: "DELETE" }).catch(() => {});
    load();
  };
  return (
    <>
      <p className="friend-lead">
        같은 강의자료(같은 PDF)로 들은 친구가 있으면 족보가 저절로 합쳐져요.
        {!prefs.share_jokbo && " 지금 내 족보는 친구에게 비공개예요."}
        {!prefs.merge_jokbo && " 지금 친구 족보 합치기를 꺼 뒀어요."}
        {(!prefs.share_jokbo || !prefs.merge_jokbo) && <button className="link" onClick={onSettings}> 공개 설정 바꾸기</button>}
      </p>
      {!docs && <p className="muted">불러오는 중…</p>}
      {docs && docs.length === 0 && <p className="friend-empty">아직 녹음한 강의가 없어요.</p>}
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
              <Icon name="file-text" size={15} /><span className="grow">{f.nickname} · 파일로 받은 족보</span>
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
function PrivacyTab({ prefs, onSaved }: { prefs: Prefs; onSaved: (d: FriendsData) => void }) {
  const [p, setP] = useState(prefs);
  const save = async (change: Partial<Prefs>) => {
    setP({ ...p, ...change });
    try { onSaved(await patch("/friends/settings", change)); } catch { setP(p); }
  };
  const toggleItem = (k: string) => void save({ items: p.items.includes(k) ? p.items.filter((x) => x !== k) : [...p.items, k] });
  const Row = ({ title, sub, on, k }: { title: string; sub: string; on: boolean; k: keyof Prefs }) => (
    <div className="set-row">
      <span className="grow set-text"><b>{title}</b><small>{sub}</small></span>
      <Switch on={on} onChange={(v) => void save({ [k]: v })} label={title} />
    </div>
  );
  return (
    <>
      <section className="set-group">
        <h3>친구에게 공개</h3>
        <Row k="share_jokbo" on={p.share_jokbo} title="내 족보 공개" sub="같은 PDF 로 들은 친구의 족보에 내 표시가 합쳐져요" />
        <Row k="share_timetable" on={p.share_timetable} title="내 시간표 공개" sub="친구가 내 시간표를 볼 수 있어요" />
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
          <p className="friend-note">녹음, 받아쓰기, 내 필기 전체는 언제나 보이지 않아요.</p>
        </section>
      )}
      <section className="set-group">
        <h3>받기</h3>
        <Row k="merge_jokbo" on={p.merge_jokbo} title="친구 족보 합치기" sub="끄면 내 족보에는 내 표시만 보여요" />
        <Row k="allow_requests" on={p.allow_requests} title="친구 신청 받기" sub="끄면 내 코드로 새 신청을 할 수 없어요" />
      </section>
      <p className="friend-note">친구 한 명씩 숨기거나 합치기를 끄려면 친구 탭에서 그 친구를 누르세요. 강의자료마다는 족보 탭에서 바꿀 수 있어요.</p>
    </>
  );
}
