import json

import pytest

from cheongyak_rag.golden.select import METRO, Candidate, select

ALL7 = ("homeless", "account", "residence", "income_asset", "rewin", "householder", "special_type")
SIX = tuple(a for a in ALL7 if a != "rewin")
THREE = ALL7[:3]
SIX_TYPES = frozenset({"다자녀가구", "신혼부부", "생애최초", "노부모 부양", "기관추천", "신생아"})


def cand(no, axes=SIX, types=SIX_TYPES, area="부산", flags=()):
    return Candidate(no, no, f"공고{no}", area, "2026-09-01", axes, frozenset(types), tuple(flags))


def pool():
    out = [cand(f"{n:03d}", area="경기" if n % 2 else "부산") for n in range(40)]
    out += [
        cand("100", axes=ALL7, flags=("speclt_rdn_earth_at",)),
        cand("101", axes=THREE, types=()),
        cand("102", axes=THREE[:3] + ("rewin",), types=()),
        cand("103", axes=SIX[:3] + ("special_type",), types={"다자녀가구"}),
        cand("104", types=SIX_TYPES | {"청년"}),
        cand("105", types=SIX_TYPES | {"이전기관 종사자"}, area="서울"),
    ]
    return out


def test_select_same_input_same_output_even_if_shuffled():
    a = select(pool(), ["000", "001"])
    b = select(list(reversed(pool())), ["000", "001"])
    assert [c.house_manage_no for c in a] == [c.house_manage_no for c in b]


def test_select_returns_twenty_with_fixed_first():
    out = select(pool(), ["000", "001", "002", "003", "004"])
    assert len(out) == 20
    assert [c.house_manage_no for c in out[:5]] == ["000", "001", "002", "003", "004"]
    assert len({c.house_manage_no for c in out}) == 20


def test_select_covers_axis_combos_types_and_regions():
    out = select(pool(), ["000"])
    assert {c.axes for c in out} >= {ALL7, SIX, THREE}
    assert {t for c in out for t in c.types} >= SIX_TYPES | {"청년", "이전기관 종사자"}
    assert any(c.area in METRO for c in out) and any(c.area not in METRO for c in out)


def test_select_unknown_fixed_raises():
    with pytest.raises(KeyError):
        select(pool(), ["nope"])


def test_candidate_is_json_ready():
    c = cand("1")
    assert json.dumps(c.to_dict(), ensure_ascii=False)


def test_merge_existing_keeps_hand_added_keys_and_refreshes_built_ones():
    from cheongyak_rag.golden.select import merge_existing

    old = {"notices": [{"house_manage_no": "A", "name": "옛 이름", "facts": {"k": 1},
        "db_mismatch": [1], "db_silent": [2], "label_facts": {"account_months": 12}}]}  # fmt: skip
    new = {"notices": [{"house_manage_no": "A", "name": "새 이름"}, {"house_manage_no": "B"}]}
    out = merge_existing(new, old)["notices"]
    assert out[0]["name"] == "새 이름"
    assert out[0]["facts"] == {"k": 1} and out[0]["db_silent"] == [2]
    assert out[0]["label_facts"] == {"account_months": 12} and out[0]["db_mismatch"] == [1]
    assert out[1] == {"house_manage_no": "B"}
