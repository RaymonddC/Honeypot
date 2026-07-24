"use client";

/**
 * Intake — the victim-report entry point (how most real cases actually start).
 * Captures the report (source, type, amount, receiving account, when), then in
 * one submit: opens a case, writes the report brief to it, logs the receiving
 * bank account, jumps to the FREEZE stage, and — the time-critical part — can
 * generate the freeze request immediately. Mirrors the police/IASC flow:
 * intake → freeze fast → trace later.
 */

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useCases } from "@/components/cases/case-provider";
import { addBankAccount } from "@/lib/casedata/api";
import { generateActions } from "@/lib/actions/api";

const CRIME_TYPES = [
  { value: "investment_scam", label: "Investment scam", glyph: "📈" },
  { value: "judol_deposit", label: "Online gambling", glyph: "🎰" },
  { value: "crypto_phishing", label: "Crypto phishing", glyph: "⛓" },
  { value: "romance_scam", label: "Romance scam", glyph: "💔" },
  { value: "impersonation", label: "Impersonation", glyph: "🎭" },
  { value: "other", label: "Other", glyph: "◇" },
];

const SOURCES = [
  { value: "iasc", label: "IASC" },
  { value: "bank", label: "Bank" },
  { value: "police", label: "Police report" },
  { value: "walk_in", label: "Direct / walk-in" },
];

const field =
  "h-9 w-full rounded-lg border border-white/10 bg-card px-3 text-[13px] text-fg outline-none placeholder:text-muted focus:border-accent/40";
const labelCls = "mb-1 block text-[11px] font-medium text-muted";

function todayTitle() {
  return `Scam report — ${new Date().toISOString().slice(0, 10)}`;
}

/** Current local date-time as "YYYY-MM-DDTHH:mm" for a <input type=datetime-local>. */
function nowLocal() {
  const d = new Date();
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
  return d.toISOString().slice(0, 16);
}

function SectionHead({ n, title, hint }: { n: number; title: string; hint?: string }) {
  return (
    <div className="mb-2.5 flex items-baseline gap-2">
      <span className="flex h-5 w-5 flex-none items-center justify-center rounded-full bg-accent/15 font-mono text-[10px] font-bold text-accent-bright">
        {n}
      </span>
      <span className="text-[12.5px] font-semibold text-fg">{title}</span>
      {hint && <span className="text-[10.5px] text-muted">· {hint}</span>}
    </div>
  );
}

