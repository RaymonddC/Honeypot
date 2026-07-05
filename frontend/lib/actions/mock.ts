/**
 * Local fallback demo data — ported from the approved Action Panel mockup
 * (artifact d592d92c · #act section). Used whenever the backend API is
 * unreachable so the screen always renders standalone.
 */

import type { ActionBundle, ActionDocument, DispatchTarget } from "./types";
import { AMBER, DOC_META, HIGH } from "./types";

export const MOCK_DOCUMENTS: ActionDocument[] = [
  {
    id: "doc-freeze",
    kind: "freeze",
    ...DOC_META.freeze,
    paperTitle: "Permintaan Pemblokiran",
    fields: [
      { label: "Wallet", value: "TХ9dQp…aQ4pJ6" },
      { label: "Exchange", value: "Indodax" },
      { label: "Tx hash", value: "a3f9…c21b" },
      { label: "Risk", value: "0.91 HIGH", color: HIGH },
      { label: "Basis", value: "POJK 27/2024" },
      { label: "SHA-256", value: "7c4d…9ffa" },
    ],
    sha256: "7c4d…9ffa",
  },
  {
    id: "doc-ltkm",
    kind: "ltkm",
    ...DOC_META.ltkm,
    paperTitle: "Laporan Transaksi Mencurigakan",
    fields: [
      { label: "Subject", value: "⬚ fill identity", color: AMBER, placeholder: true },
      { label: "Typology", value: "layering · relay" },
      { label: "Amount", value: "$412,880" },
      { label: "Indicators", value: "peel, rapid-relay" },
      { label: "Format", value: "IVMS / goAML XML" },
    ],
    sha256: "b91e…d044",
  },
];

export const MOCK_TARGETS: DispatchTarget[] = [
  {
    id: "tgt-bca",
    code: "BCA",
    name: "Bank BCA",
    action: "Freeze mule a/n 4881…",
    status: "mock",
  },
  {
    id: "tgt-idx",
    code: "IDX",
    name: "Indodax",
    action: "Flag deposit wallet",
    status: "mock",
  },
  {
    id: "tgt-ppt",
    code: "PPT",
    name: "PPATK",
    action: "Submit LTKM (goAML)",
    status: "mock",
  },
];

export function buildMockBundle(): ActionBundle {
  return {
    id: null,
    caseRef: "CASE #ITU-2026-0417",
    summary: "3 wallets · 2 mule accounts",
    evidenceHash: "7c4d09a1…9ffa",
    documents: MOCK_DOCUMENTS,
    targets: MOCK_TARGETS,
    dispatched: false,
    source: "mock",
  };
}
