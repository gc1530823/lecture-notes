// 효과음: 고급스럽고 잔잔하게. 파일 없이 Web Audio로 그 자리에서 만든다.
//
// 소리 재료 (모두 같은 음계 · E 장조 펜타토닉이라 이어서 나도 어울린다)
//  - 유리 종 (bell): FM 합성. 맑은 몸통 + 금방 사라지는 비정수 배음(유리·금속 느낌) → 정답·완료·알림
//  - 펠트 피아노 (felt): 삼각파를 부드럽게 깎아 둥글고 따뜻하게 → 녹음 시작·끝, 오답(낮고 차분하게)
//  - 클릭 (click): 아주 짧은 고음 + 걸러 낸 잡음 → 탭 바꾸기 (휴대폰 햅틱 같은 또각)
//  - 바람 (air): 높은 데서 낮은 데로 쓸려 가는 잡음, 왼쪽→오른쪽으로 → 카드 넘기기
//  - 종이 (paper): 카드 뒤집기
// 공간: 만든 잔향(합성 임펄스 응답)으로 작은 홀 같은 울림, 소리마다 좌우 위치를 살짝 다르게,
//       마지막에 리미터(컴프레서)로 크고 작은 소리를 고르게. 전체 크기는 작게.
// 원칙: 의미 있는 순간에만 (버튼마다 소리는 없다). 녹음 중에는 소리 대신 진동만 (받아쓰기를 망치지 않게).
//       설정(더보기)에서 끌 수 있다. 소리는 사용자가 한 번이라도 누른 뒤에만 난다 (브라우저 규칙).

export type SoundName = "tap" | "pop" | "success" | "wrong" | "flip" | "turn" | "alert" | "note" | "start" | "stop" | "levelup" | "complete"
  | "tick" | "swish" | "slide" | "send" | "open";

let ctx: AudioContext | null = null;
let dry: GainNode | null = null;
let wet: GainNode | null = null;
let recording = false;
const KEY = "ln.sound";
const VOLUME = 1.1;

export function soundOn(): boolean { try { return localStorage.getItem(KEY) !== "0"; } catch { return true; } }
export function setSoundOn(on: boolean) { try { localStorage.setItem(KEY, on ? "1" : "0"); } catch { /* 괜찮다 */ } if (on) play("pop"); }
/** 녹음이 켜져 있는 동안은 소리 대신 진동 */
export function setRecording(on: boolean) { recording = on; }

/** 작은 홀의 잔향: 양쪽 귀에 조금씩 다른, 점점 사라지는 잡음 (길이 2.4초, 높은 소리부터 먼저 사라진다) */
function impulse(a: BaseAudioContext, seconds = 2.4): AudioBuffer {
  const len = Math.floor(a.sampleRate * seconds);
  const buf = a.createBuffer(2, len, a.sampleRate);
  for (let c = 0; c < 2; c++) {
    const data = buf.getChannelData(c);
    let low = 0;
    for (let i = 0; i < len; i++) {
      const t = i / len;
      const noise = Math.random() * 2 - 1;
      low += (noise - low) * (0.5 - 0.42 * t); // 뒤로 갈수록 어둡게
      data[i] = low * Math.pow(1 - t, 3.2) * (i < a.sampleRate * 0.012 ? i / (a.sampleRate * 0.012) : 1);
    }
  }
  return buf;
}