export default function IntakePage() {
  const router = useRouter();
  const { createCase, updateCase, advanceStage } = useCases();

  const [title, setTitle] = useState(todayTitle());
  const [crimeType, setCrimeType] = useState("investment_scam");
  const [source, setSource] = useState("iasc");
  const [amount, setAmount] = useState("");
  const [incidentAt, setIncidentAt] = useState(nowLocal());
  const [bankName, setBankName] = useState("");
  const [accountNumber, setAccountNumber] = useState("");
  const [holderName, setHolderName] = useState("");
  const [description, setDescription] = useState("");
  const [freezeNow, setFreezeNow] = useState(true);

  const [busy, setBusy] = useState(false);
  const [stepIdx, setStepIdx] = useState(-1);
  const [error, setError] = useState<string | null>(null);

  const dateRef = useRef<HTMLInputElement>(null);
  // Open the native calendar/time picker on click (supported in modern browsers).
  const openPicker = () => {
    const el = dateRef.current as (HTMLInputElement & { showPicker?: () => void }) | null;
    try {
      el?.showPicker?.();
    } catch {
      /* showPicker unsupported / not user-activated — the field still works */
    }
  };

  const sourceLabel = SOURCES.find((s) => s.value === source)?.label ?? source;
  const crimeLabel =
    CRIME_TYPES.find((c) => c.value === crimeType)?.label ?? crimeType;
  const amountPretty = amount.trim()
    ? `Rp ${Number(amount).toLocaleString("id-ID")}`
    : "";

  const steps = [
    "Opening case",
    "Logging receiving account",
    "Advancing to Freeze",
    ...(freezeNow ? ["Generating freeze request"] : []),
  ];

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const amt = amountPretty || "an unspecified amount";
      const when = incidentAt ? new Date(incidentAt).toLocaleString() : "unknown time";
      const summary =
        `Reported via ${sourceLabel}. ${amt} lost — ${crimeLabel}. Incident: ${when}.` +
        (description.trim() ? `\n\n${description.trim()}` : "");

      setStepIdx(0);
      const created = await createCase({
        title: title.trim() || todayTitle(),
        crime_type: crimeType,
      });
      // Persist the report brief on the case (was previously discarded).
      await updateCase(created.id, { summary });

      setStepIdx(1);
      await addBankAccount({
        bank_name: bankName.trim(),
        account_number: accountNumber.trim(),
        holder_name: holderName.trim() || undefined,
        category: "scam",
        case_id: created.id,
      });

      setStepIdx(2);
      await advanceStage(created.id, "freeze");

      if (freezeNow) {
        setStepIdx(3);
        await generateActions({
          caseId: created.id,
          crimeType: crimeType.startsWith("investment") ? "investment" : crimeType,
          outputs: ["freeze"],
          entities: [
            {
              type: "bank_account",
              value: accountNumber.trim(),
              bank_name: bankName.trim() || null,
              holder_name: holderName.trim() || null,
            },
          ],
        });
      }

      router.push("/case");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Intake failed");
      setBusy(false);
      setStepIdx(-1);
    }
  };

  return (
    <div className="mx-auto max-w-[720px]">
      <div className="mb-4">
        <div className="eyebrow mb-1">Intake · new report</div>
        <h1 className="text-xl font-bold tracking-tight">Log a scam report</h1>
        <p className="mt-1 max-w-[62ch] text-xs leading-relaxed text-muted">
          The reactive entry point — a victim report from IASC, a bank, or the
          police. One submit opens the case, saves the brief, logs the receiving
          account, and (the make-or-break step) can fire the freeze request straight
          away.
        </p>
      </div>

      <form onSubmit={submit} className="space-y-4">
        {/* ── ① the report ─────────────────────────────────────────── */}
        <section className="rounded-card border border-line bg-card p-4">
          <SectionHead n={1} title="The report" />

          <div className="mb-3">
            <label className={labelCls}>Case title</label>
            <input className={field} value={title} onChange={(e) => setTitle(e.target.value)} />
          </div>

          <div className="mb-3">
            <label className={labelCls}>Scam type</label>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
              {CRIME_TYPES.map((c) => {
                const on = crimeType === c.value;
                return (
                  <button
                    key={c.value}
                    type="button"
                    onClick={() => setCrimeType(c.value)}
                    aria-pressed={on}
                    className={`flex items-center gap-2 rounded-lg border px-2.5 py-2 text-left text-[12px] transition-colors ${
                      on
                        ? "border-accent bg-accent/10 font-semibold text-accent-bright"
                        : "border-line bg-elevated text-muted hover:text-fg"
                    }`}
                  >
                    <span aria-hidden className="text-[13px]">{c.glyph}</span>
                    {c.label}
                  </button>
                );
              })}
            </div>
          </div>

          <div className="mb-3">
            <label className={labelCls}>Reported via</label>
            <div className="flex flex-wrap gap-1.5">
              {SOURCES.map((s) => {
                const on = source === s.value;
                return (
                  <button
                    key={s.value}
                    type="button"
                    onClick={() => setSource(s.value)}
                    aria-pressed={on}
                    className={`rounded-lg border px-2.5 py-1 text-[11.5px] transition-colors ${
                      on
                        ? "border-accent bg-accent/10 font-semibold text-accent-bright"
                        : "border-line bg-elevated text-muted hover:text-fg"
                    }`}
                  >
                    {s.label}
                  </button>
                );
              })}
            </div>
          </div>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <label className={labelCls}>Amount lost (IDR)</label>
              <input
                className={field}
                type="number"
                min="0"
                inputMode="numeric"
                placeholder="e.g. 25000000"
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
              />
              {amountPretty && (
                <div className="mt-1 font-mono text-[11px] text-accent-bright">{amountPretty}</div>
              )}
            </div>
            <div>
              <div className="mb-1 flex items-center justify-between">
                <label className="text-[11px] font-medium text-muted">When it happened</label>
                <button
                  type="button"
                  onClick={() => setIncidentAt(nowLocal())}
                  className="text-[10.5px] font-semibold text-accent-bright hover:underline"
                >
                  Now
                </button>
              </div>
              <div className="relative">
                <input
                  ref={dateRef}
                  className={`${field} cursor-pointer pr-9 [color-scheme:dark] [&::-webkit-calendar-picker-indicator]:opacity-0`}
                  type="datetime-local"
                  max={nowLocal()}
                  value={incidentAt}
                  onChange={(e) => setIncidentAt(e.target.value)}
                  onClick={openPicker}
                />
                <button
                  type="button"
                  onClick={openPicker}
                  aria-label="Open calendar"
                  tabIndex={-1}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-[13px] text-muted transition-colors hover:text-accent-bright"
                >
                  📅
                </button>
              </div>
            </div>
          </div>
        </section>

        {/* ── ② receiving account — the freezable target ───────────── */}
        <section className="rounded-card border border-risk-high/25 bg-risk-high/[.04] p-4">
          <SectionHead n={2} title="Receiving account" hint="the account you freeze" />
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div>
              <label className={labelCls}>Bank</label>
              <input required className={field} placeholder="BCA" value={bankName}
                onChange={(e) => setBankName(e.target.value)} />
            </div>
            <div>
              <label className={labelCls}>Account number</label>
              <input required className={field} placeholder="5271038462" value={accountNumber}
                onChange={(e) => setAccountNumber(e.target.value)} />
            </div>
            <div>
              <label className={labelCls}>Holder name</label>
              <input className={field} placeholder="Rudi Hartono" value={holderName}
                onChange={(e) => setHolderName(e.target.value)} />
            </div>
          </div>
        </section>

        {/* ── ③ context ────────────────────────────────────────────── */}
        <section className="rounded-card border border-line bg-card p-4">
          <SectionHead n={3} title="What happened" hint="optional — goes into the case brief" />
          <textarea
            className="min-h-[72px] w-full rounded-lg border border-white/10 bg-card px-3 py-2 text-[13px] leading-relaxed text-fg outline-none placeholder:text-muted focus:border-accent/40"
            placeholder="How the victim was contacted, promises made, transfers sent…"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </section>

        {/* the fast-freeze toggle */}
        <label className="flex cursor-pointer items-start gap-2.5 rounded-card border border-accent/30 bg-accent/[.06] px-3.5 py-3">
          <input type="checkbox" checked={freezeNow} onChange={(e) => setFreezeNow(e.target.checked)}
            className="mt-0.5 h-4 w-4 flex-none accent-[#10b981]" />
          <span className="text-[12.5px] leading-relaxed text-fg">
            <b className="text-accent-bright">⚡ Generate freeze request now</b> — freeze the
            receiving account first, trace later (the real 30-minute window). Lands you on the
            freeze desk ready to dispatch.
          </span>
        </label>

        {/* submit progress */}
        {busy && (
          <div className="rounded-card border border-accent/20 bg-accent/[.05] p-3">
            <ul className="space-y-1.5">
              {steps.map((s, i) => {
                const done = i < stepIdx;
                const active = i === stepIdx;
                return (
                  <li key={s} className="flex items-center gap-2 text-[11.5px]">
                    <span
                      className={`flex h-4 w-4 flex-none items-center justify-center rounded-full text-[9px] ${
                        done
                          ? "bg-accent/20 text-accent-bright"
                          : active
                            ? "border border-accent text-accent-bright"
                            : "border border-line text-muted"
                      }`}
                    >
                      {done ? "✓" : active ? "•" : ""}
                    </span>
                    <span className={done || active ? "text-fg/85" : "text-muted"}>
                      {s}
                      {active ? "…" : ""}
                    </span>
                  </li>
                );
              })}
            </ul>
          </div>
        )}

        {error && (
          <p className="rounded-lg border border-risk-high/30 bg-risk-high/10 px-3 py-2 text-[11.5px] text-risk-high">
            {error}
          </p>
        )}

        <div className="flex items-center justify-between gap-3 border-t border-line pt-3.5">
          <Link href="/case" className="text-[11.5px] text-muted hover:text-fg">
            ← Back to Case File
          </Link>
          <button type="submit" disabled={busy}
            className="h-9 rounded-lg bg-accent px-4 text-xs font-semibold text-[#04140d] transition-colors hover:bg-accent-bright disabled:opacity-60">
            {busy ? "Working…" : freezeNow ? "Open case & freeze →" : "Open case →"}
          </button>
        </div>
      </form>
    </div>
  );
}
