"""공고 하나를 요건 7축으로 쪼개고 축마다 조문·FAQ를 따로 검색한다 (#79).

    python -m cheongyak_rag.retrieval.axes <house_manage_no> [--pblanc-no N] [-k 5] [--faq-k 3]

축 하나 = 하위 질의 하나(특별공급 유형별 축은 유형마다 하나) = 검색 하나.
켜는 조건은 공고 데이터로만 정한다(`plan`). 검색(`search`)은 `chunks` 테이블에서 조문은 공고의
법령 버전(MST) 행만 거르고, dense는 DB `nearest`, BM25는 앱, 합치기는 `search.rrf`다.
"""

from dataclasses import dataclass, field
from typing import NamedTuple

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from cheongyak_rag.retrieval import index_db
from cheongyak_rag.retrieval.chunk import Chunk
from cheongyak_rag.retrieval.chunk_eval import _Doc, article_view
from cheongyak_rag.retrieval.search import BM25, rrf

# `notice_models.raw`의 유형별 특별공급 세대수 키 → 하위 질의에 끼우는 유형 이름
SPECIAL_TYPES = (
    ("MNYCH_HSHLDCO", "다자녀가구"),
    ("NWWDS_HSHLDCO", "신혼부부"),
    ("LFE_FRST_HSHLDCO", "생애최초"),
    ("OLD_PARNTS_SUPORT_HSHLDCO", "노부모 부양"),
    ("INSTT_RECOMEND_HSHLDCO", "기관추천"),
    ("YGMN_HSHLDCO", "청년"),
    ("NWBB_HSHLDCO", "신생아"),
    ("TRANSR_INSTT_ENFSN_HSHLDCO", "이전기관 종사자"),
)
OLD_PARENTS = "OLD_PARNTS_SUPORT_HSHLDCO"

# 규제 표시 칸 → 이유 문장에 쓰는 이름
REGULATION_FLAGS = (
    ("speclt_rdn_earth_at", "투기과열지구"),
    ("mdat_trget_area_secd", "청약과열지역"),
    ("parcprc_uls_at", "분양가상한제"),
    ("public_house_earth_at", "공공택지"),
)

# 하위 질의 문장. FAQ 질문 말투로 쓴다. 리포트가 이 문장을 그대로 싣는다
Q_HOMELESS = "무주택 세대구성원 기준과 주택 소유 여부 판정은 어떻게 하나요?"
Q_ACCOUNT = "청약통장 가입 기간과 예치금 기준은 어떻게 되나요?"
Q_RESIDENCE = "{area} 지역 거주 요건과 거주 기간은 어떻게 되나요?"
Q_RESIDENCE_NO_AREA = "해당 주택건설지역 거주 요건과 거주 기간은 어떻게 되나요?"
Q_INCOME_ASSET = "특별공급의 소득 기준과 자산 기준은 어떻게 되나요?"
Q_REWIN = "재당첨 제한 대상 주택과 제한 기간은 어떻게 되나요?"
Q_HOUSEHOLDER = "세대주만 청약할 수 있나요? 세대주 요건은 무엇인가요?"
Q_SPECIAL = "{type} 특별공급의 신청 자격과 요건은 어떻게 되나요?"
# 유형별 세대수가 전부 0일 때
Q_SPECIAL_NO_TYPE = "특별공급 유형별 신청 자격과 요건은 어떻게 되나요?"

# 기대 조(설계 §2). 구현 전에 조 제목만 보고 정했고 결과를 보고 바꾸지 않는다
SPECIAL_LABELS = (
    "제35조",
    "제35조의2",
    "제35조의3",
    *(f"제{n}조" for n in range(36, 48)),
)


@dataclass(frozen=True)
class AxisDef:
    id: str
    name: str
    condition: str  # 켜는 조건(사람이 읽는 문장)
    expected: tuple[str, ...]  # 기대 조 — 조문 상위 k개에 하나라도 있으면 든 것


AXES = (
    AxisDef("homeless", "무주택 여부·기간", "항상", ("제53조",)),
    AxisDef("account", "청약통장", "항상", ("제9조", "제10조", "제27조", "제28조")),
    AxisDef("residence", "거주지역·거주기간", "항상", ("제4조", "제34조")),
    AxisDef(
        "income_asset",
        "소득·자산(특별공급)",
        "공고 주택형의 특별공급 세대수 합 > 0",
        ("제35조", "제41조", "제43조", "제46조"),
    ),
    AxisDef(
        "rewin",
        "재당첨제한",
        "투기과열지구·청약과열지역·분양가상한제·공공택지 표시 중 하나라도 참",
        ("제54조",),
    ),
    AxisDef(
        "householder",
        "세대주 여부",
        "투기과열지구·청약과열지역 표시 중 하나라도 참, 또는 노부모 부양 특별공급 세대수 > 0",
        ("제2조", "제28조"),
    ),
    AxisDef(
        "special_type",
        "특별공급 유형별 요건",
        "공고 주택형의 특별공급 세대수 합 > 0",
        SPECIAL_LABELS,
    ),
)
AXIS_BY_ID = {a.id: a for a in AXES}


