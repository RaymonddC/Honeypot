/**
 * Extracted-entities side panel — icon · monospace value · context line ·
 * confidence (mockup .ent rows). Count tag reflects validated entities.
 */

import type { HpEntity } from "@/lib/honeypot/types";
import { entityIcon, formatConf } from "@/lib/honeypot/types";

export function EntityPanel({ entities }: { entities: HpEntity[] }) {
  return (
    <div className="mb-3.5 rounded-card border border-line bg-card">
      <div className="flex items-center justify-between border-b border-line px-3.5 py-3">
        <span className="eyebrow">Extracted entities</span>
        <span className="rounded-md border border-line bg-elevated px-2 py-0.5 font-mono text-[10.5px] text-white/60">
          {entities.length} · validated
        </span>
      </div>

      {entities.length ? (
        entities.map((e) => (
          <div
            key={e.id}
            className="flex items-center gap-2.5 border-b border-line px-3.5 py-[9px] last:border-b-0"
          >
            <div
              aria-label={e.type.replace(/_/g, " ")}
              role="img"
              className="grid h-6 w-6 flex-none place-items-center rounded-md border border-line bg-elevated text-[11px]"
            >
              {entityIcon(e.type)}
            </div>
            <div className="min-w-0">
              <div className="truncate font-mono text-[11px] text-fg">
                {e.value}
              </div>
              <small className="block truncate text-[10px] text-muted">
                {e.subtitle}
              </small>
            </div>
            <div className="ml-auto flex-none font-mono text-[10px] tnum text-muted">
              conf{" "}
              <b className="font-bold text-accent-bright">
                {formatConf(e.confidence)}
              </b>
            </div>
          </div>
        ))
      ) : (
        <div className="px-3.5 py-6 text-center text-[11px] text-muted">
          No validated entities yet — the agent is still baiting.
        </div>
      )}
    </div>
  );
}
