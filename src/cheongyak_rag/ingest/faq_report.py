"""FAQ 파싱 결과를 목차와 맞대고, 답변 경계·길이를 점검하는 리포트 (#70)."""

import re
import statistics
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .faq import BodyStats, FaqPair, TocEntry

SECTION_FIELDS = ("major", "middle", "minor", "question")
SHORT_ANSWER, LONG_ANSWER = 30, 3000


def _collapse(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _squash(s: str) -> str:
    return re.sub(r"\s+", "", s)


@dataclass
class Mismatch:
    q_no: int
    page: int | None
    field: str
    toc: str
    body: str


@dataclass
class Leak:
    q_no: int
    kind: str  # 머리말 | 목차 제목 | 다음 질문
    detail: str


@dataclass
class Report:
    pair_count: int
    q_no_ok: bool
    mismatches: list[Mismatch]  # 공백을 전부 빼고 비교해도 다른 것
    spacing_diffs: list[Mismatch]  # 공백 연속만 합쳐 비교했을 때만 다른 것
    leaks: list[Leak]
    length_min: int
    length_median: float
    length_max: int
    outliers: list[tuple[int, int]]  # (q_no, 글자 수)
    table_count: int
    skipped_pages: int
    skipped_chars: int
    warnings: int


def _compare(
    toc: "list[TocEntry]", pairs: "list[FaqPair]"
) -> tuple[list[Mismatch], list[Mismatch]]:
    by_q = {e.q_no: e for e in toc}
    mismatches, spacing = [], []
    seen = set()
    for p in pairs:
        e = by_q.get(p.q_no)
        if e is None:
            mismatches.append(Mismatch(p.q_no, p.page_start, "q_no", "(목차에 없음)", str(p.q_no)))
            continue
        seen.add(p.q_no)
        for f in SECTION_FIELDS:
            t, b = getattr(e, f), getattr(p, f)
            if _squash(t) != _squash(b):
                mismatches.append(Mismatch(p.q_no, p.page_start, f, t, b))
            elif _collapse(t) != _collapse(b):
                spacing.append(Mismatch(p.q_no, p.page_start, f, t, b))
    for e in toc:
        if e.q_no not in seen:
            mismatches.append(Mismatch(e.q_no, None, "q_no", str(e.q_no), "(쌍 없음)"))
    return sorted(mismatches, key=lambda m: m.q_no), spacing


def _leaks(toc: "list[TocEntry]", pairs: "list[FaqPair]") -> list[Leak]:
    majors = {e.major for e in toc}
    titles = {t for e in toc for t in (e.middle, e.minor) if t}
    next_question = {e.q_no - 1: e.question for e in toc}
    leaks = []
    for p in pairs:
        # 머리말·제목은 줄 전체로 나온다. 문장 속 `2. 입주자모집`과 안 겹치게 줄 단위로 본다
        lines = {_squash(ln) for ln in p.answer.splitlines()}
        leaks += [Leak(p.q_no, "머리말", m) for m in sorted(majors) if _squash(m) in lines]
        leaks += [Leak(p.q_no, "목차 제목", t) for t in sorted(titles) if _squash(t) in lines]
        nq = next_question.get(p.q_no)
        if nq and _squash(nq) in _squash(p.answer):
            leaks.append(Leak(p.q_no, "다음 질문", nq))
    return leaks


def build_report(
    toc: "list[TocEntry]", pairs: "list[FaqPair]", stats: "BodyStats", warnings: int
) -> Report:
    q_nos = [p.q_no for p in pairs]
    lengths = [len(p.answer) for p in pairs] or [0]
    mismatches, spacing = _compare(toc, pairs)
    return Report(
        pair_count=len(pairs),
        q_no_ok=bool(q_nos) and q_nos == list(range(1, len(pairs) + 1)),
        mismatches=mismatches,
        spacing_diffs=spacing,
        leaks=_leaks(toc, pairs),
        length_min=min(lengths),
        length_median=statistics.median(lengths),
        length_max=max(lengths),
        outliers=[
            (p.q_no, len(p.answer))
            for p in pairs
            if len(p.answer) < SHORT_ANSWER or len(p.answer) > LONG_ANSWER
        ],
        table_count=len(stats.table_q_nos),
        skipped_pages=len(stats.skipped_pages),
        skipped_chars=stats.skipped_chars,
        warnings=warnings,
    )


def format_report(r: Report) -> str:
    out = [
        "== FAQ 파싱 리포트 ==",
        f"쌍 수: {r.pair_count} (q_no 1..N 연속·중복 없음: {'예' if r.q_no_ok else '아니오'})",
        "",
        "섹션 불일치 (목차 대조, 공백 전부 제거 후 비교): "
        f"{len({m.q_no for m in r.mismatches})}쌍 (필드 {len(r.mismatches)}개)",
    ]
    out += [
        f"  Q{m.q_no} p{m.page} {m.field}: 목차={m.toc!r} 본문={m.body!r}" for m in r.mismatches
    ]
    spacing_qs = sorted({m.q_no for m in r.spacing_diffs})
    out += [
        f"  (참고) 공백 연속만 합친 엄격 비교에서만 다른 쌍: {len(spacing_qs)}건",
        "    전부 공백 차이다. 줄바꿈 지점에서 빠진 공백과 PDF 인쇄 차이가 섞여 있다",
    ]
    out += [f"    Q{m.q_no} p{m.page}: 목차={m.toc!r} 본문={m.body!r}" for m in r.spacing_diffs]
    leak_qs = sorted({leak.q_no for leak in r.leaks})
    out += ["", f"답변 경계 새는 쌍: {len(leak_qs)}건"]
    out += [f"  Q{leak.q_no} [{leak.kind}] {leak.detail!r}" for leak in r.leaks]
    out += [
        "",
        f"답변 길이(글자): 최소 {r.length_min} / 중앙값 {r.length_median:g} / 최대 {r.length_max}",
        f"  {SHORT_ANSWER}자 미만 또는 {LONG_ANSWER}자 초과: {len(r.outliers)}건",
    ]
    out += [f"  Q{q}: {n}자" for q, n in r.outliers]
    out += [
        "",
        f"표가 섞인 답변(9pt 미만 글자가 있는 것만 셈 — 하한): {r.table_count}건",
        f"건너뛴 주요내용 등 질문 없는 본문: {r.skipped_pages}쪽, {r.skipped_chars}자",
        f"PyMuPDF 경고: {r.warnings}건",
    ]
    return "\n".join(out)
