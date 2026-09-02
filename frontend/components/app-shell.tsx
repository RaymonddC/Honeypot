"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";
import { useAuth } from "@/components/auth/auth-provider";
import { CaseSwitcher } from "@/components/cases/case-switcher";
import { CaseContextBar } from "@/components/cases/case-context-bar";
import { initialsOf, roleLabel } from "@/lib/auth/types";

// Shown only to agency-admin / platform-admin. Hiding it is UX, not security —
// /api/users is role-gated server-side, and the page renders whatever 403 comes
// back rather than trusting that a hidden link kept anyone out.
const ADMIN_NAV = { href: "/users", labelKey: "users", glyph: "◫" };
const ADMIN_ROLES = ["agency-admin", "platform-admin"];

// Two clear groups: the guided case flow vs standalone tools. Labels are
// i18n keys under appShell.nav.*, resolved at render time (SidebarNav).
const NAV_GROUPS: {
  groupKey: string;
  items: { href: string; labelKey: string; glyph: string }[];
}[] = [
  {
    groupKey: "caseWorkflow",
    items: [
      { href: "/case", labelKey: "caseFile", glyph: "▤" },
      { href: "/audit", labelKey: "auditTrail", glyph: "⛓" },
      // "/users" is appended below, for admins only — see ADMIN_NAV.
    ],
  },
  {
    groupKey: "operations",
    items: [
      { href: "/honeypot", labelKey: "infiltrate", glyph: "⬡" },
      { href: "/honeypot-ops", labelKey: "honeypotOps", glyph: "☎" },
      { href: "/bridge", labelKey: "trace", glyph: "⇌" },
      { href: "/investigation", labelKey: "takedown", glyph: "◉" },
      { href: "/actions", labelKey: "uncover", glyph: "⚑" },
      { href: "/response", labelKey: "commandCenter", glyph: "▦" },
    ],
  },
];

/* ── MODE badge — real per-deployment mode from GET /api/config ─────────── */

function ModeBadge() {
  const t = useTranslations("appShell.modeBadge");
  const { config } = useAuth();
  const mode = config?.mode ?? "POC";
  const perModule = config?.modules ?? [];
  const title = [
    `${t("dataModeTitle", { mode })}${config?.source === "env" ? t("envFallback") : ""}`,
    ...perModule.map((m) => `${m.module}: ${m.mode}`),
  ].join("\n");

  return (
    <span
      className={`rounded-md border px-2 py-0.5 font-mono text-[10px] font-bold tracking-widest ${
        mode === "LIVE"
          ? "border-accent/40 bg-accent/10 text-accent-bright"
          : "border-risk-med/40 bg-risk-med/10 text-risk-med"
      } ${config ? "" : "opacity-50"}`}
      title={title}
    >
      {mode}
    </span>
  );
}

/* ── User menu — avatar from /api/auth/me + logout ──────────────────────── */

function UserMenu() {
  const t = useTranslations("appShell.userMenu");
  const { me, logout, liveVerified } = useAuth();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node))
        setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const name = me?.user.name ?? "…";
  const initials = me ? initialsOf(me.user.name) : "··";

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={t("accountLabel", { name })}
        title={name}
        className="flex h-7 w-7 cursor-pointer items-center justify-center rounded-full border border-line bg-elevated text-[11px] font-semibold text-accent-bright transition-colors hover:border-accent/40"
      >
        {initials}
      </button>

      {open && (
        <div
          role="menu"
          className="absolute right-0 top-9 z-50 w-56 rounded-lg border border-line bg-card p-1 shadow-xl shadow-black/50"
        >
          <div className="px-3 py-2">
            <div className="truncate text-[13px] font-medium text-fg">
              {name}
            </div>
            {me?.user.email && (
              <div className="truncate font-mono text-[11px] text-muted">
                {me.user.email}
              </div>
            )}
            <div className="pt-1 text-[11px] text-muted">
              {me ? roleLabel(me.role) : "—"}
              {me?.agency.name ? ` · ${me.agency.name}` : ""}
            </div>
            <div className="pt-1.5">
              <span
                className={`inline-flex items-center gap-1.5 rounded px-1.5 py-0.5 text-[10px] ${
                  liveVerified
                    ? "bg-accent/10 text-accent-bright"
                    : "bg-white/[.05] text-muted"
                }`}
              >
                <span
                  className={`h-1 w-1 rounded-full ${liveVerified ? "bg-accent" : "bg-muted"}`}
                  aria-hidden
                />
                {liveVerified ? t("sessionVerified") : t("offlineSession")}
              </span>
            </div>
          </div>
          <div className="mx-2 h-px bg-line" aria-hidden />
          <button
            type="button"
            role="menuitem"
            onClick={logout}
            className="mt-1 flex w-full cursor-pointer items-center gap-2 rounded-md px-3 py-2 text-left text-[13px] text-muted transition-colors hover:bg-white/[.04] hover:text-fg"
          >
            <span aria-hidden className="text-xs">
              ⏻
            </span>
            {t("signOut")}
          </button>
        </div>
      )}
    </div>
  );
}

/* ── Shell ──────────────────────────────────────────────────────────────── */

