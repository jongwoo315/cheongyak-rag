import Link from "next/link";

export default function NotFound() {
  return (
    <>
      <h1>공고를 찾을 수 없습니다</h1>
      <p>
        <Link href="/">공고 목록으로 돌아가기</Link>
      </p>
    </>
  );
}
