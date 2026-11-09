// Figma "강의노트 디자인 / 03 디자인" 화면을 옮긴 새 프론트. 화면은 해시 주소로 고른다 (router.ts).
import DocDetail from "./screens/DocDetail";
import ExamMap from "./screens/ExamMap";
import { JokboScreen, PrivacyScreen, ReviewScreen } from "./screens/ExamPrep";
import Home from "./screens/Home";
import Lecture from "./screens/Lecture";
import Session from "./screens/Session";
import { useRoute } from "./router";

export default function App() {
  const route = useRoute();
  switch (route.name) {
    case "home": return <Home />;
    case "doc": return <DocDetail key={route.docId} docId={route.docId} />;
    case "exam": return <ExamMap docId={route.docId} />;
    case "jokbo": return <JokboScreen docId={route.docId} />;
    case "review": return <ReviewScreen />;
    case "privacy": return <PrivacyScreen />;
    case "lecture": return <Lecture key={route.docId + (route.sessionId ?? "")} docId={route.docId} sessionId={route.sessionId} />;
    case "session": return <Session docId={route.docId} sessionId={route.sessionId} tab={route.tab} />;
  }
}
