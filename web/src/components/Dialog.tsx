// 브라우저 기본 창(confirm · alert · prompt) 대신 LUNE 모양의 아래에서 올라오는 시트와 짧은 알림.
// 어디서나 `await askYes("지울까요?")`, `await askText("이름", "기본값")`, `tell("저장했어요")` 로 부르고,
// 화면에는 App 맨 위에 둔 <DialogHost /> 하나가 그린다.
import { useEffect, useRef, useState } from "react";
import { haptic } from "../lib/haptic";

type Ask = { kind: "yes"; message: string; done: (v: boolean) => void }
  | { kind: "text"; message: string; value: string; done: (v: string | null) => void };

let push: ((a: Ask) => void) | null = null;
let toast: ((m: string) => void) | null = null;

/** 예/아니요를 묻는다. 첫 문장(…까요?)은 제목, 나머지는 설명으로 보여 준다 */
export function askYes(message: string): Promise<boolean> {
  if (!push) return Promise.resolve(window.confirm(message));
  return new Promise((done) => push!({ kind: "yes", message, done }));
}

/** 글 한 줄을 받는다. 취소하면 null */
export function askText(message: string, value = ""): Promise<string | null> {
  if (!push) return Promise.resolve(window.prompt(message, value));
  return new Promise((done) => push!({ kind: "text", message, value, done }));
}

/** 잠깐 떴다 사라지는 알림 (오류 · 완료 안내) */
export function tell(message: string): void {
  if (toast) toast(message); else window.alert(message);
}

// 묻는 말에 맞는 버튼 이름 (확인 대신 '지우기' · '빼기'처럼 무엇을 하는지)
const ACTIONS: [RegExp, string][] = [
  [/로그아웃/, "로그아웃"], [/뺄까요/, "빼기"], [/끊을까요/, "끊기"], [/나갈까요/, "나가기"], [/옮길까요/, "옮기기"],
  [/되돌릴까요/, "되돌리기"], [/받아쓸까요/, "다시 받아쓰기"], [/만들까요/, "만들기"], [/지울까요|지워/, "지우기"],
];
const DANGER = /지울까요|지워|뺄까요|끊을까요|로그아웃|나갈까요|되돌릴 수 없/;

function split(message: string): [string, string] {
  const m = message.match(/^(.+?[?？])\s*([\s\S]*)$/);
  return m ? [m[1], m[2].trim()] : [message, ""];
}

export function DialogHost() {
  const [queue, setQueue] = useState<Ask[]>([]);
  const [text, setText] = useState("");
  const [notes, setNotes] = useState<{ id: number; message: string }[]>([]);
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => {
    push = (a) => setQueue((q) => [...q, a]);
    toast = (message) => {
      const id = Date.now() + Math.random();
      setNotes((n) => [...n.slice(-1), { id, message }]);
      window.setTimeout(() => setNotes((n) => n.filter((x) => x.id !== id)), 3200);
    };
    return () => { push = null; toast = null; };
  }, []);
  const now = queue[0];
  useEffect(() => {
    if (now?.kind === "text") { setText(now.value); window.setTimeout(() => input.current?.select(), 60); }
    if (now) haptic("light");
  }, [now]);
  useEffect(() => {
    if (!now) return;
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") close(false); };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  });
  const close = (ok: boolean) => {
    if (!now) return;
    if (now.kind === "yes") now.done(ok); else now.done(ok ? text : null);
    setQueue((q) => q.slice(1));
  };
  const [title, body] = now ? split(now.message) : ["", ""];
  const action = now?.kind === "yes" ? (ACTIONS.find(([re]) => re.test(now.message))?.[1] ?? "확인") : "확인";
  const danger = now?.kind === "yes" && DANGER.test(now.message);
  return (
    <>
      {now && (
        <>
          <div className="sheet-bg" onClick={() => close(false)} />
          <div className="sheet ask-sheet" role="alertdialog" aria-modal="true" aria-label={title}>
            <span className="sheet-grip" aria-hidden />
            <b className="ask-title">{title}</b>
            {body && <p className="ask-body">{body}</p>}
            {now.kind === "text" && (
              <input ref={input} className="input" value={text} onChange={(e) => setText(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") close(true); }} />
            )}
            <div className="ask-buttons">
              <button className="btn btn-secondary" onClick={() => close(false)}>취소</button>
              <button className={`btn ${danger ? "btn-danger" : "btn-primary"}`} onClick={() => { haptic(danger ? "heavy" : "medium"); close(true); }}>{action}</button>
            </div>
          </div>
        </>
      )}
      <div className="toasts" aria-live="polite">
        {notes.map((n) => <div key={n.id} className="toast-pill">{n.message}</div>)}
      </div>
    </>
  );
}
