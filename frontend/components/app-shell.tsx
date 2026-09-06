"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";
import { useAuth } from "@/components/auth/auth-provider";
import { CaseSwitcher } from "@/components/cases/case-switcher";
import { CaseContextBar } from "@/components/cases/case-context-bar";
import { useTheme } from "@/components/theme/theme-provider";
import { CAP, can, initialsOf, roleLabel } from "@/lib/auth/types";

// Admin destinations, each shown only to someone who holds the CAPABILITY it
// needs. Gated on capabilities rather than role NAMES on purpose: a role created
// in Roles administration would be invisible to a hardcoded name list forever,
// which is the coupling capabilities exist to remove.
//
// Hiding a link is UX, not security. Both endpoints are guarded server-side and
// each page renders whatever 403 comes back, rather than trusting that a missing
// menu item kept anyone out.
// Its OWN group, not an appendix to the case flow. Administering people and
// permissions is not a step in working a case, and filing it under "Case
// workflow" said it was — someone looking for it would search the case screens,
// and someone reading the menu would infer that access is decided per case,
// which is exactly backwards.
/** One nav item. Both nav tables use this shape so they can be concatenated —
 *  `capability` gates on who you are, `crypto` on what this deployment offers.
 *  `step` numbers the four-module investigation flow (1-4) so a first-time
 *  user sees it as an order to work through, not an alphabetic menu; items
 *  without a `step` (Case File, Honeypot Ops, Command Center) aren't part of
 *  that sequence. `subKey` is a one-line plain-language gloss shown under the
 *  module's proper name — the name stays (it's the product's branding), the
 *  gloss is what tells a new investigator what clicking it actually does. */
type NavItem = {
  href: string;
  labelKey: string;
  subKey?: string;
  glyph: string;
  step?: number;
  /** Omitted = visible to everyone signed in. */
  capability?: string;
  /** Hidden when the deployment does not offer the crypto surface. */
  crypto?: boolean;
};

const ADMIN_NAV: NavItem[] = [
  // Agency-wide, not case-scoped — its own subtitle says "every recorded action
  // by your agency". It sat under the case flow for the same bad reason Users
  // did, and a trail filed under one case implies it only covers that case.
  //
  // Deliberately NOT capability-gated: everyone in the agency may read it. A
  // tamper-evident log that only administrators can see is a weaker control —
  // the people best placed to notice something wrong in the record are the ones
  // who did the work it describes.
  { href: "/audit", labelKey: "auditTrail", glyph: "⛓" },
  { href: "/users", labelKey: "users", glyph: "◫", capability: CAP.usersAdmin },
  { href: "/roles", labelKey: "roles", glyph: "⛊", capability: CAP.rolesAdmin },
];

