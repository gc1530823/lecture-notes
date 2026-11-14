"""LUNE 서버 코드 묶음을 허깅페이스 **비공개** 저장소(<아이디>/lune-server)에 올린다.
오라클 서버는 읽기 전용 토큰으로 이 묶음을 받아 설치하고, 한 시간마다 새 버전이 있는지 보고 스스로 업데이트한다 (cloud-init.sh).

  python deploy/oracle/publish.py <아이디>/lune-server

올리는 것: server/app, server/requirements.txt, web/dist(빌드 결과), 버전 표시. 자료·비밀값은 올리지 않는다.
"""

import io
import os
import subprocess
import sys
import tarfile
import time
from pathlib import Path

from huggingface_hub import HfApi

ROOT = Path(__file__).resolve().parents[2]
SKIP = {"__pycache__", ".pytest_cache"}


def keep(info: tarfile.TarInfo):
    return None if any(part in SKIP for part in Path(info.name).parts) or info.name.endswith(".pyc") else info


def main() -> None:
    repo = sys.argv[1]
    subprocess.run(["npm", "run", "build", "--silent"], cwd=ROOT / "web", check=True)
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    version = f"{commit}-{int(time.time())}"
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        tar.add(ROOT / "server" / "app", "lune/server/app", filter=keep)
        tar.add(ROOT / "server" / "requirements.txt", "lune/server/requirements.txt")
        tar.add(ROOT / "web" / "dist", "lune/web/dist", filter=keep)
        data = version.encode()
        info = tarfile.TarInfo("lune/VERSION")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    api = HfApi(token=os.environ.get("HF_TOKEN") or None)
    api.create_repo(repo, repo_type="model", private=True, exist_ok=True)
    api.upload_file(path_or_fileobj=buf.getvalue(), path_in_repo="lune-server.tar.gz", repo_id=repo,
                    commit_message=f"LUNE 서버 {version}")
    api.upload_file(path_or_fileobj=version.encode(), path_in_repo="VERSION", repo_id=repo, commit_message=f"버전 {version}")
    print(f"올렸어요 (비공개): {repo} · {version} · {len(buf.getvalue()) // 1024} KB")


if __name__ == "__main__":
    main()
