/**
 * UNCOVER API client — Action Panel data (shapes confirmed by P3-Backend):
 *
 *   POST /api/actions/generate  {case_id?, entities?, outputs?} → ActionBundle
 *   GET  /api/actions/{id}                                      → ActionBundle
 *   POST /api/actions/{id}/dispatch                             → ActionBundle
 *                       (status="dispatched", notifications[] filled, mock sink)
 *   GET  /api/documents/{id}                                    → PDF binary
 *
 * ActionBundle: { id, case_id, status: draft|dispatched, documents[]
 * (type: account_blocking|str_report|summary), goaml_draft, routing_plan[]
 * ({agency, agency_type, channel, document_type, reason}), notifications[]
 * ({target_agency, status: mock|…}), totals ({at_risk_usdt, at_risk_idr}),
 * audit[] (hash-chained, sha256) }.
 *
 * Base URL: NEXT_PUBLIC_API_URL (default http://localhost:8000). Any failure
 * falls back to the local mock (lib/actions/mock.ts) so the screen stays
 * demoable standalone.
 */

import { buildMockBundle } from "./mock";
import type {
  ActionBundle,
  ActionDocument,
  DispatchStatus,
  DispatchTarget,
  DocField,
  DocKind,
} from "./types";
import { AMBER, DOC_META, HIGH } from "./types";

import { API_BASE as BASE, apiFetch } from "@/lib/http";

/* eslint-disable @typescript-eslint/no-explicit-any */

async function request<T>(
  path: string,
  init?: RequestInit,
  timeoutMs = 8000,
): Promise<T> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await apiFetch(path, {
      ...init,
      signal: ctrl.signal,
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return (await res.json()) as T;
  } finally {
    clearTimeout(timer);
  }
}

const num = (v: unknown): number | null => {
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
};

const first = (...vals: unknown[]): any =>
  vals.find((v) => v !== undefined && v !== null);

const str = (v: unknown): string | undefined =>
  v == null ? undefined : String(v);

/** Public: document download URL (GET /api/documents/{id} → PDF binary). */
export const documentUrl = (docId: string): string =>
  `${BASE}/api/documents/${encodeURIComponent(docId)}`;

/** Best-effort filename out of a `Content-Disposition` header value. */
function filenameFromContentDisposition(value: string | null): string | null {
  if (!value) return null;
  const utf8 = /filename\*=UTF-8''([^;]+)/i.exec(value);
  if (utf8) {
    try {
      return decodeURIComponent(utf8[1]);
    } catch {
      /* malformed encoding — fall through to the plain filename form */
    }
  }
  const quoted = /filename="([^"]+)"/i.exec(value);
  if (quoted) return quoted[1];
  const bare = /filename=([^;]+)/i.exec(value);
  return bare ? bare[1].trim() : null;
}

/**
 * Download a generated document's PDF (GET /api/documents/{id}) with the
 * analyst's Bearer attached (via `apiFetch`) — the route requires identity
 * once postgres persistence is on, which a plain `<a href>` link can't
 * carry. Fetches the bytes, builds a blob URL, and triggers a save-to-disk
 * via a programmatic `<a download>`; throws on a non-2xx response so the
 * caller can surface the error (never fails silently).
 */
export async function downloadDocument(doc: ActionDocument): Promise<void> {
  const url = doc.downloadUrl ?? documentUrl(doc.id);
  const res = await apiFetch(url);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const blob = await res.blob();
  const filename =
    filenameFromContentDisposition(res.headers.get("content-disposition")) ??
    `${doc.title.trim().replace(/\s+/g, "-").toLowerCase() || "document"}.pdf`;

  const objectUrl = URL.createObjectURL(blob);
  try {
    const a = window.document.createElement("a");
    a.href = objectUrl;
    a.download = filename;
    window.document.body.appendChild(a);
    a.click();
    a.remove();
  } finally {
    // Deferred so the browser has started reading the blob before it's freed.
    setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
  }
}

/** Shorten a long hex hash / address to the mockup's "7c4d…9ffa" form. */
const short = (h: string | undefined, keep = 6): string | undefined =>
  h && h.length > 2 * keep + 1 ? `${h.slice(0, keep)}…${h.slice(-keep)}` : h;

const usd = (v: number): string =>
  `$${Math.round(v).toLocaleString("en-US")}`;

/* ── Documents ─────────────────────────────────────────────────────────── */

function normalizeKind(raw: any): DocKind | "pack" | null {
  const k = String(
    first(raw?.type, raw?.kind, raw?.doc_type, ""),
  ).toLowerCase();
  if (k.includes("freeze") || k.includes("block")) return "freeze"; // account_blocking
  if (k.includes("ltkm") || k.includes("str")) return "ltkm"; // str_report
  if (k.includes("summary") || k.includes("pack")) return "pack"; // evidence pack
  if (k.includes("alert") || k.includes("notif")) return "alert";
  return null;
}

