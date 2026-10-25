"""「주택공급에 관한 규칙」 시행일별 버전 목록을 법제처 eflaw 검색에서 받아 넣는다 (#78).

받은 행은 `law_versions`에 upsert한다.

행 하나 = (MST, 시행일). 같은 MST가 단계 시행으로 시행일 둘 이상에 나오고, 같은 시행일에 MST가
둘 이상인 날도 있다. 공고별로 어느 행을 쓸지는 view `notice_law_versions`가 정한다
(마이그레이션 0003).
HTTP·OC 처리는 `law.py`의 것을 그대로 쓴다.
"""

import argparse
import hashlib
import json
import logging
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

import httpx
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import Engine

from cheongyak_rag.config import settings
from cheongyak_rag.ingest import notice
from cheongyak_rag.ingest.law import (
    LAW_NAME,
    SEARCH_URL,
    LawApiError,
    _get_json,
    _require_oc,
    _snippet,
)

DISPLAY = 100
MAX_PAGES = 20  # 실측 2페이지. 페이지 넘김이 끝나지 않는 결함을 에러로 끊는다
DEFAULT_OUT = Path("runs/78/law_versions.json")

_meta = sa.MetaData()
LAW_VERSIONS = sa.Table(
    "law_versions",
    _meta,
    sa.Column("law_id", sa.Text, primary_key=True),
    sa.Column("mst", sa.Text, primary_key=True),
    sa.Column("effective_date", sa.Date, primary_key=True),
    sa.Column("promulgation_date", sa.Date),
    sa.Column("promulgation_no", sa.Text),
    sa.Column("law_name", sa.Text),
    sa.Column("revision_kind", sa.Text),
    sa.Column("status", sa.Text),
    sa.Column("raw", postgresql.JSONB, nullable=False),
    sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
)


def _key(raw: dict) -> tuple[str, str, str]:
    return raw.get("법령ID", ""), raw.get("법령일련번호", ""), raw.get("시행일자", "")


def fetch_versions(oc: str, client: httpx.Client | None = None) -> tuple[list[dict], int]:
    """목록을 끝까지 읽어 법령명이 정확히 일치하는 행만 돌려준다 → (행, 읽은 페이지 수).

    totalCnt는 이름이 비슷한 다른 법령까지 센 값이라 우리 행 수 대신 읽은 전체 행 수와 맞춰 본다.
    한 페이지가 DISPLAY행보다 적으면 마지막이다.
    """
    oc = _require_oc(oc)
    own = client is None
    client = client or httpx.Client(timeout=60)
    rows: list[dict] = []
    seen = total = 0
    try:
        for page in range(1, MAX_PAGES + 1):
            params = {
                "OC": oc,
                "target": "eflaw",
                "query": LAW_NAME.replace(" ", ""),
                "display": DISPLAY,
                "page": page,
                "type": "JSON",
            }
            body = _get_json(client, SEARCH_URL, params, oc)
            search = body.get("LawSearch")
            if not isinstance(search, dict):
                # 빈 페이지에서 조용히 끝내면 앞 페이지만 넣고 성공으로 보인다
                detail = _snippet(json.dumps(body, ensure_ascii=False), oc)
                raise LawApiError(f"{page}페이지 응답에 LawSearch가 없다: {detail}")
            if page == 1:
                try:
                    total = int(search["totalCnt"])
                except (KeyError, ValueError):
                    raise LawApiError("1페이지 응답의 totalCnt를 읽지 못했다") from None
            found = search.get("law", [])
            found = [found] if isinstance(found, dict) else found  # 결과가 하나면 dict로 온다
            seen += len(found)
            rows += [r for r in found if r.get("법령명한글") == LAW_NAME]
            if len(found) < DISPLAY:
                break
        else:
            raise LawApiError(f"{MAX_PAGES}페이지를 읽어도 끝나지 않는다. 페이지 넘김을 확인할 것")
    finally:
        if own:
            client.close()
    if seen != total:
        # totalCnt는 이름이 비슷한 다른 법령까지 센 값이다.
        # 우리 행 수가 아니라 읽은 전체 행 수와 같아야 한다
        raise LawApiError(f"totalCnt {total}인데 {seen}행만 읽었다. 목록이 끊겼을 수 있다")
    if not rows:
        raise LawApiError(f"법령명이 {LAW_NAME!r}인 행이 하나도 없다. 검색 응답을 확인할 것")
    if len({_key(r) for r in rows}) != len(rows):
        # 페이지 사이에 목록이 밀리면 같은 행이 두 번 오고 다른 행이 빠진다
        raise LawApiError(
            "(MST, 시행일)이 같은 행이 중복으로 왔다. 목록이 읽는 동안 바뀌었을 수 있다"
        )
    return rows, page


