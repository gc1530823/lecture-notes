// 설정 > 계정 보안: 이메일 등록(인증번호) · 비밀번호 바꾸기 · 복구 코드
// 설정 > 서버(주인만): 메일 보내기 설정(Gmail 앱 비밀번호) · 친구 비밀번호 초기화 코드
import { useEffect, useState } from "react";
import { getJSON, postJSON } from "../api/useApi";
import { Button, Icon } from "../components/ui";
import { askYes } from "../components/Dialog";

const API = import.meta.env.VITE_API_URL ?? "";
type Open = "email" | "password" | "recovery" | null;

function Row({ icon, title, sub, open, onClick }: { icon: string; title: string; sub: string; open: boolean; onClick: () => void }) {
  return (
    <button className="set-row" onClick={onClick} aria-expanded={open}>
      <span className="set-ic"><Icon name={icon} art size={24} /></span>
      <span className="grow set-text"><b>{title}</b><small>{sub}</small></span>
      <Icon name={open ? "caret-up" : "caret-down"} size={14} />
    </button>
  );
}

export function AccountSecurity() {
  const [open, setOpen] = useState<Open>(null);
  const [mail, setMail] = useState<{ email: string; pending: string; mail_ready: boolean } | null>(null);
  const [hasCode, setHasCode] = useState<boolean | null>(null);
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [cur, setCur] = useState("");
  const [next, setNext] = useState("");
  const [shown, setShown] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const load = () => {
    getJSON<typeof mail>("/account/email").then(setMail).catch(() => {});
    getJSON<{ has_code: boolean }>("/account/recovery").then((r) => setHasCode(r.has_code)).catch(() => {});
  };
  useEffect(load, []);
  const toggle = (o: Open) => { setOpen(open === o ? null : o); setMsg(null); };
  const run = async (fn: () => Promise<void>) => {
    setBusy(true); setMsg(null);
    try { await fn(); } catch (e) { setMsg(e instanceof Error ? e.message : String(e)); }
    setBusy(false);
  };

  return (
    <>
      <Row icon="envelope-simple" title="이메일" open={open === "email"} onClick={() => toggle("email")}
        sub={mail?.email ? `${mail.email}. 비밀번호를 잊으면 여기로 인증번호가 가요` : "등록하면 비밀번호를 잊었을 때 메일로 찾아요"} />
      {open === "email" && (
        <div className="set-panel">
          {!mail?.mail_ready && <p className="set-warn">이 서버는 아직 메일을 보낼 수 없어요. 서버 주인이 설정 &gt; 서버에서 메일 보내기를 켜야 해요.</p>}
          <input className="input" type="email" placeholder={mail?.email || "minji@gmail.com"} value={email} onChange={(e) => setEmail(e.target.value)} />
          <Button variant="secondary" icon="paper-plane-tilt" disabled={!email.includes("@") || busy}
            onClick={() => void run(async () => { await postJSON("/account/email", { email }); setMsg(`${email} 로 인증번호를 보냈어요. 메일함(스팸함도)을 확인해 주세요.`); load(); })}>
            인증번호 보내기
          </Button>
          {(mail?.pending || msg?.includes("보냈어요")) && (
            <div className="row">
              <input className="input grow" inputMode="numeric" placeholder="6자리 인증번호" value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))} />
              <Button disabled={code.length !== 6 || busy}
                onClick={() => void run(async () => { setMail(await postJSON("/account/email/verify", { code })); setCode(""); setEmail(""); setMsg("이메일을 등록했어요."); })}>확인</Button>
            </div>
          )}
          {mail?.email && (
            <button className="soft-link" onClick={() => void run(async () => { await fetch(`${API}/account/email`, { method: "DELETE" }); load(); setMsg("이메일을 지웠어요."); })}>이메일 지우기</button>
          )}
          {msg && <p className="set-msg">{msg}</p>}
        </div>
      )}

      <Row icon="lock-simple" title="비밀번호 바꾸기" sub="바꾸면 다른 기기의 로그인은 끊겨요" open={open === "password"} onClick={() => toggle("password")} />
      {open === "password" && (
        <div className="set-panel">
          <input className="input" type="password" placeholder="지금 비밀번호" autoComplete="current-password" value={cur} onChange={(e) => setCur(e.target.value)} />
          <input className="input" type="password" placeholder="새 비밀번호 (6자 이상)" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} />
          <Button disabled={!cur || next.length < 6 || busy}
            onClick={() => void run(async () => { await postJSON("/account/password", { current: cur, password: next }); setCur(""); setNext(""); setMsg("비밀번호를 바꿨어요."); })}>바꾸기</Button>
          {msg && <p className="set-msg">{msg}</p>}
        </div>
      )}

      <Row icon="key" title="복구 코드" open={open === "recovery"} onClick={() => toggle("recovery")}
        sub={hasCode ? "있어요. 이메일이 없을 때 비밀번호를 찾는 코드예요" : "없어요. 만들어 두면 이메일 없이도 찾아요"} />
      {open === "recovery" && (
        <div className="set-panel">
          <p className="t-caption muted" style={{ margin: 0 }}>새로 만들면 예전 코드는 못 써요. 만든 코드는 지금 한 번만 보여 줘요.</p>
          {shown ? (
            <>
              <code className="recovery-code">{shown}</code>
              <Button variant="secondary" onClick={() => void navigator.clipboard?.writeText(shown).catch(() => {})}>복사하기</Button>
            </>
          ) : (
            <Button disabled={busy} onClick={() => void run(async () => { setShown((await postJSON<{ code: string }>("/account/recovery-code")).code); setHasCode(true); })}>
              복구 코드 {hasCode ? "새로 " : ""}만들기
            </Button>
          )}
          {msg && <p className="set-msg">{msg}</p>}
        </div>
      )}
    </>
  );
}

