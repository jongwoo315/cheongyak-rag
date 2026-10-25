"""청약홈 APT 분양정보(공고·주택형)를 받아 Postgres `notices`·`notice_models`에 넣는다 (#71)."""

import argparse
import calendar
import hashlib
import json
import logging
import math
import sys
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import quote, unquote

import httpx
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Engine

from cheongyak_rag.config import settings

BASE_URL = "https://api.odcloud.kr/api/ApplyhomeInfoDetailSvc/v1"
OP_DETAIL = "getAPTLttotPblancDetail"
OP_MODELS = "getAPTLttotPblancMdl"
PER_PAGE = 1000
PACE = 0.1  # 요청 사이 간격(초)
BACKOFF = (1, 2, 4, 8)  # 429·5xx·연결 오류 재시도 대기(초). 최대 4회
SNIPPET = 200
RECHECK_LIMIT = 3  # 재조회해도 주택형이 없는 공고가 이만큼 쌓이면 그 뒤 공고는 재조회하지 않는다
DEFAULT_OUT = Path("runs/71/last_run.json")


class NoticeApiError(RuntimeError):
    """API가 정상 응답을 주지 않았다. 키·한도·서버 상태를 본다."""


# ── HTTP ─────────────────────────────────────────────────────────────────


def _secrets(key: str) -> list[str]:
    plain = unquote(key)
    forms = {key, plain, quote(plain, safe="")}
    return sorted((f for f in forms if f), key=len, reverse=True)


def _snippet(text: str, key: str) -> str:
    for s in _secrets(key):
        text = text.replace(s, "***")
    return text[:SNIPPET]


def _get(client: httpx.Client, url: str, params: dict, key: str, sleep) -> tuple[dict, int]:
    """한 요청. 재시도를 포함한 호출 수와 검증된 본문을 돌려준다."""
    calls = 0
    for attempt in range(len(BACKOFF) + 1):
        sleep(PACE)
        calls += 1
        try:
            resp = client.get(url, params=params)
        except httpx.HTTPError as e:  # 예외 문구에 키가 든 URL이 올 수 있다
            problem = f"{type(e).__name__}: {_snippet(str(e), key)}"
        else:
            if resp.status_code == 200:
                return _check(resp, key), calls
            problem = f"HTTP {resp.status_code}: {_snippet(resp.text, key)}"
            if resp.status_code not in (429, *range(500, 600)):
                raise NoticeApiError(problem) from None
        if attempt == len(BACKOFF):
            raise NoticeApiError(f"재시도 {len(BACKOFF)}회 뒤에도 실패: {problem}") from None
        sleep(BACKOFF[attempt])
    raise AssertionError("unreachable")


def _check(resp: httpx.Response, key: str) -> dict:
    try:
        body = resp.json()
    except ValueError:
        raise NoticeApiError(f"JSON이 아닌 응답: {_snippet(resp.text, key)}") from None
    if not (
        isinstance(body, dict)
        and isinstance(body.get("matchCount"), int)
        and isinstance(body.get("data"), list)
    ):
        raise NoticeApiError(f"응답에 matchCount·data가 없다: {_snippet(resp.text, key)}")
    return body


def fetch_all(
    op: str, client: httpx.Client, key: str, cond: dict, sleep=time.sleep
) -> tuple[list[dict], int, int]:
    """operation 하나를 끝까지 받는다 → (행, matchCount, 호출 수).

    페이지 수는 matchCount로 정한다. totalCount는 조건과 무관한 전체 건수라 쓰지 않는다.
    """
    url = f"{BASE_URL}/{op}"
    params = {"serviceKey": unquote(key), "perPage": PER_PAGE, **cond}
    body, calls = _get(client, url, {**params, "page": 1}, key, sleep)
    rows = list(body["data"])
    match = body["matchCount"]
    for page in range(2, math.ceil(match / PER_PAGE) + 1):
        body, n = _get(client, url, {**params, "page": page}, key, sleep)
        calls += n
        rows += body["data"]
    if len(rows) < match:
        # 빈 페이지에서 조용히 끝내면 일부만 적재하고도 성공으로 보인다
        raise NoticeApiError(f"{op}: matchCount {match}인데 {len(rows)}행만 받았다")
    return rows, match, calls


