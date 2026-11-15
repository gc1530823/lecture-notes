// 관리자 페이지 (#/admin): 사용자 계정과 따로, 관리자 비밀번호로 들어간다.
// 처음 한 번은 초대 코드로 관리자 비밀번호를 정한다. 서버 상태 · AI 진단 · 사람 목록 · 초대 코드 · 메일 · 서버 옮기기.
import { useCallback, useEffect, useState } from "react";
import { getJSON, postJSON } from "../api/useApi";
import { Button, Icon } from "../components/ui";
import { LuneMark } from "../components/Brand";
import { OwnerAccountTools } from "./Account";

const API = import.meta.env.VITE_API_URL ?? "";

interface Status { set: boolean; logged_in: boolean; auth: boolean }
interface User { id: string; name: string; created_at: number; has_email: boolean; docs: number; lectures: number; last_login: number | null }
interface Overview {
  server: { version: string; disk_free_gb: number; disk_total_gb: number; mem_total_mb: number; mem_avail_mb: number };
  ai: { groq_status?: number; groq_error?: string; vision_models?: string[]; whisper_models?: string[]; stt_engine?: string; stt_last_error?: string; ocr_runtime?: boolean; llm_mode?: string };
  users: User[]; invite_custom: boolean; mail: string;
}

async function call<T>(path: string, method: string, body?: object): Promise<T> {
  const r = await fetch(API + path, { method, headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.detail ?? `오류 (${r.status})`);
  return j as T;
}
const day = (t: number | null) => (t ? new Date(t * 1000).toLocaleDateString("ko-KR", { year: "2-digit", month: "numeric", day: "numeric" }) : "-");

export function AdminScreen() {
  const [status, setStatus] = useState<Status | null>(null);
  const load = useCallback(() => { getJSON<Status>("/admin/status").then(setStatus).catch(() => setStatus({ set: false, logged_in: false, auth: false })); }, []);
  useEffect(load, [load]);
  return (
    <div className="screen admin">
      <header className="admin-head">
        <LuneMark size={26} /><b className="grow">LUNE 관리자</b>
        <a className="chip chip-default" href="#/">앱으로</a>
      </header>
      <div className="screen-body">
        {!status && <p className="muted">불러오는 중…</p>}
        {status && !status.logged_in && <AdminGate status={status} onDone={load} />}
        {status?.logged_in && <AdminDashboard onLogout={load} />}
      </div>
    </div>
  );
}

function AdminGate({ status, onDone }: { status: Status; onDone: () => void }) {
  const [invite, setInvite] = useState("");
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const first = !status.set;
  const submit = async () => {
    setBusy(true); setError(null);
    try {
      await call(first ? "/admin/setup" : "/admin/login", "POST", { invite, password: pw });
      onDone();
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    setBusy(false);
  };
  const ready = first ? invite.trim() && pw.length >= 8 && pw === pw2 : pw.length > 0;
  return (
    <form className="admin-card" onSubmit={(e) => { e.preventDefault(); if (ready && !busy) void submit(); }}>
      <b className="admin-title">{first ? "관리자 비밀번호 만들기" : "관리자 로그인"}</b>
      <p className="t-caption muted" style={{ margin: 0 }}>
        {first ? "처음 한 번만: 서버의 초대 코드로 확인하고 관리자 비밀번호를 정해요. 정한 뒤에는 잠겨서 다른 사람이 못 바꿔요." : "사용자 계정과 따로인 관리자 비밀번호예요."}
      </p>
      {first && <input className="input" placeholder="초대 코드" value={invite} onChange={(e) => setInvite(e.target.value)} autoComplete="off" />}
      <input className="input" type="password" placeholder={first ? "관리자 비밀번호 (8자 이상)" : "관리자 비밀번호"} value={pw}
        onChange={(e) => setPw(e.target.value)} autoComplete={first ? "new-password" : "current-password"} />
      {first && <input className="input" type="password" placeholder="한 번 더" value={pw2} onChange={(e) => setPw2(e.target.value)} autoComplete="new-password" />}
      {first && pw2 && pw !== pw2 && <p className="set-msg">두 비밀번호가 달라요.</p>}
      {error && <p className="login-error">{error}</p>}
      <Button block disabled={!ready || busy}>{busy ? "잠시만요…" : first ? "만들고 들어가기" : "들어가기"}</Button>
    </form>
  );
}

function AdminDashboard({ onLogout }: { onLogout: () => void }) {
  const [data, setData] = useState<Overview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [invite, setInvite] = useState("");
  const [migrate, setMigrate] = useState<{ code: string; until: number } | null>(null);
  const [reset, setReset] = useState<{ name: string; code: string } | null>(null);
  const [cur, setCur] = useState(""); const [next, setNext] = useState("");
  const load = useCallback(() => { getJSON<Overview>("/admin/overview").then(setData).catch((e) => setError(e.message)); }, []);
  useEffect(load, [load]);
  const run = async (fn: () => Promise<void>) => { setMsg(null); try { await fn(); } catch (e) { setMsg(e instanceof Error ? e.message : String(e)); } };
  if (error) return <p className="muted">{error}</p>;
  if (!data) return <p className="muted">불러오는 중…</p>;
  const s = data.server, ai = data.ai;
  const ok = (good: boolean) => <span className={`admin-dot ${good ? "good" : "bad"}`} />;
  return (
    <div className="admin-body">
      {msg && <p className="set-msg admin-msg">{msg}</p>}

      <section className="admin-card">
        <b className="admin-title"><Icon name="gear" size={16} /> 서버</b>
        <div className="admin-stats">
          <span><small>버전</small><b>{s.version || "-"}</b></span>
          <span><small>메모리</small><b>{s.mem_total_mb ? `${Math.round((s.mem_total_mb - s.mem_avail_mb) / 102.4) / 10} / ${Math.round(s.mem_total_mb / 102.4) / 10}GB` : "-"}</b></span>
          <span><small>디스크 남음</small><b>{s.disk_free_gb} / {s.disk_total_gb}GB</b></span>
          <span><small>사람</small><b>{data.users.length}명</b></span>
        </div>
      </section>

      <section className="admin-card">
        <b className="admin-title"><Icon name="sparkle" size={16} /> AI 상태</b>
        <ul className="admin-checks">
          <li>{ok(ai.groq_status === 200)} Groq 연결 {ai.groq_status ? `(${ai.groq_status})` : ""}{ai.groq_error ? ` · ${ai.groq_error}` : ""}</li>
          <li>{ok((ai.whisper_models ?? []).length > 0)} 받아쓰기 모델 {(ai.whisper_models ?? []).join(", ") || "없음"}</li>
          <li>{ok(ai.stt_engine === "groq")} 지금 받아쓰는 곳: {ai.stt_engine === "local" ? "이 서버 (Groq 막힘 · 느림)" : "Groq"}{ai.stt_last_error ? ` · 최근 오류: ${ai.stt_last_error}` : ""}</li>
          <li>{ok((ai.vision_models ?? []).length > 0)} 사진 읽는 모델 {(ai.vision_models ?? []).join(", ") || "없음 (시간표는 서버 글자 인식으로 대신)"}</li>
          <li>{ok(!!ai.ocr_runtime)} 서버 글자 인식 {ai.ocr_runtime ? "준비됨" : "없음"}</li>
        </ul>
      </section>

      <section className="admin-card">
        <b className="admin-title"><Icon name="users" size={16} /> 사람 {data.users.length}명</b>
        <div className="admin-table">
          <div className="admin-tr admin-th"><span>이름</span><span>가입</span><span>자료·강의</span><span>이메일</span><span /></div>
          {data.users.map((u) => (
            <div key={u.id} className="admin-tr">
              <span><b>{u.name}</b></span><span>{day(u.created_at)}</span><span>{u.docs} · {u.lectures}</span><span>{u.has_email ? "있음" : "-"}</span>
              <span className="admin-actions">
                <button className="chip chip-default" onClick={() => void run(async () => setReset(await postJSON("/admin/reset-code", { name: u.name })))}>초기화 코드</button>
                <button className="chip chip-default" onClick={() => void run(async () => { if (!confirm(`${u.name}님의 모든 기기 로그인을 끊을까요?`)) return; await postJSON(`/admin/users/${u.id}/logout`); setMsg(`${u.name}님 로그인을 끊었어요.`); })}>로그인 끊기</button>
              </span>
            </div>
          ))}
        </div>
        {reset && <p className="set-msg">{reset.name}님 초기화 코드: <code className="inline-code">{reset.code}</code> · 24시간 · 로그인 화면 '비밀번호를 잊었어요'에 넣어요</p>}
      </section>

      <section className="admin-card">
        <b className="admin-title"><Icon name="key" size={16} /> 초대 코드</b>
        <p className="t-caption muted" style={{ margin: 0 }}>{data.invite_custom ? "관리자 페이지에서 바꾼 코드를 쓰는 중이에요." : "서버 설치 때 넣은 코드를 쓰는 중이에요."} 바꿔도 이미 가입한 사람은 그대로예요.</p>
        <div className="row">
          <input className="input grow" placeholder="새 초대 코드 (6자 이상)" value={invite} onChange={(e) => setInvite(e.target.value)} />
          <Button variant="secondary" disabled={invite.trim().length < 6} onClick={() => void run(async () => { await call("/admin/invite", "PUT", { code: invite }); setInvite(""); setMsg("초대 코드를 바꿨어요."); load(); })}>바꾸기</Button>
        </div>
      </section>

      <section className="admin-card">
        <b className="admin-title"><Icon name="envelope-simple" size={16} /> 메일 (비밀번호 찾기)</b>
        <OwnerAccountTools />
      </section>

      <A1Card />
      <BackupCard />

      <section className="admin-card">
        <b className="admin-title"><Icon name="arrows-clockwise" size={16} /> 새 서버로 옮기기</b>
        <p className="t-caption muted" style={{ margin: 0 }}>코드를 새 서버 설치 스크립트의 MIGRATE_CODE 에 넣으면 계정·강의·녹음을 통째로 가져가요. 2일 동안 써요.</p>
        {migrate ? (
          <div className="migrate-code">
            <small>{new Date(migrate.until * 1000).toLocaleString("ko-KR", { month: "long", day: "numeric", hour: "numeric", minute: "2-digit" })}까지</small>
            <code>{migrate.code}</code>
            <button className="chip chip-accent" onClick={() => void navigator.clipboard?.writeText(migrate.code).catch(() => {})}>복사</button>
          </div>
        ) : (
          <Button variant="secondary" onClick={() => void run(async () => { if (!confirm("옮기기 코드를 만들까요? 이 코드를 아는 서버는 모든 자료를 가져갈 수 있어요.")) return; setMigrate(await postJSON("/admin/migrate")); })}>옮기기 코드 만들기</Button>
        )}
      </section>

      <section className="admin-card">
        <b className="admin-title"><Icon name="lock-simple" size={16} /> 관리자 비밀번호</b>
        <input className="input" type="password" placeholder="지금 비밀번호" value={cur} onChange={(e) => setCur(e.target.value)} autoComplete="current-password" />
        <input className="input" type="password" placeholder="새 비밀번호 (8자 이상)" value={next} onChange={(e) => setNext(e.target.value)} autoComplete="new-password" />
        <div className="row">
          <Button variant="secondary" disabled={!cur || next.length < 8} onClick={() => void run(async () => { await postJSON("/admin/password", { current: cur, password: next }); setCur(""); setNext(""); setMsg("관리자 비밀번호를 바꿨어요."); })}>바꾸기</Button>
          <span className="grow" />
          <Button variant="secondary" onClick={() => void run(async () => { await postJSON("/admin/logout"); onLogout(); })}>로그아웃</Button>
        </div>
      </section>
    </div>
  );
}

interface Backup { repo: string; has_token: boolean; last: { at: number; files: number; total_files: number } | null; error: string; running: boolean }

/** 자동 백업: 하루 한 번 허깅페이스 비공개 데이터셋에 DB + 새 파일 */
function BackupCard() {
  const [b, setB] = useState<Backup | null>(null);
  const [token, setToken] = useState("");
  const [repo, setRepo] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const load = useCallback(() => { getJSON<Backup>("/admin/backup").then((x) => { setB(x); setRepo((r) => r || x.repo); }).catch(() => {}); }, []);
  useEffect(load, [load]);
  useEffect(() => { if (!b?.running) return; const t = window.setTimeout(load, 4000); return () => window.clearTimeout(t); }, [b, load]);
  const run = async (fn: () => Promise<void>) => { setMsg(null); try { await fn(); } catch (e) { setMsg(e instanceof Error ? e.message : String(e)); } };
  return (
    <section className="admin-card">
      <b className="admin-title"><Icon name="download-simple" size={16} /> 자동 백업</b>
      <p className="t-caption muted" style={{ margin: 0 }}>
        하루 한 번 계정·강의·필기·녹음을 허깅페이스 비공개 저장소에 올려요 (무료). 녹음은 새로 생긴 것만 올려요.
      </p>
      {b && (
        <ul className="admin-checks">
          <li><span className={`admin-dot ${b.has_token ? "good" : "bad"}`} />{b.has_token ? `켜짐 · ${b.repo}` : "꺼짐 · 아래에 토큰을 넣어 주세요"}</li>
          {b.last && <li><span className="admin-dot good" />마지막 백업 {new Date(b.last.at * 1000).toLocaleString("ko-KR", { month: "numeric", day: "numeric", hour: "numeric", minute: "2-digit" })} · 새 파일 {b.last.files}개 · 모두 {b.last.total_files}개</li>}
          {b.error && <li><span className="admin-dot bad" />최근 실패: {b.error}</li>}
          {b.running && <li><span className="spin" /> 백업하는 중…</li>}
        </ul>
      )}
      <p className="t-caption muted" style={{ margin: 0 }}>허깅페이스 → Settings → Access Tokens → Create new token → <b>Write</b> 로 만든 토큰을 넣어요.</p>
      <input className="input" placeholder="저장소 이름 (예: kimheejin0823/lune-backup)" value={repo} onChange={(e) => setRepo(e.target.value)} />
      <input className="input" type="password" placeholder={b?.has_token ? "토큰 (바꿀 때만)" : "허깅페이스 Write 토큰 hf_…"} value={token} onChange={(e) => setToken(e.target.value)} />
      <div className="row">
        <Button variant="secondary" disabled={!token.startsWith("hf_") || !repo.includes("/")}
          onClick={() => void run(async () => { await call("/admin/backup", "PUT", { token, repo }); setToken(""); setMsg("백업을 켰어요."); load(); })}>저장</Button>
        <span className="grow" />
        <Button disabled={!b?.has_token || b?.running} icon="arrows-clockwise"
          onClick={() => void run(async () => { await postJSON("/admin/backup/run"); setMsg("백업을 시작했어요. 녹음이 많으면 처음에는 오래 걸려요."); load(); })}>지금 백업</Button>
      </div>
      {msg && <p className="set-msg">{msg}</p>}
    </section>
  );
}

type A1 = { configured: boolean; enabled?: boolean; done?: boolean; tries?: number; message?: string; at?: number; instance?: string;
  region: string; has_key: boolean; has_init: boolean };

/** 큰 무료 서버(A1.Flex) 자동 만들기: 오라클 API 키와 설치 스크립트를 한 번 넣으면 이 서버가 2분마다 대신 시도 */
function A1Card() {
  const [a, setA] = useState<A1 | null>(null);
  const [f, setF] = useState({ user: "", fingerprint: "", tenancy: "", region: "ap-hyderabad-1", key: "", init: "" });
  const [preview, setPreview] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const load = useCallback(() => { getJSON<A1>("/admin/a1").then(setA).catch(() => {}); }, []);
  useEffect(load, [load]);
  useEffect(() => { if (!a?.enabled || a.done) return; const t = window.setInterval(load, 30000); return () => window.clearInterval(t); }, [a, load]);
  // 오라클 '설정 파일 미리보기'를 통째로 붙여 넣으면 다섯 값 중 넷을 알아서 채운다
  const parse = (text: string) => {
    setPreview(text);
    const pick = (k: string) => (text.match(new RegExp(`^\\s*${k}\\s*=\\s*(.+)$`, "m")) ?? [])[1]?.trim() ?? "";
    setF((x) => ({ ...x, user: pick("user") || x.user, fingerprint: pick("fingerprint") || x.fingerprint, tenancy: pick("tenancy") || x.tenancy, region: pick("region") || x.region }));
  };
  const save = async (enabled: boolean) => {
    setMsg(null);
    try { setA(await call("/admin/a1", "PUT", { ...f, enabled })); setF((x) => ({ ...x, key: "", init: "" })); setMsg(enabled ? "켰어요. 2분마다 시도해요." : "멈췄어요."); }
    catch (e) { setMsg(e instanceof Error ? e.message : String(e)); }
  };
  return (
    <section className="admin-card">
      <b className="admin-title"><Icon name="arrows-clockwise" size={16} /> 큰 무료 서버 자동 만들기</b>
      <p className="t-caption muted" style={{ margin: 0 }}>오라클에 큰 서버(4코어·24GB, 무료) 자리가 날 때까지 이 서버가 2분마다 대신 시도해요. 클라우드 셸을 켜 둘 필요가 없어요. 만들면 열쇠는 지워요.</p>
      {a && (
        <ul className="admin-checks">
          <li><span className={`admin-dot ${a.done ? "good" : a.enabled ? "good" : "bad"}`} />
            {a.done ? `만들었어요 · ${a.instance ?? ""}` : a.enabled ? `시도 중 · ${a.tries ?? 0}번째` : a.configured ? "멈춤" : "꺼짐 · 아래를 채워 주세요"}</li>
          {a.message && <li><span className="admin-dot" />{a.message}{a.at ? ` (${new Date(a.at * 1000).toLocaleTimeString("ko-KR", { hour: "numeric", minute: "2-digit" })})` : ""}</li>}
        </ul>
      )}
      {!a?.done && (
        <>
          <p className="t-caption muted" style={{ margin: 0 }}>① 오라클 콘솔 오른쪽 위 사람 모양 → 내 프로필 → <b>API 키 → API 키 추가 → 키 쌍 생성</b> → <b>개인 키 다운로드</b> → 추가. 나오는 '구성 파일 미리보기'를 통째로 복사해 아래 첫 칸에 붙여 넣어요.</p>
          <textarea className="input" rows={4} placeholder="[DEFAULT]&#10;user=ocid1.user…&#10;fingerprint=…&#10;tenancy=ocid1.tenancy…&#10;region=ap-hyderabad-1" value={preview} onChange={(e) => parse(e.target.value)} />
          {f.user && <p className="t-caption muted" style={{ margin: 0 }}>읽은 값: {f.region} · 지문 {f.fingerprint.slice(0, 11)}…</p>}
          <p className="t-caption muted" style={{ margin: 0 }}>② 내려받은 개인 키 파일(.pem)을 메모장으로 열어 전체를 붙여 넣어요.</p>
          <textarea className="input" rows={3} placeholder={a?.has_key ? "개인 키 (바꿀 때만)" : "-----BEGIN PRIVATE KEY-----…"} value={f.key} onChange={(e) => setF({ ...f, key: e.target.value })} />
          <p className="t-caption muted" style={{ margin: 0 }}>③ 키를 다 채운 새 서버 설치 스크립트(lune-init.txt) 전체를 붙여 넣어요.</p>
          <textarea className="input" rows={3} placeholder={a?.has_init ? "설치 스크립트 (바꿀 때만)" : "#!/bin/bash …"} value={f.init} onChange={(e) => setF({ ...f, init: e.target.value })} />
          <div className="row">
            <Button onClick={() => void save(true)}>저장하고 켜기</Button>
            {a?.enabled && <Button variant="secondary" onClick={() => void save(false)}>멈추기</Button>}
          </div>
        </>
      )}
      {msg && <p className="set-msg">{msg}</p>}
    </section>
  );
}
