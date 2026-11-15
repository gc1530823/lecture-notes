// 녹음 오프라인 저장 (브라우저): 수업 중 마이크 소리를 서버로 보내는 것과 함께, 폰 안(IndexedDB)에도 전부 모아 둔다.
// 강의가 끝나면 서버가 받은 길이와 견줘, 연결이 끊겨 빠진 곳이 있으면 전체 녹음을 올려 처음부터 다시 정리하게 한다.
// 그때 인터넷이 없으면 남겨 두었다가, 다음에 앱을 열거나 인터넷이 돌아오면 올린다. 빠진 곳이 없으면 지운다.

const DB = "lune-rec";
const API = import.meta.env.VITE_API_URL ?? "";
const RATE = 16000;
const GAP_MS = 5000;          // 이보다 많이 빠졌으면 전체 녹음을 올린다
const KEEP_DAYS = 7;          // 올리지 못한 녹음을 이만큼 남겨 둔다

interface Meta { sid: string; samples: number; done: boolean; at: number }

function open(): Promise<IDBDatabase> {
  return new Promise((ok, fail) => {
    const req = indexedDB.open(DB, 1);
    req.onupgradeneeded = () => {
      const db = req.result;
      const chunks = db.createObjectStore("chunks", { autoIncrement: true });
      chunks.createIndex("sid", "sid");
      db.createObjectStore("meta", { keyPath: "sid" });
    };
    req.onsuccess = () => ok(req.result);
    req.onerror = () => fail(req.error);
  });
}

function done<T>(req: IDBRequest<T>): Promise<T> {
  return new Promise((ok, fail) => { req.onsuccess = () => ok(req.result); req.onerror = () => fail(req.error); });
}

/** 한 강의의 녹음을 폰에 모은다. 5초씩 묶어 저장 (너무 잦은 저장을 피하려고) */
export class LocalRecording {
  private buf: Int16Array[] = [];
  private bufSamples = 0;
  private samples = 0;
  private db: Promise<IDBDatabase | null>;
  private sid: string;
  constructor(sid: string) {
    this.sid = sid;
    this.db = open().catch(() => null);   // 저장소를 못 쓰면(사생활 보호 창 등) 조용히 건너뛴다
  }

  append(pcm: ArrayBuffer) {
    const part = new Int16Array(pcm.slice(0));
    this.buf.push(part);
    this.bufSamples += part.length;
    this.samples += part.length;
    if (this.bufSamples >= RATE * 5) void this.flush(false);
  }

  private async flush(final: boolean) {
    const db = await this.db;
    if (!db) return;
    const parts = this.buf;
    this.buf = []; this.bufSamples = 0;
    const tx = db.transaction(["chunks", "meta"], "readwrite");
    if (parts.length) tx.objectStore("chunks").add({ sid: this.sid, data: new Blob(parts as BlobPart[]) });
    tx.objectStore("meta").put({ sid: this.sid, samples: this.samples, done: final, at: Date.now() } satisfies Meta);
    await new Promise((ok) => { tx.oncomplete = ok; tx.onerror = ok; tx.onabort = ok; });
  }

  /** 강의를 끝낼 때: 남은 소리를 저장하고 '다 녹음함'으로 표시 */
  async finish() {
    await this.flush(true);
  }
}

function wavHeader(samples: number): ArrayBuffer {
  const h = new DataView(new ArrayBuffer(44));
  const text = (o: number, s: string) => { for (let i = 0; i < s.length; i++) h.setUint8(o + i, s.charCodeAt(i)); };
  text(0, "RIFF"); h.setUint32(4, 36 + samples * 2, true); text(8, "WAVE");
  text(12, "fmt "); h.setUint32(16, 16, true); h.setUint16(20, 1, true); h.setUint16(22, 1, true);
  h.setUint32(24, RATE, true); h.setUint32(28, RATE * 2, true); h.setUint16(32, 2, true); h.setUint16(34, 16, true);
  text(36, "data"); h.setUint32(40, samples * 2, true);
  return h.buffer;
}

async function forget(db: IDBDatabase, sid: string) {
  const tx = db.transaction(["chunks", "meta"], "readwrite");
  const keys = await done(tx.objectStore("chunks").index("sid").getAllKeys(sid));
  for (const k of keys) tx.objectStore("chunks").delete(k);
  tx.objectStore("meta").delete(sid);
  await new Promise((ok) => { tx.oncomplete = ok; tx.onerror = ok; });
}

let syncing = false;

/** 다 녹음한 강의마다: 서버가 다 받았으면 지우고, 빠진 곳이 있으면 전체 녹음을 올린다. 올린 강의 수를 돌려준다 */
export async function syncRecordings(): Promise<number> {
  if (syncing || typeof indexedDB === "undefined") return 0;
  syncing = true;
  let uploaded = 0;
  try {
    const db = await open();
    const metas = await done(db.transaction("meta").objectStore("meta").getAll()) as Meta[];
    for (const m of metas) {
      if (!m.done) {
        // 녹음 중 앱이 꺼져 '끝'을 못 찍은 것도 하루가 지나면 끝난 것으로 본다
        if (Date.now() - m.at < 86400000) continue;
      }
      if (Date.now() - m.at > KEEP_DAYS * 86400000) { await forget(db, m.sid); continue; }
      let have: number;
      try {
        const r = await fetch(`${API}/sessions/${m.sid}/received`);
        if (r.status === 404) { await forget(db, m.sid); continue; }   // 지운 강의
        if (!r.ok) continue;
        have = (await r.json()).ms;
      } catch { continue; }   // 아직 인터넷이 없다 → 다음에
      const mine = (m.samples * 1000) / RATE;
      if (mine - have <= GAP_MS) { await forget(db, m.sid); continue; }
      const rows = await done(db.transaction("chunks").objectStore("chunks").index("sid").getAll(m.sid)) as { data: Blob }[];
      const file = new Blob([wavHeader(m.samples), ...rows.map((r) => r.data)], { type: "audio/wav" });
      const form = new FormData();
      form.append("file", file, `${m.sid}.wav`);
      try {
        const r = await fetch(`${API}/sessions/${m.sid}/full-audio`, { method: "POST", body: form });
        if (r.ok) { await forget(db, m.sid); uploaded++; }
      } catch { /* 다음에 */ }
    }
  } catch { /* 저장소를 못 씀 */ } finally {
    syncing = false;
  }
  return uploaded;
}

/** 앱이 켜질 때와 인터넷이 돌아올 때 올리지 못한 녹음을 올린다 */
export function watchPendingRecordings() {
  const run = () => { void syncRecordings().then((n) => { if (n) window.dispatchEvent(new CustomEvent("ln-recording-synced", { detail: n })); }); };
  window.addEventListener("online", run);
  window.setTimeout(run, 3000);
}
