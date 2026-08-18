"use client";

/**
 * Audit trail — who did what, when, and whether the record has been altered.
 *
 * Reads GET /api/audit, which is agency-scoped and **re-verifies the hash chain
 * on every read**. That verification is the point of the screen: a tamper-evident
 * log nobody looks at proves nothing, because chaining only makes alteration
 * *detectable* — someone still has to check. So the chain banner is the first
 * thing on the page, not a footnote.
 *
 * Entries are immutable by construction (append-only, hash-chained), so this
 * screen is deliberately read-only — there is no edit affordance to build.
 */

import { useCallback, useEffect, useState } from "react";
import { fetchAuditFeed, type AuditEntry, type AuditFeed } from "@/lib/cases/api";

/** Plain-language labels — `case.updated` is a key, not something to show a user. */
const ACTION_COPY: Record<string, { label: string; glyph: string }> = {
  "auth.login": { label: "Signed in", glyph: "→" },
  "case.created": { label: "Opened a case", glyph: "▤" },
  "case.updated": { label: "Changed a case", glyph: "✎" },
  "entity.reviewed": { label: "Reviewed an entity", glyph: "◇" },
  "dispatch.sent": { label: "Dispatched to an agency", glyph: "⚑" },
  "triage.attached": { label: "Filed a call into a case", glyph: "☎" },
  "triage.promoted": { label: "Opened a case from a call", glyph: "☎" },
};

function fmtTs(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const day = d.getDate();
  const month = d.toLocaleString("en-US", { month: "short" });
  const hh = `${d.getHours()}`.padStart(2, "0");
  const mm = `${d.getMinutes()}`.padStart(2, "0");
  const ss = `${d.getSeconds()}`.padStart(2, "0");
  return `${day} ${month}, ${hh}:${mm}:${ss}`;
}

/** Who acted, by name. Snapshotted at write time (see app/core/audit.py) — a
 *  uuid answers "who did what" with `9f79eb96-…`, which is unreadable to the
 *  investigator or court the trail exists for. */
function actorName(e: AuditEntry): string {
  const d = (e.detail ?? {}) as Record<string, unknown>;
  return (d._actor as string) || "Unknown user";
}

/** What was acted on, by label (case title, wallet, call number) — not a uuid. */
function targetLabel(e: AuditEntry): string {
  const d = (e.detail ?? {}) as Record<string, unknown>;
  return (d._target as string) || "";
}

/** Human summary of an entry's detail — the "what changed", not a JSON dump. */
function summarize(e: AuditEntry): string {
  const d = e.detail ?? {};
  switch (e.action) {
    case "auth.login":
      return `${d.role ?? "—"} · ${d.method === "google" ? "Google" : "demo login"}`;
    case "case.created":
      return String(d.title ?? "");
    case "case.updated": {
      const changed = (d.changed ?? {}) as Record<string, unknown>;
      const parts = Object.entries(changed).map(([k, v]) => `${k} → ${String(v)}`);
      return parts.join(" · ");
    }
    case "entity.reviewed":
      return `${d.status ?? ""} · ${d.type ?? ""} ${d.value ?? ""}`.trim();
    case "triage.attached":
      return `case ${String(d.case_id ?? "").slice(0, 8)}…`;
    case "triage.promoted": {
      const ov = (d.overrides ?? []) as string[];
      const edited = ov.length ? ` · operator edited ${ov.join(", ")}` : "";
      return `${d.title ?? ""}${edited}`;
    }
    default: {
      const rest = Object.fromEntries(
        Object.entries(d).filter(([k]) => !k.startsWith("_")),
      );
      return Object.keys(rest).length ? JSON.stringify(rest) : "";
    }
  }
}

