"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const MODE = (process.env.NEXT_PUBLIC_ITTU_MODE ?? "poc").toUpperCase();

const NAV = [
  { href: "/investigation", label: "Investigation", glyph: "◉" },
  { href: "/bridge", label: "Bridge View", glyph: "⇌" },
  { href: "/actions", label: "Action Panel", glyph: "⚑" },
  { href: "/response", label: "Response", glyph: "▦" },
  { href: "/honeypot", label: "Honeypot", glyph: "⬡" },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  return (
    <div className="flex h-screen overflow-hidden">
      {/* ── Left module rail ─────────────────────────────────────────── */}
      <aside className="flex w-56 shrink-0 flex-col border-r border-line bg-sidebar">
        <div className="flex items-center gap-2 px-4 py-4">
          <span className="flex h-6 w-6 items-center justify-center rounded-md bg-accent/15 font-mono text-xs font-bold text-accent-bright">
            IT
          </span>
          <span className="text-sm font-semibold tracking-wide">ITTU</span>
        </div>

        <nav className="flex-1 px-2 pt-2">
          <div className="eyebrow px-3 pb-2">Modules</div>
          <ul className="space-y-0.5">
            {NAV.map((item) => {
              const active = pathname.startsWith(item.href);
              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    aria-current={active ? "page" : undefined}
                    className={`flex items-center gap-2.5 rounded-lg px-3 py-2 text-[13px] transition-colors ${
                      active
                        ? "bg-accent/10 font-medium text-accent-bright"
                        : "text-muted hover:bg-white/[.04] hover:text-fg"
                    }`}
                  >
                    <span className="w-4 text-center text-xs" aria-hidden>
                      {item.glyph}
                    </span>
                    {item.label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>

        <div className="border-t border-line px-4 py-3">
          <span className="eyebrow">P0 scaffold</span>
        </div>
      </aside>

      {/* ── Main column ──────────────────────────────────────────────── */}
      <div className="flex min-w-0 flex-1 flex-col">
        {/* Top bar */}
        <header className="flex h-12 shrink-0 items-center gap-3 border-b border-line bg-sidebar px-4">
          {/* Case switcher chip */}
          <button className="flex items-center gap-2 rounded-md border border-line bg-elevated px-2.5 py-1 font-mono text-xs text-fg hover:border-white/10">
            <span className="h-1.5 w-1.5 rounded-full bg-accent" aria-hidden />
            #ITU-2026-0417
            <span className="text-muted" aria-hidden>
              ▾
            </span>
          </button>

          {/* Agency context chip */}
          <span className="rounded-md border border-line bg-elevated px-2.5 py-1 text-xs text-muted">
            Bareskrim · Siber
          </span>

          <div className="flex-1" />

          {/* POC / LIVE mode badge */}
          <span
            className={`rounded-md border px-2 py-0.5 font-mono text-[10px] font-bold tracking-widest ${
              MODE === "LIVE"
                ? "border-accent/40 bg-accent/10 text-accent-bright"
                : "border-risk-med/40 bg-risk-med/10 text-risk-med"
            }`}
            title={`Data mode: ${MODE}`}
          >
            {MODE}
          </span>

          {/* User avatar */}
          <span
            className="flex h-7 w-7 items-center justify-center rounded-full border border-line bg-elevated text-[11px] font-semibold text-accent-bright"
            title="Analyst"
          >
            AN
          </span>
        </header>

        {/* Screen canvas */}
        <main className="min-h-0 flex-1 overflow-y-auto p-6">{children}</main>
      </div>
    </div>
  );
}