/** Explicit backend `fields` (array or object) — preferred when present. */
function explicitFields(raw: any): DocField[] {
  const src = first(raw?.fields, raw?.summary_fields, raw?.preview);
  if (Array.isArray(src))
    return src
      .map((f): DocField | null => {
        const label = str(first(f?.label, f?.name, f?.key));
        const value = str(first(f?.value, f?.val));
        if (!label || value == null) return null;
        const placeholder = Boolean(
          first(f?.placeholder, f?.human_fill, f?.needs_input, false),
        );
        return {
          label,
          value,
          placeholder,
          color: f?.color
            ? String(f.color)
            : placeholder
              ? AMBER
              : /high/i.test(value)
                ? HIGH
                : undefined,
        };
      })
      .filter((f): f is DocField => f !== null);

  if (src && typeof src === "object")
    return Object.entries(src).map(([label, value]): DocField => {
      const v = String(value ?? "—");
      const placeholder = /fill|⬚|TO BE COMPLETED|TODO/i.test(v);
      return {
        label,
        value: v,
        placeholder,
        color: placeholder ? AMBER : /high/i.test(v) ? HIGH : undefined,
      };
    });
  return [];
}

/** A value the backend marks as analyst-must-fill. */
const isPlaceholder = (v: unknown): boolean =>
  /TO BE COMPLETED|⬚|fill/i.test(String(v ?? ""));

/**
 * Synthesize the freeze-request paper fields from bundle context
 * (entities + routing + totals) — the backend PDF carries the full document;
 * the card shows the mockup's key-field preview.
 */
function freezeFields(b: any): DocField[] {
  const fields: DocField[] = [];
  const entities: any[] = Array.isArray(b?.entities) ? b.entities : [];

  const wallet = entities.find((e) => String(e?.type).includes("wallet"));
  if (wallet?.value)
    fields.push({ label: "Wallet", value: short(String(wallet.value)) ?? "—" });

  const account = entities.find((e) => String(e?.type).includes("account"));
  if (account?.value)
    fields.push({
      label: "Account",
      value: `${account.bank_name ? `${account.bank_name} ` : ""}${account.value}`,
    });

  const plan: any[] = Array.isArray(b?.routing_plan) ? b.routing_plan : [];
  const exchange = plan.find((r) => String(r?.agency_type) === "exchange");
  if (exchange?.agency)
    fields.push({
      label: "Exchange",
      value: String(exchange.agency).replace(/^Exchange\s*\(([^)]+)\)$/, "$1"),
    });

  const atRisk = num(b?.totals?.at_risk_usdt);
  if (atRisk != null)
    fields.push({ label: "At risk", value: usd(atRisk), color: HIGH });

  fields.push({ label: "Basis", value: "POJK 27/2024" });
  return fields;
}

/**
 * Synthesize the LTKM/STR paper fields from the bundle's goAML draft —
 * subject identity stays a human-filled placeholder.
 */
function ltkmFields(b: any): DocField[] {
  const g = b?.goaml_draft ?? {};
  const fields: DocField[] = [];

  const subject = first(g?.subjects?.[0]?.full_name, "[TO BE COMPLETED BY ANALYST]");
  fields.push(
    isPlaceholder(subject)
      ? { label: "Subject", value: "⬚ fill identity", color: AMBER, placeholder: true }
      : { label: "Subject", value: String(subject) },
  );

  const typology = str(first(g?.crime_type, b?.crime_type));
  if (typology) fields.push({ label: "Typology", value: typology });

  const amount = num(first(b?.totals?.at_risk_usdt, g?.transactions?.[0]?.amount_original));
  if (amount != null) fields.push({ label: "Amount", value: usd(amount) });

  const indicators: any[] = Array.isArray(g?.indicators) ? g.indicators : [];
  if (indicators.length)
    fields.push({
      label: "Indicators",
      // "IND-LAY-01 layering via sequential peeling chain" → "IND-LAY-01"
      value: indicators
        .slice(0, 2)
        .map((i) => String(i).split(" ")[0])
        .join(", "),
    });

  fields.push({
    label: "Format",
    value: str(g?.schema) ?? "goAML XML draft",
  });
  return fields;
}