def since(today: date, months: int = 3) -> date:
    """달력 기준 N개월 전 같은 날. 그 달에 그날이 없으면 말일."""
    year, month0 = divmod(today.year * 12 + today.month - 1 - months, 12)
    month = month0 + 1
    return date(year, month, min(today.day, calendar.monthrange(year, month)[1]))


# ── 타입 변환 ────────────────────────────────────────────────────────────


def _text(v):
    return v if isinstance(v, str) else str(v)


def _int(v):
    if isinstance(v, bool):
        raise ValueError(v)
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    if isinstance(v, str) and v.strip().lstrip("-").isdigit():
        return int(v)
    raise ValueError(v)


def _num(v):
    try:
        d = Decimal(str(v).strip())
    except InvalidOperation:
        raise ValueError(v) from None
    if not d.is_finite():
        raise ValueError(v)
    return d


def _date(v):
    if not (isinstance(v, str) and len(v) == 10):
        raise ValueError(v)
    return datetime.strptime(v, "%Y-%m-%d").date()


def _yn(v):
    if v == "Y":
        return True
    if v == "N":
        return False
    raise ValueError(v)


# (열, API 키, 변환). 변환이 None이면 문자열 그대로(원문 보존용 텍스트 열)
_NOTICE_COLUMNS = [
    ("house_manage_no", "HOUSE_MANAGE_NO", None),
    ("pblanc_no", "PBLANC_NO", None),
    ("house_nm", "HOUSE_NM", None),
    ("house_secd", "HOUSE_SECD", None),
    ("house_dtl_secd", "HOUSE_DTL_SECD", None),
    ("rent_secd", "RENT_SECD", None),
    ("subscrpt_area_code", "SUBSCRPT_AREA_CODE", None),
    ("subscrpt_area_nm", "SUBSCRPT_AREA_CODE_NM", None),
    ("hssply_adres", "HSSPLY_ADRES", None),
    ("tot_suply_hshldco", "TOT_SUPLY_HSHLDCO", _int),
    ("rcrit_pblanc_de", "RCRIT_PBLANC_DE", _date),
    ("rcept_bgnde", "RCEPT_BGNDE", _date),
    ("rcept_endde", "RCEPT_ENDDE", _date),
    ("przwner_presnatn_de", "PRZWNER_PRESNATN_DE", _date),
    ("mvn_prearnge_ym", "MVN_PREARNGE_YM", None),
    ("speclt_rdn_earth_at", "SPECLT_RDN_EARTH_AT", _yn),
    ("mdat_trget_area_secd", "MDAT_TRGET_AREA_SECD", _yn),
    ("parcprc_uls_at", "PARCPRC_ULS_AT", _yn),
    ("public_house_earth_at", "PUBLIC_HOUSE_EARTH_AT", _yn),
    ("pblanc_url", "PBLANC_URL", None),
]
_NOTICE_REQUIRED = ("HOUSE_MANAGE_NO", "PBLANC_NO", "HOUSE_NM")

_MODEL_COLUMNS = [
    ("house_manage_no", "HOUSE_MANAGE_NO", None),
    ("pblanc_no", "PBLANC_NO", None),
    ("model_no", "MODEL_NO", None),
    ("house_ty", "HOUSE_TY", None),
    ("suply_ar", "SUPLY_AR", _num),
    ("suply_hshldco", "SUPLY_HSHLDCO", _int),
    ("spsply_hshldco", "SPSPLY_HSHLDCO", _int),
    ("lttot_top_amount", "LTTOT_TOP_AMOUNT", _int),  # 만원
]
_MODEL_REQUIRED = ("HOUSE_MANAGE_NO", "PBLANC_NO", "MODEL_NO")


@dataclass
class Converted:
    row: dict
    failed: list[tuple[str, object]] = field(
        default_factory=list
    )  # (API 키, 원문) — 값이 있는데 NULL이 된 것
    empty: int = 0  # 원문이 빈 값이라 NULL이 된 타입 열 수


