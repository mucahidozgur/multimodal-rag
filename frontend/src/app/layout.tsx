import type { Metadata } from "next";
import "./globals.css";

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
      <body className="bg-gray-50 text-gray-900 antialiased">{children}</body>
    </html>
  );
}
