/**
 * Generated-document card (mockup .doc) — header (icon · title · subtitle)
 * over a mono "paper" preview of the document's key fields. Freeze request
 * and LTKM/STR draft render through this; the multi-agency alert has its
 * own card (agency-alert-card.tsx).
 */

import type { ActionDocument } from "@/lib/actions/types";

export function DocCard({ doc }: { doc: ActionDocument }) {
  return (
    <div className="flex flex-col rounded-card border border-line bg-card">
      {/* header */}
      <div className="flex items-center gap-2.5 border-b border-line px-3.5 py-[13px]">
        <div className="grid h-7 w-7 flex-none place-items-center rounded-lg bg-accent/10 text-sm text-accent-bright">
          <span aria-hidden>{doc.icon}</span>
        </div>
        <div className="min-w-0">
          <b className="block truncate text-[12.5px]">{doc.title}</b>
          <small className="text-[10px] text-muted">{doc.subtitle}</small>
        </div>
        {doc.downloadUrl && (
          <a
            href={doc.downloadUrl}
            target="_blank"
            rel="noreferrer"
            title="Download PDF (GET /api/documents/{id})"
            className="ml-auto rounded-md border border-line bg-elevated px-2 py-0.5 font-mono text-[10px] text-white/60 transition-colors hover:border-accent/30 hover:text-accent-bright"
          >
            ↓ PDF
          </a>
        )}
      </div>

      {/* paper preview */}
      <div className="min-h-[200px] flex-1 p-3.5 text-[11.5px] text-white/60">
        <div className="rounded-lg border border-line bg-[#0c0d0f] p-[13px] font-mono text-[10.5px] leading-[1.7] text-white/60">
          <h5 className="mb-2 font-sans text-[11px] font-bold uppercase tracking-[.04em] text-fg">
            {doc.paperTitle}
          </h5>
          {doc.fields.map((f, i) => (
            <div
              key={`${f.label}-${i}`}
              className={`flex justify-between gap-3 py-1 ${
                i < doc.fields.length - 1
                  ? "border-b border-dashed border-white/5"
                  : ""
              }`}
            >
              <span className="text-muted">{f.label}</span>
              <span
                className="truncate text-right tnum"
                style={f.color ? { color: f.color } : undefined}
                title={f.placeholder ? "Human-filled before dispatch" : undefined}
              >
                {f.value}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
