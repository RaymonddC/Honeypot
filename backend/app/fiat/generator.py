"""Synthetic PT A2Z fiat generator — deterministic, seeded, offline.

Models the documented PT A2Z / Oei Hengky Wiryo laundering pattern
(full case: 4,656 accounts · 22 banks · Rp 530B; the POC generates a
*representative slice* at demo-legible scale):

    payers --QRIS Rp10k–500k--> shell merchants --sweeps--> mule accounts
    --forwards--> cluster collectors --bulk--> exchange IDR bank accounts
    ~minutes later--> USDT-TRC20 deposits at the exchange hot wallet

Money is conserved end-to-end (minus small skims/fees), so the correlation
engine genuinely *rediscovers* the on-ramp instead of being handed it:
each bulk transfer funds one USDT deposit of ``bulk / IDR_PER_USDT`` shaved
by a 0.4–0.9% fee, 6–24 minutes later.

Determinism: everything flows from ``random.Random(seed)`` + uuid5 — no
wall-clock, no unseeded randomness. Same params → byte-identical dataset
(doubles as a test fixture, per docs/Adapter-MODE-Framework.md).
"""

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from random import Random

from app.chain.schemas import Transfer
from app.fiat.schemas import (
    FiatAccountOut,
    FiatDataset,
    FiatGenParams,
    FiatTransactionOut,
)

IDR_PER_USDT = 16_300.0  # fixed demo rate (docs/TRACE-Design open Q2 — POC constant)

# Indodax USDT-TRC20 hot wallet (chain fixtures, tagged category='exchange').
HOT_WALLET = "TBGgUKGDdVWr52tsmSGYcFDkTeDoK5Sw3d"

CASE_FRAMING = {
    "case_ref": "PT A2Z / Oei Hengky Wiryo pattern",
    "full_case": "4,656 accounts · 22 banks · Rp 530B",
    "note": "POC generates a representative slice at demo-legible scale; "
            "fiat side is synthetic (real bank/QRIS data requires MoU).",
}

# 22 banks of the real case — merchant/mule/payer accounts are spread across them.
BANKS_22 = [
    "BCA", "BRI", "BNI", "Mandiri", "CIMB Niaga", "Danamon", "Permata", "Panin",
    "OCBC NISP", "Maybank", "BTN", "BSI", "Mega", "BTPN", "Sinarmas", "KB Bukopin",
    "Muamalat", "Commonwealth", "UOB", "HSBC", "DBS", "Jago",
]

MERCHANT_WORDS = [
    "BERKAH", "MAJU JAYA", "SUMBER REZEKI", "CAHAYA", "MITRA", "SEJAHTERA",
    "ABADI", "MAKMUR", "LANCAR", "BAROKAH", "SENTOSA", "HARAPAN",
]
FIRST_NAMES = [
    "Budi", "Siti", "Agus", "Dewi", "Rizky", "Putri", "Andi", "Sri", "Joko",
    "Ratna", "Hendra", "Lestari", "Bambang", "Ayu", "Dedi", "Wulan", "Fajar",
    "Indah", "Gunawan", "Maya",
]
LAST_NAMES = [
    "Santoso", "Wijaya", "Saputra", "Hidayat", "Pratama", "Utami", "Susanto",
    "Halim", "Kurniawan", "Sari", "Nugroho", "Rahayu", "Setiawan", "Gunardi",
    "Hartono", "Salim",
]

# 3 activity days aligned with the chain fixtures' day (2026-06-10).
DAY_STARTS = [
    datetime(2026, 6, 8, 7, 0, tzinfo=timezone.utc),
    datetime(2026, 6, 9, 7, 0, tzinfo=timezone.utc),
    datetime(2026, 6, 10, 7, 0, tzinfo=timezone.utc),
]

_NS = uuid.uuid5(uuid.NAMESPACE_URL, "ittu:fiat")
_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def _uid(*parts: object) -> uuid.UUID:
    return uuid.uuid5(_NS, ":".join(str(p) for p in parts))


