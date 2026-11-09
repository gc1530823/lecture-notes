// 실시간 강의 연결: 마이크 소리(16kHz 16비트 PCM)를 WebSocket으로 서버에 보내고, 서버가 보내는 필기·용어·쪽 추정 이벤트를 받는다.
// 기존 웹앱(server/app/static/app.js)과 같은 규약을 쓴다.
import type { Annotation, GlossaryTerm, Page } from "../api/types";

export interface Task { id: number; kind: string; title: string; due_text: string | null; instructions: string; done: boolean }

export type ServerEvent =
  | { type: "annotation_preview"; preview: Omit<Annotation, "id"> & { id: string } }
  | { type: "previews_resolved"; ids: string[] }
  | { type: "annotation_added"; annotation: Annotation }
  | { type: "term"; term: GlossaryTerm }
  | { type: "page_added"; page: Page }
  | { type: "page_title"; page: number; title: string }
  | { type: "page_estimate"; page: number; confidence: number }
  | { type: "task_added"; task: Task }
  | { type: "heard"; text: string }
  | { type: "spoken"; text: string; page: number; block_id: number | null }
  | { type: "error"; message: string };

/** 안드로이드 앱 안에서 열렸을 때 앱이 넣어 주는 기능 (android/…/MainActivity.kt 의 Bridge) */
interface AndroidBridge {
  start(wsUrl: string): void;
  send(text: string): void;
  stop(): void;
  isRecording(): boolean;
  saveFile(name: string, mime: string, text: string): void;
  print(title: string): void;
  changeServer(): void;
  keepScreenOn(on: boolean): void;
}

export function android(): AndroidBridge | null {
  return (window as unknown as { AndroidLive?: AndroidBridge }).AndroidLive ?? null;
}

