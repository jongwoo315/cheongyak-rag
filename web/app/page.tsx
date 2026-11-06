import Link from "next/link";
import { listNotices } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function Home() {
  const notices = await listNotices();
  return (
    <>
      <h1>청약 공고 {notices.length}건</h1>
      <p className="hint">공고를 고르고 내 프로필을 넣으면 자격을 판정합니다. 모집공고일이 늦은 순입니다.</p>
      <ul className="notice-list">
        {notices.map((n) => (
          <li key={n.house_manage_no}>
            <Link href={`/notices/${encodeURIComponent(n.house_manage_no)}`}>{n.house_nm}</Link>
            <span className="meta">
              {n.subscrpt_area_nm ?? "지역 미상"} · 모집공고 {n.rcrit_pblanc_de ?? "-"} · 접수{" "}
              {n.rcept_bgnde ?? "-"} ~ {n.rcept_endde ?? "-"}
            </span>
          </li>
        ))}
      </ul>
    </>
  );
}
