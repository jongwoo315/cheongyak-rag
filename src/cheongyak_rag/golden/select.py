"""골든셋에 쓸 공고 20건을 고른다 (#75).

    python -m cheongyak_rag.golden.select [--out runs/75/notices.json]

기준(설계 §3.5): #80 표본 공고 중 공고문 PDF가 있는 것을 먼저 넣고, 나머지는 켜지는 축 조합·특별공급
유형 8개·규제 표시 4종·수도권/비수도권·지역이 새로 들어오는 공고를 앞에서부터 채운다.
같은 입력이면 같은 결과다 — 점수가 같으면 관리번호가 작은 쪽이다.
DB는 SELECT만 하고 공고문 목록은 `data/raw/notices/manifest.jsonl`에서 읽는다.
"""

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from cheongyak_rag.config import settings
from cheongyak_rag.retrieval import axes

TARGET = 20
METRO = ("서울", "경기", "인천")
# #80 표본 공고(`runs/80/last_run.json`) 중 공고문 PDF가 있는 5건. 2026820006은 LH라 없다
FIXED = ("2026000103", "2026000202", "2026000314", "2026000401", "2026000444")
MANIFEST = Path("data/raw/notices/manifest.jsonl")
DEFAULT_OUT = Path("runs/75/notices.json")
MIN_PER_REGION_KIND = 8  # 수도권·비수도권 각각 최소 몇 건


@dataclass(frozen=True)
class Candidate:
    house_manage_no: str
    pblanc_no: str
    name: str
    area: str | None
    as_of: str  # 모집공고일 YYYY-MM-DD
    axes: tuple[str, ...]  # 켜지는 축 id
    types: frozenset[str]  # 세대수가 있는 특별공급 유형 이름
    flags: tuple[str, ...]  # 참인 규제 표시 칸(DB)

    @property
    def metro(self) -> bool:
        return self.area in METRO

    def to_dict(self) -> dict:
        d = asdict(self)
        d["types"] = sorted(self.types)
        d["axes"] = list(self.axes)
        d["flags"] = list(self.flags)
        d["metro"] = self.metro
        return d


def _gain(c: Candidate, chosen: list[Candidate]) -> int:
    combos = {x.axes for x in chosen}
    types = {t for x in chosen for t in x.types}
    flags = {f for x in chosen for f in x.flags}
    areas = {x.area for x in chosen}
    metro = sum(x.metro for x in chosen)
    other = len(chosen) - metro
    g = 100 * (c.axes not in combos) + 10 * len(c.types - types) + 5 * len(set(c.flags) - flags)
    if c.metro and metro < MIN_PER_REGION_KIND or not c.metro and other < MIN_PER_REGION_KIND:
        g += 3
    return g + (c.area not in areas)


def select(candidates: list[Candidate], fixed: list[str] | tuple[str, ...]) -> list[Candidate]:
    """고정 공고를 앞에 두고 `TARGET`건이 될 때까지 가장 많이 새로 채우는 공고를 하나씩 더한다."""
    by_no = {c.house_manage_no: c for c in candidates}
    chosen = [by_no[no] for no in fixed]  # 없으면 KeyError
    rest = sorted(
        (c for c in candidates if c.house_manage_no not in set(fixed)),
        key=lambda c: c.house_manage_no,
    )
    while len(chosen) < TARGET and rest:
        best = max(rest, key=lambda c: (_gain(c, chosen), -rest.index(c)))
        chosen.append(best)
        rest.remove(best)
    return chosen


# ── DB·목록 읽기 ────────────────────────────────────────────────────────


def pdf_notices(manifest: Path = MANIFEST) -> dict[str, dict]:
    """공고문 수집 결과가 `pdf`인 공고 → 목록 줄. 한 공고에 링크가 여럿이면 첫 PDF 줄이다."""
    out: dict[str, dict] = {}
    for line in manifest.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row["result"] == "pdf":
            out.setdefault(row["house_manage_no"], row)
    return out


def load_candidates(engine: Engine, with_pdf: set[str]) -> list[Candidate]:
    with engine.connect() as conn:
        rows = conn.execute(
            sa.text(
                "SELECT house_manage_no, pblanc_no, rcrit_pblanc_de FROM notices"
                " ORDER BY house_manage_no, pblanc_no"
            )
        ).all()
    out = []
    for h, p, de in rows:
        if h not in with_pdf:
            continue
        pblanc_no, name, facts = axes.load_facts(engine, h, p)
        on = tuple(a.id for a in axes.plan_from_facts(facts) if a.on)
        types = frozenset(n for k, n in axes.SPECIAL_TYPES if facts.by_type[k] > 0)
        flags = tuple(c for c, _ in axes.REGULATION_FLAGS if facts.flags[c])
        out.append(Candidate(h, pblanc_no, name, facts.area, de.isoformat(), on, types, flags))
    return out


def build(engine: Engine, manifest: Path = MANIFEST) -> dict:
    pdfs = pdf_notices(manifest)
    chosen = select(load_candidates(engine, set(pdfs)), FIXED)
    notices = []
    for c in chosen:
        row = pdfs[c.house_manage_no]
        notices.append(
            {
                **c.to_dict(),
                "fixed": c.house_manage_no in FIXED,
                "pdf": row["path"],
                "pages": row["pages"],
            }
        )
    covered = {
        "axis_combos": sorted({"+".join(c.axes) for c in chosen}),
        "special_types": sorted({t for c in chosen for t in c.types}),
        "regulation_flags": sorted({f for c in chosen for f in c.flags}),
        "metro": sum(c.metro for c in chosen),
        "non_metro": sum(not c.metro for c in chosen),
        "areas": sorted({c.area for c in chosen if c.area}),
    }
    criteria = {
        "target": TARGET,
        "fixed": list(FIXED),
        "fixed_source": "#80 표본 공고 6건 중 공고문 PDF가 있는 5건(runs/80/last_run.json)",
        "pool": f"공고문 PDF가 있는 공고 {len(pdfs)}건",
        "rule": (
            "고정 5건 뒤에, 켜지는 축 조합(100점)·특별공급 유형(건당 10점)·"
            "규제 표시 종류(건당 5점)·수도권/비수도권 각 8건까지(3점)·새 지역(1점)을 "
            "가장 많이 채우는 공고를 하나씩 더한다. 점수가 같으면 관리번호가 작은 쪽이다."
        ),
        "covered": covered,
    }
    return {"criteria": criteria, "notices": notices}


def merge_existing(new: dict, old: dict) -> dict:
    """다시 돌려도 Task 3이 더한 `facts`·`db_mismatch`가 지워지지 않게 같은 공고에 옮긴다."""
    keep = {n["house_manage_no"]: n for n in old.get("notices", [])}
    for n in new["notices"]:
        prev = keep.get(n["house_manage_no"], {})
        for key in ("facts", "db_mismatch"):
            if key in prev:
                n[key] = prev[key]
    return new


def main(argv: list[str] | None = None, *, engine: Engine | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cheongyak_rag.golden.select")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--manifest", type=Path, default=MANIFEST)
    args = ap.parse_args(argv)
    own = engine is None
    engine = engine or sa.create_engine(settings.database_url)
    try:
        result = build(engine, args.manifest)
        if args.out.exists():
            result = merge_existing(result, json.loads(args.out.read_text(encoding="utf-8")))
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", "utf-8")
        print(f"{len(result['notices'])}건 → {args.out}")
        return 0
    finally:
        if own:
            engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
