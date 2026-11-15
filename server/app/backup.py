"""자동 백업: 하루 한 번, 서버의 모든 자료를 허깅페이스 비공개 데이터셋 저장소에 올린다 (무료).

- DB(계정·강의·필기·시간표…): 그날 사본(db/lune-YYYY-MM-DD.db.gz) + 최신본(db/latest.db.gz). 날짜 사본은 14개만 남긴다.
- 올린 파일(강의자료·녹음·사진): 처음 한 번 다 올리고, 그다음부터는 새로 생기거나 바뀐 파일만 (이름+크기로 기억).
  녹음 중이라 아직 바뀌는 파일(10분 안에 바뀐 것)과, 다른 파일로 언제든 다시 만드는 이어 붙인 녹음(full-*.wav)은 건너뛴다.
- 설정(쓰기 토큰·저장소 이름)은 관리자 페이지에서 넣는다 (DB 의 app_settings).
"""

import gzip
import json
import os
import shutil
import tempfile
import time
from datetime import datetime

KEEP_DAYS = 14
BATCH = 20


def run(db, upload_dir: str) -> dict:
    from huggingface_hub import CommitOperationAdd, CommitOperationDelete, HfApi

    token, repo = db.get_setting("backup_token"), db.get_setting("backup_repo")
    if not token or not repo:
        raise RuntimeError("백업 설정이 없어요.")
    api = HfApi(token=token)
    api.create_repo(repo, repo_type="dataset", private=True, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="lune-backup-")
    try:
        raw = os.path.join(tmp, "lune.db")
        db.backup_to(raw)
        packed = raw + ".gz"
        with open(raw, "rb") as src, gzip.open(packed, "wb", compresslevel=6) as dst:
            shutil.copyfileobj(src, dst)
        today = datetime.now().strftime("%Y-%m-%d")
        api.create_commit(repo, repo_type="dataset", commit_message=f"DB {today}", operations=[
            CommitOperationAdd(path_in_repo=f"db/lune-{today}.db.gz", path_or_fileobj=packed),
            CommitOperationAdd(path_in_repo="db/latest.db.gz", path_or_fileobj=packed)])

        sent: dict = json.loads(db.get_setting("backup_sent") or "{}")
        new = []
        if os.path.isdir(upload_dir):
            for name in sorted(os.listdir(upload_dir)):
                path = os.path.join(upload_dir, name)
                if not os.path.isfile(path) or name.endswith((".part", ".tmp")) or name.startswith("full-"):
                    continue
                stat = os.stat(path)
                if time.time() - stat.st_mtime < 600 or sent.get(name) == stat.st_size:
                    continue
                new.append((name, path, stat.st_size))
        for i in range(0, len(new), BATCH):
            part = new[i:i + BATCH]
            api.create_commit(repo, repo_type="dataset", commit_message=f"files {today} ({i + len(part)}/{len(new)})",
                              operations=[CommitOperationAdd(path_in_repo=f"uploads/{n}", path_or_fileobj=p) for n, p, _ in part])
            for n, _, size in part:
                sent[n] = size
            db.set_setting("backup_sent", json.dumps(sent))

        old = sorted(f for f in api.list_repo_files(repo, repo_type="dataset")
                     if f.startswith("db/lune-") and f.endswith(".db.gz"))[:-KEEP_DAYS]
        if old:
            api.create_commit(repo, repo_type="dataset", commit_message="오래된 DB 사본 정리",
                              operations=[CommitOperationDelete(path_in_repo=f) for f in old])
        result = {"at": time.time(), "files": len(new), "total_files": len(sent)}
        db.set_setting("backup_last", json.dumps(result))
        db.set_setting("backup_error", None)
        return result
    except Exception as exc:
        db.set_setting("backup_error", f"{type(exc).__name__}: {exc}"[:300])
        raise
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def due(db) -> bool:
    if not db.get_setting("backup_token"):
        return False
    last = json.loads(db.get_setting("backup_last") or "{}").get("at", 0)
    return time.time() - last > 23.5 * 3600
