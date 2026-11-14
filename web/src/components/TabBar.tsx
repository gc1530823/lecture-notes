// 아래 탭: 홈 · 복습 · 할 일 · 친구 · 찾기 · 설정. 이 네 화면에서만 보인다 (App.tsx)
import { useEffect, useState } from "react";
import { getJSON } from "../api/useApi";
import { go } from "../router";
import { Icon } from "./ui";

/** 받은 친구 신청 수 (탭에 빨간 숫자). 로그인 없이 쓰는 서버면 0 */
function useFriendAsks() {
  const [n, setN] = useState(0);
  useEffect(() => {
    getJSON<{ incoming: unknown[] }>("/friends").then((d) => setN(d.incoming.length)).catch(() => setN(0));
  }, []);
  return n;
}

/** 아래 탭: 홈 · 복습 · 할 일 · 친구 · 찾기 · 설정 */
export default function TabBar({ current }: { current: "home" | "review" | "tasks" | "friends" | "search" | "more" }) {
  const tabs = [["home", "house", "홈", () => go({ name: "home" })], ["review", "cards", "복습", () => go({ name: "review" })],
    ["tasks", "calendar-dots", "할 일", () => go({ name: "tasks" })],
    ["friends", "users", "친구", () => go({ name: "friends" })],
    ["search", "magnifying-glass", "찾기", () => go({ name: "search" })], ["more", "gear", "설정", () => go({ name: "privacy" })]] as const;
  const asks = useFriendAsks();
  return (
    <nav className="tabbar" aria-label="아래 탭">
      {tabs.map(([key, icon, label, onClick]) => (
        <button key={key} className={current === key ? "on" : ""} onClick={() => { if (current !== key) onClick(); }} aria-current={current === key ? "page" : undefined}>
          <span className="tab-ic"><Icon name={icon} size={22} />{key === "friends" && asks > 0 && <i className="tab-badge">{asks}</i>}</span>{label}
        </button>
      ))}
    </nav>
  );
}
