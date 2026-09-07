"use client";

/**
 * Route gate (P5): /login renders bare (no shell); every other route requires
 * a session — anonymous visitors are redirected to /login. While the token is
 * being read a minimal splash renders (one client tick, no flash of content).
 */

import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { AppShell } from "@/components/app-shell";
import { useAuth } from "./auth-provider";

function Splash() {
  const t = useTranslations("auth.appGate");
  return (
    <div className="flex h-screen items-center justify-center bg-bg">
      <div className="flex items-center gap-2.5 text-muted">
        <span className="flex h-7 w-7 animate-pulse items-center justify-center rounded-full bg-accent/15 text-[12px] font-bold text-accent-bright">
          IT
        </span>
        <span className="text-sm tracking-wide">{t("appName")}</span>
      </div>
    </div>
  );
}

// Bare routes (no shell, no auth): the login screen and the root path — which
// is just a server redirect() to /login, so it must render (not Splash) for the
// redirect to fire. Everything else requires a session.
const PUBLIC_ROUTES = new Set(["/", "/login"]);

export function AppGate({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { status } = useAuth();
  const isLogin = pathname === "/login";
  const isPublic = PUBLIC_ROUTES.has(pathname);

  useEffect(() => {
    if (!isPublic && status === "anon") router.replace("/login");
    if (isLogin && status === "authed") router.replace("/home");
  }, [isPublic, isLogin, status, router]);

  if (isPublic) return <>{children}</>;
  if (status !== "authed") return <Splash />;
  return <AppShell>{children}</AppShell>;
}
