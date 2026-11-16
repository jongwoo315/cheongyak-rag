"""FAQ 인용 커버 리포트 (#135).

`law_report.faq_cross`가 인용 자리를 `ingest/citations.py`의 분류로 나눠 센다. 분류는 정규식이라
틀릴 수 있고 #131 정답 라벨도 같은 분류를 쓴다. 그래서 하위 에이전트가 분류 결과를 보지 않고
답변 원문을 읽어 인용 자리마다 법령 이름 라벨을 붙이고(`runs/135/law-names.jsonl`),
이 모듈이 분류와 법령 이름 라벨이 다른 자리를 센다.

    python -m cheongyak_rag.ingest.faq_cover_report inputs   라벨 붙일 입력 파일 (커밋 안 함)
    python -m cheongyak_rag.ingest.faq_cover_report merge    하위 에이전트 결과를 합쳐 검증
    python -m cheongyak_rag.ingest.faq_cover_report          docs/135-faq-cover.md를 쓴다

API·DB를 부르지 않는다. 읽는 것은 `data/processed`의 법령·FAQ JSONL과 `runs/135/`뿐이다
(실패 징후 3에서 `runs/golden.jsonl`도 읽는다).
"""

import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .citations import ARTICLE, extract_citations, sentence_of

ROOT = Path(__file__).resolve().parents[3]
RUNS_135 = ROOT / "runs" / "135"
INPUT_DIR = RUNS_135 / "inputs"  # 커밋하지 않는다
RAW_DIR = RUNS_135 / "raw"  # 하위 에이전트가 쓴 배치별 결과. 커밋하지 않는다
LABELS_PATH = RUNS_135 / "law-names.jsonl"
BATCH_PLACES = 40  # 하위 에이전트 한 명이 읽는 인용 자리 수(안팎)

LAW_LABELS = ("규칙", "다른 법령", "이름 없음", "모름")
LABEL_SIDE = {"규칙": "rule", "이름 없음": "rule", "다른 법령": "other", "모름": "unknown"}
CLASS_SIDE = {"rule": "rule", "none": "rule", "other": "other"}


def class_side(kind: str) -> str:
    """분류 rule·none은 규칙 인용, other는 다른 법령 인용이다."""
    return CLASS_SIDE[kind]


def label_side(law_label: str) -> str:
    return LABEL_SIDE[law_label]


@dataclass(frozen=True)
class Place:
    """FAQ 답변의 인용 자리 하나."""

    q_no: int
    no: int  # 그 쌍 안에서 몇 번째 자리인가(1부터)
    label: str
    kind: str  # 분류: rule | other | none
    name: str | None  # 분류가 따른 앞 법령 이름
    answer: str
    start: int
    end: int

    @property
    def sentence(self) -> str:
        s, e = sentence_of(self.answer, self.start)
        return self.answer[s:e].strip()

    @property
    def side(self) -> str:
        return class_side(self.kind)


def places(faq_rows: list[dict]) -> list[Place]:
    """답변마다 `extract_citations`가 낸 자리를 같은 순서로. 위치는 같은 정규식으로 다시 찾는다."""
    out = []
    for r in faq_rows:
        answer = r["answer"]
        cites = extract_citations(answer)
        spans = list(ARTICLE.finditer(answer))
        assert len(cites) == len(spans)  # extract_citations가 ARTICLE.finditer를 한 번씩 따라간다
        for i, (c, m) in enumerate(zip(cites, spans, strict=True), 1):
            out.append(Place(r["q_no"], i, c.label, c.kind, c.name, answer, m.start(), m.end()))
    return out


# ── 하위 에이전트에게 주는 입력 ───────────────────────────────────────────


def _context(p: Place) -> str:
    """앞 문장 + 이 자리가 든 문장(조를 【】로 표시) + 뒤 문장."""
    a = p.answer
    s, e = sentence_of(a, p.start)
    cur = a[s : p.start] + f"【{a[p.start : p.end]}】" + a[p.end : e]
    prev = a[sentence_of(a, s - 1)[0] : s] if s > 0 else ""
    nxt = a[e : sentence_of(a, e)[1]] if e < len(a) else ""
    return " ".join(x.strip() for x in (prev, cur, nxt) if x.strip())


