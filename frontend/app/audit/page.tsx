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
 *
 * **Refused actions appear here too**, and the single most important thing this
 * screen does with them is make them impossible to mistake for things that
 * happened. A denied platform-admin grant rendered like a successful one would
 * be worse than not recording it at all: the reader would draw a false
 * conclusion from evidence, rather than simply lacking it. So a denial gets its
 * own colour, a DENIED chip, past-tense phrasing that says *tried to*, and the
 * reason it was refused.
 */

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { fetchAuditFeed, type AuditEntry, type AuditFeed } from "@/lib/cases/api";
import { Icon, type IconName } from "@/components/icon";

/** Plain-language labels — `case.updated` is a key, not something to show a user.
 *  `attempt` is the phrasing used when the action was REFUSED; entries without
 *  one fall back to "attempted <label>", which reads acceptably for all of them.
 *  Labels/attempts come from i18n (see `actionCopy` in the audit namespace) —
 *  this map only carries the icon, keyed by the same backend action code. */
const ACTION_ICON: Record<string, IconName> = {
  "auth.login": "dispatch",
  "case.created": "case",
  "case.updated": "edit",
  "entity.reviewed": "reviewed",
  "dispatch.sent": "uncover",
  "triage.attached": "phone",
  "triage.promoted": "phone",
  "action.bundle.generated": "commandCenter",
  "evidence.exported": "download",
  "user.created": "plus",
  "user.role_changed": "regulator",
  "user.deactivated": "freeze",
  "user.reactivated": "reviewed",
  "access.forbidden": "cross",
};

/** Backend action code → i18n leaf-key slug. next-intl reserves "." for
 *  namespace nesting, so the raw dotted codes above (e.g. "auth.login")
 *  can't be used directly as JSON keys under `actionCopy` — this maps each
 *  one to a dot-free slug instead. Every key of ACTION_GLYPH must appear
 *  here. */
const ACTION_SLUG: Record<string, string> = {
  "auth.login": "authLogin",
  "case.created": "caseCreated",
  "case.updated": "caseUpdated",
  "entity.reviewed": "entityReviewed",
  "dispatch.sent": "dispatchSent",
  "triage.attached": "triageAttached",
  "triage.promoted": "triagePromoted",
  "action.bundle.generated": "actionBundleGenerated",
  "evidence.exported": "evidenceExported",
  "user.created": "userCreated",
  "user.role_changed": "userRoleChanged",
  "user.deactivated": "userDeactivated",
  "user.reactivated": "userReactivated",
  "access.forbidden": "accessForbidden",
};

/** Action codes that have a dedicated "attempt" phrasing when denied — used to
 *  fall back to a generic "attempted <label>" for codes that don't. */
const HAS_ATTEMPT_COPY = new Set([
  "user.created",
  "user.role_changed",
  "user.deactivated",
  "user.reactivated",
  "access.forbidden",
]);

/** Denial guard codes that have dedicated copy (see `denialCopy` in the audit
 *  namespace) — anything else falls back to the raw code, spaced out. */
const DENIAL_CODES = new Set([
  "privilege_escalation",
  "self_lockout",
  "last_admin",
  "cross_agency_forbidden",
  "user_not_found",
  // Kept alongside `missing_capability`: entries recorded before capabilities
  // existed carry the old code, and they must still render as words.
  "forbidden",
  "missing_capability",
]);

/** An entry records something that was REFUSED, not something that happened.
 *  Absence of `_outcome` means success — every entry written before denials
 *  were recorded is a success, and none of them was backfilled. */
function isDenied(e: AuditEntry): boolean {
  return (e.detail as Record<string, unknown>)?._outcome === "denied";
}

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
function actorName(e: AuditEntry, t: ReturnType<typeof useTranslations>): string {
  const d = (e.detail ?? {}) as Record<string, unknown>;
  return (d._actor as string) || t("unknownUser");
}

