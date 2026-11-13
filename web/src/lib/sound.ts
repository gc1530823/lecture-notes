// 효과음: 파일 없이 Web Audio로 그 자리에서 만든다 (가볍고, 앱 분위기에 맞게 짧고 통통한 소리).
// - 녹음 중에는 소리를 내지 않는다 (마이크에 섞여 받아쓰기를 망친다) → 진동으로 대신
// - 설정에서 끌 수 있고(기기에 기억), 기기의 "동작 줄이기"와는 따로다
// - 소리는 사용자가 한 번이라도 누른 뒤에만 난다 (브라우저 규칙)

type Name = "tap" | "pop" | "success" | "wrong" | "flip" | "turn" | "alert" | "note" | "start" | "stop" | "levelup" | "complete";

let ctx: AudioContext | null = null;
let recording = false;
const KEY = "ln.sound";

export function soundOn(): boolean { try { return localStorage.getItem(KEY) !== "0"; } catch { return true; } }
export function setSoundOn(on: boolean) { try { localStorage.setItem(KEY, on ? "1" : "0"); } catch { /* 괜찮다 */ } if (on) play("pop"); }
/** 녹음이 켜져 있는 동안은 소리 대신 진동 */
export function setRecording(on: boolean) { recording = on; }

function audio(): AudioContext | null {
  if (ctx) return ctx;
  const Ctx = window.AudioContext || (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  if (!Ctx) return null;
  ctx = new Ctx();
  return ctx;
}

/** 짧은 음 하나: 주파수, 시작(초), 길이(초), 크기, 파형, 끝 음(미끄러지기) */
function tone(a: AudioContext, freq: number, at: number, dur: number, vol = 0.18, type: OscillatorType = "sine", to?: number) {
  const t = a.currentTime + at;
  const osc = a.createOscillator();
  const gain = a.createGain();
  osc.type = type;
  osc.frequency.setValueAtTime(freq, t);
  if (to) osc.frequency.exponentialRampToValueAtTime(to, t + dur);
  gain.gain.setValueAtTime(0, t);
  gain.gain.linearRampToValueAtTime(vol, t + 0.008);
  gain.gain.exponentialRampToValueAtTime(0.0001, t + dur);
  osc.connect(gain).connect(a.destination);
  osc.start(t);
  osc.stop(t + dur + 0.02);
}

/** 바람 소리 (쪽 넘김): 걸러 낸 잡음 */
function whoosh(a: AudioContext, dur = 0.16, vol = 0.12) {
  const len = Math.floor(a.sampleRate * dur);
  const buf = a.createBuffer(1, len, a.sampleRate);
  const data = buf.getChannelData(0);
  for (let i = 0; i < len; i++) data[i] = (Math.random() * 2 - 1) * Math.sin((Math.PI * i) / len);
  const src = a.createBufferSource();
  src.buffer = buf;
  const filter = a.createBiquadFilter();
  filter.type = "bandpass";
  filter.frequency.setValueAtTime(900, a.currentTime);
  filter.frequency.exponentialRampToValueAtTime(2600, a.currentTime + dur);
  const gain = a.createGain();
  gain.gain.value = vol;
  src.connect(filter).connect(gain).connect(a.destination);
  src.start();
}

const BUZZ: Partial<Record<Name, number | number[]>> = { alert: [40, 60, 40], note: 12, success: 18, wrong: [30, 40, 30], levelup: [20, 40, 20, 40, 60] };

export function play(name: Name) {
  if (recording) { const v = BUZZ[name]; if (v) navigator.vibrate?.(v); return; }
  if (!soundOn()) return;
  const a = audio();
  if (!a) return;
  if (a.state === "suspended") void a.resume();
  switch (name) {
    case "tap": tone(a, 660, 0, 0.06, 0.07, "triangle"); break;
    case "pop": tone(a, 520, 0, 0.09, 0.14, "sine", 900); break;
    case "flip": tone(a, 440, 0, 0.08, 0.1, "triangle", 700); tone(a, 880, 0.06, 0.08, 0.08, "triangle"); break;
    case "turn": whoosh(a); break;
    case "note": tone(a, 1046, 0, 0.12, 0.08, "sine"); tone(a, 1568, 0.05, 0.14, 0.05, "sine"); break;
    case "success": tone(a, 784, 0, 0.12, 0.14, "triangle"); tone(a, 1175, 0.09, 0.22, 0.14, "triangle"); break;
    case "wrong": tone(a, 300, 0, 0.14, 0.12, "square", 220); tone(a, 220, 0.13, 0.18, 0.1, "square", 180); break;
    case "alert": tone(a, 1318, 0, 0.12, 0.13, "sine"); tone(a, 1318, 0.16, 0.18, 0.13, "sine"); break;
    case "start": tone(a, 523, 0, 0.1, 0.14, "sine"); tone(a, 784, 0.08, 0.16, 0.14, "sine"); break;
    case "stop": tone(a, 784, 0, 0.1, 0.14, "sine"); tone(a, 523, 0.08, 0.18, 0.14, "sine"); break;
    case "levelup": [523, 659, 784, 1046].forEach((f, i) => tone(a, f, i * 0.08, 0.2, 0.13, "triangle")); break;
    case "complete": [659, 784, 1046, 1318, 1568].forEach((f, i) => tone(a, f, i * 0.07, 0.26, 0.11, "triangle")); break;
  }
}

/** 누를 수 있는 것을 누르면 작게 톡 (화면 전체에 한 번만 건다) */
export function installTapSound() {
  document.addEventListener("pointerdown", (e) => {
    const el = (e.target as HTMLElement | null)?.closest("button, a.chip, .list-item");
    if (!el || (el as HTMLButtonElement).disabled) return;
    if (el.closest("[data-sound]")) return; // 자기 소리가 따로 있는 버튼
    play("tap");
  }, { passive: true });
}