/** 서버 주인: 메일 보내기(Gmail) · 친구 비밀번호 초기화 코드 */
export function OwnerAccountTools() {
  const [user, setUser] = useState("");
  const [pass, setPass] = useState("");
  const [current, setCurrent] = useState<string | null>(null);
  const [friend, setFriend] = useState("");
  const [reset, setReset] = useState<{ name: string; code: string } | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { getJSON<{ user: string }>("/admin/mail").then((r) => setCurrent(r.user)).catch(() => {}); }, []);
  const run = async (fn: () => Promise<void>) => {
    setBusy(true); setMsg(null);
    try { await fn(); } catch (e) { setMsg(e instanceof Error ? e.message : String(e)); }
    setBusy(false);
  };
  return (
    <div className="set-panel">
      <b className="set-sub">메일 보내기 (비밀번호 찾기 인증번호)</b>
      <p className="t-caption muted" style={{ margin: 0 }}>
        {current ? `지금: ${current}` : "아직 꺼져 있어요."} 무료로 Gmail 을 써요. Google 계정 → 보안 → 2단계 인증을 켠 뒤 → '앱 비밀번호'에서 16자리를 만들어 넣어요.
      </p>
      <input className="input" type="email" placeholder="보내는 Gmail 주소" value={user} onChange={(e) => setUser(e.target.value)} />
      <input className="input" type="password" placeholder="앱 비밀번호 16자리" value={pass} onChange={(e) => setPass(e.target.value)} />
      <Button disabled={!user.includes("@") || pass.replace(/\s/g, "").length < 16 || busy}
        onClick={() => void run(async () => { const r = await fetch(`${API}/admin/mail`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ user, password: pass }) });
          const j = await r.json().catch(() => ({})); if (!r.ok) throw new Error(j.detail ?? "저장하지 못했어요");
          setCurrent(j.user); setPass(""); setMsg(`${j.user} 로 시험 메일을 보냈어요. 이제 인증번호를 보낼 수 있어요.`); })}>
        {busy ? "시험 메일 보내는 중…" : "저장하고 시험 메일 보내기"}
      </Button>
      <b className="set-sub" style={{ marginTop: 10 }}>친구 비밀번호 초기화 코드</b>
      <p className="t-caption muted" style={{ margin: 0 }}>비밀번호도, 이메일도, 복구 코드도 없는 친구에게 24시간 쓰는 코드를 줘요.</p>
      <div className="row">
        <input className="input grow" placeholder="친구 이름 (가입한 이름)" value={friend} onChange={(e) => setFriend(e.target.value)} />
        <Button variant="secondary" disabled={!friend.trim() || busy}
          onClick={() => void run(async () => setReset(await postJSON("/admin/reset-code", { name: friend })))}>만들기</Button>
      </div>
      {reset && <p className="set-msg">{reset.name}님 코드: <code className="inline-code">{reset.code}</code>. 로그인 화면 '비밀번호를 잊었어요'에 넣으면 돼요</p>}
      {msg && <p className="set-msg">{msg}</p>}
    </div>
  );
}

type TrashItem = { id: string; title: string; course?: string; days_left: number };

