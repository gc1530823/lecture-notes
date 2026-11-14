// 아래 탭 (참고 디자인): 홈 · 복습 · 찾기 · 더보기. 이 네 화면에서만 보인다 (App.tsx)
import { go } from "../router";
import { Icon } from "./ui";

/** 아래 탭: 홈 · 복습 · 찾기 · 설정 */
export default function TabBar({ current }: { current: "home" | "review" | "search" | "more" }) {
  const tabs = [["home", "house", "홈", () => go({ name: "home" })], ["review", "cards", "복습", () => go({ name: "review" })],
    ["search", "magnifying-glass", "찾기", () => go({ name: "search" })], ["more", "gear", "설정", () => go({ name: "privacy" })]] as const;
  return (
    <nav className="tabbar" aria-label="아래 탭">
      {tabs.map(([key, icon, label, onClick]) => (
        <button key={key} className={current === key ? "on" : ""} onClick={() => { if (current !== key) onClick(); }} aria-current={current === key ? "page" : undefined}>
          <Icon name={icon} size={22} />{label}
        </button>
      ))}
    </nav>
  );
}
