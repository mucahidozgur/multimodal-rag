"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { TrendingUp } from "lucide-react";

import { useAuth } from "@/lib/store";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const { user, loading, checkAuth, logout } = useAuth();
  const router = useRouter();
  const [checked, setChecked] = useState(false);

  useEffect(() => {
    checkAuth().finally(() => setChecked(true));
  }, [checkAuth]);

  useEffect(() => {
    if (checked && !user) {
      router.push("/");
    }
  }, [checked, user, router]);

  if (loading || !checked) {
    return <div className="bg-[#0B1120] p-8 text-slate-300">Yükleniyor...</div>;
  }
  if (!user) {
    return null;
  }

  return (
    <div className="flex min-h-screen flex-col bg-[#0B1120]">
      <header className="flex items-center justify-between border-b border-slate-800 bg-slate-900/60 px-6 py-3">
        <span className="flex items-center gap-2 text-lg font-bold text-white">
          <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-gradient-to-br from-indigo-500 to-emerald-400">
            <TrendingUp className="h-4 w-4 text-white" />
          </span>
          Fin-RAG
        </span>
        <div className="flex items-center gap-4">
          {user && <span className="text-sm text-slate-400">{user.username}</span>}
          <button
            onClick={logout}
            className="rounded-md border border-slate-700 px-3 py-1 text-sm text-slate-300 hover:bg-slate-800"
          >
            Çıkış
          </button>
        </div>
      </header>
      <div className="flex flex-1">
        <aside className="w-[200px] shrink-0 border-r border-slate-800 bg-slate-900/40 p-4">
          <nav className="flex flex-col gap-1 text-sm">
            <Link
              href="/dashboard"
              className="rounded-md px-3 py-2 text-slate-300 hover:bg-slate-800 hover:text-white"
            >
              Dokümanlar
            </Link>
            <Link
              href="/dashboard/assistant"
              className="rounded-md px-3 py-2 text-slate-300 hover:bg-slate-800 hover:text-white"
            >
              AI Asistan
            </Link>
            <Link
              href="/dashboard/admin"
              className="rounded-md px-3 py-2 text-slate-300 hover:bg-slate-800 hover:text-white"
            >
              Analytics
            </Link>
          </nav>
        </aside>
        <main className="flex-1 p-6">{children}</main>
      </div>
    </div>
  );
}
