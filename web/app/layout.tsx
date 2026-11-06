import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "청약 자격 판정",
  description: "청약 공고별로 내 자격을 법령과 FAQ 근거로 확인한다.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko">
      <body>
        <header className="site">
          <Link href="/">청약 자격 판정</Link>
        </header>
        <main>{children}</main>
      </body>
    </html>
  );
}
