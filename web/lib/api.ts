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
  return (await get<NoticeSummary[]>("/api/notices")) ?? [];
}

export const getNotice = (houseManageNo: string) =>
  get<NoticeDetail>(`/api/notices/${encodeURIComponent(houseManageNo)}`);