function normalizeDocuments(b: any): ActionDocument[] {
  const rawDocs: any[] = first(b?.documents, b?.docs, []) ?? [];
  return rawDocs
    .map((d, i): ActionDocument | null => {
      const kind = normalizeKind(d);
      // alert renders as dispatch targets; evidence pack has no card (yet)
      if (!kind || kind === "alert" || kind === "pack") return null;
      const meta = DOC_META[kind];
      const sha = short(str(first(d?.sha256, d?.hash)), 4);
      const id = String(first(d?.id, d?.document_id, `doc-${i}`));

      let fields = explicitFields(d);
      if (!fields.length)
        fields = kind === "freeze" ? freezeFields(b) : ltkmFields(b);
      if (sha && !fields.some((f) => f.label.toLowerCase().includes("sha")))
        fields.push({ label: "SHA-256", value: sha });

      // Backend title ("Permohonan Pemblokiran — Account & Wallet Freeze
      // Request") → paper heading takes the Indonesian half.
      const rawTitle = str(first(d?.title, d?.name));
      const paperTitle =
        str(first(d?.paper_title, d?.heading)) ??
        rawTitle?.split("—")[0]?.trim() ??
        (kind === "freeze"
          ? "Permintaan Pemblokiran"
          : "Laporan Transaksi Mencurigakan");

      return {
        id,
        kind,
        icon: meta.icon,
        title: meta.title,
        subtitle: str(first(d?.subtitle, d?.format)) ?? meta.subtitle,
        paperTitle,
        fields,
        sha256: sha,
        downloadUrl: d?.download_url
          ? String(d.download_url).startsWith("http")
            ? String(d.download_url)
            : `${BASE}${String(d.download_url)}`
          : documentUrl(id),
      };
    })
    .filter((d): d is ActionDocument => d !== null);
}

/* ── Dispatch targets (routing_plan + notifications overlay) ───────────── */

const STATUSES: DispatchStatus[] = [
  "acknowledged",
  "queued",
  "sent",
  "failed",
  "mock",
];

function normalizeStatus(v: unknown): DispatchStatus {
  const s = String(v ?? "").toLowerCase();
  return (STATUSES.find((x) => s.includes(x)) ?? "mock") as DispatchStatus;
}

/** "Bank BSI" → BSI · "Exchange (Indodax)" → IND · "PPATK" → PPA. */
function agencyCode(name: string): string {
  const paren = name.match(/\(([^)]+)\)/)?.[1];
  const base =
    paren ??
    name.replace(/^Bank\s+/i, "").split(/[\s—-]+/).filter(Boolean)[0] ??
    name;
  return base.replace(/[^A-Za-z]/g, "").slice(0, 3).toUpperCase() || "AGY";
}

const DOC_TYPE_ACTIONS: Record<string, string> = {
  account_blocking: "Freeze request",
  str_report: "Submit LTKM (goAML)",
  alert: "Case alert",
};

function normalizeTargets(b: any): DispatchTarget[] {
  const notifications: any[] = Array.isArray(b?.notifications)
    ? b.notifications
    : [];
  const statusByAgency = new Map<string, DispatchStatus>(
    notifications.map((n) => [
      String(first(n?.target_agency, n?.agency, "")),
      normalizeStatus(first(n?.status, n?.delivery_status)),
    ]),
  );

  const plan: any[] = Array.isArray(b?.routing_plan)
    ? b.routing_plan
    : (first(b?.targets, b?.dispatch_targets) ?? []);

  if (plan.length)
    return plan.map((r, i): DispatchTarget => {
      const name =
        str(first(r?.agency, r?.name, r?.target)) ?? `Target ${i + 1}`;
      return {
        id: String(first(r?.id, `tgt-${i}`)),
        code: str(first(r?.code, r?.short_code)) ?? agencyCode(name),
        name,
        action:
          str(first(r?.reason, r?.action, r?.instruction)) ??
          DOC_TYPE_ACTIONS[String(r?.document_type)] ??
          "Alert",
        // Pre-dispatch nothing has been sent — targets are drafts until the
        // analyst confirms; dispatch overlays the notification status (mock…).
        status: statusByAgency.get(name) ?? "draft",
      };
    });

  // No plan — render straight from notifications (post-dispatch fetch).
  return notifications.map((n, i): DispatchTarget => {
    const name =
      str(first(n?.target_agency, n?.agency)) ?? `Target ${i + 1}`;
    return {
      id: String(first(n?.id, `ntf-${i}`)),
      code: agencyCode(name),
      name,
      action:
        str(first(n?.payload?.note, n?.channel && `via ${n.channel}`)) ??
        "Alert",
      status: normalizeStatus(first(n?.status, n?.delivery_status)),
    };
  });
}

/* ── Bundle ────────────────────────────────────────────────────────────── */