def labeler_input(ps: list[Place]) -> list[dict]:
    """쌍 번호·답변 원문·자리마다 (순번, 조 라벨, 앞뒤 문장)만. 분류 결과는 안 준다."""
    pairs: dict[int, dict] = {}
    for p in ps:
        pair = pairs.setdefault(p.q_no, {"q_no": p.q_no, "answer": p.answer, "places": []})
        pair["places"].append({"no": p.no, "label": p.label, "context": _context(p)})
    return list(pairs.values())


def batches(pairs: list[dict], size: int = BATCH_PLACES) -> list[list[dict]]:
    """쌍을 쪼개지 않고, 인용 자리가 size에 닿으면 닫는다. size 반이 안 되는 끝은 앞에 붙인다."""
    out: list[list[dict]] = []
    cur: list[dict] = []
    count = 0
    for pair in pairs:
        cur.append(pair)
        count += len(pair["places"])
        if count >= size:
            out.append(cur)
            cur, count = [], 0
    if cur and out and count < size // 2:
        out[-1] += cur
        return out
    return out + ([cur] if cur else [])


# ── 법령 이름 라벨 검증 ───────────────────────────────────────────────────


def validate_labels(ps: list[Place], rows: list[dict]) -> list[str]:
    """라벨 줄이 인용 자리와 하나씩 같은 순서로 맞는지 본다. 문제를 문장으로 돌려준다."""
    problems = []
    if len(rows) != len(ps):
        problems.append(f"줄 수 {len(rows)} ≠ 인용 자리 수 {len(ps)}")
    for p, r in zip(ps, rows, strict=False):
        where = f"Q{p.q_no} 자리 {p.no} {p.label}"
        if (r.get("q_no"), r.get("no"), r.get("label")) != (p.q_no, p.no, p.label):
            problems.append(
                f"{where}: 줄의 (q_no, no, label) {r.get('q_no'), r.get('no'), r.get('label')}"
            )
            continue
        law_label = r.get("law_label")
        if law_label not in LAW_LABELS:
            problems.append(f"{where}: 법령 이름 라벨 {law_label!r}은 허용 값이 아니다")
        if (law_label == "다른 법령") != bool(r.get("law_name")):
            problems.append(f"{where}: 법령 이름은 라벨이 `다른 법령`일 때만 있어야 한다")
        if not str(r.get("evidence") or "").strip():
            problems.append(f"{where}: 근거 구절이 비었다")
    return problems


# ── 분류와 법령 이름 라벨 비교 ────────────────────────────────────────────


@dataclass(frozen=True)
class Diff:
    place: Place
    row: dict  # 법령 이름 라벨 줄


def disagreements(ps: list[Place], rows: list[dict]) -> tuple[list[Diff], list[Diff]]:
    """(규칙 인용 ↔ 다른 법령 인용이 갈린 자리, `모름`인 자리). `모름`은 갈린 것으로 안 센다."""
    diffs, unknown = [], []
    for p, r in zip(ps, rows, strict=True):
        side = label_side(r["law_label"])
        if side == "unknown":
            unknown.append(Diff(p, r))
        elif side != p.side:
            diffs.append(Diff(p, r))
    return diffs, unknown


def _gold(pairs_places: list[Place], flipped: Place | None = None, to: str = "") -> set[str]:
    """정답 조 집합 = 규칙 인용 자리의 조. 한 자리(flipped)만 `to`쪽으로 바꿔 본다."""
    return {p.label for p in pairs_places if (to if p is flipped else p.side) == "rule"}


def gold_changing(ps: list[Place], rows: list[dict], diffs: list[Diff]) -> list[Diff]:
    """그 한 자리를 법령 이름 라벨 쪽으로 바꾸면 그 쌍의 정답 조 집합이 달라지는 자리."""
    by_pair: dict[int, list[Place]] = {}
    for p in ps:
        by_pair.setdefault(p.q_no, []).append(p)
    out = []
    for d in diffs:
        pair = by_pair[d.place.q_no]
        flipped = _gold(pair, d.place, label_side(d.row["law_label"]))
        if flipped != _gold(pair):
            out.append(d)
    return out


