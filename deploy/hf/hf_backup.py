"""LUNE 자료 백업 (허깅페이스 무료 서버): 서버는 다시 켜질 때 디스크가 비므로, DB 와 녹음을
같은 계정의 비공개 데이터 저장소(<아이디>/lune-data)에 5분마다 올리고, 켜질 때 되살린다.

  python hf_backup.py restore   # 이 서버에 DB 가 없을 때만 백업에서 되살린다
  python hf_backup.py loop      # 5분마다 바뀐 것만 백업 (끝날 때도 한 번)

HF_TOKEN(쓰기 권한) 비밀값이 있어야 한다. 없으면 백업 없이 그냥 돈다 (다시 켜지면 자료가 사라짐).
"""

import os
import signal
import sqlite3
import sys
import tempfile
import time

from huggingface_hub import HfApi, snapshot_download
from huggingface_hub.utils import HfHubHTTPError, RepositoryNotFoundError

DB = os.environ.get("DB_PATH", "/home/user/data/lecture_notes.db")
DATA = os.path.dirname(DB)
UPLOADS = os.environ.get("UPLOAD_DIR", os.path.join(DATA, "uploads"))
TOKEN = os.environ.get("HF_TOKEN", "").strip()
OWNER = os.environ.get("SPACE_AUTHOR_NAME") or (os.environ.get("SPACE_ID", "/").split("/")[0])
REPO = os.environ.get("BACKUP_REPO") or f"{OWNER}/lune-data"
EVERY = int(os.environ.get("BACKUP_SECONDS", "300"))


def say(text: str) -> None:
    print(f"[백업] {text}", flush=True)


def restore() -> None:
    if not TOKEN or not OWNER:
        say("HF_TOKEN 이 없어 백업을 쓰지 않아요 (서버가 다시 켜지면 자료가 사라져요)")
        return
    if os.path.exists(DB):
        return
    try:
        snapshot_download(REPO, repo_type="dataset", local_dir=DATA, token=TOKEN)
        say(f"되살렸어요 ← {REPO}")
    except RepositoryNotFoundError:
        say("아직 백업이 없어요 (처음 켜짐)")


def fingerprint() -> tuple:
    files = []
    for root, _, names in os.walk(UPLOADS):
        for n in names:
            p = os.path.join(root, n)
            files.append((p, os.path.getsize(p)))
    db = (os.path.getmtime(DB), os.path.getsize(DB)) if os.path.exists(DB) else None
    return db, tuple(sorted(files))


def backup(api: HfApi) -> None:
    if not os.path.exists(DB):
        return
    api.create_repo(REPO, repo_type="dataset", private=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        copy = os.path.join(tmp, os.path.basename(DB))
        src, dst = sqlite3.connect(DB), sqlite3.connect(copy)
        with dst:
            src.backup(dst)  # 쓰는 중이어도 깨지지 않게 SQLite 백업으로 복사
        src.close(), dst.close()
        api.upload_file(path_or_fileobj=copy, path_in_repo=os.path.basename(DB), repo_id=REPO, repo_type="dataset",
                        commit_message="DB 백업")
    if os.path.isdir(UPLOADS) and os.listdir(UPLOADS):
        # 녹음·강의자료 (합쳐서 만든 full-*.wav 와 만드는 중인 .tmp 는 빼고)
        api.upload_folder(folder_path=UPLOADS, path_in_repo=os.path.relpath(UPLOADS, DATA), repo_id=REPO, repo_type="dataset",
                          ignore_patterns=["full-*.wav", "*.tmp"], commit_message="녹음·자료 백업")
    say("백업했어요 → " + REPO)


def loop() -> None:
    if not TOKEN or not OWNER:
        return
    api = HfApi(token=TOKEN)
    last = fingerprint()
    stop = {"now": False}
    signal.signal(signal.SIGTERM, lambda *_: stop.__setitem__("now", True))
    while True:
        for _ in range(EVERY):
            if stop["now"]:
                break
            time.sleep(1)
        now = fingerprint()
        if now != last:
            try:
                backup(api)
                last = now
            except (HfHubHTTPError, OSError, sqlite3.Error) as exc:
                say(f"백업 실패 (다음에 다시): {exc}")
        if stop["now"]:
            return


if __name__ == "__main__":
    {"restore": restore, "loop": loop}[sys.argv[1]]()