def _convert(raw: dict, columns, required) -> Converted:
    missing = [k for k in required if raw.get(k) in (None, "")]
    if missing:
        raise ValueError(f"필수 필드가 없다: {', '.join(missing)}")
    out = Converted(row={})
    for col, src, conv in columns:
        v = raw.get(src)
        blank = v is None or (isinstance(v, str) and not v.strip())
        if conv is None:
            out.row[col] = None if blank else _text(v)
        elif blank:
            out.row[col] = None
            out.empty += 1
        else:
            try:
                out.row[col] = conv(v)
            except ValueError:
                out.row[col] = None
                out.failed.append((src, v))
    out.row["raw"] = raw
    return out


def to_notice_row(raw: dict) -> Converted:
    return _convert(raw, _NOTICE_COLUMNS, _NOTICE_REQUIRED)


def to_model_row(raw: dict) -> Converted:
    return _convert(raw, _MODEL_COLUMNS, _MODEL_REQUIRED)


# ── 적재 ─────────────────────────────────────────────────────────────────

_meta = sa.MetaData()
_TYPES = {None: sa.Text, _int: sa.Integer, _num: sa.Numeric, _date: sa.Date, _yn: sa.Boolean}


NOTICE_PK = ("house_manage_no", "pblanc_no")
MODEL_PK = (*NOTICE_PK, "model_no")


