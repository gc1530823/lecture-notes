// 친구: 내 친구 코드를 알려 주고, 친구 코드로 신청하고, 받은 신청을 수락한다.
// 친구끼리는 같은 강의자료(같은 PDF)로 들은 강의의 족보가 저절로 합쳐진다 (녹음·받아쓰기는 서로 못 본다).
import { useCallback, useEffect, useState } from "react";
import { getJSON, postJSON } from "../api/useApi";
import { Button, Icon, TopBar } from "../components/ui";
import { back } from "../router";

interface Friend { id: string; name: string; status: string; mine: boolean; created_at: number }
interface FriendsData { me: { name: string; code: string }; friends: Friend[]; incoming: Friend[]; outgoing: Friend[] }

const API = import.meta.env.VITE_API_URL ?? "";

export function FriendsScreen() {
  const [data, setData] = useState<FriendsData | null>(null);
  const [error, setError] = useState("");
  const [code, setCode] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const load = useCallback(() => {
    getJSON<FriendsData>("/friends").then(setData).catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);
  useEffect(load, [load]);

  const add = async () => {
    setMsg(""); setBusy(true);
    try {
      const r = await postJSON<{ status: string; name: string }>("/friends", { code });
      setMsg(r.status === "accepted" ? `${r.name}님과 친구가 됐어요!` : `${r.name}님에게 친구 신청을 보냈어요. 수락하면 친구가 돼요.`);
      setCode(""); load();
    } catch (e) { setMsg(e instanceof Error ? e.message : String(e)); }
    setBusy(false);
  };
  const accept = async (f: Friend) => { await postJSON(`/friends/${f.id}/accept`).catch(() => {}); navigator.vibrate?.(15); load(); };
  const remove = async (f: Friend, ask: string) => {
    if (ask && !confirm(ask)) return;
    await fetch(`${API}/friends/${f.id}`, { method: "DELETE" }).catch(() => {});
    load();
  };
  const shareCode = async () => {
    if (!data) return;
    const text = `LUNE에서 친구 추가해 줘! 내 친구 코드: ${data.me.code}\n${window.location.origin}`;
    try {
      if (navigator.share) await navigator.share({ text });
      else { await navigator.clipboard.writeText(data.me.code); setMsg("내 코드를 복사했어요. 카톡에 붙여 넣어 보내세요."); }
    } catch { /* 닫음 */ }
  };

  return (
    <div className="screen friends">
      <TopBar title="친구" onBack={() => back({ name: "privacy" })} />
      <div className="screen-body">
        {error && <p className="muted">{error}</p>}
        {data && <>
          <section className="my-code">
            <span className="t-caption">내 친구 코드</span>
            <b className="code">{data.me.code}</b>
            <span className="t-caption">친구에게 이 코드를 알려 주세요</span>
            <div className="row">
              <Button className="grow" variant="secondary" icon="export" onClick={() => void shareCode()}>코드 보내기</Button>
            </div>
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
              <div key={f.id} className="set-row">
                <span className="avatar">{f.name.slice(0, 1)}</span>
                <span className="grow set-text"><b>{f.name}</b><small>{new Date(f.created_at * 1000).toLocaleDateString("ko-KR")}부터 친구</small></span>
                <button className="chip chip-default" onClick={() => void remove(f, `${f.name}님과 친구를 끊을까요? 족보도 더 이상 합쳐지지 않아요.`)}>끊기</button>
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

          <section className="friend-how">
            <b><Icon name="users" size={16} /> 친구가 되면</b>
            <p>같은 강의자료(같은 PDF)로 들은 강의가 있으면 <strong>족보가 저절로 합쳐져요</strong>. 여럿이 시험·강조로 적은 쪽이 위로 올라와요.</p>
            <p>친구에게 보이는 것: 시험·강조·공지 표시, 용어, 예상 문제, "모르겠어요" 설명. <strong>녹음과 받아쓰기, 내 필기 전체는 보이지 않아요.</strong></p>
          </section>
        </>}
      </div>
    </div>
  );
}
