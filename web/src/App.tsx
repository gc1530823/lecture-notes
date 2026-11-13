// Figma "강의노트 디자인 / 03 디자인" 화면을 옮긴 새 프론트. 화면은 해시 주소로 고른다 (router.ts).
import DocDetail from "./screens/DocDetail";
import ExamMap from "./screens/ExamMap";
import { JokboScreen, PrivacyScreen, ReviewScreen } from "./screens/ExamPrep";
import Home from "./screens/Home";
import Intro from "./screens/Intro";
import Lecture from "./screens/Lecture";
import Semester from "./screens/Semester";
import Search from "./screens/Search";
import { QuizScreen } from "./screens/QuizChat";
import Session from "./screens/Session";
import { href, useRoute } from "./router";
import TabBar from "./components/TabBar";

export default function App() {
  const route = useRoute();
  // 화면이 바뀔 때마다 새로 그려 들어오는 모션을 준다 (styles/app.css 의 .route)
  const tab = route.name === "home" ? "home" : route.name === "review" ? "review" : route.name === "search" ? "search" : route.name === "privacy" ? "more" : null;
  return (
    <>
      <div className="route" key={href(route)}>{screen(route)}</div>
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
    case "review": return <ReviewScreen />;
    case "privacy": return <PrivacyScreen />;
    case "semester": return <Semester tab={route.tab} />;
    case "search": return <Search />;
    case "lecture": return <Lecture key={route.docId + (route.sessionId ?? "")} docId={route.docId} sessionId={route.sessionId} />;
    case "session": return <Session docId={route.docId} sessionId={route.sessionId} tab={route.tab} />;
  }
}
