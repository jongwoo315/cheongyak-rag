"""run 줄에서 지표 7개를 센다 (#76). 정의는 설계 §3.3.

지표 함수 하나가 지표 하나다. 값은 `{"value", "num", "den"}`이고 분모가 0이면 value는 None이다
(판정 정확도만 `{"total": 값, "axes": {축: 값}}`이다).
못 맞춘 라벨(`matched=false`)은 시스템 칸이 비어 있어서 분모에는 남고 분자에는 못 든다.
citation precision만 예외다 — 분모가 시스템이 인용한 조문이라 못 맞춘 라벨은 분모에도 없다.
"""

ABSTAIN = ("NEED_INFO", "UNVERIFIABLE")  # 판정을 내리지 않은 최종 판정
DECISIVE_GOLD = ("ELIGIBLE", "INELIGIBLE")
ITEM_FAILED = (
    "공고 판정 실패"  # 문항 하나가 통째로 실패한 줄의 `cause` 앞머리. run이 쓰고 counts가 센다
)


def is_law(label: str) -> bool:
    """조문 라벨은 `제53조` 꼴, FAQ 라벨은 `Q47` 꼴이다."""
    return label.startswith("제")


def ratio(num: int, den: int) -> dict:
    return {"value": num / den if den else None, "num": num, "den": den}


def _count(rows: list[dict], pick, hit) -> dict:
    """`pick`에 든 줄 중 `hit`인 줄의 비율."""
    chosen = [r for r in rows if pick(r)]
    return ratio(sum(1 for r in chosen if hit(r)), len(chosen))


def recall_at_5(rows: list[dict]) -> dict:
    """정답 근거 조문 (라벨, 조) 쌍 중 시스템 조문 검색 top-5에 든 쌍의 비율."""
    pairs = [(r, c) for r in rows for c in r["gold_citations"]]
    return ratio(sum(1 for r, c in pairs if c in r["law_top5"]), len(pairs))


def hit_at_5(rows: list[dict]) -> dict:
    """정답 근거 조문이 하나라도 top-5에 든 정답 라벨의 비율."""
    return ratio(sum(1 for r in rows if set(r["gold_citations"]) & set(r["law_top5"])), len(rows))


def citation_precision(rows: list[dict]) -> dict:
    """시스템이 인용한 조문 라벨 중 정답 근거 조문에 있는 것의 비율. FAQ 인용은 뺀다."""
    cites = [(r, c) for r in rows for c in r["sys_citations"] if is_law(c)]
    return ratio(sum(1 for r, c in cites if c in r["gold_citations"]), len(cites))


def judgment_accuracy(rows: list[dict]) -> dict:
    """시스템 최종 판정값이 정답 라벨 판정값과 같은 비율. 축마다 + 전체.

    판정이 없거나 실패한 줄(sys_verdict가 None)은 틀린 것으로 센다.
    """
    hit: dict[str, list[int]] = {}
    for r in rows:
        n = hit.setdefault(r["axis"], [0, 0])
        n[1] += 1
        n[0] += r["sys_verdict"] is not None and r["sys_verdict"] == r["gold_verdict"]
    return {
        "total": ratio(sum(n[0] for n in hit.values()), sum(n[1] for n in hit.values())),
        "axes": {a: ratio(*n) for a, n in sorted(hit.items())},
    }


def fatal_error_rate(rows: list[dict]) -> dict:
    """정답이 INELIGIBLE인 라벨 중 시스템이 ELIGIBLE을 낸 비율."""
    return _count(
        rows, lambda r: r["gold_verdict"] == "INELIGIBLE", lambda r: r["sys_verdict"] == "ELIGIBLE"
    )


def justified_abstain(rows: list[dict]) -> dict:
    """정답이 NEED_INFO인 라벨 중 시스템도 abstain한 비율."""
    return _count(
        rows, lambda r: r["gold_verdict"] == "NEED_INFO", lambda r: r["sys_verdict"] in ABSTAIN
    )


def unjustified_abstain(rows: list[dict]) -> dict:
    """정답이 ELIGIBLE·INELIGIBLE인 라벨 중 시스템이 abstain한 비율."""
    return _count(
        rows, lambda r: r["gold_verdict"] in DECISIVE_GOLD, lambda r: r["sys_verdict"] in ABSTAIN
    )


def compute(rows: list[dict]) -> dict:
    return {
        "recall_at_5": recall_at_5(rows),
        "hit_at_5": hit_at_5(rows),
        "citation_precision": citation_precision(rows),
        "judgment_accuracy": judgment_accuracy(rows),
        "fatal_error_rate": fatal_error_rate(rows),
        "justified_abstain": justified_abstain(rows),
        "unjustified_abstain": unjustified_abstain(rows),
    }


def counts(rows: list[dict]) -> dict:
    """지표 옆에 같이 내는 수. `search_incomplete`는 실패 징후 1의 값이다."""
    unmatched = sum(1 for r in rows if not r["matched"])
    no_law = sum(1 for r in rows if r["matched"] and not r["law_top5"])
    return {
        "labels": len(rows),
        "unmatched_labels": unmatched,
        "no_law_results": no_law,
        "search_incomplete": unmatched + no_law,
        "item_failures": sum(1 for r in rows if (r["cause"] or "").startswith(ITEM_FAILED)),
        "verdict_errors": sum(1 for r in rows if r["error"]),
        "faq_citations": sum(1 for r in rows for c in r["sys_citations"] if not is_law(c)),
    }
