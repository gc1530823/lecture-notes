// 데모 모드 (VITE_DEMO=1 빌드): 서버 없이 화면을 둘러볼 수 있게, 미리 받아 둔 서버 응답(demo-data.json)으로 답한다.
// 디자인을 함께 보고 고칠 때 쓰는 공유용 페이지에서만 켠다. 녹음·업로드처럼 서버가 꼭 있어야 하는 일은 하지 않는다.

type Entry = unknown | { __file: string; type: string };

let data: Record<string, Entry> = {};
const realFetch = window.fetch.bind(window);

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function pathOf(input: RequestInfo | URL): string {
  const raw = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
  const url = new URL(raw, window.location.href);
  return url.pathname.replace(/^.*?(\/(documents|sessions|semester|exams|review|privacy|health|timetable|friends|streak|waves|tasks|marks|tasks|annotations|shared|photos|quiz-sets)(\/|$))/, "$1");
}

async function answer(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const path = pathOf(input);
  const method = (init?.method ?? (input instanceof Request ? input.method : "GET")).toUpperCase();
  if (!/^\/(documents|sessions|semester|exams|review|privacy|health|timetable|friends|streak|waves|tasks|marks|tasks|annotations|shared|photos|quiz-sets)/.test(path)) {
    return realFetch(input, init); // 아이콘·pdf.js 같은 페이지 자체 파일
  }
  if (method === "GET") {
    const hit = data[path];
    if (hit && typeof hit === "object" && "__file" in (hit as object)) {
      const file = hit as { __file: string; type: string };
      return realFetch(`./${file.__file}`);
    }
    if (hit !== undefined) return json(hit);
    if (path === "/timetable") return json([]); // 데모: 빈 시간표 (등록 카드가 보이게)
    if (path.endsWith("/audio")) return new Response(null, { status: 404 });
    return json({ detail: "데모에는 없는 내용이에요" }, 404);
  }
  // 만들기 요청: 미리 만들어 둔 결과가 있으면 그것을, 없으면 "데모라 못 해요"
  if (path.includes("/study/") || path.endsWith("/notes-pdf")) {
    const ready = data[path.endsWith("/notes-pdf") ? `${path}/status` : path];
    if (ready) return json(ready, 202);
  }
  if (path.endsWith("/tutor")) {
    return json({ answer: "데모 페이지라 AI 튜터가 직접 답하지는 않아요. 실제 앱에서는 오늘 강의 내용으로 근거 쪽과 함께 답해요.", pages: [1], sources: [] });
  }
  if (path.startsWith("/review/")) return json({ ok: true });
  if (path.startsWith("/tasks/")) return json({ ok: true }); // 데모: 체크·마감일은 화면에서만
  if (path.endsWith("/quiz-set")) return makeQuiz(path);
  const grade = path.match(/^\/quiz-sets\/(\d+)\/grade$/);
  if (grade) return gradeQuiz(Number(grade[1]), JSON.parse(String(init?.body ?? "{}")));
  return json({ detail: "데모 페이지에서는 저장·녹음·업로드를 할 수 없어요" }, 400);
}

// AI 퀴즈 (데모): 미리 써 둔 문제 묶음(demo-data의 "__quiz/<자료 id>")으로 대화하듯 묻고, 채점은 브라우저에서 간단히 흉내 낸다
interface DemoQ { type: string; type_label: string; page_no: number; topic: string; question: string; choices: string[]; answer: string; accept?: string[]; keywords?: string[]; explanation: string }
const quizzes: { questions: DemoQ[]; answers: { verdict: string; score: number; feedback: string; given: string }[] }[] = [];
const norm = (t: string) => t.toLowerCase().replace(/[\s.,·:;!?'"()~_-]+/g, "");

function publicQuiz(id: number) {
  const q = quizzes[id];
  return {
    id, title: "", answered: q.answers.length, score: q.answers.reduce((s, a) => s + a.score, 0),
    questions: q.questions.map((x, i) => {
      const base = { index: i, type: x.type, type_label: x.type_label, page_no: x.page_no, topic: x.topic, question: x.question, choices: x.choices };
      return i < q.answers.length ? { ...base, answer: x.answer, explanation: x.explanation, result: q.answers[i] } : base;
    }),
  };
}

async function makeQuiz(path: string) {
  const id = path.split("/")[2];
  const docs = (data["/documents"] ?? []) as { id: string; sessions: { id: string }[] }[];
  const docId = path.startsWith("/documents/") ? id : docs.find((d) => d.sessions.some((s) => s.id === id))?.id;
  const set = (data[`__quiz/${docId}`] ?? data["__quiz/default"]) as DemoQ[] | undefined;
  if (!set) return json({ detail: "데모에는 이 자료의 AI 퀴즈가 없어요" }, 409);
  await new Promise((r) => setTimeout(r, 1600)); // AI가 공부하는 시간
  quizzes.push({ questions: set, answers: [] });
  return json(publicQuiz(quizzes.length - 1));
}

async function gradeQuiz(id: number, body: { index: number; answer: string }) {
  const q = quizzes[id];
  const x = q?.questions[body.index];
  if (!x || body.index !== q.answers.length) return json({ detail: "이 문제는 지금 채점할 수 없어요." }, 409);
  const given = norm(body.answer);
  let verdict = "wrong", feedback = "";
  if (x.type === "mcq") verdict = x.choices["ABCD".indexOf(body.answer)] === x.answer ? "correct" : "wrong";
  else if ([x.answer, ...(x.accept ?? [])].some((a) => norm(a) === given)) verdict = "correct";
  else if (x.type === "ox" || !x.keywords?.length) verdict = "wrong";
  else {
    await new Promise((r) => setTimeout(r, 900)); // AI 채점 시간
    const hit = (x.keywords ?? []).filter((k) => given.includes(norm(k)));
    const need = x.keywords.length;
    verdict = hit.length >= need ? "correct" : hit.length > 0 ? "partial" : "wrong";
    feedback = verdict === "correct" ? "핵심을 정확히 짚었어요." : verdict === "partial"
      ? `${hit.join(", ")}은(는) 맞게 썼어요. ${(x.keywords ?? []).filter((k) => !hit.includes(k)).join(", ")}에 대한 설명이 빠졌어요.`
      : "핵심 개념이 빠졌어요. 모범 답안과 해설을 같이 보세요.";
  }
  if (verdict === "wrong" && !feedback && x.type !== "mcq") feedback = "아쉬워요. 모범 답안을 확인해 보세요.";
  q.answers.push({ verdict, score: verdict === "correct" ? 1 : verdict === "partial" ? 0.5 : 0, feedback, given: body.answer });
  return json({ ...publicQuiz(id).questions[body.index], done: q.answers.length === q.questions.length });
}

/** 서버 연결(WebSocket) 대신: 데모에서는 녹음하지 않으므로 아무 일도 하지 않는 연결 */
class DemoSocket {
  readyState = 3;
  onopen: (() => void) | null = null;
  onmessage: (() => void) | null = null;
  onclose: (() => void) | null = null;
  send() { /* 데모 */ }
  close() { /* 데모 */ }
}

export async function startDemo() {
  try {
    data = await (await realFetch("./demo-data.json")).json();
  } catch {
    data = {};
  }
  window.fetch = answer as typeof window.fetch;
  (window as unknown as { WebSocket: unknown }).WebSocket = DemoSocket;
}

export const isDemo = import.meta.env.VITE_DEMO === "1";
