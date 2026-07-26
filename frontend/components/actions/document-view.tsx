"use client";

/**
 * Document viewer — renders the formal letter/report as HTML (the same markup
 * that downloads). "Print / Save as PDF" prints the letter through the browser,
 * so the saved PDF looks exactly like what's on screen. Esc / backdrop closes.
 */

import { useEffect, useMemo, useRef } from "react";
import type { ActionDocument } from "@/lib/actions/types";
import {
  buildDocumentHtml,
  documentFilename,
  downloadHtml,
  type LetterContext,
} from "@/lib/actions/letter";

export function DocumentView({
  doc,
  ctx,
  onClose,
}: {
  doc: ActionDocument;
  ctx: LetterContext;
  onClose: () => void;
}) {
  const html = useMemo(() => buildDocumentHtml(doc, ctx), [doc, ctx]);
  const frameRef = useRef<HTMLIFrameElement>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const printDoc = () => {
    const w = frameRef.current?.contentWindow;
    if (!w) return;
    w.focus();
    w.print();
  };

  const kind = doc.kind === "ltkm" ? "LTKM / STR draft" : "Freeze request letter";

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label="Document viewer"
    >
      <div
        className="flex h-[88vh] w-full max-w-[900px] flex-col overflow-hidden rounded-card border border-line bg-card shadow-2xl shadow-black/50"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between gap-3 border-b border-line px-4 py-2.5">
          <div className="min-w-0">
            <div className="eyebrow text-accent-bright">{kind}</div>
            <div className="truncate text-[10.5px] text-muted">
              Print / Save as PDF to get a copy that looks exactly like this.
            </div>
          </div>
          <div className="flex flex-none items-center gap-2">
            <button
              type="button"
              onClick={printDoc}
              className="h-8 rounded-lg bg-accent px-3.5 text-xs font-semibold text-[#04140d] transition-colors hover:bg-accent-bright"
            >
              🖶 Print / Save as PDF
            </button>
            <button
              type="button"
              onClick={() => downloadHtml(html, documentFilename(doc))}
              title="Save the letter as an HTML file"
              className="h-8 rounded-lg border border-white/10 bg-elevated px-3 text-xs font-semibold text-muted transition-colors hover:text-fg"
            >
              ⬇ HTML
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
          ref={frameRef}
          title="Document"
          srcDoc={html}
          className="w-full flex-1 bg-white"
        />
      </div>
    </div>
  );
}
