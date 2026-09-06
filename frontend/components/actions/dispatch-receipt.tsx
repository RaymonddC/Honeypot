"use client";

/**
 * Dispatch receipt viewer — shows the confirmation of a dispatched bundle
 * (agencies notified, channels, statuses). Print / Save as PDF, or download the
 * HTML. Esc / backdrop closes.
 */

import { useEffect, useMemo, useRef } from "react";
import { useTranslations } from "next-intl";
import type { ActionBundle } from "@/lib/actions/types";
import { downloadHtml } from "@/lib/actions/letter";
import { buildDispatchReceiptHtml, receiptFilename } from "@/lib/actions/receipt";

export function DispatchReceipt({
  bundle,
  onClose,
}: {
  bundle: ActionBundle;
  onClose: () => void;
}) {
  const t = useTranslations("actions.dispatchReceipt");
  const html = useMemo(() => buildDispatchReceiptHtml(bundle), [bundle]);
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

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-card/90 p-4 backdrop-blur-sm"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label={t("dispatchReceipt")}
    >
      <div
        className="flex h-[82vh] w-full max-w-[820px] flex-col overflow-hidden rounded-card border border-line bg-card shadow-2xl shadow-black/50"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between gap-3 border-b border-line px-4 py-2.5">
          <div>
            <div className="eyebrow text-accent-bright">{t("dispatchReceipt")}</div>
            <div className="text-[10.5px] text-muted">
              {t("confirmationSubtitle")}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={printDoc}
              className="h-8 rounded-full bg-accent px-3.5 text-xs font-semibold text-[#090909] transition-colors hover:bg-accent-bright"
            >
              🖶 {t("printSaveAsPdf")}
            </button>
            <button
              type="button"
              onClick={() => downloadHtml(html, receiptFilename())}
              className="h-8 rounded-lg border border-line bg-elevated px-3 text-xs font-semibold text-muted transition-colors hover:text-fg"
            >
              ⬇ {t("html")}
            </button>
            <button
              type="button"
              onClick={onClose}
              className="h-8 rounded-lg border border-line bg-elevated px-3 text-xs font-semibold text-muted transition-colors hover:text-fg"
            >
              {t("close")}
            </button>
          </div>
        </div>
        <iframe ref={frameRef} title={t("dispatchReceipt")} srcDoc={html} className="w-full flex-1 bg-white" />
      </div>
    </div>
  );
}
