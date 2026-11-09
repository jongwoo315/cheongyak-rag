"""Vercel 배포 설정 파일 (#85). 계정 없이 확인할 수 있는 것만 본다."""

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _json(rel: str) -> dict:
    return json.loads((REPO / rel).read_text(encoding="utf-8"))


def _lines(rel: str) -> set[str]:
    return {x.strip() for x in (REPO / rel).read_text(encoding="utf-8").splitlines() if x.strip()}


def test_root_vercel_json_pins_region_and_function_limits():
    cfg = _json("vercel.json")
    assert cfg["regions"] == ["sin1"]
    fn = cfg["functions"]["app.py"]
    assert fn["maxDuration"] == 300
    assert fn["excludeFiles"] == "{web/**,tests/**,docs/**,runs/**,data/**,alembic/**}"


def test_web_vercel_json_pins_region():
    assert _json("web/vercel.json")["regions"] == ["sin1"]


def test_python_version_file_is_3_12():
    assert (REPO / ".python-version").read_text(encoding="utf-8").strip().startswith("3.12")


def test_vercelignore_files_list_the_heavy_directories():
    assert _lines(".vercelignore") >= {"data/", "runs/", "docs/", "tests/", "web/", ".venv/"}
    assert _lines("web/.vercelignore") >= {"node_modules/", ".next/", "e2e/"}


def test_root_app_py_imports_the_fastapi_app_from_the_repo_root():
    # 패키지를 설치하지 않은 환경처럼 src를 PYTHONPATH 없이 찾는지 본다 (cwd = repo 루트)
    out = subprocess.run(
        [sys.executable, "-c", "import app; print(app.app.title)"],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "주택청약 RAG"


def test_root_app_py_puts_src_first_on_the_path():
    src = (REPO / "app.py").read_text(encoding="utf-8")
    assert "sys.path.insert(0," in src and "from cheongyak_rag.main import app" in src
