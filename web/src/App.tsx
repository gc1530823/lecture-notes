// Figma "강의노트 디자인 / 03 디자인" 화면을 옮긴 새 프론트. 화면은 해시 주소로 고른다 (router.ts).
import DocDetail from "./screens/DocDetail";
import { ScheduleScreen } from "./screens/Tasks";
import { FriendsScreen } from "./screens/Friends";
import { AdminScreen } from "./screens/Admin";
import { WeakScreen } from "./screens/Weak";
import ExamMap from "./screens/ExamMap";
import { JokboScreen, PrivacyScreen, ReviewScreen } from "./screens/ExamPrep";
import Home from "./screens/Home";
import Intro from "./screens/Intro";
import Lecture from "./screens/Lecture";
import Semester from "./screens/Semester";
import Search from "./screens/Search";
import { QuizScreen } from "./screens/QuizCards";
import Session from "./screens/Session";
import { href, useRoute } from "./router";
import TabBar from "./components/TabBar";
import Login, { type Me } from "./screens/Login";
import { useCallback, useEffect, useState } from "react";
import { getJSON } from "./api/useApi";
import { DialogHost } from "./components/Dialog";
import { PullRefresh } from "./components/PullRefresh";

export default function App() {
  // 관리자 페이지는 사용자 로그인과 따로 (관리자 비밀번호)
  const [hash, setHash] = useState(window.location.hash);
  useEffect(() => { const on = () => setHash(window.location.hash); window.addEventListener("hashchange", on); return () => window.removeEventListener("hashchange", on); }, []);
  return <>{hash.startsWith("#/admin") ? <AdminScreen /> : <UserApp />}<DialogHost /></>;
}

function UserApp() {
  // 친구들과 함께 쓰는 서버면 먼저 로그인 (혼자 쓰는 서버·데모는 바로)
  const [me, setMe] = useState<Me | null>(null);
  useEffect(() => {
    const check = () => getJSON<Me>("/auth/me").then(setMe).catch(() => setMe({ auth: false, user: null }));
    void check();
    const need = () => setMe((m) => (m?.auth ? { ...m, user: null } : m));
    window.addEventListener("ln-login-needed", need);
    return () => window.removeEventListener("ln-login-needed", need);
  }, []);
  if (me === null) return <div className="boot" aria-busy="true" />;
  if (me.auth && !me.user) return <Login onDone={(m) => { setMe(m); window.location.hash = "#/"; }} />;
  return <Routed />;
}

function Routed() {
  const route = useRoute();
  // 당겨서 새로고침: 지금 화면을 새로 그려서 자료를 다시 불러온다 (녹음 화면은 빼고)
  const [nonce, setNonce] = useState(0);
  const refresh = useCallback(() => setNonce((n) => n + 1), []);
  // 화면이 바뀔 때마다 새로 그려 들어오는 모션을 준다 (styles/app.css 의 .route)
  const tab = route.name === "home" ? "home" : route.name === "review" ? "review" : route.name === "search" ? "search" : route.name === "tasks" || route.name === "timetable" ? "tasks" : route.name === "friends" ? "friends" : route.name === "privacy" ? "more" : null;
  return (
    <>
      <PullRefresh enabled={route.name !== "lecture" && route.name !== "intro"} onRefresh={refresh} />
      <div className="route" key={`${href(route)}#${nonce}`}>{screen(route)}</div>
      {tab && <TabBar current={tab} />}
    </>
  );
}

function screen(route: ReturnType<typeof useRoute>) {
  switch (route.name) {
    case "home": return <Home />;
    case "intro": return <Intro />;
    case "doc": return <DocDetail key={route.docId} docId={route.docId} />;
    case "exam": return <ExamMap docId={route.docId} />;
    case "jokbo": return <JokboScreen docId={route.docId} />;
    case "quiz": return <QuizScreen docId={route.docId} />;
    case "weak": return <WeakScreen docId={route.docId} />;
    case "review": return <ReviewScreen />;
    case "privacy": return <PrivacyScreen />;
    case "semester": return <Semester tab={route.tab} />;
    case "search": return <Search />;
    case "tasks": return <ScheduleScreen view="tasks" />;
    case "timetable": return <ScheduleScreen view="timetable" />;
    case "friends": return <FriendsScreen />;
    case "lecture": return <Lecture key={route.docId + (route.sessionId ?? "")} docId={route.docId} sessionId={route.sessionId} />;
    case "session": return <Session docId={route.docId} sessionId={route.sessionId} tab={route.tab} />;
  }
}
