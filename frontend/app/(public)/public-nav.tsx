"use client";

/**
 * The public site's two jobs, as a switch.
 *
 * Checking an account and reporting one are different intentions arriving from
 * different places — someone mid-transfer wants an answer in seconds, someone
 * who has just been scammed wants to tell somebody. Putting both on one
 * scrolling page made the second look like an afterthought under the first.
 * They are separate routes, and each is linkable on its own.
 */

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";
import { Icon, type IconName } from "@/components/icon";

const TABS: Array<{ href: string; key: "check" | "report"; icon: IconName }> = [
  { href: "/cek", key: "check", icon: "search" },
  { href: "/lapor", key: "report", icon: "uncover" },
];

export function PublicNav() {
  const t = useTranslations("cekscam.nav");
  const pathname = usePathname();
  return (
    <nav className="flex gap-1.5" aria-label={t("ariaLabel")}>
      {TABS.map((tab) => {
        const active = pathname === tab.href;
        return (
          <Link
            key={tab.href}
            href={tab.href}
            aria-current={active ? "page" : undefined}
            className={`flex items-center gap-2 rounded-full border px-3.5 py-2 text-[13px] transition-colors ${
              active
                ? "border-white/25 bg-elevated font-semibold text-fg"
                : "border-line text-muted hover:text-fg"
            }`}
          >
            <Icon name={tab.icon} size={14} />
            {t(tab.key)}
          </Link>
        );
      })}
    </nav>
  );
}
