"""자료 백업·복원: 강의자료(PDF)와 DB(필기·받아쓰기·과제·요약)를 이 저장소의 data-backup 브랜치에 올린다.

Codespace가 지워지거나 새로 만들어져도 자료를 되살리기 위한 것이다. 녹음 파일은 크고(GitHub 파일 한도 100MB)
받아쓰기 결과가 이미 DB에 있으므로 올리지 않는다. 브랜치에는 가장 최근 백업 하나만 남긴다.

사용법 (server 폴더에서):
  python scripts/backup.py            # 바뀐 게 있으면 백업
  python scripts/backup.py --restore  # 이 서버에 DB가 없을 때만 백업에서 되살린다
"""

import argparse
import hashlib
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile

BRANCH = "data-backup"
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(HERE, os.getenv("DB_PATH", "data/lecture_notes.db"))
UPLOAD_DIR = os.path.join(HERE, os.getenv("UPLOAD_DIR", "data/uploads"))
STAMP = os.path.join(os.path.dirname(DB_PATH), ".last-backup")


def git(*args: str, cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def default_remote() -> str:
    return git("remote", "get-url", "origin", cwd=HERE).stdout.strip()


def snapshot(dest: str) -> str:
    """DB를 쓰는 중이어도 안전하게 복사하고(sqlite 백업 API), PDF를 모은 뒤 내용의 해시를 돌려준다."""
    os.makedirs(os.path.join(dest, "uploads"), exist_ok=True)
    src = sqlite3.connect(DB_PATH)
    out = sqlite3.connect(os.path.join(dest, "lecture_notes.db"))
    with out:
        src.backup(out)
    src.close()
    # 같은 내용이면 같은 해시가 나오도록 DB는 행 단위 덤프로 해시한다 (파일 바이트는 실행마다 달라질 수 있다)
    digest = hashlib.sha256("\n".join(out.iterdump()).encode())
    out.close()
    if os.path.isdir(UPLOAD_DIR):
        for name in sorted(os.listdir(UPLOAD_DIR)):
            # 정리 PDF(notes-*.pdf)는 DB로 언제든 다시 만들 수 있어 올리지 않는다
            if name.endswith(".pdf") and not name.startswith("notes-"):
                shutil.copy2(os.path.join(UPLOAD_DIR, name), os.path.join(dest, "uploads", name))
                with open(os.path.join(UPLOAD_DIR, name), "rb") as f:
                    digest.update(name.encode() + hashlib.sha256(f.read()).digest())
    return digest.hexdigest()


def backup(remote: str) -> None:
    if not os.path.exists(DB_PATH):
        print("백업할 자료가 아직 없어요.")
        return
    with tempfile.TemporaryDirectory() as tmp:
        digest = snapshot(tmp)
        if os.path.exists(STAMP) and open(STAMP).read().strip() == digest:
            print("바뀐 자료가 없어 백업을 건너뜁니다.")
            return
        with open(os.path.join(tmp, "README.md"), "w") as f:
            f.write("강의노트 서버 자료 자동 백업 (scripts/backup.py가 만든다). 직접 고치지 마세요.\n")
        git("init", "-q", "-b", BRANCH, cwd=tmp)
        git("add", ".", cwd=tmp)
        git("-c", "user.name=lecture-notes-backup", "-c", "user.email=backup@users.noreply.github.com",
            "commit", "-q", "-m", "자료 백업", cwd=tmp)
        git("push", "-q", "-f", remote, f"HEAD:{BRANCH}", cwd=tmp)
    with open(STAMP, "w") as f:
        f.write(digest)
    print("백업했어요.")


def restore(remote: str) -> None:
    if os.path.exists(DB_PATH):
        print("이 서버에 자료가 있어 복원하지 않습니다.")
        return
    with tempfile.TemporaryDirectory() as tmp:
        try:
            git("clone", "-q", "--depth", "1", "--branch", BRANCH, remote, "backup", cwd=tmp)
        except subprocess.CalledProcessError:
            print("백업이 아직 없어요. 새로 시작합니다.")
            return
        src = os.path.join(tmp, "backup")
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        shutil.copy2(os.path.join(src, "lecture_notes.db"), DB_PATH)
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        for name in os.listdir(os.path.join(src, "uploads")):
            shutil.copy2(os.path.join(src, "uploads", name), os.path.join(UPLOAD_DIR, name))
    print("백업에서 자료를 되살렸어요.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--restore", action="store_true")
    parser.add_argument("--remote", help="백업을 올릴 git 저장소 (기본: 이 저장소의 origin)")
    args = parser.parse_args()
    try:
        remote = args.remote or default_remote()
        (restore if args.restore else backup)(remote)
    except subprocess.CalledProcessError as exc:
        print(f"백업 실패: {exc.stderr.strip()}", file=sys.stderr)
        sys.exit(1)