@dataclass(frozen=True)
class AxisPlan:
    id: str
    name: str
    on: bool
    reason: str  # 왜 켜졌나/꺼졌나 한 줄
    queries: list[str] = field(default_factory=list)  # 꺼진 축은 비어 있다
    law_mst: str | None = None

    @property
    def line(self) -> str:
        return f"{self.name}: {'켜짐' if self.on else '꺼짐'} — {self.reason}"


class Facts(NamedTuple):
    """켜는 조건이 보는 공고 값."""

    area: str | None
    flags: dict[str, bool]  # REGULATION_FLAGS의 칸 → 참/거짓(null은 거짓)
    special: int  # 주택형의 특별공급 세대수 합
    by_type: dict[str, int]  # SPECIAL_TYPES의 키 → 세대수 합
    law_mst: str | None


def load_facts(engine: Engine, house_manage_no: str, pblanc_no: str | None = None) -> tuple:
    """공고 하나의 켜는 조건 값 → (pblanc_no, 공고명, Facts). 공고가 없으면 LookupError."""
    sums = ", ".join(
        f"coalesce(sum(nullif(m.raw->>'{key}', '')::int), 0) AS {key.lower()}"
        for key, _ in SPECIAL_TYPES
    )
    flag_cols = ", ".join(f"n.{c}" for c, _ in REGULATION_FLAGS)
    sql = sa.text(
        f"SELECT n.pblanc_no, n.house_nm, n.subscrpt_area_nm, {flag_cols}, v.mst,"
        f" coalesce(sum(m.spsply_hshldco), 0) AS special, {sums}"
        " FROM notices n"
        " LEFT JOIN notice_models m USING (house_manage_no, pblanc_no)"
        " JOIN notice_law_versions v USING (house_manage_no, pblanc_no)"
        " WHERE n.house_manage_no = :h AND (CAST(:p AS text) IS NULL OR n.pblanc_no = :p)"
        " GROUP BY n.pblanc_no, n.house_nm, n.subscrpt_area_nm, " + flag_cols + ", v.mst"
        " ORDER BY n.pblanc_no LIMIT 1"
    )
    with engine.connect() as conn:
        row = conn.execute(sql, {"h": house_manage_no, "p": pblanc_no}).mappings().first()
    if row is None:
        raise LookupError(f"공고 {house_manage_no} (pblanc_no={pblanc_no}) 없음")
    facts = Facts(
        area=row["subscrpt_area_nm"],
        flags={c: bool(row[c]) for c, _ in REGULATION_FLAGS},
        special=int(row["special"]),
        by_type={key: int(row[key.lower()]) for key, _ in SPECIAL_TYPES},
        law_mst=row["mst"],
    )
    return row["pblanc_no"], row["house_nm"], facts


def _flag_names(facts: Facts, columns: tuple[str, ...]) -> list[str]:
    names = dict(REGULATION_FLAGS)
    return [names[c] for c in columns if facts.flags[c]]


def _decide(axis_id: str, facts: Facts) -> tuple[bool, str, list[str]]:
    """축 하나의 (켜짐, 이유, 하위 질의)."""
    if axis_id == "homeless":
        return True, "항상 켜는 축", [Q_HOMELESS]
    if axis_id == "account":
        return True, "항상 켜는 축", [Q_ACCOUNT]
    if axis_id == "residence":
        q = Q_RESIDENCE.format(area=facts.area) if facts.area else Q_RESIDENCE_NO_AREA
        return True, "항상 켜는 축", [q]
    if axis_id in ("income_asset", "special_type"):
        if facts.special <= 0:
            return False, "특별공급 세대수 합 0", []
        reason = f"특별공급 세대수 합 {facts.special}"
        if axis_id == "income_asset":
            return True, reason, [Q_INCOME_ASSET]
        types = [name for key, name in SPECIAL_TYPES if facts.by_type[key] > 0]
        return True, reason, [Q_SPECIAL.format(type=t) for t in types] or [Q_SPECIAL_NO_TYPE]
    if axis_id == "rewin":
        on = _flag_names(facts, tuple(c for c, _ in REGULATION_FLAGS))
        if not on:
            return False, "투기과열·청약과열·분양가상한제·공공택지 표시 모두 거짓", []
        return True, "·".join(on) + " 표시 참", [Q_REWIN]
    if axis_id == "householder":
        on = _flag_names(facts, ("speclt_rdn_earth_at", "mdat_trget_area_secd"))
        parents = facts.by_type[OLD_PARENTS]
        if on:
            reason = "·".join(on) + " 표시 참(제28조제1항제1호다목 세대주 요건)"
            return True, reason, [Q_HOUSEHOLDER]
        if parents > 0:
            reason = f"노부모 부양 특별공급 세대수 {parents}(제46조 세대주 한정)"
            return True, reason, [Q_HOUSEHOLDER]
        return False, "투기과열·청약과열 표시 모두 거짓이고 노부모 부양 특별공급 세대수 0", []
    raise KeyError(axis_id)


