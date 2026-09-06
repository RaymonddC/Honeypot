"use client";

/**
 * Generated-document card (mockup .doc) — header (icon · title · subtitle)
 * over a mono "paper" preview of the document's key fields. Freeze request
 * and LTKM/STR draft render through this; the multi-agency alert has its
 * own card (agency-alert-card.tsx).
 *
 * P-5: the "↓ PDF" control fetches GET /api/documents/{id} with the
 * analyst's Bearer attached (lib/actions/api.ts `downloadDocument`) and
 * saves the bytes from a blob URL — the route requires identity once
 * postgres persistence is on, which a plain `<a href>` link couldn't carry.
 */

import { useState } from "react";
import { useTranslations } from "next-intl";
import { downloadDocument } from "@/lib/actions/api";
import type { ActionDocument, DispatchTarget } from "@/lib/actions/types";
import { useAuth } from "@/components/auth/auth-provider";
import { roleLabel } from "@/lib/auth/types";
import { DocumentView } from "@/components/actions/document-view";
import type { LetterContext } from "@/lib/actions/letter";

export function DocCard({
  doc,
  caseRef,
  evidenceHash,
  targets,
}: {
  doc: ActionDocument;
  /** Bundle context stamped onto the official letter. */
  caseRef?: string;
  evidenceHash?: string;
  targets?: DispatchTarget[];
}) {
  const t = useTranslations("actions.docCard");
  const { me } = useAuth();
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showDoc, setShowDoc] = useState(false);

  const letterCtx: LetterContext = {
    agencyName: me?.agency.name ?? "Agency",
    agencyType: me?.agency.type,
    officerName: me?.user.name ?? "[Nama Pejabat]",
    officerRole: me ? roleLabel(me.role) : "Pejabat Berwenang",
    caseRef: caseRef ?? "CASE #—",
    evidenceHash: evidenceHash ?? doc.sha256 ?? "—",
    targets: targets ?? [],
  };
  // Only freeze / STR letters get a formal document; the alert has its own card.
  const canPreview = doc.kind === "freeze" || doc.kind === "ltkm";

  const download = async () => {
    if (downloading) return;
    setDownloading(true);
    setError(null);
    try {
      await downloadDocument(doc);
    } catch {
      setError(t("downloadFailed"));
    } finally {
      setDownloading(false);
    }
  };

  return (
    <div className="flex flex-col rounded-card border border-line bg-card">
      {/* header */}
      <div className="flex items-center gap-2.5 border-b border-line px-3.5 py-[13px]">
        <div className="grid h-7 w-7 flex-none place-items-center rounded-full bg-accent/10 text-sm text-accent-bright">
          <span aria-hidden>{doc.icon}</span>
        </div>
        <div className="min-w-0">
          <b className="block truncate text-[12.5px]">{doc.title}</b>
          <small className="text-[12px] text-muted">{doc.subtitle}</small>
        </div>
        <div className="ml-auto flex items-center gap-1.5">
          {canPreview && (
            <button
              type="button"
              onClick={() => setShowDoc(true)}
              title={t("viewTitle")}
              className="cursor-pointer rounded-full border border-accent/30 bg-accent/10 px-2 py-0.5 text-[12px] font-semibold text-accent-bright transition-colors hover:bg-accent/20"
            >
              {t("view")}
            </button>
          )}
          {doc.downloadUrl && (
            <button
              type="button"
              onClick={() => void download()}
              disabled={downloading}
              title={t("downloadPdfTitle")}
              className="cursor-pointer rounded-md border border-line bg-elevated px-2 py-0.5 font-mono text-[12px] text-muted transition-colors hover:border-accent/30 hover:text-accent-bright disabled:cursor-default disabled:opacity-50"
            >
              {downloading ? "…" : t("pdfShort")}
            </button>
          )}
        </div>
      </div>

      {error && (
        <p role="alert" className="px-3.5 pt-2 text-[12px] leading-relaxed text-risk-high">
          {error}
        </p>
      )}

      {/* paper preview */}
      <div className="min-h-[200px] flex-1 p-3.5 text-[12px] text-muted">
        <div className="rounded-lg border border-line bg-elevated p-[13px] font-mono text-[12px] leading-[1.7] text-muted">
          <h5 className="mb-2 font-sans text-[12px] font-bold uppercase tracking-[.04em] text-fg">
            {doc.paperTitle}
          </h5>
          {doc.fields.map((f, i) => (
            <div
              key={`${f.label}-${i}`}
              className={`flex justify-between gap-3 py-1 ${
                i < doc.fields.length - 1
                  ? "border-b border-dashed border-line"
                  : ""
              }`}
            >
              <span className="text-muted">{f.label}</span>
              <span
                className="truncate text-right tnum"
                style={f.color ? { color: f.color } : undefined}
                title={f.placeholder ? t("humanFilledBeforeDispatch") : undefined}
              >
                {f.value}
              </span>
            </div>
          ))}
        </div>
      </div>

      {showDoc && canPreview && (
        <DocumentView doc={doc} ctx={letterCtx} onClose={() => setShowDoc(false)} />
      )}
    </div>
  );
}
