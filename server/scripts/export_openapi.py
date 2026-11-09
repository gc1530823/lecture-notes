"""서버 API 명세(OpenAPI)를 파일로 뽑는다. 웹 프론트는 이 파일에서 TypeScript 타입을 만든다 (web: npm run api:types).

사용법 (server 폴더에서): python scripts/export_openapi.py ../web/openapi.json
"""

import json
import os
import sys

os.environ.setdefault("LLM_MODE", "fake")
os.environ.setdefault("STT_MODE", "fake")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.main import app  # noqa: E402

with open(sys.argv[1] if len(sys.argv) > 1 else "openapi.json", "w") as f:
    json.dump(app.openapi(), f, ensure_ascii=False, indent=2)
    f.write("\n")
