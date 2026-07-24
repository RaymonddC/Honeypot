"use client";

/**
 * Trace report modal — previews the exact HTML that gets downloaded (same
 * string powers both the <iframe> and the file), so it's WYSIWYG. Esc or a
 * backdrop click closes it.
 */

import { useEffect, useMemo } from "react";
import type { BridgeData } from "@/lib/bridge/types";
import {
  buildTraceReportHtml,
  downloadHtml,
  traceReportFilename,
} from "@/lib/bridge/report";

export function TraceReport({
  data,
  caseTitle,
  onClose,
}: {
  data: BridgeData;
  caseTitle?: string;
  onClose: () => void;
}) {
  const html = useMemo(
    () => buildTraceReportHtml(data, caseTitle),
    [data, caseTitle],
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label="Trace report preview"
    >
      <div
        className="flex h-[86vh] w-full max-w-[920px] flex-col overflow-hidden rounded-card border border-line bg-card shadow-2xl shadow-black/50"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between gap-3 border-b border-line px-4 py-2.5">
          <div>
            <div className="eyebrow text-accent-bright">Trace report</div>
            <div className="text-[10.5px] text-muted">
              Preview — this is exactly what downloads
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => downloadHtml(html, traceReportFilename())}
              className="h-8 rounded-lg bg-accent px-3.5 text-xs font-semibold text-[#04140d] transition-colors hover:bg-accent-bright"
            >
              ⬇ Download report
            </button>
            <button
              type="button"
              onClick={onClose}
              className="h-8 rounded-lg border border-white/10 bg-elevated px-3 text-xs font-semibold text-muted transition-colors hover:text-fg"
            >
              Close
            </button>
          </div>
        </div>
        <iframe
          title="Trace report preview"
          srcDoc={html}
          className="w-full flex-1 bg-white"
        />
      </div>
    </div>
  );
}
