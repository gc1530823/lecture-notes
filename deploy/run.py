"""내 컴퓨터를 강의노트 서버로: 서버를 켜고, 무료 터널(Cloudflare)로 인터넷 주소를 만들어 준다.

  python deploy/run.py            서버 + 인터넷 주소 (친구들·발표용)
  python deploy/run.py --local    이 컴퓨터·같은 와이파이에서만 (터널 없이)

처음 한 번은 Groq 키와 초대 코드를 물어 deploy/.env 에 저장한다 (이 파일은 저장소에 올라가지 않는다).
- 초대 코드: 친구가 처음 가입할 때 넣는 말. 이걸 아는 사람만 가입할 수 있고, 각자 자기 자료만 본다.
- 자료(녹음·필기·강의자료)는 이 컴퓨터의 server/data/ 에 남는다. 서버를 껐다 켜도 그대로.
- 무료 터널 주소는 켤 때마다 바뀐다. 새 주소를 카톡으로 보내면 친구 앱이 눌러서 바로 연결된다.
"""

import getpass
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "server"
WEB = ROOT / "web"
ENV_FILE = ROOT / "deploy" / ".env"
PORT = int(os.environ.get("PORT", "8000"))
WIN = os.name == "nt"


def say(text: str = "") -> None:
    print(text, flush=True)


def need(cmd: str, how: str) -> str:
    path = shutil.which(cmd)
    if not path:
        say(f"\n[!] '{cmd}' 가 없어요. {how}")
        sys.exit(1)
    return path


def load_env() -> dict:
    env = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                env[key.strip()] = value.strip()
    changed = False
    if not env.get("GROQ_API_KEY"):
        say("\n[처음 한 번] Groq API 키를 넣어 주세요 (https://console.groq.com/keys 에서 무료로 만들 수 있어요).")
        say("            입력해도 화면에 보이지 않아요. 없으면 그냥 Enter (그러면 이 컴퓨터의 AI만 써요).")
        env["GROQ_API_KEY"] = getpass.getpass("Groq 키: ").strip()
        changed = True
    if not env.get("INVITE_CODE"):
        suggestion = "쫑긋-" + secrets.token_hex(2)
        say(f"\n[처음 한 번] 친구들이 가입할 때 넣을 초대 코드를 정해 주세요. 그냥 Enter 면 '{suggestion}'")
        env["INVITE_CODE"] = input("초대 코드: ").strip() or suggestion
        changed = True
    if changed:
        ENV_FILE.write_text("# 강의노트 서버 설정 (저장소에 올리지 마세요)\n" + "".join(f"{k}={v}\n" for k, v in env.items()), encoding="utf-8")
        if not WIN:
            os.chmod(ENV_FILE, 0o600)
        say(f"저장했어요: {ENV_FILE}")
    return env


def venv_python() -> Path:
    py = SERVER / ".venv" / ("Scripts/python.exe" if WIN else "bin/python")
    if not py.exists():
        say("\n파이썬 가상환경을 만드는 중… (처음 한 번)")
        subprocess.run([sys.executable, "-m", "venv", str(SERVER / ".venv")], check=True)
    stamp = SERVER / ".venv" / ".installed"
    req = SERVER / "requirements.txt"
    if not stamp.exists() or stamp.stat().st_mtime < req.stat().st_mtime:
        say("서버에 필요한 것을 설치하는 중… (처음 한 번, 몇 분 걸려요)")
        subprocess.run([str(py), "-m", "pip", "install", "-q", "--upgrade", "pip"], check=True)
        subprocess.run([str(py), "-m", "pip", "install", "-q", "-r", str(req), "qrcode"], check=True)
        stamp.write_text("ok")
    return py


def build_web() -> None:
    dist = WEB / "dist" / "index.html"
    sources = [p for p in (WEB / "src").rglob("*") if p.is_file()] + [WEB / "index.html"]
    if dist.exists() and max(p.stat().st_mtime for p in sources) < dist.stat().st_mtime:
        return
    npm = need("npm", "Node.js 를 설치해 주세요 (https://nodejs.org).")
    say("\n화면(웹앱)을 만드는 중… (처음 한 번, 또는 바뀌었을 때)")
    if not (WEB / "node_modules").exists():
        subprocess.run([npm, "ci", "--silent"], cwd=WEB, check=True)
    subprocess.run([npm, "run", "build", "--silent"], cwd=WEB, check=True)


