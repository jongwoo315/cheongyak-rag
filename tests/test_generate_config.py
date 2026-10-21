import pytest

from cheongyak_rag.config import Settings
from cheongyak_rag.generate.answer import PRICE_PER_1M, cost_usd


def test_gen_model_default():
    assert Settings(_env_file=None, openai_api_key="x").openai_gen_model == "gpt-5.4-mini"


def test_env_example_has_gen_model():
    from pathlib import Path

    text = (Path(__file__).resolve().parents[1] / ".env.example").read_text(encoding="utf-8")
    assert "OPENAI_GEN_MODEL=gpt-5.4-mini" in text


def test_cost_usd_uses_price_table():
    in_p, out_p = PRICE_PER_1M["gpt-5.4-mini"]
    assert (in_p, out_p) == (0.75, 4.50)
    assert cost_usd("gpt-5.4-mini", 1_000_000, 1_000_000) == pytest.approx(5.25)
    assert cost_usd("gpt-5.4-mini", 2000, 500) == pytest.approx(2000 * 0.75e-6 + 500 * 4.5e-6)


def test_cost_usd_unknown_model_raises():
    # 표에 없는 모델의 $를 0으로 대신하지 않는다
    with pytest.raises(KeyError):
        cost_usd("gpt-unknown", 10, 10)
