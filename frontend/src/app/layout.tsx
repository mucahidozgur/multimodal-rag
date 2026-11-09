import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Fin-RAG",
  description: "Multi-modal RAG for financial reports",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="tr">
      <body
        className={`${inter.className} bg-[#0B1120] text-slate-100 antialiased`}
      >
        {children}
      </body>
    </html>
  );
}
