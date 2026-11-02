"""강의 녹음 파일 찾기: 필기를 누르면 그 순간의 녹음을 들려주기 위해 세션의 녹음을 하나의 파일로 내준다.

- 녹음 파일로 정리한 강의: 올린 파일(세션.audio) 그대로
- 실시간 강의: 연결마다 하나씩 생긴 세션-1.wav, 세션-2.wav … 를 이어 붙인 full-세션.wav
  (다시 연결한 뒤의 받아쓰기 시각은 앞 조각들의 길이에 이어서 매기므로, 이어 붙인 파일의 위치와 같다)
"""

import os
import re
import wave

from .config import settings


def wav_parts(session_id: str) -> list[str]:
    if not os.path.isdir(settings.upload_dir):
        return []
    pattern = re.compile(rf"^{re.escape(session_id)}-(\d+)\.wav$")
    parts = [(int(m.group(1)), name) for name in os.listdir(settings.upload_dir) if (m := pattern.match(name))]
    return [os.path.join(settings.upload_dir, name) for _, name in sorted(parts)]


def _duration_ms(path: str) -> int:
    try:
        with wave.open(path, "rb") as w:
            return w.getnframes() * 1000 // w.getframerate()
    except (wave.Error, EOFError):
        return 0


def recorded_ms(session_id: str) -> int:
    """지금까지 남은 실시간 녹음의 길이 (다시 연결했을 때 받아쓰기 시각을 이어 매기는 기준)."""
    return sum(_duration_ms(p) for p in wav_parts(session_id))


def _sniff(path: str) -> str:
    with open(path, "rb") as f:
        head = f.read(12)
    if head[:4] == b"RIFF":
        return "audio/wav"
    if head[:3] == b"ID3" or head[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):
        return "audio/mpeg"
    if head[:4] == b"OggS":
        return "audio/ogg"
    if head[:4] == b"\x1a\x45\xdf\xa3":
        return "audio/webm"
    if head[:4] == b"fLaC":
        return "audio/flac"
    return "audio/mp4"  # 음성 메모(m4a)


def audio_file(session_id: str) -> tuple[str, str] | None:
    uploaded = os.path.join(settings.upload_dir, f"{session_id}.audio")
    if os.path.exists(uploaded):
        return uploaded, _sniff(uploaded)
    parts = wav_parts(session_id)
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0], "audio/wav"
    full = os.path.join(settings.upload_dir, f"full-{session_id}.wav")
    if not os.path.exists(full) or os.path.getmtime(full) < max(os.path.getmtime(p) for p in parts):
        with wave.open(full + ".tmp", "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(16000)
            for part in parts:
                try:
                    with wave.open(part, "rb") as w:
                        out.writeframes(w.readframes(w.getnframes()))
                except (wave.Error, EOFError):
                    continue
        os.replace(full + ".tmp", full)
    return full, "audio/wav"