/** 출력 연결: 소리 → (dry · 잔향) → 리미터 → 스피커 */
function audio(): { a: AudioContext; dry: GainNode; wet: GainNode } | null {
  if (ctx && dry && wet) return { a: ctx, dry, wet };
  const Ctx = window.AudioContext || (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  if (!Ctx) return null;
  ctx = new Ctx();
  const master = ctx.createGain();
  master.gain.value = VOLUME;
  const limiter = ctx.createDynamicsCompressor();
  limiter.threshold.value = -18; limiter.knee.value = 12; limiter.ratio.value = 4; limiter.attack.value = 0.003; limiter.release.value = 0.2;
  const air = ctx.createBiquadFilter(); // 아주 높은 쇳소리만 살짝 눌러 귀가 편하게
  air.type = "highshelf"; air.frequency.value = 7000; air.gain.value = -4;
  master.connect(air).connect(limiter).connect(ctx.destination);
  dry = ctx.createGain();
  dry.connect(master);
  const reverb = ctx.createConvolver();
  reverb.buffer = impulse(ctx);
  const preDelay = ctx.createDelay();
  preDelay.delayTime.value = 0.018;
  wet = ctx.createGain();
  wet.gain.value = 0.32;
  wet.connect(preDelay).connect(reverb).connect(master);
  return { a: ctx, dry, wet };
}

type Out = { a: AudioContext; dry: GainNode; wet: GainNode };

/** 소리 하나를 좌우 위치(pan)와 잔향 양(send)을 정해 내보낸다 */
function voice(o: Out, pan = 0, send = 1): GainNode {
  const g = o.a.createGain();
  const p = o.a.createStereoPanner();
  p.pan.value = pan;
  g.connect(p);
  p.connect(o.dry);
  const s = o.a.createGain();
  s.gain.value = send;
  p.connect(s).connect(o.wet);
  return g;
}

/** 유리 종: FM (몸통 사인 + 3.5배 비정수 변조로 맑은 쇳소리, 변조는 빨리 줄어 끝은 순한 사인) */
function bell(o: Out, freq: number, at = 0, vol = 0.05, decay = 1.6, pan = 0) {
  const { a } = o;
  const t = a.currentTime + at;
  const out = voice(o, pan, 1);
  const carrier = a.createOscillator(); carrier.type = "sine"; carrier.frequency.value = freq;
  const mod = a.createOscillator(); mod.type = "sine"; mod.frequency.value = freq * 3.5;
  const index = a.createGain();
  index.gain.setValueAtTime(freq * 1.6, t);
  index.gain.exponentialRampToValueAtTime(freq * 0.02, t + 0.35);
  mod.connect(index).connect(carrier.frequency);
  const env = a.createGain();
  env.gain.setValueAtTime(0, t);
  env.gain.linearRampToValueAtTime(vol, t + 0.004);
  env.gain.exponentialRampToValueAtTime(vol * 0.35, t + 0.18);
  env.gain.exponentialRampToValueAtTime(0.0001, t + decay);
  // 아주 작게 떨리는 두 번째 몸통(살짝 어긋난 음) → 공간감 있는 맥놀이
  const shimmer = a.createOscillator(); shimmer.type = "sine"; shimmer.frequency.value = freq * 2.0 + 1.3;
  const shimmerEnv = a.createGain();
  shimmerEnv.gain.setValueAtTime(0, t);
  shimmerEnv.gain.linearRampToValueAtTime(vol * 0.18, t + 0.01);
  shimmerEnv.gain.exponentialRampToValueAtTime(0.0001, t + decay * 0.6);
  carrier.connect(env).connect(out);
  shimmer.connect(shimmerEnv).connect(out);
  for (const osc of [carrier, mod, shimmer]) { osc.start(t); osc.stop(t + decay + 0.1); }
}

/** 펠트 피아노: 부드럽게 깎은 삼각파 + 한 옥타브 위 아주 작게, 해머가 닿는 순간만 밝게 */
function felt(o: Out, freq: number, at = 0, vol = 0.06, decay = 1.1, pan = 0) {
  const { a } = o;
  const t = a.currentTime + at;
  const out = voice(o, pan, 0.7);
  const lp = a.createBiquadFilter();
  lp.type = "lowpass"; lp.Q.value = 0.3;
  lp.frequency.setValueAtTime(freq * 6, t);
  lp.frequency.exponentialRampToValueAtTime(freq * 1.6, t + 0.25);
  const env = a.createGain();
  env.gain.setValueAtTime(0, t);
  env.gain.linearRampToValueAtTime(vol, t + 0.008);
  env.gain.exponentialRampToValueAtTime(0.0001, t + decay);
  lp.connect(env).connect(out);
  for (const [mult, type, level] of [[1, "triangle", 1], [2, "sine", 0.18], [1.003, "triangle", 0.5]] as const) {
    const osc = a.createOscillator(); osc.type = type; osc.frequency.value = freq * mult;
    const g = a.createGain(); g.gain.value = level;
    osc.connect(g).connect(lp);
    osc.start(t); osc.stop(t + decay + 0.1);
  }
}

/** 클릭: 아주 짧은 고음 한 점 + 걸러 낸 잡음 (휴대폰 햅틱 같은 또각) */
function click(o: Out, at = 0, vol = 0.03, pitch = 2400, pan = 0) {
  const { a } = o;
  const t = a.currentTime + at;
  const out = voice(o, pan, 0.25);
  const osc = a.createOscillator(); osc.type = "sine";
  osc.frequency.setValueAtTime(pitch, t);
  osc.frequency.exponentialRampToValueAtTime(pitch * 0.6, t + 0.03);
  const env = a.createGain();
  env.gain.setValueAtTime(vol, t);
  env.gain.exponentialRampToValueAtTime(0.0001, t + 0.035);
  osc.connect(env).connect(out);
  osc.start(t); osc.stop(t + 0.05);
  noise(o, at, 0.012, vol * 0.5, 5000, 2, pan);
}

/** 걸러 낸 잡음 (종이·바람 재료). from→to 로 주파수가 쓸려 가고, 왼쪽→오른쪽으로 움직일 수 있다 */
function noise(o: Out, at: number, dur: number, vol: number, from: number, q = 0.8, pan = 0, to = from, panTo = pan, send = 0.4) {
  const { a } = o;
  const t = a.currentTime + at;
  const len = Math.max(1, Math.floor(a.sampleRate * dur));
  const buf = a.createBuffer(1, len, a.sampleRate);
  const data = buf.getChannelData(0);
  for (let i = 0; i < len; i++) data[i] = (Math.random() * 2 - 1) * Math.pow(Math.sin((Math.PI * i) / len), 1.6);
  const src = a.createBufferSource(); src.buffer = buf;
  const bp = a.createBiquadFilter(); bp.type = "bandpass"; bp.Q.value = q;
  bp.frequency.setValueAtTime(from, t);
  if (to !== from) bp.frequency.exponentialRampToValueAtTime(to, t + dur);
  const g = a.createGain(); g.gain.value = vol;
  const p = a.createStereoPanner();
  p.pan.setValueAtTime(pan, t);
  if (panTo !== pan) p.pan.linearRampToValueAtTime(panTo, t + dur);
  src.connect(bp).connect(g).connect(p);
  p.connect(o.dry);
  const s = a.createGain(); s.gain.value = send;
  p.connect(s).connect(o.wet);
  src.start(t);
}

const BUZZ: Partial<Record<SoundName, number | number[]>> = { alert: [40, 60, 40], success: 15, wrong: [25, 40, 25], levelup: [20, 40, 20] };

// E 장조 펜타토닉 (미 파# 솔# 시 도#)
const N = { E4: 329.63, Gs4: 415.3, B4: 493.88, Cs5: 554.37, E5: 659.25, Fs5: 739.99, Gs5: 830.61, B5: 987.77, Cs6: 1108.73, E6: 1318.51, Gs6: 1661.22, B6: 1975.53 };

export function play(name: SoundName) {
  if (recording) { const v = BUZZ[name]; if (v) navigator.vibrate?.(v); return; }
  if (!soundOn()) return;
  const o = audio();
  if (!o) return;
  if (o.a.state === "suspended") void o.a.resume();
  switch (name) {
    case "tap": break;                                                         // 버튼마다 소리는 내지 않는다
    case "note": break;                                                        // 필기는 녹음 중에만 붙는다 (진동은 위에서)
    case "tick": click(o, 0, 0.09, 2600); break;                              // 탭 바꾸기
    case "pop": bell(o, N.B5, 0, 0.04, 0.8, 0.1); break;                       // 켜기
    case "flip": noise(o, 0, 0.09, 0.12, 2400, 0.7, -0.1, 1500, 0.1, 0.2); break;          // 카드 뒤집기 (종이)
    case "turn": noise(o, 0, 0.14, 0.1, 2000, 0.6, 0.2, 1100, -0.2, 0.25); break;         // 쪽 넘기기
    case "swish": noise(o, 0, 0.26, 0.12, 3200, 1.1, -0.5, 600, 0.6, 0.5); break;         // 카드 넘기기 (바람, 왼→오)
    case "slide": noise(o, 0, 0.2, 0.06, 2600, 1.2, 0.4, 900, -0.4, 0.5); break;           // 배너 넘기기
    case "send": bell(o, N.Gs5, 0, 0.022, 0.6, -0.1); bell(o, N.Cs6, 0.07, 0.02, 0.7, 0.1); break;   // 답 보내기
    case "open": bell(o, N.E5, 0, 0.035, 1.0); noise(o, 0, 0.08, 0.04, 2200); break;      // 화면 열기
    case "success": bell(o, N.Gs5, 0, 0.045, 1.4, -0.15); bell(o, N.Cs6, 0.09, 0.04, 1.8, 0.15); break;      // 정답: 맑게 올라가는 두 종
    case "wrong": felt(o, N.Gs4, 0, 0.05, 0.9, -0.1); felt(o, N.E4, 0.13, 0.045, 1.2, 0.1); break;          // 오답: 낮고 차분하게 내려가는 두 음
    case "alert": bell(o, N.B5, 0, 0.035, 1.2, -0.2); bell(o, N.E6, 0.16, 0.03, 1.6, 0.2); break;            // 시험 얘기
    case "start": felt(o, N.E4, 0, 0.05, 1.2, -0.1); felt(o, N.B4, 0.11, 0.045, 1.4, 0.1); bell(o, N.E6, 0.2, 0.012, 1.4); break; // 녹음 시작
    case "stop": felt(o, N.B4, 0, 0.045, 1.2, 0.1); felt(o, N.E4, 0.12, 0.05, 1.8, -0.1); break;            // 녹음 끝
    case "levelup": [N.E5, N.Gs5, N.B5, N.E6].forEach((f, i) => bell(o, f, i * 0.085, 0.03, 2.0, -0.3 + i * 0.2)); break;
    case "complete": // 복습·퀴즈 끝: 펠트 화음 위로 종이 반짝이며 올라간다
      [N.E4, N.B4, N.Gs5].forEach((f, i) => felt(o, f, i * 0.02, 0.03, 2.2, -0.2 + i * 0.2));
      [N.B5, N.E6, N.Gs6, N.B6].forEach((f, i) => bell(o, f, 0.12 + i * 0.09, 0.022, 2.2, -0.3 + i * 0.2));
      break;
  }
}

/** 설정 화면의 "효과음 미리 듣기" 목록 */
export const PREVIEW: [SoundName, string][] = [
  ["success", "정답"], ["wrong", "오답"], ["swish", "카드 넘기기"], ["tick", "탭 바꾸기"],
  ["alert", "시험 얘기"], ["start", "녹음 시작"], ["stop", "녹음 끝"], ["complete", "복습 끝"],
];

/** (예전 이름 유지) 버튼마다 나는 소리는 없앴다 */
export function installTapSound() { /* 일부러 비워 둠: 버튼마다 소리는 잔잔하지 않아서 */ }