export function streamUrl(sessionId: string): string {
  const base = import.meta.env.VITE_API_URL ? new URL(import.meta.env.VITE_API_URL) : window.location;
  const proto = base.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${base.host}/sessions/${sessionId}/stream`;
}

export interface Live {
  connect(): void;
  send(message: object): void;
  sendAudio(buffer: ArrayBuffer): void;
  close(): void;
  /** 이 연결이 마이크도 직접 맡는지 (안드로이드 앱: 화면이 꺼져도 녹음이 이어진다) */
  readonly nativeMic: boolean;
}

/** 안드로이드 앱: 녹음과 서버 연결을 앱의 서비스가 하고, 이벤트만 화면으로 받는다 */
export class NativeLive implements Live {
  readonly nativeMic = true;
  private bridge: AndroidBridge;
  private sessionId: string;

  constructor(bridge: AndroidBridge, sessionId: string, onEvent: (e: ServerEvent) => void) {
    this.bridge = bridge;
    this.sessionId = sessionId;
    (window as unknown as { __androidLiveEvent?: (t: string) => void }).__androidLiveEvent = (text: string) => {
      try { onEvent(JSON.parse(text)); } catch { /* 모르는 이벤트 */ }
    };
  }

  connect() { this.bridge.start(streamUrl(this.sessionId)); }
  send(message: object) { this.bridge.send(JSON.stringify(message)); }
  sendAudio() { /* 앱이 직접 녹음해 보낸다 */ }
  close() {
    this.bridge.stop();
    (window as unknown as { __androidLiveEvent?: unknown }).__androidLiveEvent = undefined;
  }
}

/** 끊기면 다시 잇고, 끊긴 동안의 소리(최대 약 60초)와 메시지는 모아 두었다가 보낸다 */
export class LiveSocket implements Live {
  readonly nativeMic = false;
  private ws: WebSocket | null = null;
  private closed = false;
  private audioBacklog: ArrayBuffer[] = [];
  private outbox: string[] = [];
  private sessionId: string;
  private onEvent: (e: ServerEvent) => void;
  private currentPage: () => number;

  constructor(sessionId: string, onEvent: (e: ServerEvent) => void, currentPage: () => number) {
    this.sessionId = sessionId;
    this.onEvent = onEvent;
    this.currentPage = currentPage;
  }

  connect() {
    const ws = new WebSocket(streamUrl(this.sessionId));
    this.ws = ws;
    ws.onopen = () => {
      // 서버는 연결마다 상태를 새로 만들므로 보던 쪽부터 알린다
      ws.send(JSON.stringify({ type: "page_view", page: this.currentPage(), initial: true }));
      while (this.outbox.length) ws.send(this.outbox.shift()!);
    };
    ws.onmessage = (e) => { try { this.onEvent(JSON.parse(e.data)); } catch { /* 모르는 이벤트는 넘긴다 */ } };
    ws.onclose = () => { if (!this.closed) setTimeout(() => this.connect(), 1500); };
  }

  private get open() { return this.ws?.readyState === WebSocket.OPEN; }

  send(message: object) {
    const text = JSON.stringify(message);
    if (this.open) this.ws!.send(text); else this.outbox.push(text);
  }

  sendAudio(buffer: ArrayBuffer) {
    if (this.open) {
      while (this.audioBacklog.length) this.ws!.send(this.audioBacklog.shift()!);
      this.ws!.send(buffer);
    } else {
      this.audioBacklog.push(buffer);
      if (this.audioBacklog.length > 240) this.audioBacklog.shift();
    }
  }

  close() { this.closed = true; this.ws?.close(); }
}

export interface Mic { stop(): void }

/** 마이크를 켜고 16kHz로 줄인 PCM 조각을 넘긴다. iPhone Safari에서 가장 안정적인 ScriptProcessor를 쓴다 */
export async function startMicrophone(onChunk: (pcm: ArrayBuffer, level: number) => void): Promise<Mic> {
  const Ctx = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
  const ctx = new Ctx();
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
  });
  await ctx.resume();
  const source = ctx.createMediaStreamSource(stream);
  const proc = ctx.createScriptProcessor(4096, 1, 1);
  const ratio = ctx.sampleRate / 16000;
  proc.onaudioprocess = (e) => {
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
    onChunk(out.buffer, peak);
  };
  source.connect(proc);
  proc.connect(ctx.destination);
  return {
    stop() {
      proc.disconnect();
      source.disconnect();
      stream.getTracks().forEach((t) => t.stop());
      ctx.close().catch(() => {});
    },
  };
}

interface Recognizer { stop(): void }
type SpeechCtor = new () => {
  lang: string; continuous: boolean; interimResults: boolean;
  onresult: (e: { resultIndex: number; results: ArrayLike<{ isFinal: boolean; 0: { transcript: string } }> }) => void;
  onerror: (e: { error: string }) => void; onend: () => void; start(): void; stop(): void;
};

/** 마이크 소리를 직접 못 받는 브라우저: 내장 음성 인식으로 받아쓴 문장을 보낸다 */
export function browserRecognizer(onFinal: (text: string, startMs: number, endMs: number) => void, onInterim: (text: string) => void,
  onDenied: () => void, startedAt: number): Recognizer | null {
  const w = window as unknown as { SpeechRecognition?: SpeechCtor; webkitSpeechRecognition?: SpeechCtor };
  const Ctor = w.SpeechRecognition ?? w.webkitSpeechRecognition;
  if (!Ctor) return null;
  const rec = new Ctor();
  let running = true;
  let segmentStart: number | null = null;
  rec.lang = "ko-KR";
  rec.continuous = true;
  rec.interimResults = true;
  rec.onresult = (e) => {
    let interim = "";
    for (let i = e.resultIndex; i < e.results.length; i++) {
      const r = e.results[i];
      const text = r[0].transcript.trim();
      segmentStart ??= Date.now() - startedAt;
      if (r.isFinal) {
        if (text) onFinal(text, segmentStart, Date.now() - startedAt);
        segmentStart = null;
      } else interim += text;
    }
    onInterim(interim);
  };
  rec.onerror = (e) => { if (e.error === "not-allowed" || e.error === "service-not-allowed") { running = false; onDenied(); } };
  // 말이 끊기면 브라우저가 인식을 멈추므로 바로 다시 시작한다
  rec.onend = () => { if (running) try { rec.start(); } catch { /* 이미 시작됨 */ } };
  rec.start();
  return { stop() { running = false; rec.stop(); } };
}