def _define(name: str, columns, pk: tuple[str, ...]) -> sa.Table:
    return sa.Table(
        name,
        _meta,
        *[sa.Column(col, _TYPES[conv], primary_key=col in pk) for col, _, conv in columns],
        sa.Column("raw", postgresql.JSONB, nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


NOTICES = _define("notices", _NOTICE_COLUMNS, NOTICE_PK)
MODELS = _define("notice_models", _MODEL_COLUMNS, MODEL_PK)
CHUNK = 500  # 한 문장에 넣는 행 수. 열 수 × 행 수가 바인드 파라미터 한도(65535)를 넘지 않게 한다


def upsert(engine: Engine, table: sa.Table, rows: list[dict]) -> tuple[int, int]:
    """PK가 같으면 고친다 → (넣은 수, 고친 수). 한 트랜잭션이라 실패하면 하나도 안 들어간다."""
    pk = [c.name for c in table.primary_key.columns]
    # 한 문장 안에서 PK가 겹치면 Postgres가 거부한다. 뒤의 행이 앞을 덮는다
    unique = {tuple(r[c] for c in pk): r for r in rows}
    rows = list(unique.values())
    inserted = updated = 0
    with engine.begin() as conn:
        for i in range(0, len(rows), CHUNK):
            stmt = pg_insert(table).values(rows[i : i + CHUNK])
            stmt = stmt.on_conflict_do_update(
                index_elements=pk,
                set_={
                    c.name: stmt.excluded[c.name]
                    for c in table.columns
                    if c.name not in pk and c.name != "fetched_at"
                }
                | {"fetched_at": sa.func.now()},
            ).returning(sa.literal_column("(xmax = 0)"))  # 새로 넣은 행만 xmax가 0이다
            flags = [r[0] for r in conn.execute(stmt)]
            inserted += sum(flags)
            updated += len(flags) - sum(flags)
    return inserted, updated


# ── 실행 ─────────────────────────────────────────────────────────────────


def _pk_str(*parts: str) -> str:
    return "/".join(parts)


def _table_state(engine: Engine, table: sa.Table) -> dict[tuple, dict]:
    pk = [table.c[c] for c in (MODEL_PK if table is MODELS else NOTICE_PK)]
    with engine.connect() as conn:
        return {tuple(r[:-1]): r[-1] for r in conn.execute(sa.select(*pk, table.c.raw))}


def _measure(engine: Engine, table: sa.Table, received: list[dict], pk_cols, extra: set) -> dict:
    """이번 실행이 받은 행이 테이블에 있는지, raw가 응답과 같은 키를 가졌는지."""
    state = _table_state(engine, table)
    got = {tuple(r[c] for c in pk_cols): r["raw"] for r in received}
    missing = sorted(k for k in got if k not in state)
    diff = sorted(k for k, raw in got.items() if k in state and set(state[k]) != set(raw))
    digest = hashlib.sha1("\n".join(sorted(_pk_str(*k) for k in state)).encode()).hexdigest()
    return {
        "received": len(received),
        "in_table": len(got) - len(missing),
        "missing": [_pk_str(*k) for k in missing],
        "extra": sorted(_pk_str(*k) for k in extra - set(got)),
        "raw_same": sum(1 for k in got if k in state) - len(diff),
        "raw_diff": [_pk_str(*k) for k in diff],
        "rows_after": len(state),
        "pk_digest": digest,
    }


def _expected_calls(match: int) -> int:
    return max(1, math.ceil(match / PER_PAGE))


def _collect(engine: Engine, client, key: str, cutoff: date, sleep) -> dict:
    started = time.monotonic()
    raws, n_match, c_detail = fetch_all(
        OP_DETAIL, client, key, {"cond[RCRIT_PBLANC_DE::GTE]": cutoff.isoformat()}, sleep
    )
    if n_match == 0:
        # 2026-10-23 실측: 상류가 HTTP 200에 totalCount 0으로 전부 비워 돌려준 적이 있다
        raise NoticeApiError(
            f"모집공고일 {cutoff} 이후 공고가 matchCount 0이다. API 상태를 확인할 것"
        )
    notices = [to_notice_row(r) for r in raws]

    model_raws: list[dict] = []
    m_match = c_models = retries = 0
    per_notice: dict[tuple, int] = {}
    for r in raws:
        pk = (r["HOUSE_MANAGE_NO"], r["PBLANC_NO"])
        rows, match, calls = fetch_all(OP_MODELS, client, key, _model_cond(pk), sleep)
        model_raws += rows
        per_notice[pk] = len(rows)
        m_match += match
        c_models += calls
        retries += max(0, calls - _expected_calls(match))
    retries += max(0, c_detail - _expected_calls(n_match))

    # 주택형이 0개인 공고는 한 번 더 물어 일시적인 누락인지 본다. 두 번째에 받았으면 그 행을 쓴다
    no_models, c_recheck = [], 0
    for pk, n in per_notice.items():
        if n:
            continue
        entry = {"pk": _pk_str(*pk), "recheck_match_count": None}
        if len(no_models) < RECHECK_LIMIT:
            rows, match, calls = fetch_all(OP_MODELS, client, key, _model_cond(pk), sleep)
            c_recheck += calls
            entry["recheck_match_count"] = match
            if rows:
                model_raws += rows
                m_match += match
                continue
        no_models.append(entry)
    if not model_raws:
        # 공고는 받았는데 주택형이 전부 비면 상류가 비워 돌려준 것이다 (위 matchCount 0 방어와 같다)
        raise NoticeApiError("받은 공고 전부에 주택형이 없다. API 상태를 확인할 것")
    models = [to_model_row(r) for r in model_raws]

    n_ins, n_upd = upsert(engine, NOTICES, [c.row for c in notices])
    m_ins, m_upd = upsert(engine, MODELS, [c.row for c in models])

    window = {
        tuple(r)
        for r in _select_pks(engine, NOTICES, NOTICES.c.rcrit_pblanc_de >= cutoff, NOTICE_PK)
    }
    got_notices = {pk for pk in per_notice}
    in_models = {
        tuple(r) for r in _select_pks(engine, MODELS, None, MODEL_PK) if (r[0], r[1]) in got_notices
    }
    n_stat = _measure(engine, NOTICES, [c.row for c in notices], NOTICE_PK, window)
    m_stat = _measure(engine, MODELS, [c.row for c in models], MODEL_PK, in_models)
    n_stat |= {"match_count": n_match, "inserted": n_ins, "updated": n_upd}
    m_stat |= {"match_count": m_match, "inserted": m_ins, "updated": m_upd}

    failed = [
        {"table": t, "pk": _pk_str(*(c.row[k] for k in pk)), "column": col, "value": str(v)}
        for t, pk, convs in (("notices", NOTICE_PK, notices), ("notice_models", MODEL_PK, models))
        for c in convs
        for col, v in c.failed
    ]
    total = c_detail + c_models + c_recheck
    return {
        "run_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "elapsed_sec": round(time.monotonic() - started, 1),
        "since": cutoff.isoformat(),
        "calls": {
            "detail": c_detail,
            "models": c_models,
            "recheck": c_recheck,
            "total": total,
            "retries": retries,
        },
        "notices": n_stat,
        "models": m_stat,
        "convert": {"empty": sum(c.empty for c in notices + models), "failed": failed},
        "no_models": no_models,
        "response_keys": {
            "notices": sorted({k for r in raws for k in r}),
            "models": sorted({k for r in model_raws for k in r}),
        },
    }


def _model_cond(pk: tuple) -> dict:
    return {"cond[HOUSE_MANAGE_NO::EQ]": pk[0], "cond[PBLANC_NO::EQ]": pk[1]}


def _select_pks(engine: Engine, table: sa.Table, where, pk_cols) -> list[tuple]:
    stmt = sa.select(*[table.c[c] for c in pk_cols])
    if where is not None:
        stmt = stmt.where(where)
    with engine.connect() as conn:
        return [tuple(r) for r in conn.execute(stmt)]


def _previous(path: Path) -> dict | None:
    try:
        old = json.loads(path.read_text(encoding="utf-8"))
        return {
            "run_at": old["run_at"],
            "notices_rows_after": old["notices"]["rows_after"],
            "models_rows_after": old["models"]["rows_after"],
            "notices_pk_digest": old["notices"]["pk_digest"],
            "models_pk_digest": old["models"]["pk_digest"],
            "notices_inserted": old["notices"]["inserted"],
            "models_inserted": old["models"]["inserted"],
        }
    except (OSError, ValueError, KeyError):
        return None


def _print_summary(s: dict, months: int) -> None:
    c, n, m = s["calls"], s["notices"], s["models"]
    print(f"기간: 모집공고일 {s['since']} 이후 ({months}개월)")
    print(
        f"호출: 총 {c['total']} (상세 {c['detail']} · 주택형 {c['models']}"
        f" · 재조회 {c['recheck']}) · 재시도 {c['retries']} · {s['elapsed_sec']}초"
    )
    for name, t in (("공고", n), ("주택형", m)):
        print(
            f"{name}: 받은 행 {t['received']} · matchCount {t['match_count']}"
            f" · 넣은 행 {t['inserted']} · 고친 행 {t['updated']}"
            f" · 테이블에 있는 수 {t['in_table']} · 테이블 전체 {t['rows_after']}"
        )
    print(f"주택형 없는 공고: {len(s['no_models'])}")
    print(f"타입 변환: 실패 {len(s['convert']['failed'])} · 빈 값 {s['convert']['empty']}")


def main(argv=None, client=None, engine=None, sleep=time.sleep, today=None) -> int:
    ap = argparse.ArgumentParser(description="청약홈 APT 공고·주택형을 notices 테이블에 적재")
    ap.add_argument("--months", type=int, default=3, help="모집공고일 기준 최근 N개월")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="실행 요약 JSON 경로")
    args = ap.parse_args(argv)

    key = settings.data_go_kr_key.strip()
    if not key:
        print("DATA_GO_KR_KEY가 비어 있다. .env에 data.go.kr 인증키를 넣을 것", file=sys.stderr)
        return 1
    # httpx는 INFO로 요청 URL(serviceKey 포함)을 찍는다
    logging.getLogger("httpx").setLevel(logging.WARNING)

    cutoff = since(today or date.today(), args.months)
    own_client, own_engine = client is None, engine is None
    client = client or httpx.Client(timeout=60)
    engine = engine or sa.create_engine(settings.database_url)
    try:
        summary = _collect(engine, client, key, cutoff, sleep)
    except (NoticeApiError, ValueError) as e:
        print(f"수집 실패: {e}", file=sys.stderr)
        return 1
    finally:
        if own_client:
            client.close()
        if own_engine:
            engine.dispose()

    summary["months"] = args.months
    summary["previous"] = _previous(args.out)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.out.with_suffix(args.out.suffix + ".part")
    try:
        tmp.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(args.out)
    finally:
        tmp.unlink(missing_ok=True)
    _print_summary(summary, args.months)
    # 받은 행이 테이블에 다 있어야 성공이다.
    # 페이지 사이에 같은 PK가 두 번 오면 한 행으로 합쳐져 모자란다
    short = [
        f"{name} {t['received']}행 받았는데 테이블에 {t['in_table']}행"
        for name, t in (("공고", summary["notices"]), ("주택형", summary["models"]))
        if t["received"] != t["in_table"]
    ]
    if short:
        print("적재 불일치: " + " · ".join(short), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
