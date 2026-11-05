// 서버에서만 쓴다. FastAPI 주소는 환경 변수 API_BASE_URL (기본 http://127.0.0.1:8000).
import type { NoticeDetail, NoticeSummary } from "./types";

export const apiBase = () => process.env.API_BASE_URL ?? "http://127.0.0.1:8000";

async function get<T>(path: string): Promise<T | null> {
  const res = await fetch(`${apiBase()}${path}`, { cache: "no-store" });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`FastAPI ${path} → ${res.status}`);
  return (await res.json()) as T;
}

export async function listNotices(): Promise<NoticeSummary[]> {
  // 목록 경로의 404는 「공고 0건」이 아니라 API_BASE_URL이 엉뚱한 서버를 가리킨다는 뜻이다
  const list = await get<NoticeSummary[]>("/api/notices");
  if (list === null) throw new Error(`FastAPI /api/notices → 404 (API_BASE_URL=${apiBase()})`);
  return list;
}

export const getNotice = (houseManageNo: string) =>
  get<NoticeDetail>(`/api/notices/${encodeURIComponent(houseManageNo)}`);
