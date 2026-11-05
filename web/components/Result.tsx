import type { Answer } from "@/lib/types";

export default function Result({ answer }: { answer: Answer }) {
  return (
    <section aria-labelledby="result-title">
      <h2 id="result-title">판정 결과</h2>
      <p>
        전역 판정: <strong data-testid="verdict-global">{answer.verdict ?? "판정 없음"}</strong>
      </p>
      <p>체크리스트 {answer.checklist.length}개</p>
    </section>
  );
}
