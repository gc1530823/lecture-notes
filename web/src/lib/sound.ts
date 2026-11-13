// 효과음: 공부하는 자리에 맞게 아주 잔잔하게. 파일 없이 Web Audio로 그 자리에서 만든다.
// - 소리는 의미 있는 순간에만: 정답·오답, 복습 끝, 녹음 시작·끝, 시험 얘기가 나왔을 때. 버튼마다 나는 소리는 없다
// - 음색은 나무 마림바처럼 둥글고 짧게 (사인파 + 금방 사라지는 배음), 살짝 울림을 남긴다
// - 모든 소리가 같은 음계(C 펜타토닉)라 이어서 나도 어울린다. 크기는 작게
// - 녹음 중에는 소리를 내지 않고 진동만 (마이크에 섞여 받아쓰기를 망치지 않게)
// - 설정(더보기)에서 끌 수 있다. 소리는 사용자가 한 번이라도 누른 뒤에만 난다 (브라우저 규칙)

type Name = "tap" | "pop" | "success" | "wrong" | "flip" | "turn" | "alert" | "note" | "start" | "stop" | "levelup" | "complete";

let ctx: AudioContext | null = null;
let bus: GainNode | null = null;
let recording = false;
const KEY = "ln.sound";
const VOLUME = 0.6; // 전체 크기

export function soundOn(): boolean { try { return localStorage.getItem(KEY) !== "0"; } catch { return true; } }
export function setSoundOn(on: boolean) { try { localStorage.setItem(KEY, on ? "1" : "0"); } catch { /* 괜찮다 */ } if (on) play("pop"); }
/** 녹음이 켜져 있는 동안은 소리 대신 진동 */
export function setRecording(on: boolean) { recording = on; }

/** 출력: 부드럽게 깎고(저역 통과) 짧은 울림(지연 되먹임)을 조금 더한다 */
function audio(): { a: AudioContext; out: GainNode } | null {
  if (ctx && bus) return { a: ctx, out: bus };
  const Ctx = window.AudioContext || (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  if (!Ctx) return null;
  ctx = new Ctx();
  bus = ctx.createGain();
  bus.gain.value = VOLUME;
  const soft = ctx.createBiquadFilter();
  soft.type = "lowpass";
  soft.frequency.value = 2600;
  const delay = ctx.createDelay();
  delay.delayTime.value = 0.13;
  const feedback = ctx.createGain();
  feedback.gain.value = 0.22;
  const wet = ctx.createGain();
  wet.gain.value = 0.18;
  bus.connect(soft).connect(ctx.destination);
  soft.connect(delay).connect(feedback).connect(delay);
  delay.connect(wet).connect(ctx.destination);
  return { a: ctx, out: bus };
}

/** 마림바 같은 한 음: 몸통(사인) + 금방 사라지는 4배 배음(나무를 두드린 느낌) */
function mallet(a: AudioContext, out: AudioNode, freq: number, at: number, vol = 0.05, length = 0.5) {
  const t = a.currentTime + at;
  const body = a.createOscillator();
  const bodyGain = a.createGain();
  body.type = "sine";
  body.frequency.value = freq;
  bodyGain.gain.setValueAtTime(0, t);
  bodyGain.gain.linearRampToValueAtTime(vol, t + 0.006);
  bodyGain.gain.exponentialRampToValueAtTime(0.0001, t + length);
  const knock = a.createOscillator();
  const knockGain = a.createGain();
  knock.type = "sine";
  knock.frequency.value = freq * 4;
  knockGain.gain.setValueAtTime(0, t);
  knockGain.gain.linearRampToValueAtTime(vol * 0.35, t + 0.003);
  knockGain.gain.exponentialRampToValueAtTime(0.0001, t + 0.06);
  body.connect(bodyGain).connect(out);
  knock.connect(knockGain).connect(out);
  body.start(t); knock.start(t);
  body.stop(t + length + 0.05); knock.stop(t + 0.1);
}

/** 종이 넘기는 소리: 아주 작은 걸러 낸 잡음 */
function paper(a: AudioContext, out: AudioNode, dur = 0.14, vol = 0.025) {
  const len = Math.floor(a.sampleRate * dur);
  const buf = a.createBuffer(1, len, a.sampleRate);
  const data = buf.getChannelData(0);
  for (let i = 0; i < len; i++) data[i] = (Math.random() * 2 - 1) * Math.pow(Math.sin((Math.PI * i) / len), 2);
  const src = a.createBufferSource();
  src.buffer = buf;
  const filter = a.createBiquadFilter();
  filter.type = "bandpass";
  filter.frequency.value = 1800;
  filter.Q.value = 0.6;
  const gain = a.createGain();
  gain.gain.value = vol;
  src.connect(filter).connect(gain).connect(out);
  src.start();
}

const BUZZ: Partial<Record<Name, number | number[]>> = { alert: [40, 60, 40], success: 15, wrong: [25, 40, 25], levelup: [20, 40, 20] };

// C 펜타토닉 (도 레 미 솔 라)
const N = { G4: 392, A4: 440, C5: 523.25, D5: 587.33, E5: 659.25, G5: 783.99, A5: 880, C6: 1046.5 };

export function play(name: Name) {
  if (recording) { const v = BUZZ[name]; if (v) navigator.vibrate?.(v); return; }
  if (!soundOn()) return;
  const io = audio();
  if (!io) return;
  const { a, out } = io;
  if (a.state === "suspended") void a.resume();
  switch (name) {
    case "tap": break;                                   // 버튼마다 소리는 내지 않는다
    case "pop": mallet(a, out, N.G5, 0, 0.035, 0.35); break;
    case "flip": paper(a, out, 0.12, 0.02); break;
    case "turn": paper(a, out, 0.16, 0.025); break;
    case "note": break;                                  // 필기는 녹음 중에만 붙으므로 (진동은 위에서) 소리 없음
    case "success": mallet(a, out, N.E5, 0, 0.045); mallet(a, out, N.A5, 0.11, 0.04, 0.7); break;
    case "wrong": mallet(a, out, N.D5, 0, 0.035); mallet(a, out, N.A4, 0.13, 0.03, 0.6); break;
    case "alert": mallet(a, out, N.A5, 0, 0.035); mallet(a, out, N.C6, 0.16, 0.03, 0.6); break;
    case "start": mallet(a, out, N.C5, 0, 0.04); mallet(a, out, N.G5, 0.12, 0.035, 0.7); break;
    case "stop": mallet(a, out, N.G5, 0, 0.035); mallet(a, out, N.C5, 0.12, 0.04, 0.8); break;
    case "levelup": [N.C5, N.E5, N.G5, N.C6].forEach((f, i) => mallet(a, out, f, i * 0.1, 0.035, 0.7)); break;
    case "complete": [N.G4, N.C5, N.E5, N.G5].forEach((f, i) => mallet(a, out, f, i * 0.11, 0.035, 0.9)); break;
  }
}

/** (예전 이름 유지) 버튼마다 나는 소리는 없앴다 */
export function installTapSound() { /* 일부러 비워 둠: 버튼마다 소리는 잔잔하지 않아서 */ }
