/**
 * UNCOVER / Action Panel screen — frontend-canonical types.
 *
 * The API layer (lib/actions/api.ts) normalizes whatever the backend returns
 * (docs/API-Contract.md · UNCOVER endpoints) into these shapes; the mock
 * fallback (lib/actions/mock.ts) produces them directly, ported from the
 * approved mockup's Action Panel (#act) section.
 */

export type DataSource = "api" | "mock";

/* ── Generated documents ───────────────────────────────────────────────── */

export type DocKind = "freeze" | "ltkm" | "alert";

export interface DocField {
  label: string;
  value: string;
  /** Value color override (e.g. risk red, placeholder amber). */
  color?: string;
  /** Human-must-fill placeholder (LTKM subject identity). */
  placeholder?: boolean;
}

export interface ActionDocument {
  id: string;
  kind: DocKind;
  /** Card title, e.g. "Freeze Request". */
  title: string;
  /** Card subtitle, e.g. "PDF · bank + exchange". */
  subtitle: string;
  /** Icon glyph for the card header. */
  icon: string;
  /** In-paper document heading, e.g. "Permintaan Pemblokiran". */
  paperTitle: string;
  fields: DocField[];
  /** SHA-256 evidence hash (short form ok). */
  sha256?: string;
  /** Set when the backend persisted a PDF → GET /api/documents/{id}. */
  downloadUrl?: string;
}

/* ── Multi-agency dispatch targets ─────────────────────────────────────── */

export type DispatchStatus =
  | "draft" // pre-dispatch: generated, awaiting analyst confirmation
  | "mock" // dispatched into the POC mock sink
  | "queued"
  | "sent"
  | "failed"
  | "acknowledged";

export interface DispatchTarget {
  id: string;
  /** Short badge code, e.g. "BCA" / "IDX" / "PPT". */
  code: string;
  /** Full name, e.g. "Bank BCA". */
  name: string;
  /** What gets asked of them, e.g. "Freeze mule a/n 4881…". */
  action: string;
  status: DispatchStatus;
  /** Delivery channel/protocol, e.g. "goAML" / "IASC" / "Compliance API". */
  channel?: string;
  /** Agency type, e.g. "regulator" / "bank" / "exchange" / "police". */
  agencyType?: string;
}

/* ── Aggregate bundle ──────────────────────────────────────────────────── */

export interface ActionBundle {
  /** Backend bundle id (null when running on the mock). */
  id: string | null;
  /** e.g. "CASE #ITU-2026-0417". */
  caseRef: string;
  /** e.g. "3 wallets · 2 mule accounts". */
  summary: string;
  /** Bundle-level SHA-256 evidence hash (custody manifest). */
  evidenceHash: string;
  documents: ActionDocument[];
  targets: DispatchTarget[];
  /** True once the analyst confirmed & dispatched. */
  dispatched: boolean;
  source: DataSource;
}

/* ── Status styling (mockup .status.mock = amber) ──────────────────────── */

export const STATUS_COLORS: Record<DispatchStatus, string> = {
  draft: "rgba(255,255,255,.34)",
  mock: "#f5a524",
  queued: "#f5a524",
  sent: "#34d399",
  acknowledged: "#34d399",
  failed: "#ef4444",
};

export const STATUS_LABELS: Record<DispatchStatus, string> = {
  draft: "· draft",
  mock: "● mock",
  queued: "● queued",
  sent: "● sent",
  acknowledged: "● ack’d",
  failed: "● failed",
};

/* ── Doc card chrome by kind (mockup #act cards) ───────────────────────── */

export const DOC_META: Record<DocKind, { icon: string; title: string; subtitle: string }> = {
  freeze: { icon: "🧊", title: "Freeze Request", subtitle: "PDF · bank + exchange" },
  ltkm: { icon: "📄", title: "LTKM / STR Draft", subtitle: "goAML · PPATK" },
  alert: { icon: "📡", title: "Multi-agency Alert", subtitle: "bank · exchange · PPATK" },
};

export const AMBER = "#f5a524";
export const HIGH = "#ef4444";
