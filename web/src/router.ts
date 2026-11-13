// 해시 주소로 화면을 고른다 (서버 정적 파일로 올려도 새로고침이 깨지지 않게).
//   #/                     자료 목록
//   #/doc/:docId           자료 상세 (강의 목록)
//   #/session/:sid/:tab    강의 다시 보기 (notes | study | glossary)
//   #/doc/:docId/exam      시험 예상 지도
//   #/doc/:docId/lecture[/:sid]  강의 화면 (녹음 / 자료 위에서 다시 보기)
import { useEffect, useState } from "react";
import { flushSync } from "react-dom";

export type Route =
  | { name: "home" }
  | { name: "intro" }
  | { name: "doc"; docId: string }
  | { name: "exam"; docId: string }
  | { name: "lecture"; docId: string; sessionId?: string }
  | { name: "jokbo"; docId: string }
  | { name: "quiz"; docId: string }
  | { name: "review" }
  | { name: "privacy" }
  | { name: "semester"; tab: string }
  | { name: "search" }
  | { name: "session"; docId: string; sessionId: string; tab: string };

export function parse(hash: string): Route {
  const parts = hash.replace(/^#\/?/, "").split("/").filter(Boolean).map(decodeURIComponent);
  if (parts[0] === "doc" && parts[1] && parts[2] === "exam") return { name: "exam", docId: parts[1] };
  if (parts[0] === "intro") return { name: "intro" };
  if (parts[0] === "review") return { name: "review" };
  if (parts[0] === "privacy") return { name: "privacy" };
  if (parts[0] === "search") return { name: "search" };
  if (parts[0] === "semester") return { name: "semester", tab: parts[1] ?? "map" };
  if (parts[0] === "doc" && parts[1] && parts[2] === "quiz") return { name: "quiz", docId: parts[1] };
  if (parts[0] === "doc" && parts[1] && parts[2] === "jokbo") return { name: "jokbo", docId: parts[1] };
  if (parts[0] === "doc" && parts[1] && parts[2] === "lecture") return { name: "lecture", docId: parts[1], sessionId: parts[3] };
  if (parts[0] === "doc" && parts[1] && parts[2] === "session" && parts[3])
    return { name: "session", docId: parts[1], sessionId: parts[3], tab: parts[4] ?? "notes" };
  if (parts[0] === "doc" && parts[1]) return { name: "doc", docId: parts[1] };
  return { name: "home" };
}

export function href(route: Route): string {
  switch (route.name) {
    case "home": return "#/";
    case "intro": return "#/intro";
    case "doc": return `#/doc/${route.docId}`;
    case "exam": return `#/doc/${route.docId}/exam`;
    case "jokbo": return `#/doc/${route.docId}/jokbo`;
    case "quiz": return `#/doc/${route.docId}/quiz`;
    case "review": return "#/review";
    case "privacy": return "#/privacy";
    case "search": return "#/search";
    case "semester": return `#/semester/${route.tab}`;
    case "lecture": return `#/doc/${route.docId}/lecture${route.sessionId ? `/${route.sessionId}` : ""}`;
    case "session": return `#/doc/${route.docId}/session/${route.sessionId}/${route.tab}`;
  }
}

// 뒤로 가기: 들어온 순서를 기억해 두었다가 바로 앞 화면으로 돌아간다.
// (홈의 "족보 노트"처럼 자료 상세를 거치지 않고 들어온 화면도 뒤로 가면 홈으로)
// 같은 화면 안에서 탭만 바꾸는 것은 기록을 쌓지 않는다 (뒤로 가기가 탭을 되감지 않게)
const stack: string[] = [window.location.hash || "#/"];
let replacing = false;
window.addEventListener("hashchange", () => {
  const h = window.location.hash || "#/";
  if (replacing) { stack[stack.length - 1] = h; replacing = false; return; }
  if (stack.length > 1 && stack[stack.length - 2] === h) stack.pop();
  else stack.push(h);
});

function sameScreen(a: Route, b: Route): boolean {
  const ids = (r: Route) => [r.name, "docId" in r ? r.docId : "", "sessionId" in r ? r.sessionId ?? "" : ""].join("/");
  return ids(a) === ids(b);
}

export function go(route: Route) {
  const next = href(route);
  if (next === (window.location.hash || "#/")) return;
  if (sameScreen(parse(window.location.hash), route) && route.name !== "doc") {
    replacing = true;
    window.location.replace(next);
  } else window.location.hash = next;
}

/** 화면 위 뒤로 버튼: 앱 안에서 온 화면이 있으면 그리로, 바로 열었으면 fallback으로 */
export function back(fallback: Route) {
  if (stack.length > 1) window.history.back();
  else go(fallback);
}

/** 화면 깊이: 깊은 화면으로 갈 때는 오른쪽에서 들어오고, 돌아올 때는 왼쪽에서 (styles/app.css 의 화면 전환) */
function depth(route: Route): number {
  return route.name === "home" || route.name === "intro" ? 0 : route.name === "doc" || route.name === "review" || route.name === "privacy" || route.name === "search" || route.name === "semester" ? 1 : 2;
}

type Transition = { finished: Promise<void> };
const startTransition = (document as unknown as { startViewTransition?: (cb: () => void) => Transition }).startViewTransition?.bind(document);

export function useRoute(): Route {
  const [route, setRoute] = useState(() => parse(window.location.hash));
  useEffect(() => {
    let current = parse(window.location.hash);
    const on = () => {
      const next = parse(window.location.hash);
      const apply = () => { flushSync(() => setRoute(next)); window.scrollTo(0, 0); };
      const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
      // 같은 화면 안에서 탭만 바뀌는 것은 전환 없이
      if (!startTransition || still || (next.name === current.name && depth(next) === 2 && next.name !== "lecture")) { apply(); current = next; return; }
      document.documentElement.dataset.nav = depth(next) < depth(current) ? "back" : depth(next) > depth(current) ? "forward" : "same";
      current = next;
      startTransition(apply);
    };
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return route;
}
