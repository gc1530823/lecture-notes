"""LUNE 서버를 허깅페이스 무료 서버(Space)에 올린다: 웹을 빌드하고, 서버 코드·웹 결과물·이 폴더를 모아 한 번에 올린다.

  python deploy/hf/publish.py <아이디>/lune     (허깅페이스 쓰기 토큰: HF_TOKEN 또는 huggingface-cli login)

올리면 허깅페이스가 알아서 다시 빌드하고 켠다. 자료(DB·녹음)와 비밀값은 올리지 않는다.
"""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from huggingface_hub import HfApi

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def main() -> None:
    space = sys.argv[1]
    subprocess.run(["npm", "run", "build", "--silent"], cwd=ROOT / "web", check=True)
    api = HfApi(token=os.environ.get("HF_TOKEN") or None)
    api.create_repo(space, repo_type="space", space_sdk="docker", exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp)
        skip = shutil.ignore_patterns("__pycache__", "*.pyc", "data", ".venv", ".pytest_cache", "tests", "scripts")
        shutil.copytree(ROOT / "server" / "app", stage / "server" / "app", ignore=skip)
        shutil.copy(ROOT / "server" / "requirements.txt", stage / "server" / "requirements.txt")
        shutil.copytree(ROOT / "web" / "dist", stage / "web" / "dist")
        (stage / "hf").mkdir()
        for name in ("start.sh", "hf_backup.py"):
            shutil.copy(HERE / name, stage / "hf" / name)
        for name in ("Dockerfile", "README.md"):
            shutil.copy(HERE / name, stage / name)
        api.upload_folder(folder_path=str(stage), repo_id=space, repo_type="space", commit_message="LUNE 서버 올리기",
                          delete_patterns=["server/**", "web/**", "hf/**"])
    owner, name = space.split("/")
    print(f"올렸어요. 빌드가 끝나면 열려요: https://{owner}-{name}.hf.space/web/")


if __name__ == "__main__":
    main()
