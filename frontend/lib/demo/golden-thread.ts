/**
 * The "golden thread" demo dataset — one consistent identity that flows through
 * all four pillars so the end-to-end story is clickable:
 *
 *   INFILTRATE  the honeypot extracts a mule BANK ACCOUNT + a collection WALLET
 *        │      (BCA 5271038462 · TXtR9dQpR7mK2vN8fLbY3wZaQ4pJ6)
 *        ▼
 *   TRACE       the account is shown bridged to the wallet (fiat → USDT on-ramp)
 *        │
 *        ▼
 *   TAKEDOWN    the wallet's full network is graphed — it fans out to 10 mules
 *        │      and peels TLa… → TKe… into the exchange exit TBGgUKG… (all these
 *        │      edges live in backend/app/chain/fixtures/transfers.json)
 *        ▼
 *   UNCOVER     a clicked wallet is packaged into the account-freeze request
 *
 * These constants are the SINGLE place the demo identity is defined. The
 * honeypot's investment_scam scenario discloses the same account + wallet
 * (backend/app/infiltrate/channels.py · DEMO_BCA_ACCOUNT / DEMO_TRON_WALLET),
 * and the wallet network is the P1 chain fixture, so promoting the honeypot
 * lead threads straight into Trace → Takedown → Uncover with no re-entry.
 */

/** IDR per USDT — matches the backend demo rate (app/fiat/generator.py). */
export const IDR_PER_USDT = 16_300;

export const GOLDEN = {
  /** Mule receiving account the honeypot bait extracts. */
  bank: { bankName: "BCA", accountNumber: "5271038462", holder: "Rudi Hartono" },
  /** Collection wallet the fiat is converted into (P1 graph fixture root). */
  wallet: "TXtR9dQpR7mK2vN8fLbY3wZaQ4pJ6",
  /** On-ramp deposit sender → collection wallet (transfers.json, 09:00). */
  onrampSender: "TN3xKp8VqYmWdR5tJcE2sLbHnG9aQfU4Zw",
  /** Downstream peeling-chain exit = the exchange hot wallet. */
  exit: "TBGgUKGDdVWr52tsmSGYcFDkTeDoK5Sw3d",
  /** Representative on-ramp size (matches the 50,000 USDT deposit in the fixture). */
  amountUsdt: 50_000,
} as const;

export const GOLDEN_AMOUNT_IDR = GOLDEN.amountUsdt * IDR_PER_USDT; // Rp 815,000,000

/** Compact IDR, e.g. "Rp 815M". */
export function idrShort(v: number): string {
  if (!Number.isFinite(v) || v <= 0) return "—";
  if (v >= 1e12) return `Rp ${(v / 1e12).toFixed(1)}T`;
  if (v >= 1e9) return `Rp ${(v / 1e9).toFixed(2)}B`;
  if (v >= 1e6) return `Rp ${Math.round(v / 1e6)}M`;
  return `Rp ${Math.round(v).toLocaleString("en-US")}`;
}

/** Compact USDT, e.g. "50,000 USDT". */
export function usdtShort(v: number): string {
  return `${Math.round(v).toLocaleString("en-US")} USDT`;
}

export interface CaseBridge {
  bankLabel: string; // "BCA 5271038462"
  bankHolder?: string;
  wallet: string;
  amountIdr: number;
  amountUsdt: number;
  confidence: number; // 0..1
}

/** A tracked bank account, loosely typed (case rollup row). */
type BankRow = { bank_name?: unknown; account_number?: unknown; holder_name?: unknown; category?: unknown };

/**
 * Derive the case's fiat→crypto on-ramp edge from its tracked accounts + wallets.
 * Returns null until the case has both a (scam/mule) bank account and a wallet —
 * i.e. once the Infiltrate lead has been promoted. Prefers the golden wallet.
 */
export function deriveCaseBridge(banks: BankRow[], wallets: string[]): CaseBridge | null {
  if (!banks.length || !wallets.length) return null;
  const pick =
    banks.find((b) => {
      const c = String(b.category ?? "").toLowerCase();
      return c === "scam" || c === "mule";
    }) ?? banks[0];
  const wallet = wallets.includes(GOLDEN.wallet) ? GOLDEN.wallet : wallets[0];
  const isGolden = wallet === GOLDEN.wallet;
  const usdt = isGolden ? GOLDEN.amountUsdt : 0;
  return {
    bankLabel: `${String(pick.bank_name ?? "Bank")} ${String(pick.account_number ?? "")}`.trim(),
    bankHolder: pick.holder_name ? String(pick.holder_name) : undefined,
    wallet,
    amountUsdt: usdt,
    amountIdr: usdt * IDR_PER_USDT,
    confidence: isGolden ? 0.98 : 0.9,
  };
}
