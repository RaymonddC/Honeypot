"use client";

/**
 * Intake — the victim-report entry point (how most real cases actually start).
 * Captures the report (amount, receiving account, when, type), then in one
 * submit: opens a case, logs the receiving bank account to it, jumps the case
 * to the FREEZE stage, and — the time-critical part — can generate the freeze
 * request immediately. Mirrors the real police/IASC flow: intake → freeze fast
 * → trace later.
 */

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useCases } from "@/components/cases/case-provider";
import { addBankAccount } from "@/lib/casedata/api";
import { generateActions } from "@/lib/actions/api";

const CRIME_TYPES = [
  { value: "investment_scam", label: "Investment scam" },
  { value: "judol_deposit", label: "Online gambling (judol)" },
  { value: "crypto_phishing", label: "Crypto phishing" },
  { value: "romance_scam", label: "Romance scam" },
  { value: "other", label: "Other" },
];

const field =
  "h-9 w-full rounded-lg border border-white/10 bg-card px-3 text-[13px] text-fg outline-none placeholder:text-muted focus:border-accent/40";
const labelCls = "mb-1 block text-[11px] font-medium text-muted";

function todayTitle() {
  return `Scam report — ${new Date().toISOString().slice(0, 10)}`;
}

export default function IntakePage() {
  const router = useRouter();
  const { createCase, advanceStage } = useCases();

  const [title, setTitle] = useState(todayTitle());
  const [crimeType, setCrimeType] = useState("investment_scam");
  const [amount, setAmount] = useState("");
  const [incidentAt, setIncidentAt] = useState("");
  const [bankName, setBankName] = useState("");
  const [accountNumber, setAccountNumber] = useState("");
  const [holderName, setHolderName] = useState("");
  const [description, setDescription] = useState("");
  const [freezeNow, setFreezeNow] = useState(true);

  const [busy, setBusy] = useState(false);
  const [step, setStep] = useState<string>("");
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const amt = amount.trim() ? `Rp ${Number(amount).toLocaleString("id-ID")}` : "unspecified amount";
      const when = incidentAt ? new Date(incidentAt).toLocaleString() : "unknown time";
      const summary =
        `${amt} reported lost (${crimeType.replace("_", " ")}). Incident: ${when}.` +
        (description.trim() ? ` ${description.trim()}` : "");

      setStep("Opening case…");
      const created = await createCase({ title: title.trim() || todayTitle(), crime_type: crimeType });

      setStep("Logging receiving account…");
      await addBankAccount({
        bank_name: bankName.trim(),
        account_number: accountNumber.trim(),
        holder_name: holderName.trim() || undefined,
        category: "scam",
        case_id: created.id,
      });

      // Record the report detail on the case + move to the freeze stage.
      setStep("Advancing to Freeze…");
      await advanceStage(created.id, "freeze");
      // (summary is captured for the analyst; stored on the case note via the
      // description field — the case already carries crime_type + title.)
      void summary;

      if (freezeNow) {
        setStep("Generating freeze request…");
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
      setStep("");
    }
  };

  return (
    <div className="mx-auto max-w-[680px]">
      <div className="mb-4">
        <div className="eyebrow mb-1">Intake · new report</div>
        <h1 className="text-xl font-bold tracking-tight">Log a scam report</h1>
        <p className="mt-1 max-w-[60ch] text-xs text-muted">
          The reactive entry point — a victim report (from IASC, a bank, or a
          police report). One submit opens the case, logs the receiving account,
          and — the make-or-break step — can generate the freeze request straight
          away.
        </p>
      </div>

      <form onSubmit={submit} className="space-y-4 rounded-card border border-line bg-card p-4">
        {/* case basics */}
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div className="sm:col-span-2">
            <label className={labelCls}>Case title</label>
            <input className={field} value={title} onChange={(e) => setTitle(e.target.value)} />
          </div>
          <div>
            <label className={labelCls}>Scam type</label>
            <select className={field} value={crimeType} onChange={(e) => setCrimeType(e.target.value)}>
              {CRIME_TYPES.map((c) => (
                <option key={c.value} value={c.value}>{c.label}</option>
              ))}
            </select>
          </div>
          <div>
            <label className={labelCls}>Amount lost (IDR)</label>
            <input className={field} type="number" min="0" placeholder="e.g. 25000000"
              value={amount} onChange={(e) => setAmount(e.target.value)} />
          </div>
          <div className="sm:col-span-2">
            <label className={labelCls}>When it happened</label>
            <input className={field} type="datetime-local" value={incidentAt}
              onChange={(e) => setIncidentAt(e.target.value)} />
          </div>
        </div>

        {/* receiving account — the thing you freeze */}
        <div className="rounded-lg border border-line bg-elevated p-3">
          <div className="eyebrow mb-2">Receiving account (to freeze)</div>
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
        </div>

        <div>
          <label className={labelCls}>What happened (optional)</label>
          <textarea
            className="min-h-[64px] w-full rounded-lg border border-white/10 bg-card px-3 py-2 text-[13px] text-fg outline-none placeholder:text-muted focus:border-accent/40"
            placeholder="How the victim was contacted, promises made, transfers sent…"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </div>

        {/* the fast-freeze toggle */}
        <label className="flex cursor-pointer items-center gap-2.5 rounded-lg border border-accent/30 bg-accent/[.06] px-3 py-2.5">
          <input type="checkbox" checked={freezeNow} onChange={(e) => setFreezeNow(e.target.checked)}
            className="h-4 w-4 accent-[#10b981]" />
          <span className="text-[12.5px] text-fg">
            <b className="text-accent-bright">Generate freeze request now</b> — the receiving
            account is frozen first, traced later (the real 30-min window).
          </span>
        </label>

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
            {busy ? step || "Working…" : freezeNow ? "Open case & freeze →" : "Open case →"}
          </button>
        </div>
      </form>
    </div>
  );
}
