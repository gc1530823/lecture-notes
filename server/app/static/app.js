// 강의노트 웹앱: iPhone Safari·안드로이드·PC 브라우저에서 쓰는 버전.
// 서버(FastAPI)와 같은 주소에서 열리므로 API는 상대 경로로 부른다.
"use strict";

pdfjsLib.GlobalWorkerOptions.workerSrc = "vendor/pdfjs/pdf.worker.min.js";

const TYPES = {
  explanation: { label: "보충설명", icon: "chat-teardrop-text" },
  example: { label: "예시", icon: "lightbulb" },
  emphasis: { label: "강조", icon: "warning-circle" },
  exam: { label: "시험", icon: "star" },
  notice: { label: "공지", icon: "megaphone" },
  tip: { label: "AI 팁", icon: "sparkle" },
  qa: { label: "질문", icon: "hand-waving" },
};
// 기기별 설정 (자막 모드 등). 사생활 보호 모드 등에서 저장소를 못 쓰면 그냥 기본값으로 동작한다
const prefs = {
  get(key) { try { return localStorage.getItem(`ln.${key}`); } catch { return null; } },
  set(key, value) { try { localStorage.setItem(`ln.${key}`, value); } catch {} },
};

// 아이콘: Phosphor Icons duotone (MIT, vendor/phosphor/LICENSE). icons.svg 스프라이트에서 이름으로 꺼내 쓴다
const I = (name, cls = "") => `<svg class="ic ${cls}" aria-hidden="true"><use href="icons.svg#${name}"/></svg>`;

const TASK_KINDS = {
  in_class: { label: "수업 중 과제", icon: "timer", color: "var(--record)" },
  homework: { label: "숙제", icon: "house-line", color: "var(--accent)" },
  report: { label: "레포트", icon: "file-text", color: "var(--tip-ink)" },
  exam_prep: { label: "시험 준비", icon: "graduation-cap", color: "var(--emphasis-ink)" },
};
const TILTS = [-2.2, 1.6, -1.0, 2.4, -0.5, 1.1];
const FOLLOW_CONFIDENCE = 0.6;
const MANUAL_PAUSE_MS = 20000;

const $app = document.getElementById("app");
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const tilt = (id) => TILTS[Math.abs(id) % TILTS.length];
const fmtTime = (s) => `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

function toast(message) {
  const el = document.createElement("div");
  el.className = "toast";
  el.textContent = message;
  document.body.append(el);
  setTimeout(() => el.remove(), 3500);
}

// ---------- 서버 ----------

async function api(method, path, body) {
  const options = { method };
  if (body instanceof FormData) options.body = body;
  else if (body !== undefined) {
    options.headers = { "Content-Type": "application/json" };
    options.body = JSON.stringify(body);
  }
  const res = await fetch(path, options);
  if (!res.ok) {
    let detail = `서버 오류 (${res.status})`;
    try { detail = (await res.json()).detail || detail; } catch {}
    throw new Error(detail);
  }
  return res.status === 204 ? null : res.json();
}

// ---------- 이 기기에 저장하는 목록 (강의자료와 지난 강의) ----------

const store = {
  load() {
    try { return JSON.parse(localStorage.getItem("lecture-notes") || "[]"); } catch { return []; }
  },
  save(docs) {
    try { localStorage.setItem("lecture-notes", JSON.stringify(docs)); } catch {}
  },
  add(doc) {
    const docs = this.load().filter((d) => d.id !== doc.id);
    docs.unshift({ id: doc.id, title: doc.title, pageCount: doc.page_count, kind: doc.kind || "slides", sessions: [] });
    this.save(docs);
  },
  addSession(docId, sessionId) {
    const docs = this.load();
    const doc = docs.find((d) => d.id === docId);
    if (doc) doc.sessions.unshift({ id: sessionId, startedAt: Date.now() });
    this.save(docs);
  },
  remove(docId) { this.save(this.load().filter((d) => d.id !== docId)); },
};

// 서버의 목록이 기준이다. 서버에 못 닿을 때만 기기에 남겨 둔 목록을 쓴다.
async function syncDocs() {
  try {
    const docs = (await api("GET", "/documents")).map((d) => ({
      id: d.id, title: d.title, pageCount: d.page_count, kind: d.kind || "slides",
      sessions: d.sessions.map((s) => ({ id: s.id, startedAt: s.started_at * 1000 })),
    }));
    store.save(docs);
    return docs;
  } catch {
    return store.load();
  }
}

const pdfCache = new Map();
function loadPdf(docId) {
  if (!pdfCache.has(docId)) pdfCache.set(docId, pdfjsLib.getDocument({
    url: `/documents/${docId}/pdf`,
    // 한글 PDF는 CID 글꼴을 많이 써서 문자표(cmap)가 있어야 글자가 보인다
    cMapUrl: "vendor/pdfjs/cmaps/", cMapPacked: true, standardFontDataUrl: "vendor/pdfjs/standard_fonts/",
  }).promise);
  return pdfCache.get(docId);
}

async function renderPage(pdf, pageNo, canvas, width) {
  const page = await pdf.getPage(pageNo);
  const base = page.getViewport({ scale: 1 });
  const ratio = Math.min(window.devicePixelRatio || 1, 3);
  const viewport = page.getViewport({ scale: (width / base.width) * ratio });
  canvas.width = viewport.width;
  canvas.height = viewport.height;
  await page.render({ canvasContext: canvas.getContext("2d"), viewport }).promise;
}

// ---------- 화면 이동 ----------

let current = null; // 지금 화면의 정리 함수 (녹음 중지 등)

function route() {
  if (current) current();
  current = null;
  const [, view, a, b] = location.hash.split("/");
  if (view === "doc") renderDetail(a);
  else if (view === "lecture") renderLecture(a, b);
  else if (view === "exam") renderExamMap(a);
  else renderList();
}
window.addEventListener("hashchange", route);

// ---------- 자료 목록 ----------

async function renderList() {
  const docs = await syncDocs();
  $app.innerHTML = `
    <div class="screen">
      <div class="topbar"><h1>강의노트</h1></div>
      ${docs.length ? `<div class="list">${docs.map((d) => `
        <button class="card doc-card" data-id="${d.id}">
          ${d.kind === "notebook" ? `<span class="nb-thumb">${I("notebook")}</span>` : `<canvas data-thumb="${d.id}"></canvas>`}
          <span style="flex:1"><b>${esc(d.title)}</b><small>${d.kind === "notebook" ? `${I("notebook")} 노트 ${d.pageCount}쪽` : `${I("file-text")} ${d.pageCount}쪽`} · ${I("microphone")} 강의 ${d.sessions.length}회</small></span>
          <span class="muted">${I("caret-right")}</span>
        </button>`).join("")}</div>` : `
        <div class="empty">
          <div class="notes">
            ${noteHTML({ id: 1, type: "explanation", text: "교수님 설명이 자료 옆에 자동으로 붙어요" }, 1).replace('class="note-wrap', 'style="margin-left:-175px;top:0" class="note-wrap')}
            ${noteHTML({ id: 2, type: "exam", text: "시험에 나온다고 한 부분은 빨간 포스트잇" }, 2).replace('class="note-wrap', 'style="margin-left:-5px;top:100px" class="note-wrap')}
          </div>
          <h2>첫 강의자료를 올려 보세요</h2>
          <p class="muted">PDF를 올리고 녹음을 시작하면<br>설명이 해당 문단 옆에 필기로 붙어요.</p>
        </div>`}
      <div class="fab fab-row"><button class="primary" id="add">＋ 강의자료 올리기</button>
        <button class="primary ghost" id="addnote">${I("notebook")} 자료 없이 노트로</button></div>
      <input type="file" id="file" accept="application/pdf" class="hidden">
    </div>`;
  $app.querySelectorAll(".empty .note-wrap").forEach((n) => { n.style.position = "absolute"; n.style.width = "170px"; n.style.left = "50%"; });
  $app.querySelectorAll(".doc-card").forEach((el) => el.addEventListener("click", () => (location.hash = `#/doc/${el.dataset.id}`)));
  $app.querySelectorAll("canvas[data-thumb]").forEach(async (canvas) => {
    try { await renderPage(await loadPdf(canvas.dataset.thumb), 1, canvas, 104); } catch {}
  });
  const input = $app.querySelector("#file");
  $app.querySelector("#add").addEventListener("click", () => input.click());
  // 강의자료가 없는 수업: 빈 줄 노트로 바로 녹음을 시작한다
  $app.querySelector("#addnote").addEventListener("click", async () => {
    const title = prompt("수업 이름 (비워도 돼요)", "");
    if (title === null) return;
    try {
      const doc = await api("POST", "/documents/notebook", { title });
      store.add(doc);
      location.hash = `#/lecture/${doc.id}`;
    } catch (e) { toast(e.message); }
  });
  input.addEventListener("change", async () => {
    const file = input.files[0];
    if (!file) return;
    const button = $app.querySelector("#add");
    button.textContent = "강의자료 분석 중…";
    button.disabled = true;
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("title", file.name.replace(/\.pdf$/i, ""));
      const doc = await api("POST", "/documents", form);
      store.add(doc);
      location.hash = `#/doc/${doc.id}`;
    } catch (e) {
      toast(e.message);
      renderList();
    }
  });
}

// ---------- 자료 상세 (새 강의 · 지난 강의) ----------