function ChainBanner({ feed }: { feed: AuditFeed }) {
  if (feed.chain_ok) {
    return (
      <div className="mb-3.5 rounded-card border border-accent/[.22] bg-accent/[.06] px-3.5 py-2.5">
        <p className="text-[11.5px] text-accent-bright">
          ✓ Chain verified — every entry links to the one before it.
        </p>
        <p className="mt-1 text-[10.5px] text-muted">
          Each record is hashed together with its predecessor, so editing or
          removing any entry breaks every hash after it. Re-checked just now.
        </p>
      </div>
    );
  }
  return (
    <div className="mb-3.5 rounded-card border border-risk-high/40 bg-risk-high/[.08] px-3.5 py-2.5">
      <p className="text-[11.5px] font-semibold text-risk-high">
        ✗ Chain verification FAILED
        {feed.broken_at_seq != null ? ` at entry #${feed.broken_at_seq}` : ""}
      </p>
      <p className="mt-1 text-[10.5px] text-muted">
        The log has been altered since it was written, or entries are missing.
        Everything from that point on should be treated as unreliable and
        investigated — do not rely on this trail as evidence until it is
        explained.
      </p>
    </div>
  );
}

export default function AuditPage() {
  const [feed, setFeed] = useState<AuditFeed | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setFeed(await fetchAuditFeed(200));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "could not load the audit trail");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const entries = feed?.entries ?? [];

  return (
    <div className="mx-auto max-w-5xl px-4 py-5">
      <div className="mb-3.5 flex items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold tracking-tight">Audit trail</h1>
          <p className="mt-1 text-xs text-muted">
            Every recorded action by your agency, newest first — who did it, when,
            and what changed. Append-only and hash-chained, so alteration is
            detectable. Other agencies&apos; actions are never shown.
          </p>
        </div>
        <button
          type="button"
          onClick={() => void load()}
          disabled={loading}
          className="h-8 shrink-0 rounded-lg border border-line bg-elevated px-3 text-[11px] font-semibold text-fg transition-colors hover:border-accent/40 disabled:opacity-50"
        >
          {loading ? "…" : "Re-verify"}
        </button>
      </div>

      {error && (
        <p className="mb-3 text-[11px] text-risk-high">✗ {error}</p>
      )}
      {feed && <ChainBanner feed={feed} />}

      <div className="rounded-card border border-line bg-card">
        <div className="flex items-center justify-between border-b border-line px-3.5 py-2.5">
          <span className="eyebrow">Recorded actions · {entries.length}</span>
        </div>
        <div className="p-2">
          {loading && !feed ? (
            <p className="px-1.5 py-2 text-[11px] text-muted">Loading…</p>
          ) : entries.length === 0 ? (
            <p className="px-1.5 py-3 text-[11px] text-muted">
              Nothing recorded yet. Actions appear here as they happen — signing
              in, opening or changing a case, reviewing an extracted entity,
              filing a call into a case.
            </p>
          ) : (
            <ul className="space-y-1">
              {entries.map((e) => {
                const copy = ACTION_COPY[e.action] ?? { label: e.action, glyph: "·" };
                const detail = summarize(e);
                return (
                  <li
                    key={`${e.seq}-${e.sha256}`}
                    className="rounded-lg bg-elevated px-2.5 py-2 text-[11.5px]"
                  >
                    <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                      <span className="w-8 shrink-0 font-mono text-[10px] text-muted">
                        #{e.seq}
                      </span>
                      <span className="shrink-0 text-muted">{copy.glyph}</span>
                      {/* WHO first — that is the question an audit trail exists
                          to answer, and it was a uuid until we snapshotted the
                          name at write time. */}
                      <span className="font-semibold text-fg">{actorName(e)}</span>
                      <span className="text-fg">{copy.label.toLowerCase()}</span>
                      {targetLabel(e) && (
                        <span className="font-medium text-accent-bright">
                          {targetLabel(e)}
                        </span>
                      )}
                      {detail && (
                        <span className="text-muted">— {detail}</span>
                      )}
                      <span className="ml-auto shrink-0 font-mono text-[10px] text-muted">
                        {fmtTs(e.ts)}
                      </span>
                    </div>
                    {/* The hash is what makes the entry verifiable; showing a
                        prefix lets a reviewer eyeball the chain without
                        drowning the row in 64 hex characters. */}
                    <div className="mt-1 flex flex-wrap gap-x-3 font-mono text-[9.5px] text-muted">
                      <span title={e.sha256}>sha {e.sha256.slice(0, 12)}…</span>
                      <span title={e.prev_sha256}>
                        prev {e.prev_sha256.slice(0, 12)}…
                      </span>
                      {e.target_type && (
                        <span>
                          {e.target_type}
                          {e.target_id ? ` ${e.target_id.slice(0, 8)}…` : ""}
                        </span>
                      )}
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
