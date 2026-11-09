"""Vercel Python 함수 진입점 (#85). Vercel이 repo 루트 `app.py`의 `app`을 찾는다.

`src/` 아래 패키지가 설치돼 있든 아니든 import되도록 `src`를 경로 맨 앞에 넣는다.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from cheongyak_rag.main import app  # noqa: E402

__all__ = ["app"]
