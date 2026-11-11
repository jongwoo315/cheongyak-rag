"""run 줄에서 지표를 센다 (#76). 설계 §3.3.

지표 함수 하나가 지표 하나다. 값은 `{"value", "num", "den"}`이고 분모가 0이면 value는 None이다.
"""


def ratio(num: int, den: int) -> dict:
    return {"value": num / den if den else None, "num": num, "den": den}


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


def compute(rows: list[dict]) -> dict:
    return {"judgment_accuracy": judgment_accuracy(rows)}