// Two clear groups: the guided case flow vs standalone tools. Labels are
// i18n keys under appShell.nav.*, resolved at render time (SidebarNav).
// `crypto` items disappear when the deployment does not offer the crypto
// surface. Hiding is not the protection — the server answers 404 for those
// routes either way — it just stops a menu item leading somewhere that cannot
// load.
const NAV_GROUPS: { groupKey: string; items: NavItem[] }[] = [
  {
    groupKey: "caseWorkflow",
    items: [{ href: "/case", labelKey: "caseFile", glyph: "▤" }],
  },
  {
    groupKey: "operations",
    items: [
      { href: "/honeypot", labelKey: "infiltrate", subKey: "infiltrateSub", glyph: "①", step: 1 },
      // TRACE keeps its FIAT half (mule bank accounts) when crypto is off,
      // so it is NOT hidden. TAKEDOWN is crypto in its entirety.
      { href: "/bridge", labelKey: "trace", subKey: "traceSub", glyph: "②", step: 2 },
      { href: "/investigation", labelKey: "takedown", subKey: "takedownSub", glyph: "③", step: 3, crypto: true },
      { href: "/actions", labelKey: "uncover", subKey: "uncoverSub", glyph: "④", step: 4 },
      { href: "/honeypot-ops", labelKey: "honeypotOps", subKey: "honeypotOpsSub", glyph: "☎" },
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

/* ── Theme toggle — quick access next to the mode badge ──────────────────
 * Cycles light → dark → system on each click, so the common case (flip
 * between light and dark) is one click, with "system" reachable as the
 * third stop rather than needing to open the Control Panel for the full
 * three-way choice (that's still there — see ThemeCard in app/settings). */

const THEME_CYCLE: Record<
  ReturnType<typeof useTheme>["theme"],
  ReturnType<typeof useTheme>["theme"]
> = {
  light: "dark",
  dark: "system",
  system: "light",
};

function ThemeToggle() {
  const t = useTranslations("appShell.themeToggle");
  const { theme, setTheme } = useTheme();
  const icon = theme === "dark" ? "☾" : theme === "light" ? "☼" : "◐";
  return (
    <button
      type="button"
      onClick={() => setTheme(THEME_CYCLE[theme])}
      title={t("title", { current: t(theme) })}
      aria-label={t("title", { current: t(theme) })}
      className="flex h-7 w-7 flex-none items-center justify-center rounded-full border border-line bg-elevated text-[13px] text-muted transition-colors hover:border-accent/40 hover:text-fg"
    >
      <span aria-hidden>{icon}</span>
    </button>
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
                    : "bg-fg/[.05] text-muted"
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
            className="mt-1 flex w-full cursor-pointer items-center gap-2 rounded-md px-3 py-2 text-left text-[13px] text-muted transition-colors hover:bg-fg/[.04] hover:text-fg"
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
  cryptoEnabled,
  onNavigate,
}: {
  pathname: string;
  me: ReturnType<typeof useAuth>["me"];
  cryptoEnabled: boolean;
  onNavigate?: () => void;
}) {
  const t = useTranslations("appShell.nav");
  const tCommon = useTranslations("common");
  const adminItems = ADMIN_NAV.filter(
    (item) => !item.capability || can(me, item.capability),
  );
  const visible = (items: NavItem[]): NavItem[] =>
    items.filter((item) => !item.crypto || cryptoEnabled);

  return (
    <>
      <div className="flex items-center gap-2.5 px-5 py-5">
        <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent text-sm font-bold text-white">
          IT
        </span>
        <span className="text-[15px] font-semibold tracking-tight">{tCommon("appName")}</span>
      </div>

      <nav className="flex-1 overflow-y-auto px-3 pb-2">
        {/* Home */}
        <Link
          href="/home"
          onClick={onNavigate}
          aria-current={pathname === "/home" ? "page" : undefined}
          className={`mb-3 flex items-center gap-2.5 rounded-lg px-3 py-2.5 text-[13.5px] font-medium transition-colors ${
            pathname === "/home"
              ? "bg-accent/10 text-accent-bright"
              : "text-fg hover:bg-fg/[.04]"
          }`}
        >
          <span className="w-4 text-center text-[15px]" aria-hidden>⌂</span>
          {t("home")}
        </Link>

        {[
          ...NAV_GROUPS,
          // Appended rather than declared inline so the whole group disappears
          // — heading included — for anyone holding neither capability.
          ...(adminItems.length
            ? [{ groupKey: "administration", items: adminItems }]
            : []),
        ].map((group) => (
          <div key={group.groupKey} className="mb-4">
            <div className="eyebrow px-3 pb-2">{t(group.groupKey)}</div>
            <ul className="space-y-1">
              {(() => {
                const shown = visible(group.items);
                // Renumber sequentially by DISPLAY order, not the `step`
                // each item is declared with — if crypto is off and step 3
                // (Takedown) is hidden, the visible steps must read 1·2·3,
                // never 1·2·4. A gap in the sequence reads as a missing
                // page or a bug, not as "step 3 isn't offered here".
                let stepCounter = 0;
                return shown.map((item) => {
                  const active = pathname.startsWith(item.href);
                  const displayStep = item.step ? ++stepCounter : undefined;
                  return (
                    <li key={item.href}>
                      <Link
                        href={item.href}
                        onClick={onNavigate}
                        aria-current={active ? "page" : undefined}
                        className={`flex items-center gap-2.5 rounded-lg px-3 py-2 transition-colors ${
                          active
                            ? "bg-accent/10"
                            : "hover:bg-fg/[.04]"
                        }`}
                      >
                        <span
                          className={`flex h-6 w-6 flex-none items-center justify-center rounded-md text-[11px] font-bold ${
                            displayStep
                              ? active
                                ? "bg-accent text-white"
                                : "bg-elevated text-muted"
                              : ""
                          } ${displayStep ? "" : "text-[15px]"}`}
                          aria-hidden
                        >
                          {displayStep ?? item.glyph}
                        </span>
                        <span className="min-w-0">
                          <span
                            className={`block truncate text-[13.5px] leading-tight ${
                              active ? "font-semibold text-accent-bright" : "font-medium text-fg"
                            }`}
                          >
                            {t(item.labelKey)}
                          </span>
                          {item.subKey && (
                            <span className="block truncate text-[11px] leading-tight text-muted">
                              {t(item.subKey)}
                            </span>
                          )}
                        </span>
                      </Link>
                    </li>
                  );
                });
              })()}
            </ul>
          </div>
        ))}
      </nav>

      <div className="border-t border-line px-3 py-3">
        <Link
          href="/guide"
          onClick={onNavigate}
          aria-current={pathname.startsWith("/guide") ? "page" : undefined}
          className={`flex items-center gap-2.5 rounded-lg px-3 py-2 text-[13px] font-medium transition-colors ${
            pathname.startsWith("/guide")
              ? "bg-accent/10 text-accent-bright"
              : "text-fg hover:bg-fg/[.04]"
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
          className={`flex items-center gap-2.5 rounded-lg px-3 py-2 text-[13px] font-medium transition-colors ${
            pathname.startsWith("/settings")
              ? "bg-accent/10 text-accent-bright"
              : "text-fg hover:bg-fg/[.04]"
          }`}
        >
          <span className="w-4 text-center text-xs" aria-hidden>
            ⚙
          </span>
          {t("controlPanel")}
        </Link>
      </div>
    </>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const t = useTranslations("common");
  const tShell = useTranslations("appShell.agencyChip");
  const pathname = usePathname();
  const { me, config } = useAuth();
  const cryptoEnabled = config?.cryptoEnabled ?? false;
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
        <SidebarNav pathname={pathname} me={me} cryptoEnabled={cryptoEnabled} />
      </aside>

      {/* ── Mobile drawer — hidden nav, slides in over the page ──────── */}
      {mobileNavOpen && (
        <div className="fixed inset-0 z-50 flex md:hidden">
          <div
            className="fixed inset-0 bg-card/90"
            aria-hidden
            onClick={() => setMobileNavOpen(false)}
          />
          <aside className="relative flex h-full w-64 max-w-[80vw] flex-col border-r border-line bg-sidebar shadow-xl shadow-black/50">
            <SidebarNav
              pathname={pathname}
              me={me}
              cryptoEnabled={cryptoEnabled}
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

          <ThemeToggle />
          <ModeBadge />
          <UserMenu />
        </header>

        {/* Case context — the connective thread across MODULE screens. Hidden on
            administration, where it is actively misleading: a case banner over
            "Users" suggests access is granted per case, when roles and accounts
            are agency- and platform-wide. */}
        {!ADMIN_NAV.some((item) => pathname.startsWith(item.href)) && <CaseContextBar />}

        {/* Screen canvas */}
        <main className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden p-3 sm:p-6">{children}</main>
      </div>
    </div>
  );
}
