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
  return url.pathname.replace(/^.*?(\/(documents|sessions|semester|exams|review|privacy|health|timetable|marks|tasks|annotations|shared|photos)(\/|$))/, "$1");
}

async function answer(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const path = pathOf(input);
  const method = (init?.method ?? (input instanceof Request ? input.method : "GET")).toUpperCase();
  if (!/^\/(documents|sessions|semester|exams|review|privacy|health|timetable|marks|tasks|annotations|shared|photos)/.test(path)) {
    return realFetch(input, init); // 아이콘·pdf.js 같은 페이지 자체 파일
  }
  if (method === "GET") {
    const hit = data[path];
    if (hit && typeof hit === "object" && "__file" in (hit as object)) {
      const file = hit as { __file: string; type: string };
      return realFetch(`./${file.__file}`);
    }
    if (hit !== undefined) return json(hit);
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
  return json({ detail: "데모 페이지에서는 저장·녹음·업로드를 할 수 없어요" }, 400);
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
