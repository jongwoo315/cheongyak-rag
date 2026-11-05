import type { Range, Verdict } from "./types";

// 뜻은 docs/concepts.md 「판정값 5개」 표 그대로다.
export const VERDICT_GLOSS: Record<Verdict, string> = {
  ELIGIBLE: "프로필에 있는 값이 요건을 채운다고 근거로 확인된다",
  INELIGIBLE: "프로필 값이 요건을 못 채운다고 근거로 확인된다",
  CONDITIONAL: "지금은 못 채우지만 공고 이후 신청자가 행동하면(전입, 통장 가입, 세대주 변경 등) 채운다",
  NEED_INFO: "요건을 가릴 값이 프로필에 없다. 그 값만 있으면 판정이 정해진다",
  UNVERIFIABLE: "근거에서 요건의 근거를 못 찾았거나 규정끼리 부딪힌다",
};

export const NO_VERDICT = "판정 없음";

export const verdictText = (v: Verdict | null) => v ?? NO_VERDICT;

export const gloss = (v: Verdict | null) => (v ? VERDICT_GLOSS[v] : "판정을 낼 근거가 없다");

export function rangeText(r?: Range): string {
  if (!r || r.lo == null || r.hi == null) return "-";
  return r.lo === r.hi ? `${r.lo}점` : `${r.lo}~${r.hi}점`;
}
