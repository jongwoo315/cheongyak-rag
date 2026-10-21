"""검색 결과로 인용 단 답 생성 (#139).

python -m cheongyak_rag.generate.answer "무주택세대구성원이란 무엇인가요?"
"""

# 가격 $ / 1M 토큰 (입력, 출력).
# 출처: developers.openai.com/api/docs/models/gpt-5.4-mini, 2026-10-22 확인
PRICE_PER_1M = {"gpt-5.4-mini": (0.75, 4.50)}


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    """표에 없는 모델이면 KeyError — 0으로 대신하면 비용 상한이 조용히 무력해진다."""
    in_p, out_p = PRICE_PER_1M[model]
    return (input_tokens * in_p + output_tokens * out_p) / 1_000_000
