"use client";

/**
 * Multi-agency alert card — a broadcast dispatch record: one row per agency
 * with its type, the delivery channel/protocol it's routed over (goAML · IASC ·
 * compliance API · secure email), the requested action, and per-target delivery
 * status. Reads like a real coordinated-alert manifest.
 */

import { useTranslations } from "next-intl";
import type { DispatchTarget } from "@/lib/actions/types";
import { DOC_META, STATUS_COLORS, STATUS_LABELS } from "@/lib/actions/types";

// Distinct category hues drawn from the Framer accent + gradient family.
const TYPE_COLOR: Record<string, string> = {
  regulator: "#0099ff", // blue — the primary accent
  bank: "#6a4cf5", // violet
  exchange: "#d44df0", // magenta
  police: "#ff7a3d", // orange
};

function typeOf(t: DispatchTarget): string {
  const at = (t.agencyType ?? "").toLowerCase();
  if (at) return at;
  const n = t.name.toLowerCase();
  if (n.includes("ppatk") || n.includes("ojk")) return "regulator";
  if (n.includes("bank")) return "bank";
  if (/indodax|tokocrypto|reku|exchange|binance/.test(n)) return "exchange";
  if (n.includes("bareskrim") || n.includes("pol")) return "police";
  return "";
}

/** Delivery channel per agency — real routing protocols, defaulted by type. */
function channelOf(target: DispatchTarget, tr: (key: string) => string): string {
  if (target.channel) return target.channel;
  switch (typeOf(target)) {
    case "regulator":
      return "goAML";
    case "bank":
      return "IASC";
    case "exchange":
      return tr("channelComplianceApi");
    case "police":
      return tr("channelSecureEmail");
    default:
      return tr("channelSecureChannel");
  }
}

export function AgencyAlertCard({
  targets,
  caseRef,
}: {
  targets: DispatchTarget[];
  caseRef?: string;
}) {
  const t = useTranslations("actions.agencyAlertCard");
  const meta = DOC_META.alert;
  const ref = `ALT-${(caseRef?.match(/\d+/)?.[0] ?? "0417").slice(-4)}/${new Date().getFullYear()}`;

  return (
    <div className="flex flex-col rounded-card border border-line bg-card">
      {/* header */}
      <div className="flex items-center gap-2.5 border-b border-line px-3.5 py-2.5">
        <div className="grid h-7 w-7 flex-none place-items-center rounded-full bg-accent/10 text-sm text-accent-bright">
          <span aria-hidden>{meta.icon}</span>
        </div>
        <div className="min-w-0">
          <b className="block truncate text-[12.5px]">{meta.title}</b>
          <small className="font-mono text-[10px] text-muted">
            {ref} ·{" "}
            {targets.length === 1
              ? t("agencyCountOne")
              : t("agencyCountOther", { count: targets.length })}
          </small>
        </div>
        <span className="ml-auto flex-none rounded-md border border-risk-high/40 bg-risk-high/10 px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wide text-risk-high">
          ⚠ {t("urgent")}
        </span>
      </div>

      {/* target rows */}
      <div className="min-h-[180px] flex-1">
        {targets.length ? (
          targets.map((target) => {
            const type = typeOf(target);
            const color = TYPE_COLOR[type] ?? "rgba(255,255,255,.5)";
            return (
              <div
                key={target.id}
                className="flex items-start gap-2.5 border-b border-line px-3.5 py-2.5 last:border-b-0"
              >
                <div
                  className="grid h-[32px] w-[32px] flex-none place-items-center rounded-lg border text-[10px] font-extrabold"
                  style={{ color, borderColor: `${color}55`, background: `${color}12` }}
                >
                  {target.code}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5">
                    <b className="truncate text-xs">{target.name}</b>
                    {type && (
                      <span
                        className="flex-none rounded px-1 py-px text-[8.5px] font-semibold uppercase tracking-wide"
                        style={{ color, background: `${color}18` }}
                      >
                        {type}
                      </span>
                    )}
                  </div>
                  <small className="mt-0.5 block truncate text-[10px] text-muted">
                    {target.action}
                  </small>
                  <span className="mt-1 inline-flex items-center gap-1 rounded border border-line bg-elevated px-1.5 py-px font-mono text-[9px] text-muted">
                    <span aria-hidden>↗</span> {t("viaChannel", { channel: channelOf(target, t) })}
                  </span>
                </div>
                <span
                  className="flex-none text-[10.5px] font-bold uppercase tracking-[.05em]"
                  style={{ color: STATUS_COLORS[target.status] }}
                >
                  {STATUS_LABELS[target.status]}
                </span>
              </div>
            );
          })
        ) : (
          <div className="px-3.5 py-6 text-center text-[11px] text-muted">
            {t("noTargets")}
          </div>
        )}
      </div>

      {/* footer — dispatch posture */}
      <div className="border-t border-line px-3.5 py-2 text-[9.5px] leading-relaxed text-muted">
        {t.rich("footerNote", {
          b: (chunks) => <b className="text-fg">{chunks}</b>,
        })}
      </div>
    </div>
  );
}
