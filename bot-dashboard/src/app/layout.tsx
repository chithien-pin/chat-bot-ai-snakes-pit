import type { Metadata } from "next";
import { Inter } from "next/font/google";
import { Sidebar } from "@/components/layout/Sidebar";
import { MainShell } from "@/components/layout/MainShell";
import "./globals.css";

const inter = Inter({
  subsets: ["latin", "vietnamese"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "CPS Bot Analytics",
  description: "CellphoneS chatbot operations dashboard",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="vi">
      <body className={inter.className}>
        <Sidebar />
        <MainShell>{children}</MainShell>
      </body>
    </html>
  );
}
