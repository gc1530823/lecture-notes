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
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const submit = async () => {
    setBusy(true); setError(null);
    try {
      onDone(await postJSON<Me>(`/auth/${mode}`, { name, password, invite }));
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    setBusy(false);
  };
  const ready = name.trim() && password.length >= (mode === "signup" ? 6 : 1) && (mode === "login" || invite.trim());
  return (
    <div className="login">
      <LuneMark size={84} className="login-mark" />
      <h1 aria-label="LUNE"><LuneWordmark height={30} /></h1>
      <p className="login-tag">{TAGLINE}</p>
      <p className="t-caption muted">녹음하면 강의자료 위에 AI 필기가 붙어요</p>
      <form className="login-card" onSubmit={(e) => { e.preventDefault(); if (ready && !busy) void submit(); }}>
        <SlidingTabs label="로그인 방법" value={mode} onChange={(m) => { setMode(m); setError(null); }}
          items={[["login", "로그인"], ["signup", "처음이에요"]] as const} />
        {mode === "signup" && (
          <label><span>초대 코드</span>
            <input className="input" value={invite} onChange={(e) => setInvite(e.target.value)} placeholder="친구에게 받은 코드" autoComplete="off" />
          </label>
        )}
        <label><span>이름</span>
          <input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="예: 민지" autoComplete="username" maxLength={20} />
        </label>
        <label><span>비밀번호</span>
          <input className="input" type="password" value={password} onChange={(e) => setPassword(e.target.value)}
            placeholder={mode === "signup" ? "6자 이상" : ""} autoComplete={mode === "signup" ? "new-password" : "current-password"} />
        </label>
        {error && <p className="login-error">{error}</p>}
        <Button block disabled={!ready || busy}>{busy ? "잠시만요…" : mode === "signup" ? "가입하고 시작하기" : "로그인"}</Button>
        <p className="t-caption faint" style={{ textAlign: "center", margin: 0 }}>
          {mode === "signup" ? "내 강의·녹음·필기는 나만 볼 수 있어요" : "한 번 로그인하면 이 기기에서 계속 유지돼요"}
        </p>
      </form>
    </div>
  );
}