def gold_pair_changes(
    ps: list[Place], rows: list[dict]
) -> list[tuple[int, set[str], set[str], set[str]]]:
    """법령 이름 라벨을 전부 따르면 정답 조 집합이 달라지는 쌍.

    (쌍 번호, 더해지는 조, 빠지는 조, 새 집합).

    `모름`은 분류 쪽을 그대로 둔다.
    """
    by_pair: dict[int, list[tuple[Place, str]]] = {}
    for p, r in zip(ps, rows, strict=True):
        side = label_side(r["law_label"])
        by_pair.setdefault(p.q_no, []).append((p, p.side if side == "unknown" else side))
    out = []
    for q_no, items in by_pair.items():
        old = {p.label for p, _ in items if p.side == "rule"}
        new = {p.label for p, side in items if side == "rule"}
        if old != new:
            out.append((q_no, new - old, old - new, new))
    return out


@dataclass
class LabelCover:
    rule_pairs: int  # 법령 이름 라벨로 규칙 인용이 하나 이상 있는 쌍
    uncovered: list[Place]  # 그 규칙 인용 중 현행에 없는 조의 자리

    @property
    def uncovered_pairs(self) -> int:
        return len({p.q_no for p in self.uncovered})


def label_based_cover(ps: list[Place], rows: list[dict], current: set[str]) -> LabelCover:
    """법령 이름 라벨이 `규칙`·`이름 없음`인 자리 중 현행 규칙에 없는 조를 센다."""
    rule_pairs: set[int] = set()
    uncovered = []
    for p, r in zip(ps, rows, strict=True):
        if label_side(r["law_label"]) != "rule":
            continue
        rule_pairs.add(p.q_no)
        if p.label not in current:
            uncovered.append(p)
    return LabelCover(len(rule_pairs), uncovered)