def _mask(node, oc: str):
    """응답 행의 `법령상세링크`에 OC가 들어 있다. DB에 키가 남지 않게 가린다."""
    if isinstance(node, str):
        return node.replace(oc, "***")
    if isinstance(node, list):
        return [_mask(n, oc) for n in node]
    if isinstance(node, dict):
        return {k: _mask(v, oc) for k, v in node.items()}
    return node


def _ymd(v: str | None) -> date | None:
    if not v:
        return None
    return datetime.strptime(v, "%Y%m%d").date()


def to_row(raw: dict, oc: str) -> dict:
    try:
        effective = _ymd(raw.get("시행일자"))
        promulgation = _ymd(raw.get("공포일자"))
    except ValueError as e:
        raise LawApiError(f"날짜를 읽지 못했다 (MST {raw.get('법령일련번호')}): {e}") from None
    if effective is None or not raw.get("법령ID") or not raw.get("법령일련번호"):
        raise LawApiError(f"법령ID·법령일련번호·시행일자가 빠진 행이다: MST {_key(raw)[1]!r}")
    return {
        "law_id": raw["법령ID"],
        "mst": raw["법령일련번호"],
        "effective_date": effective,
        "promulgation_date": promulgation,
        "promulgation_no": raw.get("공포번호") or None,
        "law_name": raw.get("법령명한글"),
        "revision_kind": raw.get("제개정구분명") or None,
        "status": raw.get("현행연혁코드") or None,
        "raw": _mask(raw, oc),
    }


def _same_day_multi_mst(rows: list[dict]) -> list[dict]:
    by_day: dict[date, set[str]] = defaultdict(set)
    for r in rows:
        by_day[r["effective_date"]].add(r["mst"])
    return [
        {"effective_date": d.isoformat(), "msts": sorted(m)}
        for d, m in sorted(by_day.items(), reverse=True)
        if len(m) > 1
    ]


def _table_state(engine: Engine) -> tuple[int, str]:
    """테이블 전체 행 수와 PK 집합 해시. 재실행 때 같은지 본다."""
    t = LAW_VERSIONS.c
    with engine.connect() as conn:
        pks = [tuple(r) for r in conn.execute(sa.select(t.law_id, t.mst, t.effective_date))]
    digest = hashlib.sha1("\n".join(sorted("/".join(map(str, p)) for p in pks)).encode())
    return len(pks), digest.hexdigest()


def _previous(path: Path) -> dict | None:
    try:
        old = json.loads(path.read_text(encoding="utf-8"))
        return {
            "run_at": old["run_at"],
            "rows_after": old["rows_after"],
            "pk_digest": old["pk_digest"],
            "inserted": old["inserted"],
        }
    except (OSError, ValueError, KeyError):
        return None


def main(argv=None, client: httpx.Client | None = None, engine: Engine | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="주택공급에 관한 규칙 시행일별 버전을 law_versions에 적재"
    )
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="실행 요약 JSON 경로")
    args = ap.parse_args(argv)

    oc = settings.law_oc.strip()
    # httpx는 INFO로 요청 URL(OC 포함)을 찍는다
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        raws, pages = fetch_versions(oc, client)
        rows = [to_row(r, oc) for r in raws]
    except LawApiError as e:
        print(f"API 오류: {e}", file=sys.stderr)
        return 1

    own = engine is None
    engine = engine or sa.create_engine(settings.database_url)
    try:
        # 지우지 않는다. 법제처가 기존 행의 시행일을 옮기면 옛 행이 남는데,
        # asof의 본문 대조가 어긋남으로 잡는다
        inserted, updated = notice.upsert(engine, LAW_VERSIONS, rows)
        rows_after, digest = _table_state(engine)
    finally:
        if own:
            engine.dispose()

    dates = [r["effective_date"] for r in rows]
    summary = {
        "run_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "received": len(rows),
        "pages": pages,
        "calls": pages,
        "inserted": inserted,
        "updated": updated,
        "duplicates": 0,  # 중복이 오면 fetch_versions가 에러로 멈춘다
        "rows_after": rows_after,
        "pk_digest": digest,
        "oldest": min(dates).isoformat(),
        "newest": max(dates).isoformat(),
        "same_day_multi_mst": _same_day_multi_mst(rows),
        "previous": _previous(args.out),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.out.with_suffix(args.out.suffix + ".part")
    try:
        tmp.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(args.out)
    finally:
        tmp.unlink(missing_ok=True)

    print(f"받은 행: {len(rows)} (법령명 일치) · 페이지 {pages} · 호출 {pages}")
    print(f"넣은 행 {inserted} · 고친 행 {updated} · 테이블 전체 {rows_after}")
    print(
        f"시행일 {summary['oldest']} ~ {summary['newest']}"
        f" · 같은 날 여러 MST {len(summary['same_day_multi_mst'])}일"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