function normalizeBundle(raw: any): ActionBundle {
  const b = first(raw?.bundle, raw?.action_bundle, raw) ?? {};
  const documents = normalizeDocuments(b);
  const targets = normalizeTargets(b);

  if (!documents.length && !targets.length)
    throw new Error("empty action bundle from API");

  const caseRef = str(first(b?.case_ref, b?.case_id, b?.case));
  const status = String(first(b?.status, "draft")).toLowerCase();

  // Bundle summary: "N wallets · M mule accounts" from the echoed entities.
  const entities: any[] = Array.isArray(b?.entities) ? b.entities : [];
  const wallets = entities.filter((e) => String(e?.type).includes("wallet")).length;
  const accounts = entities.filter((e) => String(e?.type).includes("account")).length;
  const summary =
    str(first(b?.summary, b?.scope)) ??
    (entities.length
      ? [
          wallets && `${wallets} wallet${wallets > 1 ? "s" : ""}`,
          accounts && `${accounts} mule account${accounts > 1 ? "s" : ""}`,
        ]
          .filter(Boolean)
          .join(" · ")
      : "confirmed case entities");

  // Evidence hash: explicit field, else the audit chain head, else doc[0].
  const audit: any[] = Array.isArray(b?.audit) ? b.audit : [];
  const chainHead = audit.length
    ? str(audit[audit.length - 1]?.sha256)
    : undefined;
  const evidenceHash =
    short(str(first(b?.evidence_hash, b?.manifest_hash)), 6) ??
    short(chainHead, 6) ??
    documents[0]?.sha256 ??
    "—";

  return {
    id: str(first(b?.id, b?.bundle_id)) ?? null,
    caseRef: caseRef
      ? /case/i.test(caseRef)
        ? caseRef
        : `CASE #${caseRef}`
      : "CASE #ITU-2026-0417",
    summary,
    evidenceHash,
    documents,
    targets,
    dispatched: status === "dispatched" || status === "issued",
    source: "api",
  };
}

/* ── Public surface ────────────────────────────────────────────────────── */

/** Demo inputs confirmed by P3-Backend (fixture peeling-chain source). */
const DEMO_REQUEST = {
  case_id: "CASE-2026-0142",
  crime_type: "investment",
  entities: [
    {
      type: "crypto_wallet",
      value: "TXtR9dQpR7mK2vN8fLbY3wZaQ4pJ6",
      chain: "tron",
    },
    {
      type: "bank_account",
      value: "5178446866",
      bank_name: "BSI",
      holder_name: null,
    },
  ],
  outputs: ["freeze", "ltkm", "alert", "pack"],
};

/**
 * Generate (or regenerate) the document bundle for the demo case.
 * POST /actions/generate; falls back to the mock bundle when the API is
 * unreachable or returns an empty bundle.
 */
export interface GenerateOptions {
  /** Active case id — the bundle attaches here (shows in the Case File rollup). */
  caseId?: string | null;
  /** Entities to action; when omitted/empty the demo fixture entities are used. */
  entities?: Array<Record<string, unknown>>;
}

export async function generateActions(
  opts: GenerateOptions = {},
): Promise<ActionBundle> {
  // Build the request from the active case when provided, else the demo fixture.
  const entities =
    opts.entities && opts.entities.length ? opts.entities : DEMO_REQUEST.entities;
  const body = {
    ...DEMO_REQUEST,
    ...(opts.caseId ? { case_id: opts.caseId } : {}),
    entities,
  };
  try {
    const raw = await request<any>(
      "/actions/generate",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      },
      20000,
    );
    return normalizeBundle(raw);
  } catch {
    return buildMockBundle();
  }
}

/**
 * Human-gated dispatch. POST /actions/{id}/dispatch when the bundle came
 * from the API (backend echoes the bundle with status="dispatched" +
 * notifications filled, POC = mock sink). On the mock (or on failure)
 * resolves locally so the POC flow still demos — nothing leaves the system
 * either way in POC mode.
 */
export async function dispatchActions(
  bundle: ActionBundle,
): Promise<ActionBundle> {
  // Local resolution: draft targets land in the POC mock sink.
  const resolveLocal = (): ActionBundle => ({
    ...bundle,
    targets: bundle.targets.map((t) =>
      t.status === "draft" ? { ...t, status: "mock" } : t,
    ),
    dispatched: true,
  });

  if (bundle.source === "api" && bundle.id) {
    try {
      const raw = await request<any>(`/actions/${bundle.id}/dispatch`, {
        method: "POST",
      });
      try {
        return { ...normalizeBundle(raw), dispatched: true };
      } catch {
        return resolveLocal();
      }
    } catch {
      /* fall through to local resolution (e.g. 409 already_dispatched) */
    }
  }
  return resolveLocal();
}
