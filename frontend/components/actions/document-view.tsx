"use client";

/**
 * Document viewer — renders the formal letter/report as HTML (the same markup
 * that downloads). "Print / Save as PDF" prints the letter through the browser,
 * so the saved PDF looks exactly like what's on screen. Esc / backdrop closes.
 */

import { useEffect, useMemo, useRef } from "react";
import { useTranslations } from "next-intl";
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
  const t = useTranslations("actions.documentView");
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

  const kind = doc.kind === "ltkm" ? t("kindLtkm") : t("kindFreeze");

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-card/90 p-4 backdrop-blur-sm"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label={t("documentViewer")}
    >
      <div
        className="flex h-[88vh] w-full max-w-[900px] flex-col overflow-hidden rounded-card border border-line bg-card shadow-2xl shadow-black/50"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between gap-3 border-b border-line px-4 py-2.5">
          <div className="min-w-0">
            <div className="eyebrow text-accent-bright">{kind}</div>
            <div className="truncate text-[12px] text-muted">
              {t("printHint")}
            </div>
          </div>
          <div className="flex flex-none items-center gap-2">
            <button
              type="button"
              onClick={printDoc}
              className="h-8 rounded-full bg-accent px-3.5 text-[12px] font-semibold text-[#090909] transition-colors hover:bg-accent-bright"
            >
              {t("printSaveAsPdf")}
            </button>
            <button
              type="button"
              onClick={() => downloadHtml(html, documentFilename(doc))}
              title={t("saveAsHtmlTitle")}
              className="h-8 rounded-lg border border-line bg-elevated px-3 text-[12px] font-semibold text-muted transition-colors hover:text-fg"
            >
              {t("html")}
            </button>
            <button
              type="button"
              onClick={onClose}
              className="h-8 rounded-lg border border-line bg-elevated px-3 text-[12px] font-semibold text-muted transition-colors hover:text-fg"
            >
              {t("close")}
            </button>
          </div>
        </div>
        <iframe
          ref={frameRef}
          title={t("document")}
          srcDoc={html}
          className="w-full flex-1 bg-white"
        />
      </div>
    </div>
  );
}