function SidebarNav({
  pathname,
  me,
  onNavigate,
}: {
  pathname: string;
  me: ReturnType<typeof useAuth>["me"];
  onNavigate?: () => void;
}) {
  const t = useTranslations("appShell.nav");
  const tCommon = useTranslations("common");

  return (
    <>
      <div className="flex items-center gap-2 px-4 py-4">
        <span className="flex h-6 w-6 items-center justify-center rounded-md bg-accent/15 font-mono text-xs font-bold text-accent-bright">
          IT
        </span>
        <span className="text-sm font-semibold tracking-wide">{tCommon("appName")}</span>
      </div>

      <nav className="flex-1 overflow-y-auto px-2 pt-1">
        {/* Home */}
        <Link
          href="/home"
          onClick={onNavigate}
          aria-current={pathname === "/home" ? "page" : undefined}
          className={`mb-1 flex items-center gap-2.5 rounded-lg px-3 py-2 text-[13px] transition-colors ${
            pathname === "/home"
              ? "bg-accent/10 font-medium text-accent-bright"
              : "text-muted hover:bg-white/[.04] hover:text-fg"
          }`}
        >
          <span className="w-4 text-center text-xs" aria-hidden>⌂</span>
          {t("home")}
        </Link>

        {NAV_GROUPS.map((group) => (
          <div key={group.groupKey} className="mt-2">
            <div className="eyebrow px-3 pb-1.5">{t(group.groupKey)}</div>
            <ul className="space-y-0.5">
              {(group.groupKey === "caseWorkflow" && me && ADMIN_ROLES.includes(me.role)
                ? [...group.items, ADMIN_NAV]
                : group.items
              ).map((item) => {
                const active = pathname.startsWith(item.href);
                return (
                  <li key={item.href}>
                    <Link
                      href={item.href}
                      onClick={onNavigate}
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
                      {t(item.labelKey)}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </nav>

      <div className="border-t border-line px-2 py-2">
        <Link
          href="/guide"
          onClick={onNavigate}
          aria-current={pathname.startsWith("/guide") ? "page" : undefined}
          className={`flex items-center gap-2.5 rounded-lg px-3 py-2 text-[13px] transition-colors ${
            pathname.startsWith("/guide")
              ? "bg-accent/10 font-medium text-accent-bright"
              : "text-muted hover:bg-white/[.04] hover:text-fg"
          }`}
        >
          <span className="w-4 text-center text-xs" aria-hidden>
            ?
          </span>
          {t("guide")}
        </Link>
        <Link
          href="/settings"
          onClick={onNavigate}
          aria-current={pathname.startsWith("/settings") ? "page" : undefined}
          className={`flex items-center gap-2.5 rounded-lg px-3 py-2 text-[13px] transition-colors ${
            pathname.startsWith("/settings")
              ? "bg-accent/10 font-medium text-accent-bright"
              : "text-muted hover:bg-white/[.04] hover:text-fg"
          }`}
        >
          <span className="w-4 text-center text-xs" aria-hidden>
            ⚙
          </span>
          {t("controlPanel")}
        </Link>
        <span className="eyebrow mt-1 block px-3">{t("authBadge")}</span>
      </div>
    </>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const t = useTranslations("common");
  const tShell = useTranslations("appShell.agencyChip");
  const pathname = usePathname();
  const { me } = useAuth();
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  // Close the mobile drawer whenever the route changes (covers back/forward
  // nav that doesn't go through a Link's onClick).
  useEffect(() => {
    setMobileNavOpen(false);
  }, [pathname]);

  // Lock body scroll while the mobile drawer is open.
  useEffect(() => {
    if (!mobileNavOpen) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [mobileNavOpen]);

  return (
    <div className="flex h-screen overflow-hidden">
      {/* ── Left module rail — desktop/tablet only ───────────────────── */}
      <aside className="hidden w-56 shrink-0 flex-col border-r border-line bg-sidebar md:flex">
        <SidebarNav pathname={pathname} me={me} />
      </aside>

      {/* ── Mobile drawer — hidden nav, slides in over the page ──────── */}
      {mobileNavOpen && (
        <div className="fixed inset-0 z-50 flex md:hidden">
          <div
            className="fixed inset-0 bg-black/60"
            aria-hidden
            onClick={() => setMobileNavOpen(false)}
          />
          <aside className="relative flex h-full w-64 max-w-[80vw] flex-col border-r border-line bg-sidebar shadow-xl shadow-black/50">
            <SidebarNav
              pathname={pathname}
              me={me}
              onNavigate={() => setMobileNavOpen(false)}
            />
          </aside>
        </div>
      )}

      {/* ── Main column ──────────────────────────────────────────────── */}
      <div className="flex min-w-0 flex-1 flex-col">
        {/* Top bar */}
        <header className="flex h-12 shrink-0 items-center gap-2 border-b border-line bg-sidebar px-3 sm:gap-3 sm:px-4">
          {/* Hamburger — mobile only */}
          <button
            type="button"
            onClick={() => setMobileNavOpen(true)}
            aria-label={t("openNavigationMenu")}
            aria-haspopup="menu"
            aria-expanded={mobileNavOpen}
            className="flex h-8 w-8 flex-none items-center justify-center rounded-md border border-line bg-elevated text-fg md:hidden"
          >
            <span aria-hidden>☰</span>
          </button>

          {/* Case switcher — the active-case selector (case-centric flow) */}
          <CaseSwitcher />

          {/* Agency context chip — from GET /api/auth/me. Hidden on the
              smallest screens so it never pushes the mode badge / avatar
              off-screen; the case switcher already carries the case name. */}
          <span
            className="hidden max-w-[16rem] truncate rounded-md border border-line bg-elevated px-2.5 py-1 text-xs text-muted sm:inline"
            title={
              me
                ? tShell("signedInAs", { agency: me.agency.name, role: roleLabel(me.role) })
                : tShell("loading")
            }
          >
            {me?.agency.name ?? "…"}
            {me?.agency.type ? ` · ${me.agency.type}` : ""}
          </span>

          <div className="flex-1" />

          <ModeBadge />
          <UserMenu />
        </header>

        {/* Case context — the connective thread across module screens */}
        <CaseContextBar />

        {/* Screen canvas */}
        <main className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden p-3 sm:p-6">{children}</main>
      </div>
    </div>
  );
}