/** What was acted on, by label (case title, wallet, call number) — not a uuid. */
function targetLabel(e: AuditEntry): string {
  const d = (e.detail ?? {}) as Record<string, unknown>;
  return (d._target as string) || "";
}

/** Human summary of an entry's detail — the "what changed", not a JSON dump.
 *  `t` is `useTranslations("audit.page")` from next-intl. */
function summarize(e: AuditEntry, t: ReturnType<typeof useTranslations>): string {
  const d = e.detail ?? {};
  if (isDenied(e)) {
    // NEVER fall through to the success summaries: `from → to` on a refused
    // role change describes a change that did not occur. Say why it was
    // refused instead — that is the whole content of the entry.
    const code = String(d._denial_code ?? "");
    const why = DENIAL_CODES.has(code)
      ? t(`denialCopy.${code}`)
      : code.replace(/_/g, " ");
    const attempted = d.attempted_role ? ` (${String(d.attempted_role)})` : "";
    const where = d.path ? ` · ${String(d.method ?? "")} ${String(d.path)}` : "";
    return `${why}${attempted}${where}`;
  }
  switch (e.action) {
    case "auth.login":
      return `${d.role ?? "—"} · ${d.method === "google" ? t("loginMethod.google") : t("loginMethod.demo")}`;
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
    // Generated a document bundle — readable count + the requested outputs,
    // instead of dumping the per-document sha256 array inline. The full
    // array (with every hash) is still there for anyone who expands details.
    case "action.bundle.generated": {
      const docs = (d.documents ?? []) as Array<Record<string, unknown>>;
      const outputs = (d.outputs ?? []) as string[];
      return t("summaries.bundleGenerated", {
        count: docs.length,
        outputs: outputs.join(", ") || String(d.crime_type ?? ""),
      });
    }
    // Dispatched notifications — which agencies and how many documents, not
    // the full per-notification id/status array (still in the raw detail).
    case "dispatch.sent": {
      const recipients = (d.recipients ?? []) as string[];
      const docCount =
        typeof d.documents === "number"
          ? d.documents
          : ((d.notifications ?? []) as unknown[]).length;
      return t("summaries.dispatchSent", {
        agencies: recipients.join(", ") || "—",
        docCount,
      });
    }
    case "evidence.exported":
      return t("summaries.evidenceExported", {
        type: String(d.type ?? "—"),
        status: String(d.status ?? "—"),
      });
    case "user.created":
      return t("summaries.userRole", { role: String(d.role ?? "—") });
    case "user.role_changed":
      return t("summaries.roleChange", { from: String(d.from ?? "—"), to: String(d.to ?? "—") });
    case "user.deactivated":
    case "user.reactivated":
      return t("summaries.userRole", { role: String(d.role ?? "—") });
    default:
      // Nothing dedicated for this action — the raw detail is still available
      // via the per-entry "show technical details" toggle below, never dropped.
      return "";
  }
}

/** The fields worth hiding behind "show details" for an entry that already
 *  has a human summary — everything else in `detail` (minus the underscore-
 *  prefixed bookkeeping fields), so the raw evidence is one click away
 *  rather than competing with the summary line for attention. NEVER used to
 *  remove data: this only decides what's collapsed by default. */
function rawDetail(e: AuditEntry): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(e.detail ?? {}).filter(([k]) => !k.startsWith("_")),
  );
}

