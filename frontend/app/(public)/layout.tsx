"use client";

/**
 * Chrome shared by the public (Layer 1 · B2C) pages.
 *
 * Deliberately NOT the investigator AppShell: no case switcher, no mode badge,
 * no module rail. A member of the public has no case and no account, and the
 * vocabulary of the console would only tell them they are in the wrong place.
 *
 * The limits block sits here rather than on one page because it qualifies both:
 * the check is answering from a demo index, and the report is not transmitted.
 * A caveat that only appears on one of the two screens is a caveat someone can
 * miss by arriving at the other.
 */

import { useTranslations } from "next-intl";
import { INDEX_SIZE } from "@/lib/cekscam/mock";
import { PublicNav } from "./public-nav";

export default function PublicLayout({ children }: { children: React.ReactNode }) {
  const t = useTranslations("cekscam");
  return (
    <div className="min-h-screen bg-bg text-fg">
      <header className="border-b border-line">
        <div className="mx-auto max-w-[860px] px-5 py-4">
          <div className="flex items-center gap-2.5">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-white/10 text-[13px] font-bold text-white">
              IT
            </span>
            <div className="min-w-0">
              <div className="text-[15px] font-semibold tracking-tight">{t("brand")}</div>
              <div className="text-[12px] text-muted">{t("brandSub")}</div>
            </div>
            <span className="ml-auto flex-none rounded-md border border-risk-med/30 bg-risk-med/10 px-2 py-1 text-[12px] text-risk-med">
              {t("demoBadge")}
            </span>
          </div>
          <div className="mt-3.5">
            <PublicNav />
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[860px] px-5 pb-16 pt-8 sm:pt-10">{children}</main>

      <footer className="mx-auto max-w-[860px] px-5 pb-14">
        <div className="border-t border-line pt-5">
          <div className="eyebrow mb-2">{t("limits.eyebrow")}</div>
          <ul className="max-w-[70ch] space-y-1.5 text-[12.5px] leading-relaxed text-muted">
            <li>{t("limits.demo", { count: INDEX_SIZE })}</li>
            <li>{t("limits.notSafe")}</li>
            <li>{t("limits.notOfficial")}</li>
          </ul>
        </div>
      </footer>
    </div>
  );
}
