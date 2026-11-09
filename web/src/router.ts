// 해시 주소로 화면을 고른다 (서버 정적 파일로 올려도 새로고침이 깨지지 않게).
//   #/                     자료 목록
//   #/doc/:docId           자료 상세 (강의 목록)
//   #/session/:sid/:tab    강의 다시 보기 (notes | study | glossary)
//   #/doc/:docId/exam      시험 예상 지도
//   #/doc/:docId/lecture[/:sid]  강의 화면 (녹음 / 자료 위에서 다시 보기)
import { useEffect, useState } from "react";

export type Route =
  | { name: "home" }
  | { name: "doc"; docId: string }
  | { name: "exam"; docId: string }
  | { name: "lecture"; docId: string; sessionId?: string }
  | { name: "session"; docId: string; sessionId: string; tab: string };

export function parse(hash: string): Route {
  const parts = hash.replace(/^#\/?/, "").split("/").filter(Boolean).map(decodeURIComponent);
  if (parts[0] === "doc" && parts[1] && parts[2] === "exam") return { name: "exam", docId: parts[1] };
  if (parts[0] === "doc" && parts[1] && parts[2] === "lecture") return { name: "lecture", docId: parts[1], sessionId: parts[3] };
  if (parts[0] === "doc" && parts[1] && parts[2] === "session" && parts[3])
    return { name: "session", docId: parts[1], sessionId: parts[3], tab: parts[4] ?? "notes" };
  if (parts[0] === "doc" && parts[1]) return { name: "doc", docId: parts[1] };
  return { name: "home" };
}

export function href(route: Route): string {
  switch (route.name) {
    case "home": return "#/";
    case "doc": return `#/doc/${route.docId}`;
    case "exam": return `#/doc/${route.docId}/exam`;
    case "lecture": return `#/doc/${route.docId}/lecture${route.sessionId ? `/${route.sessionId}` : ""}`;
    case "session": return `#/doc/${route.docId}/session/${route.sessionId}/${route.tab}`;
  }
}

export function go(route: Route) { window.location.hash = href(route); }

export function useRoute(): Route {
  const [route, setRoute] = useState(() => parse(window.location.hash));
  useEffect(() => {
    const on = () => { setRoute(parse(window.location.hash)); window.scrollTo(0, 0); };
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return route;
}
