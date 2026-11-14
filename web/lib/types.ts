// FastAPI 응답 모양. 정의는 src/cheongyak_rag/api.py · generate/aggregate.py 가 기준이다.

export type Verdict =
  | "ELIGIBLE"
  | "CONDITIONAL"
  | "INELIGIBLE"
  | "NEED_INFO"
  | "UNVERIFIABLE";

export type NoticeSummary = {
  house_manage_no: string;
  pblanc_no: string;
  house_nm: string;
  subscrpt_area_nm: string | null;
  rcrit_pblanc_de: string | null;
  rcept_bgnde: string | null;
  rcept_endde: string | null;
};

export type NoticeModel = {
  model_no: string;
  house_ty: string | null;
  suply_ar: number | null;
  suply_hshldco: number | null;
  spsply_hshldco: number | null;
  lttot_top_amount: number | null;
};

export type NoticeDetail = NoticeSummary & {
  house_secd: string | null;
  hssply_adres: string | null;
  tot_suply_hshldco: number | null;
  przwner_presnatn_de: string | null;
  mvn_prearnge_ym: string | null;
  pblanc_url: string | null;
  models: NoticeModel[];
};

export type Route = {
  key: string;
  name: string;
  verdict: Verdict | null;
  axes: string[];
  n: number;
};

export type Evidence = {
  label: string;
  kind: "law" | "faq";
  title: string;
  text: string;
  source: string;
  url: string | null;
};

export type ChecklistItem = {
  axis: string;
  axis_name: string;
  query: string;
  verdict: Verdict | null;
  reason: string;
  conditions: string[];
  need_info: string[];
  citations: Evidence[];
  outside: string[];
  note: string;
  error: string | null;
};

export type Range = { lo: number | null; hi: number | null };

// 응답의 질문 한 줄. 정의는 src/cheongyak_rag/generate/questions.py `Question`이 기준이다.
// 배열 순서가 곧 물을 차례다.
export type Question = {
  name: string;
  text: string;
  has_field: boolean;
  can_rule_out: boolean;
  axes: string[];
  routes: string[];
};

export type Answer = {
  house_manage_no: string;
  pblanc_no: string;
  name: string;
  as_of: string;
  law_mst: string | null;
  law_effective_date: string | null;
  verdict: Verdict | null;
  general: Route;
  special: Route[];
  applicable: Route[];
  checklist: ChecklistItem[];
  score: {
    homeless?: Range;
    dependents?: Range;
    savings?: Range;
    total?: Range;
    missing?: string[];
  };
  questions: Question[];
  trace_id: number | null;
  trace_error: string | null;
};
