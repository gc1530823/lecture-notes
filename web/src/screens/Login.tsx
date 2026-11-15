// 로그인: 친구들과 함께 쓰는 서버(INVITE_CODE)일 때만 나온다. 혼자 쓰는 서버·데모에서는 보이지 않는다.
// 처음이면 초대 코드 + 이름 + 비밀번호로 가입, 다음부터는 이름 + 비밀번호. 로그인은 180일 동안 유지돼요.
import { useState } from "react";
import { postJSON } from "../api/useApi";
import { Button } from "../components/ui";
import SlidingTabs from "../components/SlidingTabs";
import { LuneMark, LuneWordmark, TAGLINE } from "../components/Brand";

export interface Me { auth: boolean; user: { id: string; name: string } | null }

export default function Login({ onDone }: { onDone: (me: Me) => void }) {
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [invite, setInvite] = useState("");
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [forgot, setForgot] = useState(false);
  const [code, setCode] = useState("");
  const [mailNote, setMailNote] = useState<string | null>(null);
  const sendMail = async () => {
    setError(null); setMailNote(null); setBusy(true);
    try { setMailNote((await postJSON<{ message: string }>("/auth/forgot", { who: name })).message); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    setBusy(false);
  };
  // 가입 직후: 복구 코드를 보여 주고, 이메일을 적었으면 인증번호를 확인한다
  const [saved, setSaved] = useState<{ me: Me; code: string; email: string; status?: string } | null>(null);
  const [six, setSix] = useState("");
  const [verified, setVerified] = useState(false);
  const verify = async () => {
    setBusy(true); setError(null);
    try { await postJSON("/account/email/verify", { code: six }); setVerified(true); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    setBusy(false);
  };
  const submit = async () => {
    setBusy(true); setError(null);
    try {
      if (forgot) {
        onDone(await postJSON<Me>("/auth/reset", { name, code, password }));
      } else {
        const me = await postJSON<Me & { recovery_code?: string; email_status?: string }>(`/auth/${mode}`,
          mode === "signup" ? { name, password, invite, email: email.trim() } : { name, password });
        if (me.recovery_code) setSaved({ me, code: me.recovery_code, email: email.trim(), status: me.email_status }); else onDone(me);
      }
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    setBusy(false);
  };
  const codeLen = code.replace(/[^A-Za-z0-9]/g, "").length;
  const ready = forgot ? name.trim() && (codeLen === 6 || codeLen >= 12) && password.length >= 6
    : name.trim() && password.length >= (mode === "signup" ? 6 : 1) && (mode === "login" || invite.trim());

  if (saved) return (
    <div className="login">
      <LuneMark size={64} className="login-mark" />
      <div className="login-card">
        <h2 className="t-title-m" style={{ margin: 0 }}>복구 코드를 저장해 두세요</h2>
        <p className="t-caption muted" style={{ margin: 0 }}>비밀번호를 잊었을 때 이 코드로 새 비밀번호를 만들 수 있어요. 지금 한 번만 보여 줘요.</p>
        <code className="recovery-code">{saved.code}</code>
        <Button variant="secondary" onClick={() => void navigator.clipboard?.writeText(saved.code).catch(() => {})}>복사하기</Button>
        <p className="t-caption faint" style={{ margin: 0 }}>메모장·카톡 나에게 보내기 등에 붙여 두세요. 설정에서 새로 만들 수도 있어요.</p>
        {saved.status === "sent" && !verified && (
          <div className="signup-mail">
            <b>{saved.email} 로 인증번호를 보냈어요</b>
            <small>확인해 두면 비밀번호를 잊었을 때 이 메일로 찾을 수 있어요. 메일함·스팸함을 확인해 주세요.</small>
            <div className="row">
              <input className="input grow" inputMode="numeric" placeholder="6자리 인증번호" value={six}
                onChange={(e) => setSix(e.target.value.replace(/\D/g, "").slice(0, 6))} autoComplete="one-time-code" />
              <Button disabled={six.length !== 6 || busy} onClick={() => void verify()}>확인</Button>
            </div>
            {error && <p className="login-error">{error}</p>}
          </div>
        )}
        {verified && <p className="signup-mail ok"><b>이메일을 확인했어요.</b> 비밀번호를 잊으면 이 메일로 찾을 수 있어요.</p>}
        {saved.status === "pending" && (
          <p className="signup-mail"><small>{saved.email} 은 저장해 뒀어요. 지금은 메일을 보낼 수 없어서, 나중에 설정 › 이메일에서 인증해 주세요.</small></p>
        )}
        <Button block onClick={() => onDone(saved.me)}>저장했어요, 시작하기</Button>
      </div>
    </div>
  );
  return (
    <div className="login">
      <LuneMark size={84} className="login-mark" />
      <h1 aria-label="LUNE"><LuneWordmark height={30} /></h1>
      <p className="login-tag">{TAGLINE}</p>
      <p className="t-caption muted">녹음하면 강의자료 위에 AI 필기가 붙어요</p>
      <form className="login-card" onSubmit={(e) => { e.preventDefault(); if (ready && !busy) void submit(); }}>
        {forgot ? (
          <div className="forgot-head"><b>비밀번호 다시 만들기</b><small>이메일로 인증번호를 받거나, 가입할 때 받은 복구 코드(또는 서버 주인에게 받은 초기화 코드)를 넣어 주세요</small></div>
        ) : (
          <SlidingTabs label="로그인 방법" value={mode} onChange={(m) => { setMode(m); setError(null); }}
            items={[["login", "로그인"], ["signup", "처음이에요"]] as const} />
        )}
        {!forgot && mode === "signup" && (
          <label><span>초대 코드</span>
            <input className="input" value={invite} onChange={(e) => setInvite(e.target.value)} placeholder="친구에게 받은 코드" autoComplete="off" />
          </label>
        )}
        <label><span>{forgot ? "이름 또는 이메일" : "이름"}</span>
          <input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder={forgot ? "예: 민지 또는 minji@gmail.com" : "예: 민지"}
            autoComplete="username" maxLength={forgot ? 120 : 20} />
        </label>
        {forgot && (
          <Button type="button" variant="secondary" icon="paper-plane-tilt" disabled={!name.trim() || busy} onClick={() => void sendMail()}>인증번호 메일로 받기</Button>
        )}
        {forgot && mailNote && <p className="forgot-note">{mailNote}</p>}
        {forgot && (
          <label><span>인증번호 또는 복구 코드</span>
            <input className="input" value={code} onChange={(e) => setCode(e.target.value.toUpperCase())} placeholder="메일의 6자리 숫자 · ABCD-EFGH-JKLM" autoComplete="one-time-code" />
          </label>
        )}
        {!forgot && mode === "signup" && (
          <label><span>이메일 <small className="faint">(선택 · 비밀번호를 잊었을 때 찾는 곳)</small></span>
            <input className="input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="예: 2024142012@ptu.ac.kr" autoComplete="email" />
          </label>
        )}
        <label><span>{forgot ? "새 비밀번호" : "비밀번호"}</span>
          <input className="input" type="password" value={password} onChange={(e) => setPassword(e.target.value)}
            placeholder={forgot || mode === "signup" ? "6자 이상" : ""} autoComplete={forgot || mode === "signup" ? "new-password" : "current-password"} />
        </label>
        {error && <p className="login-error">{error}</p>}
        <Button block disabled={!ready || busy}>{busy ? "잠시만요…" : forgot ? "새 비밀번호로 로그인" : mode === "signup" ? "가입하고 시작하기" : "로그인"}</Button>
        {(forgot || mode === "login") && (
          <button type="button" className="soft-link" onClick={() => { setForgot(!forgot); setError(null); setPassword(""); }}>
            {forgot ? "로그인으로 돌아가기" : "비밀번호를 잊었어요"}
          </button>
        )}
        <p className="t-caption faint" style={{ textAlign: "center", margin: 0 }}>
          {mode === "signup" ? "내 강의·녹음·필기는 나만 볼 수 있어요" : "한 번 로그인하면 이 기기에서 계속 유지돼요"}
        </p>
      </form>
    </div>
  );
}
