/**
 * Multi-agency alert card (mockup third .doc) — one row per dispatch target
 * (bank · exchange · PPATK) with its short-code badge, the requested action,
 * and the per-target delivery status (POC = "● mock").
 */

import type { DispatchTarget } from "@/lib/actions/types";
import { DOC_META, STATUS_COLORS, STATUS_LABELS } from "@/lib/actions/types";

export function AgencyAlertCard({ targets }: { targets: DispatchTarget[] }) {
  const meta = DOC_META.alert;
  return (
    <div className="flex flex-col rounded-card border border-line bg-card">
      {/* header */}
      <div className="flex items-center gap-2.5 border-b border-line px-3.5 py-[13px]">
        <div className="grid h-7 w-7 flex-none place-items-center rounded-lg bg-accent/10 text-sm text-accent-bright">
          <span aria-hidden>{meta.icon}</span>
        </div>
        <div>
          <b className="block text-[12.5px]">{meta.title}</b>
          <small className="text-[10px] text-muted">{meta.subtitle}</small>
        </div>
      </div>

      {/* target rows */}
      <div className="min-h-[200px] flex-1">
        {targets.length ? (
          targets.map((t) => (
            <div
              key={t.id}
              className="flex items-center gap-[11px] border-b border-line px-3.5 py-[11px] last:border-b-0"
            >
              <div className="grid h-[34px] w-[34px] flex-none place-items-center rounded-lg border border-line bg-elevated text-[10px] font-extrabold text-white/60">
                {t.code}
              </div>
              <div className="min-w-0">
                <b className="block truncate text-xs">{t.name}</b>
                <small className="block truncate text-[10px] text-muted">
                  {t.action}
                </small>
              </div>
              <span
                className="ml-auto flex-none text-[10.5px] font-bold uppercase tracking-[.05em]"
                style={{ color: STATUS_COLORS[t.status] }}
              >
                {STATUS_LABELS[t.status]}
              </span>
            </div>
          ))
        ) : (
          <div className="px-3.5 py-6 text-center text-[11px] text-muted">
            No dispatch targets — generate documents first.
          </div>
        )}
      </div>
    </div>
  );
}
