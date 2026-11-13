// 효과음: 파일 없이 Web Audio로 그 자리에서 만든다. 잔잔한 종소리 같은 사인파, 모두 같은 음계(펜타토닉)라 이어져도 어울린다.
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

/** 잔잔한 음 하나: 부드럽게 올라와 길게 사라지는 사인파 (+ 한 옥타브 위를 아주 작게 섞어 맑게). 실로폰·종 같은 느낌 */
function tone(a: AudioContext, freq: number, at: number, dur: number, vol = 0.05, to?: number) {
  const t = a.currentTime + at;
  const out = a.createGain();
  out.gain.setValueAtTime(0, t);
  out.gain.linearRampToValueAtTime(vol, t + 0.018);
  out.gain.exponentialRampToValueAtTime(0.0001, t + dur * 1.6);
  const lowpass = a.createBiquadFilter();
  lowpass.type = "lowpass";
  lowpass.frequency.value = 3200;
  out.connect(lowpass).connect(a.destination);
  for (const [mult, level] of [[1, 1], [2, 0.18]] as const) {
    const osc = a.createOscillator();
    const g = a.createGain();
    g.gain.value = level;
    osc.type = "sine";
    osc.frequency.setValueAtTime(freq * mult, t);
    if (to) osc.frequency.exponentialRampToValueAtTime(to * mult, t + dur);
    osc.connect(g).connect(out);
    osc.start(t);
    osc.stop(t + dur * 1.6 + 0.05);
  }
}

/** 바람 소리 (쪽 넘김): 걸러 낸 잡음 */
function whoosh(a: AudioContext, dur = 0.16, vol = 0.04) {
  const len = Math.floor(a.sampleRate * dur);
  const buf = a.createBuffer(1, len, a.sampleRate);
  const data = buf.getChannelData(0);
  for (let i = 0; i < len; i++) data[i] = (Math.random() * 2 - 1) * Math.sin((Math.PI * i) / len);
  const src = a.createBufferSource();
  src.buffer = buf;
  const filter = a.createBiquadFilter();
  filter.type = "bandpass";
  filter.frequency.setValueAtTime(600, a.currentTime);
  filter.frequency.exponentialRampToValueAtTime(1600, a.currentTime + dur);
  filter.Q.value = 0.7;
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
  // 모두 C장조 펜타토닉(도·레·미·솔·라)으로 맞춰 어떤 소리가 이어져도 어울리게. 크기는 작게
  const C5 = 523.25, D5 = 587.33, E5 = 659.25, G5 = 783.99, A5 = 880, C6 = 1046.5, E6 = 1318.5, G4 = 392, A4 = 440;
  switch (name) {
    case "tap": tone(a, E6, 0, 0.05, 0.018); break;
    case "pop": tone(a, G5, 0, 0.12, 0.04); break;
    case "flip": tone(a, E5, 0, 0.1, 0.03); tone(a, A5, 0.06, 0.12, 0.025); break;
    case "turn": whoosh(a, 0.18, 0.04); break;
    case "note": tone(a, C6, 0, 0.22, 0.03); break;
    case "success": tone(a, E5, 0, 0.18, 0.045); tone(a, A5, 0.1, 0.32, 0.045); break;
    case "wrong": tone(a, D5, 0, 0.16, 0.035); tone(a, A4, 0.12, 0.28, 0.035); break;
    case "alert": tone(a, A5, 0, 0.2, 0.04); tone(a, E6, 0.14, 0.3, 0.035); break;
    case "start": tone(a, C5, 0, 0.18, 0.045); tone(a, G5, 0.1, 0.3, 0.045); break;
    case "stop": tone(a, G5, 0, 0.18, 0.045); tone(a, C5, 0.1, 0.32, 0.045); break;
    case "levelup": [C5, E5, G5, C6].forEach((f, i) => tone(a, f, i * 0.09, 0.3, 0.04)); break;
    case "complete": [G4, C5, E5, G5, C6].forEach((f, i) => tone(a, f, i * 0.08, 0.36, 0.035)); break;
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