async function renderDetail(docId) {
  const doc = (await syncDocs()).find((d) => d.id === docId);
  if (!doc) return (location.hash = "#/");
  $app.innerHTML = `
    <div class="screen">
      <div class="topbar"><button class="icon-btn" id="back">${I("caret-left")}</button><div class="title">${esc(doc.title)}</div><button class="icon-btn" id="del">${I("trash")}</button></div>
      <div class="list">
        <div class="page"><canvas id="cover"></canvas></div>
        <button class="primary red" id="start" style="width:100%;height:56px;border-radius:18px">${I("microphone")} 새 강의 녹음하기</button>
        <button class="card item" id="audio" style="align-items:center">
          <span class="badge">${I("headphones")}</span>
          <span style="flex:1"><b>녹음 파일로 정리하기</b><br><small class="muted">iPhone '음성 메모'로 녹음한 파일을 올리면 화면을 꺼 둔 수업도 필기·요약·퀴즈로 만들어요</small></span>
          <span class="muted">${I("caret-right")}</span>
        </button>
        <button class="card item" id="exammap" style="align-items:center">
          <span class="badge">${I("target")}</span>
          <span style="flex:1"><b>시험 예상 지도</b><br><small class="muted">교수님이 강조하고 시험에 나온다고 한 곳을 페이지 위에 표시하고, 예상 문제를 만들어요</small></span>
          <span class="muted">${I("caret-right")}</span>
        </button>
        <h3 style="margin:8px 0 0">지난 강의</h3>
        ${doc.sessions.length ? doc.sessions.map((s, i) => `
          <button class="card item" data-session="${s.id}">
            <span class="badge">${doc.sessions.length - i}</span>
            <span style="flex:1"><b>${doc.sessions.length - i}회차 강의</b><br><small class="muted">${new Date(s.startedAt).toLocaleString("ko-KR")}</small></span>
            <span class="muted">${I("caret-right")}</span>
          </button>`).join("") : `<div class="empty-note">아직 녹음한 강의가 없어요</div>`}
      </div>
      <input type="file" id="audiofile" accept="audio/*,.m4a,.mp3,.wav" class="hidden">
    </div>`;
  $app.querySelector("#back").onclick = () => (location.hash = "#/");
  $app.querySelector("#del").onclick = () => {
    if (!confirm("이 강의자료와 지난 강의 필기를 모두 지울까요? 되돌릴 수 없어요.")) return;
    api("DELETE", `/documents/${docId}`)
      .then(() => { store.remove(docId); location.hash = "#/"; })
      .catch((e) => toast(e.message));
  };
  $app.querySelector("#start").onclick = () => (location.hash = `#/lecture/${docId}`);
  $app.querySelector("#exammap").onclick = () => (location.hash = `#/exam/${docId}`);
  const audioInput = $app.querySelector("#audiofile");
  $app.querySelector("#audio").onclick = () => audioInput.click();
  audioInput.onchange = () => {
    const file = audioInput.files[0];
    if (!file) return;
    const label = $app.querySelector("#audio b");
    const form = new FormData();
    form.append("document_id", docId);
    form.append("file", file);
    // 큰 파일이라 올라가는 정도를 보여 주려고 XHR을 쓴다
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/sessions/from-audio");
    xhr.upload.onprogress = (e) => { if (e.lengthComputable) label.textContent = `올리는 중… ${Math.round((e.loaded / e.total) * 100)}%`; };
    xhr.onload = () => {
      if (xhr.status >= 300) { toast(`올리지 못했어요 (${xhr.status})`); label.textContent = "녹음 파일로 정리하기"; return; }
      const session = JSON.parse(xhr.responseText);
      store.addSession(docId, session.id);
      location.hash = `#/lecture/${docId}/${session.id}`;
    };
    xhr.onerror = () => { toast("올리지 못했어요. 인터넷 연결을 확인해 주세요."); label.textContent = "녹음 파일로 정리하기"; };
    xhr.send(form);
  };
  $app.querySelectorAll("[data-session]").forEach((el) => (el.onclick = () => (location.hash = `#/lecture/${docId}/${el.dataset.session}`)));
  if (doc.kind === "notebook") {
    $app.querySelector("#cover").replaceWith(Object.assign(document.createElement("div"), {
      className: "notebook-page cover", innerHTML: `<h2>${esc(doc.title)}</h2><p class="nb-line muted">강의자료 없이 듣는 수업 · 노트 ${doc.pageCount}쪽</p>` }));
  } else {
    loadPdf(docId).then((pdf) => renderPage(pdf, 1, $app.querySelector("#cover"), Math.min(innerWidth - 32, 700))).catch(() => {});
  }
}

// ---------- 시험 예상 지도 ----------

const HEAT = {
  high: { label: `${I("fire")} 시험 유력`, color: "var(--exam-ink)" },
  medium: { label: `${I("warning")} 나올 수 있음`, color: "var(--emphasis-ink)" },
  low: { label: "", color: "transparent" },
};

async function renderExamMap(docId) {
  const doc = (await syncDocs()).find((d) => d.id === docId);
  if (!doc) return (location.hash = "#/");
  $app.innerHTML = `
    <div class="screen">
      <div class="topbar"><button class="icon-btn" id="back">${I("caret-left")}</button><div class="title">${I("target")} 시험 예상 지도</div><span style="width:36px"></span></div>
      <div class="list" id="exam"><p class="muted"><span class="spin"></span> 강의를 모아 분석하는 중…</p></div>
    </div>`;
  $app.querySelector("#back").onclick = () => (location.hash = `#/doc/${docId}`);
  const box = $app.querySelector("#exam");
  let alive = true;
  current = () => { alive = false; };

  const draw = (m) => {
    const ranked = m.top.map((no) => m.pages.find((p) => p.page_no === no));
    const qs = Object.fromEntries(m.questions.map((q) => [q.page_no, q]));
    const building = m.job.status === "building";
    const stale = m.questions.some((q) => q.stale) || m.questions.length < m.top.length;
    box.innerHTML = m.lectures === 0 ? `<div class="empty-note">강의를 녹음하면 교수님이 강조한 곳을 찾아 표시해요</div>` : `
      <p class="muted" style="margin:0">강의 ${m.lectures}회를 분석했어요. 색이 진할수록 시험에 나올 가능성이 높아요.</p>
      <div class="heat-grid">${m.pages.map((p) => `
        <button class="heat-cell" data-page="${p.page_no}" style="--heat:${HEAT[p.level].color};--alpha:${Math.round(p.score * 38)}%">
          <canvas data-heat="${p.page_no}"></canvas>
          <span class="heat-no">${p.page_no}</span>
          ${p.level !== "low" ? `<span class="heat-tag">${HEAT[p.level].label}</span>` : ""}
        </button>`).join("")}</div>
      <h3 style="margin:10px 0 0">시험에 나올 곳</h3>
      ${ranked.length ? ranked.map((p, i) => `
        <div class="card" style="padding:14px 16px" id="rank-${p.page_no}">
          <div class="row"><span class="badge" style="background:color-mix(in srgb,${HEAT[p.level].color} 16%,transparent);color:${HEAT[p.level].color}">${i + 1}</span>
            <b style="flex:1">${p.page_no}쪽 <small style="color:${HEAT[p.level].color}">${HEAT[p.level].label}</small></b></div>
          <div class="row" style="flex-wrap:wrap;gap:6px;margin-top:8px">${p.reasons.map((r) => `<span class="chip" style="color:var(--ink-2);background:var(--line)">${esc(r)}</span>`).join("")}</div>
          ${(qs[p.page_no]?.questions || []).map((q, j) => `
            <div class="predict">
              <b><span style="color:var(--accent)">예상 ${j + 1}</span> ${esc(q.question)}</b>
              <details><summary>모범 답안 보기</summary><p>${esc(q.answer)}</p></details>
              <small class="muted">${I("lightbulb")} ${esc(q.reason)}</small>
            </div>`).join("")}
        </div>`).join("") : `<div class="empty-note">아직 강조하거나 시험에 나온다고 한 곳이 없어요</div>`}
      ${ranked.length ? `<button class="primary" id="predict" style="width:100%;height:52px" ${building ? "disabled" : ""}>
        ${building ? `<span class="spin"></span> 예상 문제 만드는 중… ${m.job.total ? `(${m.job.done}/${m.job.total}쪽)` : ""}` : stale ? `${I("sparkle")} 예상 문제 만들기` : `${I("sparkle")} 예상 문제 다시 만들기`}</button>` : ""}`;
    box.querySelectorAll("canvas[data-heat]").forEach(async (canvas) => {
      if (doc.kind === "notebook") {
        // 노트 모드: 쪽마다 주제 제목을 보여 준다
        const page = m.pages.find((p) => p.page_no === Number(canvas.dataset.heat));
        canvas.replaceWith(Object.assign(document.createElement("div"), { className: "nb-tile", textContent: page?.title || `${canvas.dataset.heat}쪽` }));
        return;
      }
      try { await renderPage(await loadPdf(docId), Number(canvas.dataset.heat), canvas, Math.min((innerWidth - 44) / 2, 340)); } catch {}
    });
    box.querySelectorAll("[data-page]").forEach((b) => (b.onclick = () => {
      const card = box.querySelector(`#rank-${b.dataset.page}`);
      if (card) card.scrollIntoView({ behavior: "smooth", block: "center" });
      else toast(`${b.dataset.page}쪽은 아직 강조된 내용이 없어요`);
    }));
    const button = box.querySelector("#predict");
    if (button) button.onclick = async () => {
      try { await api("POST", `/documents/${docId}/exam-questions`); poll(); } catch (e) { toast(e.message); }
    };
  };

  const poll = async () => {
    while (alive) {
      let m;
      try { m = await api("GET", `/documents/${docId}/exam-map`); } catch (e) { box.innerHTML = `<p class="muted">${esc(e.message)}</p>`; return; }
      if (!alive) return;
      draw(m);
      if (m.job.status !== "building") return;
      await new Promise((r) => setTimeout(r, 2000));
    }
  };
  poll();
}

// ---------- 포스트잇 ----------

function noteHTML(a, number, { selected = false, preview = false, fresh = false, playable = false, beyond = false } = {}) {
  const t = TYPES[a.type] || TYPES.explanation;
  return `
    <div class="note-wrap${fresh ? " fresh" : ""}" data-note="${a.id}" style="--tape:${-tilt(a.id) * 1.5}deg">
      <button class="note${selected ? " sel" : ""}${preview ? " preview" : ""}"
        style="background:var(--${a.type});--ink-c:var(--${a.type}-ink);transform:rotate(${tilt(a.id)}deg);width:100%">
        <div class="head" style="color:var(--${a.type}-ink)">${I(t.icon)} ${t.label}
          ${number ? `<span class="num" style="background:var(--${a.type}-ink)">${number}</span>` : ""}</div>
        <div class="text">${esc(a.text)}</div>
        ${preview ? `<div class="sub"><span class="spin"></span> AI가 정리 중…</div>` : ""}
        ${a.type === "tip" ? `<div class="sub">교수님 말씀이 아니라 AI가 덧붙인 내용이에요</div>` : ""}
        ${beyond ? `<div class="beyond">${I("chalkboard-teacher")} 슬라이드에 없는 설명</div>` : ""}
        ${a.edited_by_user ? `<div class="sub">${I("pencil-simple")} 직접 수정함</div>` : ""}
      </button>
      ${playable ? `<button class="play" data-play="${a.start_ms}" aria-label="이 필기 때 녹음 듣기">${I("play")} ${clock(a.start_ms)}</button>` : ""}
    </div>`;
}

function clock(ms) {
  const s = Math.max(0, Math.floor(ms / 1000));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  return `${h ? `${h}:${String(m).padStart(2, "0")}` : m}:${String(sec).padStart(2, "0")}`;
}

// ---------- 강의 화면 ----------

