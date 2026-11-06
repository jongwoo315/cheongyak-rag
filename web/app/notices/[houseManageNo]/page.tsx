import type { Metadata } from "next";
import { notFound } from "next/navigation";
import VerdictForm from "@/components/VerdictForm";
import { getNotice } from "@/lib/api";

export const dynamic = "force-dynamic";

type Props = { params: Promise<{ houseManageNo: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const notice = await getNotice((await params).houseManageNo);
  if (!notice) return { title: "공고를 찾을 수 없습니다" };
  return {
    title: `${notice.house_nm} 청약 자격 판정`,
    description: `${notice.house_nm}(${notice.subscrpt_area_nm ?? "지역 미상"}) 청약 공고. 모집공고 ${notice.rcrit_pblanc_de ?? "-"}. 내 프로필로 일반공급·특별공급 자격을 확인한다.`,
  };
}

const won = (v: number | null) => (v == null ? "-" : `${v.toLocaleString("ko-KR")}만원`);

export default async function NoticePage({ params }: Props) {
  const notice = await getNotice((await params).houseManageNo);
  if (!notice) notFound();
  return (
    <>
      <h1>{notice.house_nm}</h1>
      <section aria-labelledby="info-title">
        <h2 id="info-title">공고 정보</h2>
        <dl className="info">
          <dt>지역</dt>
          <dd>{notice.subscrpt_area_nm ?? "-"}</dd>
          <dt>주소</dt>
          <dd>{notice.hssply_adres ?? "-"}</dd>
          <dt>공급 세대</dt>
          <dd>{notice.tot_suply_hshldco ?? "-"}</dd>
          <dt>모집공고일</dt>
          <dd>{notice.rcrit_pblanc_de ?? "-"}</dd>
          <dt>접수 기간</dt>
          <dd>
            {notice.rcept_bgnde ?? "-"} ~ {notice.rcept_endde ?? "-"}
          </dd>
          <dt>당첨자 발표일</dt>
          <dd>{notice.przwner_presnatn_de ?? "-"}</dd>
          <dt>청약홈</dt>
          <dd>
            {notice.pblanc_url ? (
              <a href={notice.pblanc_url} target="_blank" rel="noopener noreferrer">
                공고문 보기
              </a>
            ) : (
              "-"
            )}
          </dd>
        </dl>
      </section>
      <section aria-labelledby="models-title">
        <h2 id="models-title">주택형</h2>
        <div className="table-wrap">
          <table data-testid="models-table">
            <thead>
              <tr>
                <th>주택형</th>
                <th>공급면적(㎡)</th>
                <th>일반 공급 세대</th>
                <th>특별 공급 세대</th>
                <th>최고 분양가</th>
              </tr>
            </thead>
            <tbody>
              {notice.models.map((m) => (
                <tr key={m.model_no}>
                  <td>{m.house_ty ?? m.model_no}</td>
                  <td>{m.suply_ar ?? "-"}</td>
                  <td>{m.suply_hshldco ?? "-"}</td>
                  <td>{m.spsply_hshldco ?? "-"}</td>
                  <td>{won(m.lttot_top_amount)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      <section aria-labelledby="form-title">
        <h2 id="form-title">내 프로필로 판정하기</h2>
        <VerdictForm houseManageNo={notice.house_manage_no} />
      </section>
    </>
  );
}
