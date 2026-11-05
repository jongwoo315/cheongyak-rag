// 프로필 입력 칸 15개. 정의는 src/cheongyak_rag/profile.py `Profile`이 기준이고,
// `name`은 그 칸 이름 그대로다 (측정이 이 이름으로 칸을 찾는다).

export type Kind = "bool" | "date" | "count";

export const FIELDS: { name: string; label: string; kind: Kind }[] = [
  { name: "birth_date", label: "생년월일", kind: "date" },
  { name: "married", label: "공고일 현재 배우자가 있다", kind: "bool" },
  { name: "ever_married", label: "혼인한 적이 있다 (이혼·사별 포함)", kind: "bool" },
  { name: "marriage_date", label: "최초 혼인신고일", kind: "date" },
  { name: "homeless_now", label: "지금 무주택이다", kind: "bool" },
  { name: "ever_owned", label: "집을 가진 적이 있다", kind: "bool" },
  { name: "homeless_since", label: "무주택이 된 날", kind: "date" },
  { name: "is_household_head", label: "세대주다", kind: "bool" },
  { name: "children_unmarried", label: "미혼 자녀 수", kind: "count" },
  { name: "children_30plus_1y", label: "30세 이상 자녀 중 1년 넘게 같이 산 수", kind: "count" },
  { name: "ascendants_3y", label: "3년 넘게 부양한 직계존속 수", kind: "count" },
  {
    name: "ascendants_any_owner",
    label: "부양하는 직계존속 중 집을 가진 사람이 있다",
    kind: "bool",
  },
  { name: "savings_join_date", label: "청약통장 가입일", kind: "date" },
  { name: "spouse_has_savings", label: "배우자 청약통장이 있다", kind: "bool" },
  { name: "spouse_savings_join_date", label: "배우자 청약통장 가입일", kind: "date" },
];

// 입력 칸의 값은 전부 글자다. bool은 "" (모름) · "true" · "false".
export type FormState = Record<string, string>;

/** 빈 칸과 「모름」은 JSON에서 뺀다 (`Profile`에서 없는 칸 = 모른다). */
export function toPayload(state: FormState): Record<string, string | number | boolean> {
  const out: Record<string, string | number | boolean> = {};
  for (const f of FIELDS) {
    const v = (state[f.name] ?? "").trim();
    if (v === "") continue;
    if (f.kind === "bool") out[f.name] = v === "true";
    else if (f.kind === "count") out[f.name] = Number(v);
    else out[f.name] = v;
  }
  return out;
}

// 탭 안에서만 유지한다. 서버·localStorage에는 두지 않는다.
const KEY = "cheongyak-profile";

export function loadState(): FormState {
  try {
    return JSON.parse(sessionStorage.getItem(KEY) ?? "{}") as FormState;
  } catch {
    return {};
  }
}

export function saveState(state: FormState) {
  try {
    sessionStorage.setItem(KEY, JSON.stringify(state));
  } catch {
    // 저장이 막힌 브라우저에서도 입력은 된다
  }
}