function ChainBanner({ feed }: { feed: AuditFeed }) {
  const t = useTranslations("audit.page");
  if (feed.chain_ok) {
    return (
      <div className="mb-4 rounded-card border border-accent/[.22] bg-accent/[.06] px-4 py-3.5">
        <p className="flex items-center gap-2 text-[13px] font-semibold text-accent-bright">
          <Icon name="check" size={14} />
          {t("chainVerified.title")}
        </p>
        <p className="mt-1.5 text-[12px] leading-relaxed text-muted">
          {t("chainVerified.body")}
        </p>
        {/* Says what the green tick does NOT cover. "Verified" invites the
            reading "nothing is missing", which is a stronger claim than a hash
            chain can support: an entry that was never written leaves no gap,
            because the entries around it still link to each other. Better an
            investigator meets that here than in front of a court. The last
            sentence matters as much as the caveat — without it this reads as a
            shrug, when write failures are in fact counted and alerted on. */}
        <p className="mt-1.5 text-[12px] leading-relaxed text-muted">
          {t.rich("chainVerified.caveat", {
            b: (chunks) => <span className="text-fg">{chunks}</span>,
          })}
        </p>
      </div>
    );
  }
  return (
    <div className="mb-4 rounded-card border border-risk-high/40 bg-risk-high/[.08] px-4 py-3.5">
      <p className="flex items-center gap-2 text-[13px] font-semibold text-risk-high">
        <Icon name="cross" size={14} />
        {feed.broken_at_seq != null
          ? t("chainFailed.titleAtEntry", { seq: feed.broken_at_seq })
          : t("chainFailed.title")}
      </p>
      <p className="mt-1.5 text-[12px] leading-relaxed text-muted">
        {t("chainFailed.body")}
      </p>
    </div>
  );
}