def ai_mode(env: dict) -> dict:
    """Groq 키가 있으면 Groq, 이 컴퓨터에 Ollama 모델이 있으면 한도에 걸릴 때 그 모델이 이어서"""
    out = {}
    models = ""
    if shutil.which("ollama"):
        try:
            models = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=10).stdout
        except (OSError, subprocess.SubprocessError):
            models = ""
    local = "lecture-notes" if re.search(r"^lecture-notes", models, re.M) else "qwen3:4b" if "qwen3:4b" in models else None
    if env.get("GROQ_API_KEY") and local:
        out.update(LLM_MODE="hybrid", OLLAMA_MODEL=local, HYBRID_LOCAL_FIRST="1" if local == "lecture-notes" else "0")
        say(f"AI: 수업 중은 Groq, 한도에 걸리면 이 컴퓨터의 AI({local})가 이어서")
    elif env.get("GROQ_API_KEY"):
        out.update(LLM_MODE="groq")
        say("AI: Groq (무료 한도에 걸리면 잠시 기다려요. 'ollama pull qwen3:4b' 를 해 두면 한도 없이 이어서 해요)")
    elif local:
        out.update(LLM_MODE="ollama", OLLAMA_MODEL=local, STT_MODE="whisper")
        say(f"AI: 이 컴퓨터의 AI({local}) 만 (느릴 수 있어요)")
    else:
        say("\n[!] Groq 키도, 이 컴퓨터의 AI(Ollama)도 없어요. deploy/.env 에 GROQ_API_KEY 를 넣거나 Ollama 를 설치해 주세요.")
        sys.exit(1)
    return out


def wait_health(proc: subprocess.Popen) -> None:
    for _ in range(60):
        if proc.poll() is not None:
            say("\n[!] 서버가 켜지지 않았어요. 위의 오류를 확인해 주세요.")
            sys.exit(1)
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=2):
                return
        except OSError:
            time.sleep(1)
    say("\n[!] 서버가 1분 안에 대답하지 않았어요.")
    sys.exit(1)


def lan_address() -> str | None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return None


def start_tunnel() -> tuple[subprocess.Popen, str]:
    cloudflared = need("cloudflared", "설치 스크립트(start-windows.bat / start-mac.command)를 쓰면 함께 설치돼요.")
    say("\n인터넷 주소를 만드는 중… (Cloudflare 무료 터널)")
    proc = subprocess.Popen([cloudflared, "tunnel", "--no-autoupdate", "--url", f"http://localhost:{PORT}"],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    found: list[str] = []

    def read():
        for line in proc.stdout:  # type: ignore[union-attr]
            m = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", line)
            if m and not found:
                found.append(m.group(0))
    threading.Thread(target=read, daemon=True).start()
    for _ in range(60):
        if found:
            return proc, found[0]
        if proc.poll() is not None:
            break
        time.sleep(1)
    say("\n[!] 인터넷 주소를 만들지 못했어요. 인터넷 연결을 확인하고 다시 켜 주세요. (--local 로 켜면 같은 와이파이에서는 쓸 수 있어요)")
    proc.terminate()
    sys.exit(1)


def show_qr(py: Path, text: str) -> None:
    subprocess.run([str(py), "-c", "import qrcode,sys; q=qrcode.QRCode(border=1); q.add_data(sys.argv[1]); q.print_ascii(invert=True)", text])


def main() -> None:
    # 창을 닫거나 끄기 신호가 와도 서버·터널을 함께 끈다
    if not WIN:
        import signal
        signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    local_only = "--local" in sys.argv
    say("=" * 56 + "\n 쫑긋 강의노트 서버\n" + "=" * 56)
    need("ffmpeg", "설치 스크립트(start-windows.bat / start-mac.command)를 쓰면 함께 설치돼요.")
    env = load_env()
    py = venv_python()
    build_web()
    run_env = {**os.environ, **{k: v for k, v in env.items() if v}, **ai_mode(env)}
    run_env.setdefault("DB_PATH", str(SERVER / "data" / "lecture_notes.db"))
    run_env.setdefault("UPLOAD_DIR", str(SERVER / "data" / "uploads"))
    (SERVER / "data").mkdir(exist_ok=True)

    say("\n서버를 켜는 중…")
    server = subprocess.Popen([str(py), "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0" if local_only else "127.0.0.1",
                               "--port", str(PORT), "--proxy-headers", "--forwarded-allow-ips", "127.0.0.1"], cwd=SERVER, env=run_env)
    procs = [server]
    try:
        wait_health(server)
        if local_only:
            lan = lan_address()
            url = f"http://{lan}:{PORT}" if lan else f"http://localhost:{PORT}"
        else:
            tunnel, url = start_tunnel()
            procs.append(tunnel)
        (ROOT / "deploy" / "last-url.txt").write_text(url + "/web/\n", encoding="utf-8")
        say("\n" + "=" * 56)
        say(" 켜졌어요! 이 창을 닫으면 서버도 꺼져요.\n")
        say(f" 주소 (폰 앱·브라우저):  {url}/web/")
        say(f" 초대 코드 (처음 가입할 때):  {env['INVITE_CODE']}")
        say("\n 친구에게: 위 주소를 카톡으로 보내면, 앱이 깔린 폰에서 눌러 바로 연결돼요.")
        if not local_only:
            say(" (무료 터널이라 서버를 다시 켜면 주소가 바뀌어요. 그때 새 주소를 다시 보내 주세요)")
        say("=" * 56)
        show_qr(py, f"{url}/web/")
        while all(p.poll() is None for p in procs):
            time.sleep(2)
        say("\n[!] 서버나 터널이 멈췄어요. 다시 켜 주세요.")
    except KeyboardInterrupt:
        say("\n끄는 중…")
    finally:
        for p in procs:
            if p.poll() is None:
                p.terminate()


if __name__ == "__main__":
    main()