async function renderLecture(docId, sessionId) {
  const state = {
    doc: null, pdf: null, page: 1, notes: [], previews: [], tasks: [],
    selected: null, fresh: null, freshTimer: null, recording: false, ended: !!sessionId,
    sessionId, ws: null, recognizer: null, startedAt: 0, timer: null, autoFollow: true,
    lastManual: 0, estimate: null, wakeLock: null, pageWidth: 0, seen: new Set(), hasAudio: false, player: null,
    // 자막 모드: 지금 설명하는 문단 표시, 최근 문장 크게, 시험·공지·과제 때 강하게 알림
    a11y: prefs.get("a11y") === "1", spoken: null, lines: [],
    beyond: new Set(), beyondRatio: null, terms: [],
  };

  $app.innerHTML = `
    <div class="screen lecture" id="lecture">
      <div class="topbar"><button class="icon-btn" id="back">${I("caret-left")}</button><div class="title" id="title"></div><button class="icon-btn glossary-btn" id="glossary" title="용어 사전">${I("book-open-text")}<span class="count hidden" id="gcount"></span></button><button class="icon-btn" id="a11y" title="자막 모드 (크게 보기·중요할 때 진동)" aria-pressed="false">${I("closed-captioning")}</button><button class="icon-btn" id="notespdf" title="강의 정리 PDF">${I("file-pdf")}</button><button class="icon-btn" id="sum" title="공부하기 (요약·퀴즈·플래시카드·마인드맵·개념 메모·암기·AI 튜터)">${I("sparkle")}</button></div>
      <div class="pager"><div class="page" id="page"><canvas></canvas><div class="marks"></div></div></div>
      <div class="board-head">
        <h2 id="bh"></h2><span class="count" id="bc"></span><span class="spacer"></span>
        <button class="chip hidden" id="taskchip" style="color:var(--record);background:color-mix(in srgb,var(--record) 12%,transparent)"></button>
        <button class="chip hidden" id="pendchip" style="color:var(--emphasis-ink);background:color-mix(in srgb,var(--emphasis-ink) 14%,transparent)"></button>
        <button class="chip hidden" id="follow" style="color:var(--accent);background:color-mix(in srgb,var(--accent) 12%,transparent)"></button>
      </div>
      <div class="board" id="board"></div>
      <div class="dock">
        <button class="ask hidden" id="ask">${I("hand-waving")} 방금 뭐라고?</button>
        <div class="caption hidden" id="caption"><span class="dot"></span><span id="captext">듣고 있어요…</span></div>
        <div class="bar">
          <div class="pages"><button id="prev">‹</button><span id="pno"></span><button id="next">›</button></div>
          <div id="main"></div>
          <div class="status" id="status">00:00</div>
        </div>
      </div>
    </div>`;
  const $ = (sel) => $app.querySelector(sel);
  $("#back").onclick = () => {
    if (state.recording && !confirm("녹음을 멈추고 나갈까요?")) return;
    location.hash = `#/doc/${docId}`;
  };

  try {
    state.doc = await api("GET", `/documents/${docId}`);
    state.notebook = state.doc.kind === "notebook";
    if (!state.notebook) state.pdf = await loadPdf(docId);
    if (sessionId) {
      state.notes = await api("GET", `/sessions/${sessionId}/annotations`);
      state.tasks = await api("GET", `/sessions/${sessionId}/tasks`);
      state.notes.forEach((n) => state.seen.add(n.id));
      checkAudio();
      checkBeyond();
      state.terms = await api("GET", `/sessions/${sessionId}/glossary`).catch(() => []);
    }
  } catch (e) {
    toast(`불러오지 못했어요: ${e.message}`);
    return;
  }
  $("#title").textContent = state.doc.title;
  if (state.notebook) $("#lecture").classList.add("notebook");

  const pageInfo = () => state.doc.pages[state.page - 1];
  const visible = () => [...state.notes, ...state.previews].filter((n) => n.page_no === state.page && !n.pending);

  // --- 페이지와 필기 표시 ---

  async function drawPage() {
    if (state.notebook) return drawNotebook();
    const width = $("#page").clientWidth;
    state.pageWidth = width;
    await renderPage(state.pdf, state.page, $("#page canvas"), width);
    drawMarks();
  }

  // 노트 모드: 디지털 필기 노트처럼 — 색 머리띠(제목·날짜), 모눈 종이, 주제마다 "1. 제목" 아래로 AI가 한 줄씩 써 내려간다.
  // 주제(쪽)들을 한 장에 이어 쓰고, 지금 설명 중인 주제로 스크롤한다
  const NOTE_COLORS = ["#d9d1ff", "#c7ebff", "#c2f0cc", "#fff1a8", "#ffd6a8", "#ffc9d4", "#f4d8ff", "#d6e7c8", "#e8e2d6", "#dfe3ea"];

  function noteLine(n) {
    // "개념: 설명" 꼴이면 개념을 색 글씨로, 둘째 문장부터는 → 로 내려 쓴다
    const parts = n.text.split(/(?<=[.?!])\s+|\n/).filter(Boolean);
    const first = esc(parts[0] || n.text).replace(/^([^:：]{2,18})[:：]\s*/, `<b class="kw">$1</b> `);
    const sub = parts.slice(1).map((p) => `<span class="nb-sub">→ ${esc(p)}</span>`).join("");
    const mark = { explanation: "-", example: "예)", emphasis: "!", exam: "★", notice: "공지)", tip: "(+)", qa: "Q." }[n.type] || "-";
    return `<div class="nb-line t-${n.type}${n.id === state.selected ? " sel" : ""}${n.id < 0 ? " preview" : ""}${n.id === state.fresh ? " fresh" : ""}" data-flag="${n.id}" role="button" tabindex="0">
      <span class="nb-mark">${mark}</span>
      <span class="nb-text"><span class="nb-main">${first}</span>${sub}${state.beyond.has(n.id) ? ` <small class="nb-beyond">교수님만 말함</small>` : ""}</span>
      ${state.hasAudio && !state.recording && n.id > 0 ? `<button class="nb-play" data-play="${n.start_ms}" aria-label="이 필기 때 녹음 듣기">${I("play")}</button>` : ""}
    </div>`;
  }

  function drawNotebook() {
    const box = $("#page");
    box.classList.add("notebook-page");
    const color = prefs.get(`nbcolor.${docId}`) || NOTE_COLORS[0];
    box.style.setProperty("--nb", color);
    const all = [...state.notes, ...state.previews].filter((n) => !n.pending);
    const date = new Date(state.startedAt || Date.now());
    const sections = state.doc.pages.map((page) => {
      const notes = all.filter((n) => n.page_no === page.page_no);
      const now = page.page_no === state.page;
      const title = page.text ? esc(page.text) : `<span class="muted">${state.recording && now ? "주제를 듣는 중…" : "제목 없음"}</span>`;
      return `<section class="nb-sec${now ? " now" : ""}" data-sec="${page.page_no}">
        <h3><span class="nb-no">${page.page_no}.</span> <span class="nb-title">${title}</span></h3>
        ${notes.length ? notes.map(noteLine).join("") : `<p class="nb-line muted">${state.recording && now ? "교수님 설명을 듣고 있어요. 필기가 여기에 써져요." : "아직 필기가 없어요"}</p>`}
      </section>`;
    }).join("");
    box.innerHTML = `<header class="nb-head">
        <span class="nb-label">title</span><b class="nb-doc">${esc(state.doc.title)}</b>
        <span class="nb-date">${String(date.getFullYear()).slice(2)}. ${String(date.getMonth() + 1).padStart(2, "0")}. ${String(date.getDate()).padStart(2, "0")}</span>
        <span class="nb-colors">${NOTE_COLORS.map((c) => `<button class="nb-color${c === color ? " on" : ""}" data-color="${c}" style="background:${c}" aria-label="노트 색"></button>`).join("")}</span>
      </header><div class="nb-body">${sections}</div>`;
    box.querySelectorAll("[data-color]").forEach((b) => (b.onclick = (e) => { e.stopPropagation(); prefs.set(`nbcolor.${docId}`, b.dataset.color); drawNotebook(); }));
    box.querySelectorAll("[data-flag]").forEach((el) => (el.onclick = () => select(state.selected === Number(el.dataset.flag) ? null : Number(el.dataset.flag))));
    box.querySelectorAll("[data-play]").forEach((b) => (b.onclick = (e) => { e.stopPropagation(); playFrom(Number(b.dataset.play)); }));
    const target = box.querySelector(".nb-line.fresh") || (state.notebookScrolled !== state.page && box.querySelector(".nb-sec.now"));
    if (target) { target.scrollIntoView({ block: "nearest", behavior: "smooth" }); state.notebookScrolled = state.page; }
  }

  function drawMarks() {
    if (state.notebook) return drawNotebook();
    const marks = $("#page .marks");
    const page = pageInfo();
    const notes = visible();
    const blocks = Object.fromEntries(page.blocks.map((b) => [b.id, b]));
    let html = "";
    // 형광펜: 필기가 붙은 문단
    for (const block of page.blocks) {
      const last = [...notes].reverse().find((n) => n.block_id === block.id);
      if (!last) continue;
      const strong = notes.some((n) => n.block_id === block.id && n.id === state.selected);
      html += `<div class="hl" style="left:calc(${block.x * 100}% - 4px);top:${(block.y + block.h * 0.1) * 100}%;width:calc(${block.w * 100}% + 8px);height:${block.h * 90}%;background:var(--${last.type}-ink);opacity:${strong ? 0.36 : 0.22}"></div>`;
    }
    // 자막 모드: 교수님이 지금 설명하는 문단
    const here = state.a11y && state.spoken && state.spoken.page === state.page && blocks[state.spoken.block_id];
    if (here) {
      html += `<div class="here" style="left:calc(${here.x * 100}% - 6px);top:calc(${here.y * 100}% - 4px);width:calc(${here.w * 100}% + 12px);height:calc(${here.h * 100}% + 8px)"><span>지금 여기</span></div>`;
    }
    // 깃발: 번호는 아래 포스트잇과 같다
    let loose = 0;
    notes.forEach((n, i) => {
      const block = blocks[n.block_id];
      let x, y;
      if (block) {
        const before = notes.slice(0, i).filter((m) => m.block_id === n.block_id).length;
        x = `min(calc(${Math.min(block.x + block.w, 1) * 100}% + ${20 + before * 30}px), calc(100% - 18px))`;
        y = `max(${(block.y + block.h / 2) * 100}%, 16px)`;
      } else {
        x = `min(${26 + loose++ * 34}px, calc(100% - 20px))`;
        y = "calc(100% - 18px)";
      }
      html += `<button class="flag${n.id === state.selected ? " sel" : ""}${n.id < 0 ? " preview" : ""}" data-flag="${n.id}"
        style="left:${x};top:${y};background:var(--${n.type});--ink-c:var(--${n.type}-ink);rotate:${tilt(n.id) * 2}deg">${i + 1}</button>`;
    });
    // 자료 위에 펼친 포스트잇: 방금 들어온 필기, 또는 고른 필기
    const spot = notes.find((n) => n.id === (state.selected ?? state.fresh));
    if (spot) {
      const block = blocks[spot.block_id];
      const left = block ? `clamp(8px, ${block.x * 100}%, calc(38% - 8px))` : "4%";
      const below = block && block.y + block.h < 0.62;
      const pos = below ? `top:calc(${(block.y + block.h) * 100}% + 6px)` : `bottom:calc(${block ? (1 - block.y) * 100 : 8}% + 6px)`;
      const t = TYPES[spot.type] || TYPES.explanation;
      html += `<div class="callout" data-callout style="left:${left};${pos};background:var(--${spot.type});rotate:${tilt(spot.id) * 0.5}deg">
        <span class="kind" style="color:var(--${spot.type}-ink)">${I(t.icon)} ${t.label}</span>${esc(spot.text)}</div>`;
    }
    marks.innerHTML = html;
    marks.querySelectorAll("[data-flag]").forEach((el) => (el.onclick = () => select(Number(el.dataset.flag))));
    const callout = marks.querySelector("[data-callout]");
    if (callout) callout.onclick = () => select(null);
  }

  function drawBoard() {
    if (state.notebook) drawNotebook();
    const notes = visible();
    $("#bh").textContent = `${state.page}쪽 필기`;
    $("#bc").textContent = notes.length;
    $("#pno").textContent = `${state.page}/${state.doc.pages.length}`;
    const board = $("#board");
    board.innerHTML = notes.length
      ? notes.map((n, i) => noteHTML(n, i + 1, { selected: n.id === state.selected, preview: n.id < 0, fresh: !state.seen.has(n.id),
          playable: state.hasAudio && !state.recording && n.id > 0 && n.start_ms != null,
          beyond: state.beyond.has(n.id) })).join("")
      : `<div class="empty-note">${state.recording ? "교수님 설명을 듣고 있어요.<br>필기가 여기에 붙어요." : "이 페이지에는 아직 필기가 없어요"}</div>`;
    notes.forEach((n) => state.seen.add(n.id));
    board.querySelectorAll("[data-note]").forEach((el) => {
      const id = Number(el.dataset.note);
      el.onclick = () => select(state.selected === id ? null : id);
      if (id > 0) el.oncontextmenu = (e) => { e.preventDefault(); editNote(id); };
    });
    board.querySelectorAll("[data-play]").forEach((b) => (b.onclick = (e) => { e.stopPropagation(); playFrom(Number(b.dataset.play)); }));
    const pending = state.notes.filter((n) => n.pending);
    $("#pendchip").classList.toggle("hidden", !pending.length);
    $("#pendchip").innerHTML = `${I("tray-arrow-down")} 보류 ${pending.length}`;
    const open = state.tasks.filter((t) => !t.done);
    $("#taskchip").classList.toggle("hidden", !state.tasks.length);
    $("#taskchip").innerHTML = `${I("clipboard-text")} 과제 ${open.length}`;
    $("#follow").classList.toggle("hidden", !state.recording);
    const elsewhere = state.estimate && state.estimate !== state.page;
    $("#follow").innerHTML = state.autoFollow ? `${I("magic-wand")} 자동 넘김` : elsewhere ? `${I("hand-palm")} 지금 ${state.estimate}쪽 설명 중` : `${I("hand-palm")} 직접 넘김`;
  }

  function redraw() { drawMarks(); drawBoard(); }

  function select(id) {
    state.selected = id;
    redraw();
    if (id !== null) {
      const el = $(`#board [data-note="${id}"]`);
      if (el) el.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }

  async function goTo(page, { manual = true } = {}) {
    if (page < 1 || page > state.doc.pages.length || page === state.page) return;
    state.page = page;
    state.selected = null;
    if (manual) {
      state.lastManual = Date.now();
      send({ type: "page_view", page }); // 신호 A: 직접 넘긴 페이지
    }
    await drawPage();
    drawBoard();
  }

  $("#prev").onclick = () => goTo(state.page - 1);
  $("#next").onclick = () => goTo(state.page + 1);
  // 페이지 위에서 좌우로 밀어 넘기기
  let touchX = null;
  $("#page").addEventListener("touchstart", (e) => (touchX = e.touches[0].clientX), { passive: true });
  $("#page").addEventListener("touchend", (e) => {
    if (touchX === null) return;
    const dx = e.changedTouches[0].clientX - touchX;
    touchX = null;
    if (Math.abs(dx) > 50) goTo(state.page + (dx < 0 ? 1 : -1));
  });
  $("#follow").onclick = () => { state.autoFollow = !state.autoFollow; drawBoard(); };
  $("#pendchip").onclick = () => openPending();
  $("#taskchip").onclick = () => openTasks();
  $("#sum").onclick = () => state.sessionId ? openSummary() : toast("강의를 녹음하고 끝내면 요약과 퀴즈가 만들어져요");
  $("#ask").onclick = openAsk;
  $("#glossary").onclick = () => openGlossary();
  $("#a11y").onclick = () => { setA11y(!state.a11y); toast(state.a11y ? "자막 모드: 지금 설명하는 곳을 표시하고, 시험·공지·과제 때 진동으로 알려요" : "자막 모드를 껐어요"); };
  $("#notespdf").onclick = () => state.sessionId ? openNotesPdf() : toast("강의를 녹음하면 필기를 붙인 정리 PDF를 만들 수 있어요");

  const onResize = () => { if (Math.abs($("#page").clientWidth - state.pageWidth) > 4) drawPage(); };
  window.addEventListener("resize", onResize);

  // --- 실시간 연결 ---

  // --- 마이크 소리를 서버로 (서버가 Whisper로 받아쓴다) ---

  const audioBacklog = []; // 연결이 끊긴 동안의 소리 (최대 60초)
  function sendAudio(buffer) {
    if (state.ws && state.ws.readyState === WebSocket.OPEN) {
      while (audioBacklog.length) state.ws.send(audioBacklog.shift());
      state.ws.send(buffer);
    } else {
      audioBacklog.push(buffer);
      if (audioBacklog.length > 240) audioBacklog.shift();
    }
  }

  async function startMicrophone() {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    const ctx = new Ctx();
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    await ctx.resume();
    const source = ctx.createMediaStreamSource(stream);
    // AudioWorklet보다 오래된 방식이지만 iPhone Safari에서 가장 안정적이다
    const proc = ctx.createScriptProcessor(4096, 1, 1);
    const ratio = ctx.sampleRate / 16000;
    proc.onaudioprocess = (e) => {
      if (!state.recording) return;
      const input = e.inputBuffer.getChannelData(0);
      const out = new Int16Array(Math.floor(input.length / ratio));
      let peak = 0;
      for (let i = 0; i < out.length; i++) {
        const from = Math.floor(i * ratio), to = Math.floor((i + 1) * ratio);
        let sum = 0;
        for (let j = from; j < to; j++) sum += input[j];
        const v = Math.max(-1, Math.min(1, sum / (to - from)));
        peak = Math.max(peak, Math.abs(v));
        out[i] = v * 0x7fff;
      }
      state.level = peak;
      sendAudio(out.buffer);
    };
    source.connect(proc);
    proc.connect(ctx.destination);
    state.mic = { ctx, stream, proc, source };
  }

  function stopMicrophone() {
    if (!state.mic) return;
    state.mic.proc.disconnect();
    state.mic.source.disconnect();
    state.mic.stream.getTracks().forEach((t) => t.stop());
    state.mic.ctx.close().catch(() => {});
    state.mic = null;
  }

  const outbox = [];
  function send(message) {
    if (!state.recording) return;
    const text = JSON.stringify(message);
    if (state.ws && state.ws.readyState === WebSocket.OPEN) state.ws.send(text);
    else outbox.push(text);
  }

  function connect() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/sessions/${state.sessionId}/stream`);
    state.ws = ws;
    ws.onopen = () => {
      // 서버는 연결마다 상태를 새로 만들므로 보던 페이지부터 알린다
      ws.send(JSON.stringify({ type: "page_view", page: state.page, initial: true }));
      while (outbox.length) ws.send(outbox.shift());
    };
    ws.onmessage = (e) => handle(JSON.parse(e.data));
    ws.onclose = () => { if (state.recording) setTimeout(connect, 1500); };
  }

  let previewSeq = -1;
  const previewIds = new Map();

  function handle(event) {
    if (event.type === "annotation_preview") {
      const id = previewSeq--;
      previewIds.set(event.preview.id, id);
      state.previews.push({ ...event.preview, id });
      flash(id);
    } else if (event.type === "previews_resolved") {
      const ids = new Set(event.ids.map((k) => previewIds.get(k)));
      state.previews = state.previews.filter((p) => !ids.has(p.id));
      redraw();
    } else if (event.type === "annotation_added") {
      if (state.notes.some((n) => n.id === event.annotation.id)) return;
      state.notes.push(event.annotation);
      if (navigator.vibrate) navigator.vibrate(15);
      flash(event.annotation.id);
      if (event.annotation.type === "exam") alertImportant("star", "시험에 나온다고 했어요", event.annotation.text);
      else if (event.annotation.type === "notice") alertImportant("megaphone", "공지", event.annotation.text);
    } else if (event.type === "term") {
      // 실시간 용어 사전: 처음 나온 전문용어를 카드로 띄우고 서랍에 쌓는다
      if (state.terms.some((t) => t.id === event.term.id)) return;
      state.terms.push(event.term);
      drawGlossaryCount();
      showTermCard(event.term);
    } else if (event.type === "page_added") {
      // 노트 모드: 교수님이 주제를 바꿔 새 쪽이 생겼다
      state.doc.pages.push(event.page);
      if (state.autoFollow) goTo(event.page.page_no, { manual: false }); else drawBoard();
    } else if (event.type === "page_title") {
      const page = state.doc.pages[event.page - 1];
      if (page) page.text = event.title;
      if (event.page === state.page) drawPage();
    } else if (event.type === "page_estimate") {
      state.estimate = event.page;
      const canFollow = state.autoFollow && Date.now() - state.lastManual > MANUAL_PAUSE_MS;
      if (canFollow && event.confidence >= FOLLOW_CONFIDENCE && event.page !== state.page) goTo(event.page, { manual: false });
      else drawBoard();
    } else if (event.type === "task_added") {
      state.tasks.push(event.task);
      drawBoard();
      showTaskBanner(event.task);
      // 과제는 위쪽 배너가 이미 크게 뜨므로 자막 모드에서는 진동만 더한다
      if (state.a11y && navigator.vibrate) navigator.vibrate([220, 120, 220, 120, 220]);
    } else if (event.type === "heard") {
      // Whisper가 받아쓴 문장을 자막으로 보여 준다
      if (!state.a11y) $("#captext").textContent = event.text;
    } else if (event.type === "spoken") {
      state.spoken = event;
      state.lines = [...state.lines, event.text].slice(-3);
      if (state.a11y) { drawCaptionLines(); drawMarks(); }
    } else if (event.type === "error") {
      toast(event.message);
    }
  }

  // 새 필기는 5초 동안 자료 위에 펼쳐 두었다가 깃발로 접는다
  function flash(id) {
    state.fresh = id;
    clearTimeout(state.freshTimer);
    state.freshTimer = setTimeout(() => { state.fresh = null; drawMarks(); }, 5000);
    redraw();
    const el = $(`#board [data-note="${id}"]`);
    if (el) el.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  // --- 녹음과 받아쓰기 (브라우저 음성 인식) ---

  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;

  function startRecognizer() {
    const rec = new Recognition();
    rec.lang = "ko-KR";
    rec.continuous = true;
    rec.interimResults = true;
    let segmentStart = null;
    rec.onresult = (e) => {
      let interim = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const result = e.results[i];
        const text = result[0].transcript.trim();
        if (segmentStart === null) segmentStart = Date.now() - state.startedAt;
        if (result.isFinal) {
          if (text) send({ type: "transcript_final", text, start_ms: segmentStart, end_ms: Date.now() - state.startedAt });
          segmentStart = null;
        } else {
          interim += text;
        }
      }
      if (!state.a11y || !state.lines.length) $("#captext").textContent = interim || "듣고 있어요…";
    };
    rec.onerror = (e) => {
      if (e.error === "not-allowed" || e.error === "service-not-allowed") {
        toast("마이크·음성 인식 권한을 허용해 주세요");
        stopLecture(false);
      }
    };
    // 브라우저는 말이 끊기면 인식을 멈추므로, 녹음 중에는 바로 다시 시작한다
    rec.onend = () => { if (state.recording) try { rec.start(); } catch {} };
    rec.start();
    state.recognizer = rec;
  }

  async function startLecture() {
    // 마이크는 버튼을 누른 바로 그 순간에 켜야 iPhone Safari가 허락한다 (서버 응답을 기다리기 전에)
    const mic = startMicrophone();
    try {
      const session = await api("POST", "/sessions", { document_id: docId });
      state.sessionId = session.id;
      store.addSession(docId, session.id);
      history.replaceState(null, "", `#/lecture/${docId}/${session.id}`);
    } catch (e) {
      return toast(e.message);
    }
    state.recording = true;
    state.startedAt = Date.now();
    connect();
    try {
      await mic;
      state.engine = "whisper";
    } catch (e) {
      // 마이크 소리를 직접 못 받는 브라우저: 내장 음성 인식으로 대신한다
      if (!Recognition) {
        toast("마이크를 쓸 수 없어요. 브라우저 설정에서 마이크 권한을 허용해 주세요.");
        return stopLecture(false);
      }
      state.engine = "browser";
      startRecognizer();
    }
    // 수업 중 화면이 꺼지면 받아쓰기가 멈추므로 화면을 켜 둔다
    try { state.wakeLock = await navigator.wakeLock?.request("screen"); } catch {}
    state.timer = setInterval(() => ($("#status .t") || {}).textContent = fmtTime((Date.now() - state.startedAt) / 1000), 500);
    drawControls();
    drawBoard();
  }

  async function stopLecture(finish = true) {
    state.recording = false;
    try { state.recognizer?.stop(); } catch {}
    stopMicrophone();
    clearInterval(state.timer);
    try { state.wakeLock?.release(); } catch {}
    if (finish && state.ws) {
      $("#main").innerHTML = `<span class="spin" style="width:28px;height:28px;color:var(--accent)"></span>`;
      // 마지막 받아쓰기의 필기를 받을 시간을 준다
      state.ws.send(JSON.stringify({ type: "flush" }));
      await new Promise((r) => setTimeout(r, 6000));
      try { await api("POST", `/sessions/${state.sessionId}/end`); } catch (e) { toast(e.message); }
      state.ended = true;
      checkAudio();
      checkBeyond();
      if (state.notebook) {
        // 마지막 주제의 제목은 연결이 끊긴 뒤에 붙으므로 잠시 뒤 다시 받아 온다
        setTimeout(async () => {
          try { state.doc = await api("GET", `/documents/${docId}`); drawNotebook(); } catch {}
        }, 4000);
      }
    }
    state.ws?.close();
    drawControls();
    drawBoard();
  }

  function drawControls() {
    $("#caption").classList.toggle("hidden", !state.recording);
    $("#ask").classList.toggle("hidden", !state.sessionId);
    $("#status").classList.toggle("on", state.recording);
    $("#status").innerHTML = state.recording
      ? `<span class="wave">${[0.45, 0.8, 1, 0.7, 0.5].map((h, i) => `<i style="height:${h * 22}px;animation-delay:${i * 0.12}s"></i>`).join("")}</span><span class="t">00:00</span>`
      : "";
    if (state.recording) $("#main").innerHTML = `<button class="rec on" id="rec" aria-label="강의 끝내기"><span class="stop"></span></button>`;
    else if (state.ended) $("#main").innerHTML = `<button class="primary" id="rec" style="height:48px">${I("graduation-cap")} 공부하기</button>`;
    else $("#main").innerHTML = `<button class="rec" id="rec" aria-label="녹음 시작">${I("microphone")}</button>`;
    $("#rec").onclick = () => (state.recording ? stopLecture() : state.ended ? openSummary() : startLecture());
  }

  // --- 실시간 용어 사전 ---

  function drawGlossaryCount() {
    const badge = $("#gcount");
    badge.textContent = state.terms.length;
    badge.classList.toggle("hidden", !state.terms.length);
  }

  function showTermCard(term) {
    const stack = document.querySelector(".term-stack") || document.body.appendChild(Object.assign(document.createElement("div"), { className: "term-stack" }));
    const card = document.createElement("button");
    card.className = "term-card";
    card.innerHTML = `<b>${I("book-open-text")} ${esc(term.term)}</b><span>${esc(term.definition)}</span>`;
    card.onclick = () => { card.remove(); openGlossary(term.id); };
    stack.prepend(card);
    [...stack.children].slice(2).forEach((c) => c.remove());
    setTimeout(() => card.classList.add("out"), 7000);
    setTimeout(() => card.remove(), 7400);
  }

  function openGlossary(focusId) {
    const { el } = sheet(`<h3>${I("book-open-text")} 용어 사전 <small class="muted">${state.terms.length}개</small></h3>
      <input class="search" id="gq" placeholder="용어 찾기" autocomplete="off"><div id="glist"></div>`);
    const draw = (q = "") => {
      const shown = state.terms.filter((t) => !q || `${t.term} ${t.definition}`.toLowerCase().includes(q.toLowerCase()));
      el.querySelector("#glist").innerHTML = shown.length ? shown.map((t) => `<div class="card concept${t.id === focusId ? " focus" : ""}" id="term-${t.id}">
          <div class="row"><b style="flex:1">${esc(t.term)}</b>${t.page_no ? `<button class="chip pagechip" data-goto="${t.page_no}">${t.page_no}쪽</button>` : ""}<small class="muted">${clock(t.start_ms)}</small></div>
          <p>${esc(t.definition)}</p></div>`).join("")
        : `<p class="muted">${state.terms.length ? "찾는 용어가 없어요." : "강의 중에 전문용어가 나오면 여기에 모여요."}</p>`;
      el.querySelectorAll("[data-goto]").forEach((b) => (b.onclick = () => { document.querySelector(".sheet-bg").click(); goTo(Number(b.dataset.goto)); }));
    };
    el.querySelector("#gq").oninput = (e) => draw(e.target.value.trim());
    draw();
    el.querySelector(`#term-${focusId}`)?.scrollIntoView({ block: "center" });
  }

  // --- 자막 모드 (청각장애 학생·시끄러운 강의실) ---

  function setA11y(on) {
    state.a11y = on;
    prefs.set("a11y", on ? "1" : "0");
    $(".lecture").classList.toggle("a11y", on);
    $("#a11y").setAttribute("aria-pressed", String(on));
    if (on) drawCaptionLines();
    redraw();
  }

  function drawCaptionLines() {
    if (!state.lines.length) return;
    $("#captext").innerHTML = state.lines.map((l, i) =>
      `<span class="line${i === state.lines.length - 1 ? " now" : ""}">${esc(l)}</span>`).join("");
  }

  function alertImportant(icon, title, text) {
    // 자막 모드에서는 소리를 못 들어도 알 수 있게 강하게 진동하고 화면 위에 크게 띄운다
    if (!state.a11y) return;
    if (navigator.vibrate) navigator.vibrate([220, 120, 220, 120, 220]);
    document.querySelector(".alert")?.remove();
    const el = document.createElement("div");
    el.className = "alert";
    el.setAttribute("role", "alert");
    el.innerHTML = `${I(icon)}<span><b>${esc(title)}</b><br>${esc(text)}</span>`;
    el.onclick = () => el.remove();
    document.body.append(el);
    setTimeout(() => el.remove(), 6000);
  }

  // --- 필기를 누르면 그 순간의 녹음 듣기 ---

  async function checkBeyond() {
    // 강의가 끝난 뒤: 슬라이드에 없는 설명을 담은 필기에 표시를 붙인다
    try {
      const res = await api("GET", `/sessions/${state.sessionId}/beyond-slides`);
      state.beyond = new Set(res.annotation_ids);
      state.beyondRatio = res.ratio;
    } catch {}
    drawBoard();
  }

  async function checkAudio() {
    // 녹음이 서버에 있는지 앞 1바이트만 받아 본다
    try {
      const res = await fetch(`/sessions/${state.sessionId}/audio`, { headers: { Range: "bytes=0-0" } });
      state.hasAudio = res.ok;
    } catch { state.hasAudio = false; }
    drawBoard();
  }

  function playFrom(ms) {
    if (!state.player) {
      const audio = new Audio(`/sessions/${state.sessionId}/audio`);
      const bar = document.createElement("div");
      bar.className = "player";
      bar.innerHTML = `<button id="pp">${I("pause")}</button><span class="pt">0:00</span>
        <input type="range" min="0" max="100" value="0" step="0.1" aria-label="재생 위치"><button id="px">${I("x")}</button>`;
      $(".dock").prepend(bar);
      const range = bar.querySelector("input");
      audio.ontimeupdate = () => {
        bar.querySelector(".pt").textContent = clock(audio.currentTime * 1000);
        if (audio.duration) range.value = (audio.currentTime / audio.duration) * 100;
      };
      audio.onplay = () => (bar.querySelector("#pp").innerHTML = I("pause"));
      audio.onpause = () => (bar.querySelector("#pp").innerHTML = I("play"));
      range.oninput = () => { if (audio.duration) audio.currentTime = (range.value / 100) * audio.duration; };
      bar.querySelector("#pp").onclick = () => (audio.paused ? audio.play() : audio.pause());
      bar.querySelector("#px").onclick = () => stopPlayer();
      state.player = { audio, bar };
    }
    // 필기는 설명이 끝날 즈음 붙으므로 조금 앞에서부터 들려준다
    const { audio } = state.player;
    const start = Math.max(0, ms / 1000 - 3);
    const go = () => { audio.currentTime = start; audio.play().catch(() => toast("재생하지 못했어요")); };
    if (audio.readyState >= 1) go(); else audio.addEventListener("loadedmetadata", go, { once: true });
  }

  function stopPlayer() {
    if (!state.player) return;
    state.player.audio.pause();
    state.player.bar.remove();
    state.player = null;
  }

  // --- "방금 뭐라고?": 수업 중 질문 → 지금 페이지의 관련 문단 옆에 질문 포스트잇 ---

  const QUICK_QUESTIONS = ["방금 뭐라고 했어?", "쉽게 다시 설명해 줘", "예시 하나만 들어 줘", "이거 시험에 어떻게 나올까?"];

  function openAsk() {
    const page = state.page;
    const { el, close } = sheet(`<h3>${I("hand-waving")} 방금 뭐라고?</h3>
      <p class="muted">최근 2분 동안의 설명과 ${page}쪽 자료를 보고 답해서, 관련 문단 옆에 붙여 줘요.</p>
      <div class="row" style="flex-wrap:wrap;margin-bottom:12px">${QUICK_QUESTIONS.map((q) =>
        `<button class="chip" data-q="${esc(q)}" style="color:var(--qa-ink);background:color-mix(in srgb,var(--qa-ink) 12%,transparent)">${esc(q)}</button>`).join("")}</div>
      <form id="askform" class="row"><input id="askq" placeholder="궁금한 걸 적어도 돼요" autocomplete="off" style="flex:1">
        <button class="primary" style="height:44px;padding:0 18px">묻기</button></form>
      <h3 style="margin-top:22px">${I("clock-counter-clockwise")} 딴생각했어요</h3>
      <div class="row" style="flex-wrap:wrap">${[1, 3, 5].map((m) =>
        `<button class="chip" data-catch="${m}" style="color:var(--accent);background:color-mix(in srgb,var(--accent) 12%,transparent)">최근 ${m}분 따라잡기</button>`).join("")}</div>`);
    const send = (question) => { close(); askQuestion(question, page); };
    el.querySelectorAll("[data-catch]").forEach((b) => (b.onclick = () => { close(); catchUp(Number(b.dataset.catch)); }));
    el.querySelectorAll("[data-q]").forEach((b) => (b.onclick = () => send(b.dataset.q)));
    el.querySelector("#askform").onsubmit = (e) => { e.preventDefault(); send(el.querySelector("#askq").value.trim()); };
  }

  async function catchUp(minutes) {
    const { el } = sheet(`<h3>${I("clock-counter-clockwise")} 최근 ${minutes}분 따라잡기</h3><div id="catchbox"><p class="muted"><span class="spin"></span> 놓친 설명을 정리하는 중…</p></div>`);
    const box = el.querySelector("#catchbox");
    let res;
    try { res = await api("POST", `/sessions/${state.sessionId}/catch-up`, { minutes }); } catch (e) { box.innerHTML = `<p class="muted">${esc(e.message)}</p>`; return; }
    if (!res.points.length) { box.innerHTML = `<p class="muted">그동안 받아쓴 설명이 없어요.</p>`; return; }
    box.innerHTML = `<p class="muted">${clock(res.from_ms)} ~ ${clock(res.to_ms)} 사이에 교수님이 한 설명이에요.</p>
      <div class="card" style="padding:14px 16px">${res.points.map((p) => {
        const important = p.startsWith("[중요]");
        return `<p class="catch${important ? " important" : ""}">${important ? I("warning") : I("dot-outline")} ${esc(p.replace(/^\[중요\]\s*/, ""))}</p>`;
      }).join("")}</div>
      <div class="row" style="flex-wrap:wrap;margin-top:12px">${res.pages.map((no) =>
        `<button class="chip" data-goto="${no}" style="color:var(--accent);background:color-mix(in srgb,var(--accent) 12%,transparent)">${no}쪽 보기</button>`).join("")}</div>`;
    box.querySelectorAll("[data-goto]").forEach((b) => (b.onclick = () => { document.querySelector(".sheet-bg").click(); goTo(Number(b.dataset.goto)); }));
  }

  async function askQuestion(question, page) {
    const button = $("#ask");
    button.disabled = true;
    button.innerHTML = `<span class="spin"></span> 답을 찾는 중…`;
    try {
      const note = await api("POST", `/sessions/${state.sessionId}/ask`, { question, page_no: page });
      state.notes.push(note);
      if (state.page !== note.page_no) await goTo(note.page_no);
      if (navigator.vibrate) navigator.vibrate(15);
      flash(note.id);
    } catch (e) { toast(e.message); }
    button.disabled = false;
    button.innerHTML = `${I("hand-waving")} 방금 뭐라고?`;
  }

  // --- 필기 수정·삭제 ---

  async function editNote(id) {
    const note = state.notes.find((n) => n.id === id);
    const text = prompt("필기 수정 (비우면 삭제)", note.text);
    if (text === null) return;
    try {
      if (!text.trim()) {
        await api("DELETE", `/annotations/${id}`);
        state.notes = state.notes.filter((n) => n.id !== id);
      } else {
        Object.assign(note, await api("PATCH", `/annotations/${id}`, { text }));
      }
      redraw();
    } catch (e) { toast(e.message); }
  }

  // --- 시트: 보류함 · 과제 · 요약 ---

  function sheet(html) {
    const bg = document.createElement("div");
    bg.className = "sheet-bg";
    const el = document.createElement("div");
    el.className = "sheet";
    el.innerHTML = `<div class="grab"></div>${html}`;
    const close = () => { bg.remove(); el.remove(); };
    bg.onclick = close;
    document.body.append(bg, el);
    return { el, close };
  }

  function openPending() {
    const pending = state.notes.filter((n) => n.pending);
    const { el, close } = sheet(`<h3>보류함</h3><p class="muted">AI가 어느 페이지 이야기인지 확신하지 못한 필기예요. 붙일 페이지를 골라 주세요.</p>
      ${pending.map((n) => `${noteHTML(n, 0)}<div class="row" style="flex-wrap:wrap;margin:10px 0 22px">${state.doc.pages.map((p) =>
        `<button class="chip" data-place="${n.id}:${p.page_no}" style="color:var(--accent);background:color-mix(in srgb,var(--accent) 10%,transparent)">${p.page_no}쪽에 붙이기</button>`).join("")}</div>`).join("")}`);
    el.querySelectorAll("[data-place]").forEach((b) => (b.onclick = async () => {
      const [id, page] = b.dataset.place.split(":").map(Number);
      try {
        const placed = await api("PATCH", `/annotations/${id}`, { page_no: page });
        state.notes = state.notes.map((n) => (n.id === id ? placed : n));
        close();
        await goTo(page);
        flash(id);
      } catch (e) { toast(e.message); }
    }));
  }

  function showTaskBanner(task) {
    document.querySelector(".banner")?.remove();
    const k = TASK_KINDS[task.kind] || TASK_KINDS.homework;
    const el = document.createElement("div");
    el.className = "banner";
    el.innerHTML = `<span class="task-ic" style="color:${k.color}">${I(k.icon)}</span>
      <span style="flex:1;min-width:0"><small style="color:${k.color};font-weight:900">새 ${k.label}${task.due_text ? ` · ${esc(task.due_text)}` : ""}</small>
      <b style="display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(task.title)}</b></span>
      <button class="chip" style="color:#fff;background:${k.color}">바로 하기</button><button class="muted">${I("x")}</button>`;
    el.querySelector(".chip").onclick = () => { el.remove(); openTask(task.id); };
    el.querySelector("button.muted").onclick = () => el.remove();
    document.body.append(el);
    setTimeout(() => el.remove(), 8000);
  }

  function openTasks() {
    const { el, close } = sheet(`<h3>이번 강의 과제</h3>${state.tasks.map((t) => {
      const k = TASK_KINDS[t.kind] || TASK_KINDS.homework;
      return `<button class="card item" data-task="${t.id}"><span class="task-ic" style="color:${t.done ? "#2fb35a" : k.color}">${I(t.done ? "check-circle" : k.icon)}</span>
        <span style="flex:1"><b style="${t.done ? "text-decoration:line-through" : ""}">${esc(t.title)}</b><br>
        <small class="muted">${k.label}${t.due_text ? ` · ${esc(t.due_text)}` : ""}</small></span>${t.draft ? I("sparkle") : ""}<span class="muted">${I("caret-right")}</span></button>`;
    }).join("")}`);
    el.querySelectorAll("[data-task]").forEach((b) => (b.onclick = () => { close(); openTask(Number(b.dataset.task)); }));
  }

  function openTask(taskId) {
    const task = state.tasks.find((t) => t.id === taskId);
    const k = TASK_KINDS[task.kind] || TASK_KINDS.homework;
    const { el } = sheet(`
      <div class="card" style="padding:16px;margin-top:6px">
        <small style="color:${k.color};font-weight:900">${I(k.icon)} ${k.label}${task.due_text ? ` · ${I("clock")} ${esc(task.due_text)}` : ""}</small>
        <h3 style="margin:6px 0">${esc(task.title)}</h3><p class="muted" style="margin:0 0 10px">${esc(task.instructions)}</p>
        <button class="chip" id="done" style="color:${task.done ? "#2fb35a" : "var(--ink-2)"}">${task.done ? `${I("check-circle")} 완료함` : `${I("circle")} 완료 표시`}</button>
      </div>
      <div id="draftbox" style="margin-top:16px"></div>`);
    el.querySelector("#done").onclick = async () => {
      try {
        Object.assign(task, await api("PATCH", `/tasks/${task.id}`, { done: !task.done }));
        el.querySelector("#done").innerHTML = task.done ? `${I("check-circle")} 완료함` : `${I("circle")} 완료 표시`;
        drawBoard();
      } catch (e) { toast(e.message); }
    };
    const box = el.querySelector("#draftbox");
    const showDraft = () => {
      const d = task.draft;
      box.innerHTML = `
        <h3>${I("check-square")} 요구사항 체크리스트</h3><div class="card" style="padding:14px">${d.checklist.map((c) =>
          `<label class="row" style="padding:6px 0"><input type="checkbox"> <span>${esc(c)}</span></label>`).join("")}</div>
        <h3>${I("list-numbers")} 개요</h3><div class="card" style="padding:14px">${d.outline.map((o, i) =>
          `<div class="row" style="padding:5px 0;align-items:flex-start"><span class="badge" style="width:22px;height:22px;font-size:12px">${i + 1}</span><span>${esc(o)}</span></div>`).join("")}</div>
        <div class="row"><h3 style="flex:1">${I("note-pencil")} 초안 (바로 고쳐 쓰세요)</h3><button class="chip" id="copy" style="color:var(--accent)">복사</button></div>
        <textarea class="draft" id="draft">${esc(d.draft)}</textarea>
        <p style="font-size:13px;color:var(--accent);font-weight:800">근거: ${d.sources.map((s) => `${s}쪽`).join(", ")}</p>
        <p class="muted" style="font-size:12px">${I("shield-check")} AI가 만든 초안이에요. 수업마다 AI 사용 규칙이 다르니 확인하고, 본인 말로 고쳐서 제출하세요.</p>`;
      box.querySelector("#copy").onclick = async () => {
        try { await navigator.clipboard.writeText(box.querySelector("#draft").value); toast("복사했어요"); } catch { toast("복사하지 못했어요"); }
      };
    };
    if (task.draft) return showDraft();
    box.innerHTML = `<button class="primary" id="make" style="width:100%;height:56px;border-radius:18px">${I("sparkle")} AI와 바로 하기</button>`;
    box.querySelector("#make").onclick = async (e) => {
      e.target.disabled = true;
      e.target.innerHTML = `<span class="spin"></span> 오늘 강의 내용으로 만드는 중…`;
      try {
        Object.assign(task, await api("POST", `/tasks/${task.id}/draft`));
        showDraft();
        drawBoard();
      } catch (err) {
        toast(err.message);
        e.target.disabled = false;
        e.target.innerHTML = `${I("sparkle")} AI와 바로 하기`;
      }
    };
  }

  // 강의 정리 PDF: 필기가 붙은 슬라이드 + 페이지별 전체 정리 + 교수님 설명 + 과제.
  // 누를 때마다 지금까지의 필기로 새로 만든다 (바뀌지 않은 페이지는 서버가 전에 만든 정리를 다시 쓴다)
  async function openNotesPdf() {
    const { el } = sheet(`<h3>강의 정리 PDF</h3><p class="muted">필기가 붙은 슬라이드와 페이지마다 교수님 설명을 빠짐없이 정리한 노트, 과제를 PDF 한 권으로 만들어요.</p><div id="pdfbox"></div>`);
    const box = el.querySelector("#pdfbox");
    const url = `/sessions/${state.sessionId}/notes-pdf`;
    let res;
    try { res = await api("POST", url); } catch (e) { box.innerHTML = `<p class="muted">${esc(e.message)}</p>`; return; }
    while (res.status === "building" && document.body.contains(el)) {
      const pct = res.total ? ` (${res.done}/${res.total}쪽)` : "";
      box.innerHTML = `<p class="muted"><span class="spin"></span> AI가 페이지별로 정리하는 중${pct}…</p>`;
      await new Promise((r) => setTimeout(r, 2000));
      try { res = await api("GET", `${url}/status`); } catch (e) { box.innerHTML = `<p class="muted">${esc(e.message)}</p>`; return; }
    }
    if (res.status === "failed") { box.innerHTML = `<p class="muted">PDF를 만들지 못했어요. 잠시 뒤 다시 눌러 주세요.</p>`; return; }
    box.innerHTML = `<a class="primary" href="${url}?t=${Date.now()}" target="_blank" rel="noopener" style="display:flex;align-items:center;justify-content:center;height:48px;text-decoration:none">${I("file-text")} 정리 PDF 열기</a>
      <p class="muted" style="margin-top:10px"><small>열린 PDF에서 공유 버튼을 누르면 파일·굿노트 등에 저장할 수 있어요.</small></p>`;
  }

  // --- 공부하기: 요약·퀴즈 · 플래시카드 · 마인드맵 · 개념 메모 · 암기 · AI 튜터 ---

  const STUDY_TABS = [
    ["summary", "sparkle", "요약·퀴즈"], ["flashcards", "cards", "플래시카드"], ["mindmap", "tree-structure", "마인드맵"],
    ["concepts", "book-open-text", "개념 메모"], ["cloze", "brain", "암기"], ["tutor", "chats-circle", "AI 튜터"],
  ];

  function openSummary(tab = "summary") {
    const { el } = sheet(`<h3>공부하기</h3>
      <div class="tabs">${STUDY_TABS.map(([k, icon, label]) => `<button class="tab" data-tab="${k}">${I(icon)} ${label}</button>`).join("")}</div>
      <div id="sumbox"></div>`);
    const box = el.querySelector("#sumbox");
    const show = (k) => {
      el.querySelectorAll("[data-tab]").forEach((b) => b.classList.toggle("on", b.dataset.tab === k));
      box.innerHTML = "";
      ({ summary: showSummary, flashcards: showFlashcards, mindmap: showMindmap, concepts: showConcepts,
         cloze: showCloze, tutor: showTutor })[k](box, el);
    };
    el.querySelectorAll("[data-tab]").forEach((b) => (b.onclick = () => show(b.dataset.tab)));
    show(tab);
  }

  async function showSummary(box, el) {
    box.innerHTML = `<p class="muted"><span class="spin"></span> 필기를 모아 요약과 퀴즈를 만드는 중…</p>`;
    for (let tries = 0; tries < 200 && document.body.contains(el) && box.isConnected; tries++) {
      let res;
      try { res = await api("GET", `/sessions/${state.sessionId}/summary`); } catch (e) { box.innerHTML = `<p class="muted">${esc(e.message)}</p>`; return; }
      if (!box.isConnected || !box.querySelector(".spin")) return;
      if (res.summary) return drawSummary(box, res.summary);
      if (res.status === "failed") { box.innerHTML = `<p class="muted">요약을 만들지 못했어요.</p>`; return; }
      if (res.status === "recording") { box.innerHTML = `<p class="muted">강의를 끝내면 요약이 만들어져요.</p>`; return; }
      await new Promise((r) => setTimeout(r, 3000));
    }
  }

  // AI로 만드는 공부 도구: 없으면 만들기 버튼, 만드는 중이면 진행률, 다 되면 그린다
  async function loadStudy(kind, box, draw, label) {
    const url = `/sessions/${state.sessionId}/study/${kind}`;
    const token = Symbol();
    box.dataset.kind = kind;
    box._token = token;
    const alive = () => box.isConnected && box._token === token;
    let res;
    try { res = await api("GET", url); } catch (e) { box.innerHTML = `<p class="muted">${esc(e.message)}</p>`; return; }
    while (alive()) {
      if (res.status === "ready") {
        draw(res.body);
        if (res.stale) box.insertAdjacentHTML("afterbegin", `<button class="chip remake" style="color:var(--accent)">${I("sparkle")} 새 필기로 다시 만들기</button>`);
        const remake = box.querySelector(".remake");
        if (remake) remake.onclick = async () => { await api("POST", url); loadStudy(kind, box, draw, label); };
        return;
      }
      if (res.status === "none") {
        box.innerHTML = `<button class="primary" id="make" style="width:100%;height:52px">${I("sparkle")} ${label} 만들기</button>`;
        box.querySelector("#make").onclick = async () => {
          try { res = await api("POST", url); } catch (e) { toast(e.message); return; }
          loadStudy(kind, box, draw, label);
        };
        return;
      }
      box.innerHTML = `<p class="muted"><span class="spin"></span> AI가 ${label} 만드는 중…${res.total ? ` (${res.done}/${res.total}쪽)` : ""}</p>`;
      await new Promise((r) => setTimeout(r, 1500));
      try { res = await api("GET", url); } catch { return; }
    }
  }

  function gotoChip(no) {
    return no ? `<button class="chip pagechip" data-goto="${no}">${no}쪽</button>` : "";
  }

  function bindGoto(box) {
    box.querySelectorAll("[data-goto]").forEach((b) => (b.onclick = () => { document.querySelector(".sheet-bg")?.click(); goTo(Number(b.dataset.goto)); }));
  }

  function showFlashcards(box) {
    loadStudy("flashcards", box, (cards) => {
      if (!cards.length) { box.innerHTML = `<p class="muted">만들 카드가 없었어요.</p>`; return; }
      const key = `fc.${state.sessionId}`;
      const known = new Set(JSON.parse(prefs.get(key) || "[]"));
      let onlyUnknown = false, i = 0, flipped = false;
      const deck = () => cards.map((c, n) => ({ ...c, n })).filter((c) => !onlyUnknown || !known.has(c.n));
      const draw = () => {
        const list = deck();
        if (!list.length) { box.innerHTML = `<div class="done-card">${I("check-circle")}<b>다 외웠어요!</b><button class="chip" id="reset">처음부터</button></div>`;
          box.querySelector("#reset").onclick = () => { known.clear(); prefs.set(key, "[]"); onlyUnknown = false; i = 0; draw(); }; return; }
        i = (i + list.length) % list.length;
        const c = list[i];
        box.innerHTML = `<div class="row" style="justify-content:space-between;margin-bottom:10px">
            <small class="muted">${i + 1} / ${list.length} · 알아요 ${known.size}</small>
            <button class="chip" id="only" style="color:var(--accent)">${onlyUnknown ? "전체 보기" : "모르는 것만"}</button></div>
          <button class="flash${flipped ? " flipped" : ""}" id="card"><span class="face front">${esc(c.front)}<small>눌러서 뒤집기</small></span>
            <span class="face back">${esc(c.back)}</span></button>
          <div class="row" style="margin-top:14px;gap:10px">${gotoChip(c.page_no)}<span style="flex:1"></span>
            <button class="chip" id="no" style="color:var(--exam-ink)">${I("x")} 몰라요</button>
            <button class="chip" id="yes" style="color:#2fb35a">${I("check-circle")} 알아요</button></div>`;
        box.querySelector("#card").onclick = () => { flipped = !flipped; box.querySelector("#card").classList.toggle("flipped", flipped); };
        box.querySelector("#only").onclick = () => { onlyUnknown = !onlyUnknown; i = 0; flipped = false; draw(); };
        box.querySelector("#no").onclick = () => { known.delete(c.n); prefs.set(key, JSON.stringify([...known])); i++; flipped = false; draw(); };
        box.querySelector("#yes").onclick = () => { known.add(c.n); prefs.set(key, JSON.stringify([...known])); if (!onlyUnknown) i++; flipped = false; draw(); };
        bindGoto(box);
      };
      draw();
    }, "플래시카드");
  }

  function showMindmap(box) {
    loadStudy("mindmap", box, (map) => {
      const node = (n, depth) => `<li><button class="mm-node d${depth}" ${n.page_no ? `data-goto="${n.page_no}"` : ""}>${esc(n.label)}${n.page_no ? ` <small>${n.page_no}쪽</small>` : ""}</button>
        ${n.children?.length ? `<ul>${n.children.map((c) => node(c, depth + 1)).join("")}</ul>` : ""}</li>`;
      box.innerHTML = `<p class="muted" style="margin-top:0">가지를 누르면 그 쪽으로 가요. 옆으로 밀어서 볼 수 있어요.</p><div class="mindmap"><ul>${node(map, 0)}</ul></div>`;
      bindGoto(box);
    }, "마인드맵");
  }

  function showConcepts(box) {
    loadStudy("concepts", box, (generated) => {
      // 수업 중에 실시간으로 모은 용어 + 강의 뒤 AI가 정리한 개념
      const seen = new Set(generated.map((c) => c.term.toLowerCase()));
      const items = [...state.terms.filter((t) => !seen.has(t.term.toLowerCase()))
        .map((t) => ({ term: t.term, definition: t.definition, example: "", page_no: t.page_no })), ...generated];
      box.innerHTML = `<input id="csearch" class="search" placeholder="개념 찾기" autocomplete="off"><div id="clist"></div>`;
      const draw = (q = "") => {
        const shown = items.filter((c) => !q || `${c.term} ${c.definition} ${c.example}`.includes(q));
        box.querySelector("#clist").innerHTML = shown.map((c) => `<div class="card concept">
            <div class="row"><b style="flex:1">${esc(c.term)}</b>${gotoChip(c.page_no)}</div>
            <p>${esc(c.definition)}</p>${c.example ? `<p class="muted">${I("lightbulb")} ${esc(c.example)}</p>` : ""}</div>`).join("")
          || `<p class="muted">찾는 개념이 없어요.</p>`;
        bindGoto(box);
      };
      box.querySelector("#csearch").oninput = (e) => draw(e.target.value.trim());
      draw();
    }, "개념 메모");
  }

  async function showCloze(box) {
    let res;
    try { res = await api("GET", `/sessions/${state.sessionId}/study/cloze`); } catch (e) { box.innerHTML = `<p class="muted">${esc(e.message)}</p>`; return; }
    const items = res.body;
    if (!items.length) { box.innerHTML = `<p class="muted">빈칸으로 낼 용어가 있는 필기가 아직 없어요.</p>`; return; }
    const key = `cz.${state.sessionId}`;
    const done = new Set(JSON.parse(prefs.get(key) || "[]"));
    box.innerHTML = `<p class="muted" style="margin-top:0">빈칸을 눌러 답을 확인하고, 외운 문장은 체크하세요. 시험·강조 필기가 먼저 나와요.</p>
      ${items.map((c, n) => `<div class="card cloze${done.has(n) ? " done" : ""}" data-n="${n}">
        <p>${c.important ? `<span class="imp">${I("star")}</span>` : ""}${esc(c.text).replace("____", `<button class="blank" data-a="${esc(c.answer)}">____</button>`)}</p>
        <div class="row">${gotoChip(c.page_no)}<span style="flex:1"></span><button class="chip memo">${I(done.has(n) ? "check-circle" : "circle")} 외웠어요</button></div></div>`).join("")}`;
    box.querySelectorAll(".blank").forEach((b) => (b.onclick = () => { b.textContent = b.dataset.a; b.classList.add("shown"); }));
    box.querySelectorAll(".cloze").forEach((card) => (card.querySelector(".memo").onclick = () => {
      const n = Number(card.dataset.n);
      done.has(n) ? done.delete(n) : done.add(n);
      prefs.set(key, JSON.stringify([...done]));
      card.classList.toggle("done", done.has(n));
      card.querySelector(".memo").innerHTML = `${I(done.has(n) ? "check-circle" : "circle")} 외웠어요`;
    }));
    bindGoto(box);
  }

  function showTutor(box) {
    const key = `tutor.${state.sessionId}`;
    const messages = JSON.parse(prefs.get(key) || "[]");
    const quick = ["이 강의 핵심 3가지 설명해 줘", "나한테 문제 하나 내 줘", "제일 헷갈리는 개념 쉽게 설명해 줘"];
    box.innerHTML = `<div class="chat" id="chat"></div>
      <div class="row" style="flex-wrap:wrap;margin:10px 0">${quick.map((q) => `<button class="chip" data-q="${esc(q)}" style="color:var(--accent)">${esc(q)}</button>`).join("")}</div>
      <form id="tform" class="row"><input id="tq" class="search" placeholder="강의 내용으로 무엇이든 물어보세요" autocomplete="off" style="flex:1;margin:0">
        <button class="primary" style="height:44px;padding:0 18px">보내기</button></form>`;
    const chat = box.querySelector("#chat");
    const draw = () => {
      chat.innerHTML = messages.length ? messages.map((m) => `<div class="bubble ${m.role}">${esc(m.content)}
        ${m.pages?.length ? `<div class="row" style="flex-wrap:wrap;margin-top:6px">${m.pages.map(gotoChip).join("")}</div>` : ""}</div>`).join("")
        : `<p class="muted">${I("chats-circle")} 이 강의의 슬라이드와 교수님 설명을 아는 튜터예요. 모르는 걸 묻거나 문제를 내 달라고 해 보세요.</p>`;
      chat.scrollTop = chat.scrollHeight;
      bindGoto(box);
    };
    const send = async (text) => {
      if (!text) return;
      messages.push({ role: "user", content: text });
      draw();
      chat.insertAdjacentHTML("beforeend", `<div class="bubble assistant pending"><span class="spin"></span> 생각하는 중…</div>`);
      chat.scrollTop = chat.scrollHeight;
      try {
        const res = await api("POST", `/sessions/${state.sessionId}/tutor`, { messages: messages.map(({ role, content }) => ({ role, content })) });
        messages.push({ role: "assistant", content: res.answer, pages: res.pages });
      } catch (e) { messages.pop(); toast(e.message); }
      prefs.set(key, JSON.stringify(messages.slice(-30)));
      draw();
    };
    box.querySelectorAll("[data-q]").forEach((b) => (b.onclick = () => send(b.dataset.q)));
    box.querySelector("#tform").onsubmit = (e) => { e.preventDefault(); const q = box.querySelector("#tq"); send(q.value.trim()); q.value = ""; };
    draw();
  }

  function drawSummary(box, s) {
    box.innerHTML = `
      <div class="overview"><small>${I("sparkle")} 한눈에 보는 강의</small>${esc(s.overview)}</div>
      ${state.beyondRatio ? `<div class="stat">${I("chalkboard-teacher")}<span><b>${Math.round(state.beyondRatio * 100)}%</b> 오늘 교수님 설명 중 슬라이드에 없던 내용<br><small class="muted">"슬라이드에 없는 설명" 표시가 붙은 필기를 꼭 챙겨 보세요</small></span></div>` : ""}
      <button class="card item" id="topdf"><span class="badge">${I("file-pdf")}</span><span style="flex:1"><b>강의 정리 PDF 만들기</b><br><small class="muted">필기 붙은 슬라이드 + 요약이 아닌 전체 정리</small></span></button>
      <h3>페이지별 요약</h3>${s.pages.map((p) => `<button class="card item" data-goto="${p.page_no}"><span class="badge">${p.page_no}</span><span style="flex:1">${esc(p.summary)}</span></button>`).join("")}
      ${s.tips?.length ? `<h3>더 알아보기</h3>${s.tips.map((t) => `<a class="card item" href="${esc(t.url)}" target="_blank" rel="noopener" style="text-decoration:none;color:inherit"><span class="badge">${I("compass")}</span><span><b>${esc(t.title)}</b><br><small class="muted">${esc(t.text)}</small></span></a>`).join("")}` : ""}
      <div class="row"><h3 style="flex:1">복습 퀴즈</h3><span class="chip" id="score" style="color:#2fb35a;background:color-mix(in srgb,#2fb35a 12%,transparent)">0 / ${s.quiz.length}</span></div>
      ${s.quiz.map((q, i) => `<div class="card" style="padding:16px;margin-bottom:12px" data-q="${i}"><b><span style="color:var(--accent)">Q${i + 1}</span> ${esc(q.question)}</b>
        ${q.choices.map((c, j) => `<button class="choice" data-c="${j}">○ ${esc(c)}</button>`).join("")}<div class="explain"></div></div>`).join("")}`;
    box.querySelectorAll("[data-goto]").forEach((b) => (b.onclick = () => { document.querySelector(".sheet-bg").click(); goTo(Number(b.dataset.goto)); }));
    box.querySelector("#topdf").onclick = () => { document.querySelector(".sheet-bg").click(); openNotesPdf(); };
    let correct = 0;
    box.querySelectorAll("[data-q]").forEach((card) => {
      const q = s.quiz[Number(card.dataset.q)];
      card.querySelectorAll("[data-c]").forEach((b) => (b.onclick = () => {
        if (card.dataset.done) return;
        card.dataset.done = "1";
        const pick = Number(b.dataset.c);
        card.querySelectorAll("[data-c]")[q.answer_index].classList.add("right");
        if (pick === q.answer_index) correct++;
        else { b.classList.add("wrong"); navigator.vibrate?.([30, 40, 30]); }
        box.querySelector("#score").textContent = `${correct} / ${s.quiz.length}`;
        card.querySelector(".explain").innerHTML = `<p style="font-weight:900;color:${pick === q.answer_index ? "#2fb35a" : "#e5484d"}">${pick === q.answer_index ? "정답이에요!" : `아쉬워요, 정답은 ${q.answer_index + 1}번`}</p><p class="muted">${esc(q.explanation)}</p>`;
      }));
    });
  }

  // 녹음 파일로 만든 강의는 서버가 정리하는 동안 진행률을 보여 주고, 필기를 계속 새로 받아 온다
  let pollTimer = null;
  async function pollProcessing() {
    let res;
    try { res = await api("GET", `/sessions/${state.sessionId}/summary`); } catch { return; }
    if (!["transcribing", "processing"].includes(res.status)) {
      document.querySelector(".banner.progress")?.remove();
      if (res.status === "failed") toast("녹음 파일을 정리하지 못했어요. 다른 파일로 다시 시도해 주세요.");
      if (pollTimer) {
        clearInterval(pollTimer);
        pollTimer = null;
        state.notes = await api("GET", `/sessions/${state.sessionId}/annotations`);
        state.tasks = await api("GET", `/sessions/${state.sessionId}/tasks`);
        redraw();
        toast("정리가 끝났어요! 위쪽 요약 버튼으로 요약·퀴즈를 볼 수 있어요");
      }
      return;
    }
    let banner = document.querySelector(".banner.progress");
    if (!banner) {
      banner = document.createElement("div");
      banner.className = "banner progress";
      document.body.append(banner);
    }
    const pct = res.progress != null ? ` ${Math.round(res.progress * 100)}%` : "";
    banner.innerHTML = `<span class="spin" style="color:var(--accent)"></span><span style="flex:1"><b>${res.status === "transcribing" ? `녹음 받아쓰는 중${pct}` : "필기·요약 만드는 중"}</b><br>
      <small class="muted">끝나면 필기가 자료 위에 붙어요. 다른 화면에 다녀와도 돼요.</small></span>`;
    const notes = await api("GET", `/sessions/${state.sessionId}/annotations`);
    if (notes.length !== state.notes.length) { state.notes = notes; redraw(); }
    if (!pollTimer) pollTimer = setInterval(pollProcessing, 4000);
  }

  // 화면이 꺼졌다 켜지거나 다른 앱에 다녀오면 받아쓰기와 연결을 다시 잇는다
  let hiddenAt = null;
  function onVisibility() {
    if (!state.recording) return;
    if (document.hidden) { hiddenAt = Date.now(); return; }
    const away = hiddenAt ? (Date.now() - hiddenAt) / 1000 : 0;
    hiddenAt = null;
    // 멈춘 인식기만 다시 켠다 (이미 돌고 있으면 start()가 예외를 내고 그대로 둔다)
    try { state.recognizer?.start(); } catch {}
    if (state.mic) {
      state.mic.ctx.resume().catch(() => {});
      // iPhone은 화면이 꺼지면 마이크를 끊는다: 끊겼으면 다시 연다
      if (state.mic.stream.getAudioTracks().every((t) => t.readyState === "ended")) {
        stopMicrophone();
        startMicrophone().catch(() => toast("마이크가 꺼졌어요. 녹음 버튼을 다시 눌러 주세요."));
      }
    }
    if (!state.ws || state.ws.readyState > WebSocket.OPEN) connect();
    navigator.wakeLock?.request("screen").then((l) => (state.wakeLock = l)).catch(() => {});
    if (away > 5) toast(`화면이 꺼져 있던 ${fmtTime(away)} 동안은 받아쓰지 못했어요. 그 부분은 '음성 메모' 녹음 파일로 채울 수 있어요.`);
  }
  document.addEventListener("visibilitychange", onVisibility);

  await drawPage();
  drawControls();
  drawBoard();
  if (state.a11y) setA11y(true);
  drawGlossaryCount();
  if (sessionId) pollProcessing();

  current = () => {
    stopPlayer();
    clearInterval(pollTimer);
    document.removeEventListener("visibilitychange", onVisibility);
    if (state.recording) stopLecture(false);
    window.removeEventListener("resize", onResize);
    document.querySelectorAll(".sheet, .sheet-bg, .banner, .alert, .term-stack").forEach((n) => n.remove());
  };
}

route();