def _tron_addr(seed_str: str) -> str:
    """Deterministic, base58-shaped TRON address for synthetic deposit senders."""
    digest = hashlib.sha256(seed_str.encode()).digest()
    return "T" + "".join(_B58[b % 58] for b in digest[:33])


def _tx_hash(seed_str: str) -> str:
    return hashlib.sha256(seed_str.encode()).hexdigest()


def _person(rng: Random) -> str:
    return f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"


def _acct_no(rng: Random) -> str:
    return str(rng.randrange(10**9, 10**10))


@lru_cache(maxsize=8)
def _generate(seed: int, n_merchants: int, n_clusters: int, n_payers: int) -> FiatDataset:
    params = FiatGenParams(
        seed=seed, n_merchants=n_merchants, n_clusters=n_clusters, n_payers=n_payers
    )
    rng = Random(seed)
    accounts: list[FiatAccountOut] = []
    txs: list[FiatTransactionOut] = []
    deposits: list[Transfer] = []
    tx_i = 0

    def account(role: str, holder: str, cluster: str | None = None,
                bank: str | None = None) -> FiatAccountOut:
        a = FiatAccountOut(
            id=_uid(seed, "acct", len(accounts)),
            account_number=_acct_no(rng),
            bank_name=bank or rng.choice(BANKS_22),
            holder_name=holder,
            role=role,
            cluster=cluster,
        )
        accounts.append(a)
        return a

    def tx(frm: FiatAccountOut, to: FiatAccountOut, amount: float, ts: datetime,
           channel: str, kind: str) -> FiatTransactionOut:
        nonlocal tx_i
        t = FiatTransactionOut(
            id=_uid(seed, "tx", tx_i), from_account_id=frm.id, to_account_id=to.id,
            amount=round(amount), ts=ts, channel=channel, kind=kind,
        )
        tx_i += 1
        txs.append(t)
        return t

    # ---- accounts -----------------------------------------------------------
    exchange_accts = [
        account("exchange", "PT Indodax Nasional Indonesia", bank=b)
        for b in ("BCA", "Mandiri", "BRI")
    ]
    clusters = [f"C{i + 1}" for i in range(n_clusters)]
    merchants = [
        account("shell_merchant",
                f"TOKO {MERCHANT_WORDS[i % len(MERCHANT_WORDS)]} {i + 1:02d}",
                cluster=clusters[i % n_clusters])
        for i in range(n_merchants)
    ]
    mules: dict[str, list[FiatAccountOut]] = {}
    collectors: dict[str, FiatAccountOut] = {}
    for c in clusters:
        mules[c] = [account("mule", _person(rng), cluster=c)
                    for _ in range(rng.randint(12, 16))]
        collectors[c] = account("collector_mule", _person(rng), cluster=c)
    payers = [account("payer", _person(rng)) for _ in range(n_payers)]
    retail = [account("retail", _person(rng)) for _ in range(3)]

    # ---- daily flow ---------------------------------------------------------
    # collector ledger: un-bulked receipts (ts, amount)
    pending: dict[str, list[tuple[datetime, float]]] = {c: [] for c in clusters}

    for day_i, day in enumerate(DAY_STARTS):
        # 1) QRIS micro-deposits (Rp 10k–500k) + 2) merchant sweeps → mules
        mule_inflow: dict[uuid.UUID, list[tuple[datetime, float]]] = {}
        for m in merchants:
            n_dep = rng.randint(18, 28)
            dep_ts = sorted(day + timedelta(minutes=rng.uniform(0, 600))
                            for _ in range(n_dep))
            amounts = [rng.randint(10, 500) * 1000 for _ in range(n_dep)]
            for ts_, amt in zip(dep_ts, amounts):
                tx(rng.choice(payers), m, amt, ts_, "qris", "qris_deposit")

            # two sweeps: midday (covers morning) + evening (covers afternoon)
            midday = day + timedelta(hours=6.0)  # 13:00 UTC+0 offset
            for sweep_i, sweep_base in enumerate((midday, day + timedelta(hours=11.5))):
                if sweep_i == 0:
                    batch = [a for t, a in zip(dep_ts, amounts) if t < midday]
                else:
                    batch = [a for t, a in zip(dep_ts, amounts) if t >= midday]
                total = sum(batch) * rng.uniform(0.97, 0.99)
                if total < 50_000:
                    continue
                sweep_ts = sweep_base + timedelta(minutes=rng.uniform(10, 45))
                recipients = rng.sample(mules[m.cluster], k=min(rng.randint(3, 5),
                                                                len(mules[m.cluster])))
                shares = [rng.uniform(0.7, 1.3) for _ in recipients]
                for mu, sh in zip(recipients, shares):
                    amt = total * sh / sum(shares)
                    t = tx(m, mu, amt, sweep_ts, "transfer", "merchant_sweep")
                    mule_inflow.setdefault(mu.id, []).append((t.ts, t.amount))

        # 3) mule forwards → collector (brief hold: 30–90 min after last inflow)
        for c in clusters:
            for mu in mules[c]:
                inflows = mule_inflow.get(mu.id, [])
                if not inflows:
                    continue
                total_in = sum(a for _, a in inflows)
                fwd_ts = max(t for t, _ in inflows) + timedelta(minutes=rng.uniform(30, 90))
                fwd = tx(mu, collectors[c], total_in * rng.uniform(0.96, 0.985),
                         fwd_ts, "transfer", "mule_forward")
                pending[c].append((fwd.ts, fwd.amount))

        # 4) collector bulk → exchange bank account (mornings of day 2 & 3),
        #    each funding one USDT deposit at the hot wallet minutes later.
        if day_i >= 1:
            for c in clusters:
                bulk_ts = day + timedelta(hours=rng.uniform(2.5, 5.5))  # 09:30–12:30 UTC
                ready = [(t, a) for t, a in pending[c] if t < bulk_ts]
                amount = sum(a for _, a in ready) * rng.uniform(0.992, 0.998)
                if amount < 1_000_000:
                    continue
                pending[c] = [(t, a) for t, a in pending[c] if t >= bulk_ts]
                bulk = tx(collectors[c], rng.choice(exchange_accts), amount,
                          bulk_ts, "transfer", "bulk_to_exchange")

                fee = rng.uniform(0.004, 0.009)
                deposits.append(Transfer(
                    tx_hash=_tx_hash(f"bridge:{seed}:{bulk.id}"),
                    from_addr=_tron_addr(f"bridge:{seed}:{c}"),
                    to_addr=HOT_WALLET,
                    value=round(bulk.amount / IDR_PER_USDT * (1 - fee), 2),
                    token_symbol="USDT",
                    ts=bulk.ts + timedelta(seconds=rng.uniform(360, 1440)),
                    block_number=62_110_000 + len(deposits) * 40,
                    data_mode="poc",
                ))

    # 5) retail noise: legit customer deposits to exchange accounts —
    #    amounts far below any bulk (≈120–500 USDT) → must never correlate.
    for i, r in enumerate(retail):
        tx(r, exchange_accts[i % len(exchange_accts)],
           rng.randint(2_000, 8_000) * 1000,
           DAY_STARTS[2] + timedelta(hours=rng.uniform(0.2, 8.0)),
           "transfer", "retail_noise")

    txs.sort(key=lambda t: (t.ts, str(t.id)))
    deposits.sort(key=lambda d: d.ts)

    return FiatDataset(
        params=params,
        accounts=accounts,
        transactions=txs,
        crypto_deposits=deposits,
        idr_per_usdt=IDR_PER_USDT,
        hot_wallet=HOT_WALLET,
        case_framing=CASE_FRAMING,
    )


def generate_dataset(params: FiatGenParams | None = None) -> FiatDataset:
    """Deterministic PT A2Z dataset (cached per param set)."""
    p = params or FiatGenParams()
    return _generate(p.seed, p.n_merchants, p.n_clusters, p.n_payers)
