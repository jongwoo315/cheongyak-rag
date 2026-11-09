// 브라우저 → 이 핸들러 → FastAPI. FastAPI의 상태 코드와 본문을 그대로 돌려준다.
import { apiBase } from "@/lib/api";

export const dynamic = "force-dynamic";
// Vercel 함수 제한(300초) 안쪽. 이 시간 안에 FastAPI가 답하지 않으면 끊고 504를 낸다
const TIMEOUT_MS = Number(process.env.VERDICT_TIMEOUT_MS ?? 280_000);

export async function POST(
  req: Request,
  ctx: { params: Promise<{ houseManageNo: string }> },
) {
  const { houseManageNo } = await ctx.params;
  const body = await req.text();
  try {
    const upstream = await fetch(
      `${apiBase()}/api/notices/${encodeURIComponent(houseManageNo)}/verdict`,
      {
        method: "POST",
        headers: { "content-type": "application/json" },
        body,
        cache: "no-store",
        signal: AbortSignal.timeout(TIMEOUT_MS),
      },
    );
    return new Response(await upstream.text(), {
      status: upstream.status,
      headers: {
        "content-type": upstream.headers.get("content-type") ?? "application/json",
      },
    });
  } catch (e) {
    const name = e instanceof Error ? e.name : typeof e;
    const message = e instanceof Error ? e.message : String(e);
    console.error(`판정 서버 호출 실패: ${name}: ${message}`);
    if (name === "TimeoutError") {
      return Response.json(
        { detail: "판정이 너무 오래 걸려 끊었다. 잠시 뒤 다시 시도해 달라" },
        { status: 504 },
      );
    }
    return Response.json({ detail: "판정 서버에 연결하지 못했다" }, { status: 502 });
  }
}