def plan(engine: Engine, house_manage_no: str, pblanc_no: str | None = None) -> list[AxisPlan]:
    """공고 하나의 축 7개 — 켜짐 여부·이유·하위 질의·법령 버전(MST). 공고가 없으면 LookupError."""
    return plan_from_facts(load_facts(engine, house_manage_no, pblanc_no)[2])


def plan_from_facts(facts: Facts) -> list[AxisPlan]:
    out = []
    for axis in AXES:
        on, reason, queries = _decide(axis.id, facts)
        out.append(AxisPlan(axis.id, axis.name, on, reason, queries, facts.law_mst))
    return out


# ── 축별 검색 ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class QueryHits:
    """하위 질의 하나의 검색 결과. `law_pool`은 조문 후보 행 수, `law_dense`는 dense가 낸 행 수."""

    query: str
    law: list[Chunk]
    faq: list[Chunk]
    law_pool: int = 0
    law_dense: int = 0


@dataclass(frozen=True)
class AxisResult:
    id: str
    name: str
    hits: list[QueryHits]


@dataclass
class _Corpus:
    """(source, MST) 하나의 청크와 BM25. 만드는 데 형태소 분석이 들어서 한 번만 만든다."""

    by_id: dict[str, Chunk]
    bm25: BM25 | None  # 행이 없으면 None


Cache = dict[tuple[str, str | None], _Corpus]


def _corpus(engine: Engine, source: str, mst: str | None, cache: Cache) -> _Corpus:
    key = (source, mst)
    if key not in cache:
        sql = "SELECT chunk_id, label, path, title, text FROM chunks WHERE source = :s"
        params = {"s": source}
        if mst is not None:
            sql += " AND law_mst = :m"
            params["m"] = mst
        with engine.connect() as conn:
            rows = conn.execute(sa.text(sql + " ORDER BY chunk_id"), params).all()
        chunks = [
            Chunk(r.chunk_id, r.label, r.path, r.text, source, {"title": r.title}) for r in rows
        ]
        bm25 = BM25([_Doc(c.chunk_id, c.text) for c in chunks]) if chunks else None
        cache[key] = _Corpus({c.chunk_id: c for c in chunks}, bm25)
    return cache[key]


def _law_top(corpus: _Corpus, dense_ids: list[str], query: str, k: int) -> list[Chunk]:
    """`query.Index.search`와 같다: 청크 순위를 조 순위로 줄여 RRF로 합치고 조마다 한 청크."""
    by_id = corpus.by_id
    bm_labels, bm_paths = article_view([by_id[x] for x in corpus.bm25.rank(query)])
    dn_labels, dn_paths = article_view([by_id[x] for x in dense_ids])
    by_path = {c.path: c for c in by_id.values()}
    out = []
    for label, _ in rrf([bm_labels, dn_labels])[:k]:
        bm_rank = bm_labels.index(label) if label in bm_paths else len(by_id)
        dn_rank = dn_labels.index(label) if label in dn_paths else len(by_id)
        out.append(by_path[bm_paths[label] if bm_rank <= dn_rank else dn_paths[label]])
    return out


def _faq_top(corpus: _Corpus, dense_ids: list[str], query: str, k: int) -> list[Chunk]:
    hybrid = [x for x, _ in rrf([corpus.bm25.rank(query), dense_ids])]
    return [corpus.by_id[x] for x in hybrid[:k]]


def search(
    engine: Engine,
    embedder,
    house_manage_no: str,
    pblanc_no: str | None = None,
    *,
    k: int = 5,
    faq_k: int = 3,
    plans: list[AxisPlan] | None = None,
    cache: Cache | None = None,
) -> list[AxisResult]:
    """켜진 축마다 하위 질의별 조문 상위 k개·FAQ 상위 faq_k개. `plans`·`cache`는 반복 호출용이다.

    조문은 공고의 법령 버전(MST) 행만 후보로 삼는다. MST를 못 정했으면 조문은 비어 있다.
    """
    plans = plans or plan(engine, house_manage_no, pblanc_no)
    cache = {} if cache is None else cache
    on = [p for p in plans if p.on]
    queries = list(dict.fromkeys(q for p in on for q in p.queries))
    if not queries:
        return []
    vecs = dict(zip(queries, embedder.embed(queries), strict=True))  # 한 번에 묶어 임베딩한다
    mst = plans[0].law_mst
    law = _corpus(engine, "law", mst, cache) if mst is not None else None
    faq = _corpus(engine, "faq", None, cache)
    out = []
    for p in on:
        hits = []
        for q in p.queries:
            law_hits, pool, n_dense = [], 0, 0
            if law is not None and law.bm25 is not None:
                pool = len(law.by_id)
                dense = [c for c, _ in index_db.nearest(engine, vecs[q], "law", pool, law_mst=mst)]
                n_dense = len(dense)
                law_hits = _law_top(law, dense, q, k)
            faq_hits = []
            if faq.bm25 is not None:
                dense = [c for c, _ in index_db.nearest(engine, vecs[q], "faq", len(faq.by_id))]
                faq_hits = _faq_top(faq, dense, q, faq_k)
            hits.append(QueryHits(q, law_hits, faq_hits, pool, n_dense))
        out.append(AxisResult(p.id, p.name, hits))
    return out
