// 브라우저 → 이 핸들러 → FastAPI. FastAPI의 상태 코드와 본문을 그대로 돌려준다.
import { apiBase } from "@/lib/api";

export const dynamic = "force-dynamic";

export async function POST(
  req: Request,
  ctx: { params: Promise<{ houseManageNo: string }> },
) {
  const { houseManageNo } = await ctx.params;
  let upstream: Response;
  try {
    upstream = await fetch(
      `${apiBase()}/api/notices/${encodeURIComponent(houseManageNo)}/verdict`,
      {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: await req.text(),
        cache: "no-store",
      },
    );
  } catch {
    return Response.json({ detail: "판정 서버에 연결하지 못했다" }, { status: 502 });
  }
  return new Response(await upstream.text(), {
    status: upstream.status,
    headers: {
      "content-type": upstream.headers.get("content-type") ?? "application/json",
    },
  });
}
