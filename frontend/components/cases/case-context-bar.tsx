"use client";

/**
 * Case context bar — the connective thread across the app. A slim strip under
 * the top bar on every module screen showing the active case, its stage, the
 * one-line "what to do now", and a jump back to the Case File. Makes each
 * module screen visibly part of the same case. Hidden on the Case File itself
 * and on non-case screens (settings/guide/login).
 */

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";
import { useCases } from "@/components/cases/case-provider";
import { isNavActive } from "@/lib/nav";
import { Icon } from "@/components/icon";

// Routes that are NOT part of a case workflow → no bar.
const HIDDEN = ["/home", "/case", "/settings", "/guide", "/login"];

export function CaseContextBar() {
  const t = useTranslations("cases.contextBar");
  const pathname = usePathname();
  const { activeCase } = useCases();

  if (HIDDEN.some((p) => isNavActive(pathname, p))) return null;

  if (!activeCase) {
    return (
      <div className="flex items-center gap-2 border-b border-line bg-sidebar px-4 py-1.5 text-[12px]">
        <span className="text-muted">{t("noActiveCase")}</span>
        <Link href="/case" className="font-semibold text-accent-bright hover:underline">
          {t("openACase")}
        </Link>
        <span className="text-muted/70">{t("openACaseHint")}</span>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-2.5 border-b border-line bg-sidebar px-4 py-1.5 text-[12px]">
      <Link
        href="/case"
        className="flex items-center gap-1.5 font-medium text-fg hover:text-accent-bright"
        title={t("backToCaseFile")}
      >
        <Icon name="case" size={13} className="flex-none text-muted" />
        <span className="max-w-[16rem] truncate">{activeCase.title}</span>
      </Link>
      <span
        className="rounded border border-accent/30 bg-accent/10 px-1.5 py-0.5 text-[12px] font-bold uppercase tracking-wide text-accent-bright"
        title={t("currentStageTitle")}
      >
        {activeCase.stage}
      </span>
      <span className="hidden truncate text-muted sm:inline">
        · {t(`stageTask.${activeCase.stage}`)}
      </span>
      <div className="flex-1" />
      <Link href="/case" className="flex-none text-muted hover:text-fg">
        {t("caseFileLink")}
      </Link>
    </div>
  );
}