export default function AuditPage() {
  const t = useTranslations("audit.page");
  const [feed, setFeed] = useState<AuditFeed | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setFeed(await fetchAuditFeed(200));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("errorFallback"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void load();
  }, [load]);

  const entries = feed?.entries ?? [];

  return (
    <div className="mx-auto max-w-[1000px]">
      <div className="mb-4 flex items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">{t("title")}</h1>
          <p className="mt-2 max-w-[64ch] text-[13px] leading-relaxed text-muted">
            {t("pageLead")}
          </p>
          <p className="mt-1 max-w-[64ch] text-[12px] leading-relaxed text-muted">
            {t.rich("subtitle", {
              r: (chunks) => <span className="text-risk-high">{chunks}</span>,
            })}
          </p>
        </div>
        <button
          type="button"
          onClick={() => void load()}
          disabled={loading}
          className="h-8 shrink-0 rounded-lg border border-line bg-elevated px-3 text-[12px] font-semibold text-fg transition-colors hover:border-accent/40 disabled:opacity-50"
        >
          {loading ? t("reverifying") : t("reverify")}
        </button>
      </div>

      {error && (
        <p className="mb-3 flex items-center gap-1.5 text-[12px] text-risk-high"><Icon name="cross" size={12} />{error}</p>
      )}
      {feed && <ChainBanner feed={feed} />}

      <div className="rounded-card border border-line bg-card">
        <div className="flex items-center justify-between border-b border-line px-3.5 py-2.5">
          <span className="eyebrow">{t("recordedActionsEyebrow", { count: entries.length })}</span>
        </div>
        <div className="p-2">
          {loading && !feed ? (
            <p className="px-1.5 py-2 text-[12px] text-muted">{t("loading")}</p>
          ) : entries.length === 0 ? (
            <p className="px-1.5 py-3 text-[12px] text-muted">
              {t("emptyState")}
            </p>
          ) : (
            <ul className="space-y-1">
              {entries.map((e) => {
                const hasCopy = e.action in ACTION_ICON;
                const slug = ACTION_SLUG[e.action];
                const label = hasCopy ? t(`actionCopy.${slug}.label`) : e.action;
                const icon = ACTION_ICON[e.action] ?? "entity";
                const detail = summarize(e, t);
                const raw = rawDetail(e);
                const hasRaw = Object.keys(raw).length > 0;
                const denied = isDenied(e);
                const verb = denied
                  ? HAS_ATTEMPT_COPY.has(e.action)
                    ? t(`actionCopy.${slug}.attempt`)
                    : t("attemptedFallback", { label: label.toLowerCase() })
                  : label.toLowerCase();
                return (
                  <li
                    key={`${e.seq}-${e.sha256}`}
                    className={`rounded-lg px-2.5 py-2 text-[12px] ${
                      denied
                        ? "border border-risk-high/30 bg-risk-high/[.07]"
                        : "bg-elevated"
                    }`}
                  >
                    <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                      <span className="w-8 shrink-0 text-[12px] text-muted">
                        #{e.seq}
                      </span>
                      <Icon
                        name={denied ? "cross" : icon}
                        size={13}
                        className={`mt-[2px] shrink-0 ${denied ? "text-risk-high" : "text-muted"}`}
                      />
                      {/* The chip comes before the sentence on purpose: a reader
                          skimming the column must not read half a row and
                          conclude the thing happened. */}
                      {denied && (
                        <span className="shrink-0 rounded bg-risk-high/20 px-1.5 py-[1px] text-[12px] font-bold uppercase tracking-wide text-risk-high">
                          {t("deniedChip")}
                        </span>
                      )}
                      {/* WHO first — that is the question an audit trail exists
                          to answer, and it was a uuid until we snapshotted the
                          name at write time. */}
                      <span className="font-semibold text-fg">{actorName(e, t)}</span>
                      <span className={denied ? "text-risk-high" : "text-fg"}>{verb}</span>
                      {targetLabel(e) && (
                        <span
                          className={`font-medium ${
                            denied ? "text-risk-high/80" : "text-accent-bright"
                          }`}
                        >
                          {targetLabel(e)}
                        </span>
                      )}
                      {detail && (
                        <span className="text-muted">— {detail}</span>
                      )}
                      <span className="ml-auto shrink-0 text-[12px] text-muted">
                        {fmtTs(e.ts)}
                      </span>
                    </div>
                    {/* The volume cap is bounded per actor/action/window, so a
                        run of refusals stops being written down. Saying so is
                        the difference between a capped chain and a quiet one. */}
                    {Boolean((e.detail as Record<string, unknown>)?._denial_cap_reached) && (
                      <p className="mt-1 text-[12px] text-risk-high/80">
                        {t("rateCapReached", {
                          cap: String((e.detail as Record<string, unknown>)._denial_cap),
                        })}
                      </p>
                    )}
                    {/* Everything below is collapsed by default — the summary
                        line above already answers "who did what, when" for a
                        skim. Nothing here is ever removed, only tucked behind
                        one click: the hash chain (sha/prev-sha) and the full
                        raw detail this entry recorded (document arrays,
                        nested sha256 hashes, full URLs, case ids — whatever
                        the backend attached), for the reviewer who needs to
                        verify rather than just skim. */}
                    <details className="group mt-1.5">
                      <summary className="inline-flex cursor-pointer select-none items-center gap-1 text-[12px] text-muted transition-colors hover:text-fg [&::-webkit-details-marker]:hidden">
                        <Icon
                          name="dispatch"
                          size={11}
                          className="transition-transform group-open:rotate-90"
                        />
                        <span className="group-open:hidden">{t("showDetails")}</span>
                        <span className="hidden group-open:inline">{t("hideDetails")}</span>
                      </summary>
                      <div className="mt-1.5 space-y-1.5 border-t border-line/60 pt-1.5">
                        {/* The hash is what makes the entry verifiable; showing
                            a prefix lets a reviewer eyeball the chain without
                            drowning the row in 64 hex characters. */}
                        <div className="flex flex-wrap gap-x-3 text-[12px] text-muted">
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
                        {hasRaw && (
                          <div>
                            <div className="text-[12px] uppercase tracking-wide text-muted/80">
                              {t("detailsRawLabel")}
                            </div>
                            <pre className="mt-1 overflow-x-auto rounded-md border border-line bg-card px-2.5 py-2 text-[12px] leading-relaxed text-fg/80">
                              {JSON.stringify(raw, null, 2)}
                            </pre>
                          </div>
                        )}
                      </div>
                    </details>
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
