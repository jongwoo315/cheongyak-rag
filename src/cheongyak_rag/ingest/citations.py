"""FAQ 답변의 `제N조` 인용을 법령 이름으로 나누는 분류 (#131에서 만들고 #135에서 옮겼다).

#70 파서의 `cited_articles`는 법령 이름이 없어 「주택법」 제2조도 규칙 제2조로 잡는다.
답변 원문에서 인용 자리마다 같은 문장 안의 가장 가까운 앞 법령 이름을 찾아 셋으로 나눈다.

    rule  규칙 — 정답에 넣는다
    other 다른 법령 — 안 넣는다 (셈만 한다)
    none  이름 없음 — FAQ가 청약 FAQ라 규칙으로 보고 넣는다

#131 정답 라벨(`retrieval/golden.py`)과 #135 FAQ 인용 커버 리포트(`ingest/law_report.py`)가
같은 함수를 쓴다. 두 곳이 다른 규칙으로 세면 정답 라벨과 리포트가 다시 갈린다.
"""

import re
from dataclasses import dataclass

BEFORE_CHARS = 60

ARTICLE = re.compile(r"제\s?(\d+)\s?조(?:\s?의\s?(\d+))?")
# 문장 끝(`다.` `요.`)과 목록 항목의 시작. 목록 번호 `1.` `가.`의 마침표는 끝으로 안 본다
SENTENCE_END = re.compile(r"(?<=[가-힣)”’\"'])(?<!\s[가-힣])[.?!](?=\s|$)")
LIST_START = re.compile(r"\n\s*(?:\d+[.)]|[가-힣][.)]|[①-⑳]|[-*▴○●ㆍ·※])\s")
# 「…」 ｢…｣ 안의 이름, 또는 법·령·규칙으로 끝나는 낱말, 또는 낱말 `영`
NAME = re.compile(
    r"[「｢](?P<b>[^」｣]*)[」｣]"
    r"|(?<![가-힣])(?P<w>[가-힣]*(?:시행령|시행규칙|규칙|법|령)|영)(?![가-힣])"
)
ADDENDA = re.compile(r"부\s*칙\s*$")  # `부칙 제6조`는 본문 제6조가 아니다
RULE_BRACKET = ("주택공급에관한규칙", "주택공급규칙")
RULE_WORDS = {"규칙", "동규칙"}  # 낱말 `규칙` 앞의 `이`·`같은`·`동`은 따로 안 봐도 규칙이다


@dataclass(frozen=True)
class Citation:
    label: str
    kind: str  # rule | other | none
    before: str  # 인용 앞 글자 (표본 출력용)
    name: str | None = None  # 분류가 따른 앞 법령 이름. 이름이 없으면 None. 부칙이면 `부칙`


def _name_kind(m: re.Match) -> str | None:
    if m["b"] is not None:
        name = re.sub(r"\s", "", m["b"])
        return "rule" if name.startswith(RULE_BRACKET) else "other"
    word = m["w"]
    if word.endswith(
        ("방법", "부령")
    ):  # 「공개의 방법」, `국토교통부령 제512호`는 법령 이름이 아니다
        return None
    is_rule = word in RULE_WORDS or ("주택공급" in word and word.endswith("규칙"))
    return "rule" if is_rule or word.endswith("공급규칙") else "other"


def _name_text(m: re.Match) -> str:
    return re.sub(r"\s+", " ", m["b"]).strip() if m["b"] is not None else m["w"]


def _sentence_start(text: str, pos: int) -> int:
    cuts = [m.end() for m in SENTENCE_END.finditer(text, 0, pos)]
    cuts += [m.start() + 1 for m in LIST_START.finditer(text, 0, pos)]
    return max(cuts, default=0)


def extract_citations(answer: str) -> list[Citation]:
    """답변의 `제N조` 인용을 등장 순서대로. 항·호는 뗀다. 중복은 그대로 둔다(인용 자리 수)."""
    out = []
    for m in ARTICLE.finditer(answer):
        start = _sentence_start(answer, m.start())
        sentence = answer[start : m.start()]
        kind, name = "none", None
        for nm in NAME.finditer(sentence):
            if found := _name_kind(nm):  # 가장 가까운(마지막) 이름을 따른다
                kind, name = found, _name_text(nm)
        if ADDENDA.search(answer[: m.start()]):
            kind = "other"  # 부칙 조문은 규칙 본문 조문이 아니라 정답에서 뺀다
            name = name or "부칙"
        label = f"제{m[1]}조" + (f"의{m[2]}" if m[2] else "")
        before = re.sub(r"\s+", " ", answer[max(0, m.start() - BEFORE_CHARS) : m.start()])
        out.append(Citation(label, kind, before, name))
    return out
