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
import { useCases } from "@/components/cases/case-provider";
import type { CaseStage } from "@/lib/cases/api";

const STAGE_TASK: Record<CaseStage, string> = {
  intake: "Surface suspect accounts & wallets (Honeypot)",
  freeze: "Generate & dispatch the freeze request (Action Panel)",
  trace: "Trace the money flow (Bridge)",
  takedown: "Score the wallet network (Investigation)",
  report: "File the STR / LTKM (Action Panel)",
  recovery: "Track fund recovery (Response)",
  closed: "Case closed",
};

// Routes that are NOT part of a case workflow → no bar.
const HIDDEN = ["/case", "/settings", "/guide", "/login"];

export function CaseContextBar() {
  const pathname = usePathname();
  const { activeCase } = useCases();

  if (HIDDEN.some((p) => pathname.startsWith(p))) return null;

  if (!activeCase) {
    return (
      <div className="flex items-center gap-2 border-b border-line bg-sidebar px-4 py-1.5 text-[11.5px]">
        <span className="text-muted">No active case.</span>
        <Link href="/case" className="font-semibold text-accent-bright hover:underline">
          Open a case →
        </Link>
        <span className="text-muted/70">— your work here will attach to it.</span>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-2.5 border-b border-line bg-sidebar px-4 py-1.5 text-[11.5px]">
      <Link
        href="/case"
        className="flex items-center gap-1.5 font-medium text-fg hover:text-accent-bright"
        title="Back to the Case File"
      >
        <span aria-hidden className="text-muted">▤</span>
        <span className="max-w-[16rem] truncate">{activeCase.title}</span>
      </Link>
      <span
        className="rounded border border-accent/30 bg-accent/10 px-1.5 py-0.5 text-[9.5px] font-bold uppercase tracking-wide text-accent-bright"
        title="Current investigation stage"
      >
        {activeCase.stage}
      </span>
      <span className="hidden truncate text-muted sm:inline">
        · {STAGE_TASK[activeCase.stage]}
      </span>
      <div className="flex-1" />
      <Link href="/case" className="flex-none text-muted hover:text-fg">
        Case File →
      </Link>
    </div>
  );
}