def even_sample(items: list, n: int) -> list:
    """순서대로 고르게(간격 뽑기). 목록을 n칸으로 똑같이 나눠 칸마다 첫 항목 하나씩 뽑는다."""
    if n <= 0 or not items:
        return []
    if len(items) <= n:
        return list(items)
    return [items[i * len(items) // n] for i in range(n)]


# ── 입력 파일·결과 합치기 ─────────────────────────────────────────────────


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def write_inputs(faq_rows: list[dict], out_dir: Path = INPUT_DIR) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for i, batch in enumerate(batches(labeler_input(places(faq_rows))), 1):
        path = out_dir / f"batch-{i:02d}.json"
        path.write_text(json.dumps(batch, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        paths.append(path)
    return paths


def merge_raw(faq_rows: list[dict], raw_dir: Path = RAW_DIR, out: Path = LABELS_PATH) -> list[str]:
    """배치별 결과(batch-NN.jsonl)를 이어 붙여 검증하고, 문제가 없으면 law-names.jsonl로 쓴다."""
    ps = places(faq_rows)
    rows = []
    for path in sorted(raw_dir.glob("batch-*.jsonl")):
        rows += load_jsonl(path)
    order = {(p.q_no, p.no): i for i, p in enumerate(ps)}
    rows.sort(key=lambda r: order.get((r.get("q_no"), r.get("no")), len(order)))
    problems = validate_labels(ps, rows)
    if not problems:
        out.parent.mkdir(parents=True, exist_ok=True)
        keys = ("q_no", "no", "label", "law_label", "law_name", "evidence")
        out.write_text(
            "".join(
                json.dumps({k: r.get(k) for k in keys}, ensure_ascii=False) + "\n" for r in rows
            ),
            encoding="utf-8",
        )
    return problems


# ── 실패 징후 구간 (plan §실패 징후) ──────────────────────────────────────

EXPECTED_NEW_COVER = (123, 123, 59)  # 착수 때 main: 규칙 인용 쌍 · 커버 · 다른 법령 인용만 있는 쌍
KICKOFF_BY_NUMBER = (182, 142, 40)  # 착수 때 번호로만 센 값: 인용 있는 쌍 · 커버 · 커버 안 됨
KICKOFF_PLACES = 415  # 착수 때 인용 자리 수 (규칙 183 · 다른 법령 171 · 이름 없음 61)


def band_sign1(n: int) -> str:
    return "통과" if n == 0 else "다시 잰다" if n <= 2 else "미완"


def band_sign2(n: int) -> str:
    return "정상" if n <= 4 else "다시 잰다" if n <= 20 else "미완"


def band_sign3(same: bool) -> str:
    return "정상" if same else "미완"


def band_sign4(got: tuple[int, int, int], want: tuple[int, int, int] = EXPECTED_NEW_COVER) -> str:
    return "정상" if got == want else "다시 잰다"


def golden_unchanged() -> bool:
    """지금 코드로 정답 라벨을 다시 만들어 `runs/golden.jsonl`과 글자 그대로 같은지 본다(cmp)."""
    from cheongyak_rag.retrieval.corpus import LAW_PATH, load_articles
    from cheongyak_rag.retrieval.golden import GOLDEN_PATH, build_golden, load_faq

    res = build_golden(load_faq(), {a.label for a in load_articles(LAW_PATH)})
    text = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in res.rows)
    return text == GOLDEN_PATH.read_text(encoding="utf-8")


# ── jw 표본 ──────────────────────────────────────────────────────────────

SAMPLE_OTHER_UNCOVERED = 10
SAMPLE_OTHER_IN_RULE = 5
SAMPLE_NONE = 5


def sample_groups(
    ps: list[Place], current: set[str], faq_rows: list[dict]
) -> tuple[list[Place], list[Place], list[Place]]:
    """표본 후보 세 목록(자리 순서). 첫째는 번호로만 센 커버 안 됨 쌍의 다른 법령 인용 중
    현행에 없는 조, 둘째는 조 번호가 현행에 있는 다른 법령 인용, 셋째는 분류가 이름 없음인 것."""
    from .law_report import _cited_labels

    old_uncovered = {
        r["q_no"] for r in faq_rows if any(lb not in current for lb in _cited_labels(r))
    }
    other = [p for p in ps if p.kind == "other"]
    return (
        [p for p in other if p.q_no in old_uncovered and p.label not in current],
        [p for p in other if p.label in current],
        [p for p in ps if p.kind == "none"],
    )


def sample_places(ps: list[Place], current: set[str], faq_rows: list[dict]) -> list[Place]:
    """jw가 직접 읽을 표본. 고르는 방법은 `even_sample`(순서대로 고르게)이다.

    - 다른 법령 인용 중 번호로만 센 커버 안 됨 쌍의 것(현행에 없는 조) 10
    - 다른 법령 인용 중 조 번호가 규칙에 있는 것 5
    - 분류가 `이름 없음`인 것 5
    """
    uncovered, in_rule, none = sample_groups(ps, current, faq_rows)
    return (
        even_sample(uncovered, SAMPLE_OTHER_UNCOVERED)
        + even_sample(in_rule, SAMPLE_OTHER_IN_RULE)
        + even_sample(none, SAMPLE_NONE)
    )


# ── 리포트 ───────────────────────────────────────────────────────────────


def _cell(text: str | None) -> str:
    return " ".join((text or "").split()).replace("|", "\\|")


def _class_text(p: Place) -> str:
    if p.kind == "other":
        return f"다른 법령 인용({_cell(p.name)})"
    return "규칙 인용(이름 없음)" if p.kind == "none" else f"규칙 인용({_cell(p.name)})"


def _label_text(r: dict) -> str:
    return f"{r['law_label']}({_cell(r['law_name'])})" if r.get("law_name") else r["law_label"]


def _pair_change_text(q: int, add: set[str], rem: set[str], new: set[str]) -> str:
    parts = []
    if add:
        parts.append(
            f"더해짐 {len(add)}개" + (f" {'·'.join(sorted(add))}" if len(add) <= 3 else "")
        )
    if rem:
        parts.append(f"빠짐 {len(rem)}개" + (f" {'·'.join(sorted(rem))}" if len(rem) <= 3 else ""))
    if not new:
        parts.append("정답이 비어 이 쌍은 정답 라벨에서 빠진다")
    return f"Q{q}({', '.join(parts)})"


def build_report(
    faq_rows: list[dict], law_rows: list[dict], label_rows: list[dict], golden_same: bool
) -> str:
    from .law_report import faq_cross

    current = {r["label"] for r in law_rows if not r["deleted"]}
    ps = places(faq_rows)
    cross = faq_cross(law_rows, faq_rows)
    lab = label_based_cover(ps, label_rows, current)
    diffs, unknown = disagreements(ps, label_rows)
    cover_changing = [d for d in diffs if d.place.label not in current]
    gold_changing_ = gold_changing(ps, label_rows, diffs)
    new_cover = (cross.rule_pairs, cross.covered_pairs, cross.other_only_pairs)
    sample = sample_places(ps, current, faq_rows)
    groups = sample_groups(ps, current, faq_rows)
    pair_changes = gold_pair_changes(ps, label_rows)
    by_place = {(p.q_no, p.no): r for p, r in zip(ps, label_rows, strict=True)}
    label_names = Counter(" ".join(r["law_name"].split()) for r in label_rows if r.get("law_name"))
    side_counts = {k: sum(1 for p in ps if p.kind == k) for k in ("rule", "other", "none")}
    label_counts = {k: sum(1 for r in label_rows if r["law_label"] == k) for k in LAW_LABELS}

    out = [
        "# #135 FAQ 인용 커버 — 법령 이름으로 센 값",
        "",
        "- 이 리포트는 `python -m cheongyak_rag.ingest.faq_cover_report`가 쓴다."
        " API·DB를 부르지 않고 `data/processed`의 법령·FAQ JSONL과"
        " `runs/135/law-names.jsonl`을 읽는다",
        "- 용어는 `docs/concepts.md` `## 용어` 절 그대로다."
        " 규칙 인용 = 같은 문장의 가장 가까운 앞 법령 이름이"
        " 주택공급에 관한 규칙이거나 이름이 없는 인용 자리",
        "- 법령 이름 라벨은 분류 결과를 보지 않은 하위 에이전트가 답변 원문을 읽고 붙였다."
        " **같은 모델이 읽은 것이라 완전히 독립된 확인이 아니다**",
        "- 하위 에이전트에게 `부칙 제N조`는 본문 조가 아니니 `다른 법령`으로 붙이라고 알려 줬다."
        " 분류의 부칙 처리와 같은 약속이라 이 맞댐으로는 부칙 처리를 검사하지 못한다",
        f"- 인용 자리 {len(ps)}개(착수 때 {KICKOFF_PLACES}). 분류: 규칙 {side_counts['rule']}"
        f" · 다른 법령 {side_counts['other']} · 이름 없음 {side_counts['none']}."
        f" 법령 이름 라벨: 규칙 {label_counts['규칙']} · 다른 법령 {label_counts['다른 법령']}"
        f" · 이름 없음 {label_counts['이름 없음']} · 모름 {label_counts['모름']}",
        "",
        "## 실패 징후",
        "",
        "| 징후 | 착수 때 값 | 이번 값 | 구간 |",
        "| --- | --- | --- | --- |",
        "| 1. jw 기준 — 규칙 인용인데 현행 규칙에 없는 조를 인용한 쌍 |"
        " 분류 기준 0/123 · 라벨 기준 없음 |"
        f" 라벨 기준 {lab.uncovered_pairs}/{lab.rule_pairs} · 분류 기준"
        f" {cross.uncovered_pairs}/{cross.rule_pairs} | {band_sign1(lab.uncovered_pairs)} |",
        f"| 2. 분류와 법령 이름 라벨이 다른 인용 자리 | 없음 | {len(diffs)}/{len(ps)}"
        f" (`모름` {len(unknown)}은 따로) | {band_sign2(len(diffs))} |",
        "| 3. #131 정답 라벨(`runs/golden.jsonl`)이 그대로인가 | 같다 |"
        f" {'같다' if golden_same else '다르다'}"
        f" | {band_sign3(golden_same)} |",
        "| 4. 새 커버 숫자 (규칙 인용 쌍 · 커버 · 다른 법령 인용만 있는 쌍) |"
        f" {' · '.join(map(str, EXPECTED_NEW_COVER))} | {' · '.join(map(str, new_cover))} |"
        f" {band_sign4(new_cover)} |",
        "",
        "- 구간: 징후 1은 0 통과 · 1~2 다시 잰다 · 3 이상 미완이다",
        "- 징후 2는 0~4 정상 · 5~20 다시 잰다 · 21 이상 미완이다",
        "- 징후 3은 같으면 정상 · 다르면 미완이다."
        " 지금 코드로 정답 라벨을 다시 만들어 파일과 글자 그대로 맞췄다",
        "- 징후 4는 세 값이 같으면 정상 · 다르면 다시 잰다",
        f"- 징후 1의 분모는 라벨 기준 {lab.rule_pairs}쌍, 분류 기준 {cross.rule_pairs}쌍이다."
        " 라벨이 규칙 인용으로 붙인 자리가 하나도 없는 쌍은 라벨 기준 분모에서 빠진다",
        f"- 징후 2에서 커버 판정을 바꾸는 자리(조가 현행 규칙에 없는 것) {len(cover_changing)}"
        " · #131 정답 라벨을 바꾸는 자리"
        "(그 한 자리만 라벨 쪽으로 바꾸면 그 쌍의 정답 조 집합이 달라진다)"
        f" {len(gold_changing_)}",
        "- 법령 이름 라벨을 전부 따르면 정답 조 집합이 달라지는 쌍 "
        f"{len(pair_changes)}: "
        + (" · ".join(_pair_change_text(*c) for c in pair_changes) or "없음"),
        "",
        "## 새 커버와 번호로만 센 커버",
        "",
        "| | 인용 있는 쌍 | 커버 | 커버 안 됨 | 분모 밖(다른 법령 인용만) |",
        "| --- | --- | --- | --- | --- |",
        f"| 번호로만 센 커버 (예전 셈, 착수 때 {' · '.join(map(str, KICKOFF_BY_NUMBER))}) |"
        f" {cross.by_number_cited} | {cross.by_number_covered}"
        f" | {cross.by_number_uncovered} | 없음 |",
        f"| 새 커버 (법령 이름으로 센다) | {cross.rule_pairs} | {cross.covered_pairs}"
        f" | {cross.uncovered_pairs} | {cross.other_only_pairs} |",
        "",
        f"- 새 커버: 규칙 인용 있는 쌍 {cross.rule_pairs} · 커버 {cross.covered_pairs}"
        f" · 커버 안 됨 {cross.uncovered_pairs}"
        f" · 다른 법령 인용만 있는 쌍 {cross.other_only_pairs}",
        f"- 다른 법령 인용 자리 {cross.other_places}. 앞 법령 이름별: "
        + " · ".join(f"{n} {c}" for n, c in cross.other_by_name.items()),
        "- 다른 법령 인용 자리를 법령 이름 라벨의 이름별로 센 값(공백 정리): "
        + (" · ".join(f"{n} {c}" for n, c in label_names.most_common()) or "없음"),
        "",
        "## 분류와 법령 이름 라벨이 다른 자리",
        "",
        f"{len(diffs)}자리. 분류가 규칙 인용인데 라벨이 다른 법령이거나 그 반대다."
        " 분류는 이번에 고치지 않는다.",
        "",
        "- 쌍마다 갈린 자리 수: "
        + (
            " · ".join(f"Q{q} {n}" for q, n in Counter(d.place.q_no for d in diffs).most_common())
            or "없음"
        ),
        "",
        "| 쌍 | 자리 | 조 | 분류 | 법령 이름 라벨 | 근거 구절 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    out += [
        f"| Q{d.place.q_no} | {d.place.no} | {d.place.label} | {_class_text(d.place)}"
        f" | {_label_text(d.row)} | {_cell(d.row['evidence'])} |"
        for d in diffs
    ]
    if not diffs:
        out.append("| (없음) | | | | | |")
    out += [
        "",
        f"## `모름`으로 붙은 자리 {len(unknown)}개 (갈린 것으로 안 센다)",
        "",
        "| 쌍 | 자리 | 조 | 분류 | 근거 구절 |",
        "| --- | --- | --- | --- | --- |",
    ]
    out += [
        f"| Q{d.place.q_no} | {d.place.no} | {d.place.label} | {_class_text(d.place)}"
        f" | {_cell(d.row['evidence'])} |"
        for d in unknown
    ]
    if not unknown:
        out.append("| (없음) | | | | |")
    if lab.uncovered:
        out += [
            "",
            "## 실패 징후 1에 걸린 쌍 (라벨 기준 규칙 인용인데 현행에 없는 조)",
            "",
            "예전 규칙 번호인지는 `law_versions`를 읽어야 확인되는데"
            " 이 리포트는 DB를 읽지 않는다. 확인하지 않았다.",
            "",
            "| 쌍 | 자리 | 조 | 문장 전체 | 분류 | 법령 이름 라벨 |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        out += [
            f"| Q{p.q_no} | {p.no} | {p.label} | {_cell(p.sentence)} | {_class_text(p)}"
            f" | {_label_text(by_place[(p.q_no, p.no)])} |"
            for p in lab.uncovered
        ]
    out += [
        "",
        f"## jw 표본 {len(sample)}자리",
        "",
        "고르는 방법: 순서대로 고르게(간격 뽑기). 후보 목록을 쌍 번호·자리 순서로 두고"
        " 후보를 n칸으로 똑같이 나눠 칸마다 첫 항목을 뽑았다(꼬리도 닿는다).",
        "- 다른 법령 인용 중 번호로만 센 커버 안 됨 쌍의 것(현행에 없는 조)"
        f" {SAMPLE_OTHER_UNCOVERED}개(후보 {len(groups[0])}자리. 착수 때 46은 쌍마다 같은 조를"
        " 한 번만 센 값이고 자리로 세면 이 수다)",
        f"- 다른 법령 인용 중 조 번호가 현행 규칙에 있는 것 {SAMPLE_OTHER_IN_RULE}개"
        f"(후보 {len(groups[1])}자리)",
        f"- 분류가 이름 없음인 것 {SAMPLE_NONE}개(후보 {len(groups[2])}자리)",
        "",
        "| 쌍 | 자리 | 조 | 문장 전체 | 분류 | 법령 이름 라벨 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    out += [
        f"| Q{p.q_no} | {p.no} | {p.label} | {_cell(p.sentence)} | {_class_text(p)}"
        f" | {_label_text(by_place[(p.q_no, p.no)])} |"
        for p in sample
    ]
    return "\n".join(out) + "\n"


REPORT_PATH = ROOT / "docs" / "135-faq-cover.md"


def main(argv: list[str] | None = None) -> int:
    from cheongyak_rag.retrieval.corpus import LAW_PATH
    from cheongyak_rag.retrieval.golden import load_faq

    args = sys.argv[1:] if argv is None else argv
    faq_rows = load_faq()
    if args[:1] == ["inputs"]:
        paths = write_inputs(faq_rows)
        print(f"입력 파일 {len(paths)}개 → {INPUT_DIR}")
        return 0
    if args[:1] == ["merge"]:
        problems = merge_raw(faq_rows)
        for line in problems:
            print(line, file=sys.stderr)
        print(f"문제 {len(problems)}건" if problems else f"문제 없음 → {LABELS_PATH}")
        return 1 if problems else 0
    label_rows = load_jsonl(LABELS_PATH)
    problems = validate_labels(places(faq_rows), label_rows)
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    text = build_report(faq_rows, load_jsonl(LAW_PATH), label_rows, golden_unchanged())
    REPORT_PATH.write_text(text, encoding="utf-8")
    print(f"리포트 → {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