/** 설정 › 휴지통: 지운 강의자료를 7일 동안 되살리기 */
export function TrashPanel() {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<TrashItem[] | null>(null);
  const load = () => { getJSON<TrashItem[]>("/trash").then(setItems).catch(() => setItems([])); };
  useEffect(load, []);
  const restore = async (t: TrashItem) => { await postJSON(`/trash/${t.id}/restore`).catch(() => {}); load(); };
  const purge = async (t: TrashItem) => {
    if (!await askYes(`'${t.title}'을(를) 완전히 지울까요? 녹음·필기도 함께 지워지고 되돌릴 수 없어요.`)) return;
    await fetch(`${API}/trash/${t.id}`, { method: "DELETE" }).catch(() => {}); load();
  };
  return (
    <>
      <Row icon="trash" title="휴지통" open={open} onClick={() => setOpen(!open)}
        sub={items?.length ? `${items.length}개 있어요. 지운 뒤 7일 동안 되살릴 수 있어요` : "비어 있어요. 지운 강의자료는 7일 동안 여기 있어요"} />
      {open && (
        <div className="set-panel">
          {!items?.length && <p className="t-caption muted" style={{ margin: 0 }}>휴지통이 비어 있어요.</p>}
          {items?.map((t) => (
            <div key={t.id} className="trash-row">
              <span className="grow"><b>{t.title}</b><small>{t.days_left}일 뒤 완전히 지워져요{t.course ? `, ${t.course}` : ""}</small></span>
              <button className="chip chip-accent" onClick={() => void restore(t)}>되살리기</button>
              <button className="chip chip-default danger" onClick={() => void purge(t)}>지우기</button>
            </div>
          ))}
        </div>
      )}
    </>
  );
}

/** 설정 › 계정 삭제: 비밀번호를 한 번 더 받고 모든 자료와 계정을 지운다 */
export function DeleteAccount() {
  const [open, setOpen] = useState(false);
  const [pw, setPw] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const run = async () => {
    if (!await askYes("정말 계정을 지울까요? 강의자료·녹음·필기·시간표·친구가 모두 지워지고 되돌릴 수 없어요.")) return;
    setBusy(true); setMsg(null);
    try { await postJSON("/account/delete", { password: pw }); window.location.hash = "#/"; window.location.reload(); }
    catch (e) { setMsg(e instanceof Error ? e.message : String(e)); setBusy(false); }
  };
  return (
    <>
      <Row icon="warning-circle" title="계정 삭제" sub="계정과 모든 자료를 완전히 지워요" open={open} onClick={() => setOpen(!open)} />
      {open && (
        <div className="set-panel">
          <p className="set-warn">강의자료·녹음·필기·복습 기록·시간표·친구가 모두 지워지고 되돌릴 수 없어요. 친구 족보에 합쳐졌던 내 필기도 사라져요.</p>
          <input className="input" type="password" placeholder="비밀번호 확인" autoComplete="current-password" value={pw} onChange={(e) => setPw(e.target.value)} />
          <Button variant="record" disabled={!pw || busy} onClick={() => void run()}>{busy ? "지우는 중…" : "계정 삭제"}</Button>
          {msg && <p className="set-msg">{msg}</p>}
        </div>
      )}
    </>
  );
}

type Usage = { documents: number; lectures: number; recorded_minutes: number; trash: number; bytes: { audio: number; documents: number; photos: number; total: number } };
const mb = (b: number) => (b >= 1024 ** 3 ? `${(b / 1024 ** 3).toFixed(1)}GB` : `${Math.max(0.1, b / 1024 ** 2).toFixed(1)}MB`);

/** 설정 › 내 사용량: 강의자료·강의 수, 녹음 시간, 서버에서 차지하는 크기 */
export function UsagePanel() {
  const [open, setOpen] = useState(false);
  const [u, setU] = useState<Usage | null>(null);
  useEffect(() => { getJSON<Usage>("/account/usage").then(setU).catch(() => {}); }, []);
  const hours = u ? Math.floor(u.recorded_minutes / 60) : 0;
  return (
    <>
      <Row icon="sliders-horizontal" title="내 사용량" open={open} onClick={() => setOpen(!open)}
        sub={u ? `강의 ${u.lectures}개, 녹음 ${hours ? `${hours}시간 ` : ""}${u.recorded_minutes % 60}분, ${mb(u.bytes.total)}` : "불러오는 중…"} />
      {open && u && (
        <div className="set-panel">
          <div className="usage-bars">
            {([["녹음", u.bytes.audio], ["강의자료", u.bytes.documents], ["사진", u.bytes.photos]] as const).map(([k, v]) => (
              <div key={k} className="usage-row">
                <span>{k}</span>
                <i style={{ width: `${u.bytes.total ? Math.max(2, (v / u.bytes.total) * 100) : 0}%` }} />
                <b>{mb(v)}</b>
              </div>
            ))}
          </div>
          <p className="t-caption muted" style={{ margin: 0 }}>강의자료 {u.documents}개, 강의 {u.lectures}개{u.trash ? `, 휴지통 ${u.trash}개` : ""}. 무료 서버라 공간이 넉넉하지 않아요. 안 보는 강의자료는 지워 주세요.</p>
        </div>
      )}
    </>
  );
}
