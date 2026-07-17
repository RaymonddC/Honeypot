"""Response Dashboard read-model — GET /api/metrics/response (Screen 4).

Narrates ITTU's core promise: response time **days → minutes**. Combines
- a **deterministic demo baseline** (seeded cases so the dashboard is
  populated before the first live demo click), and
- **real generated actions** from the UNCOVER orchestrator (every
  generate→dispatch during the demo moves the numbers).

Benchmarks (docs/Response-Dashboard.md): >12h manual time-to-freeze baseline;
IASC 4.76% recovery-rate baseline.
"""

from datetime import datetime, timedelta, timezone
from typing import Literal

from pydantic import BaseModel, Field

from app.chain.adapters import _load_fixture_transfers
from app.fiat.generator import IDR_PER_USDT
from app.uncover import service
from app.uncover.repository import UncoverRepository

RangeKey = Literal["7d", "30d", "all"]
RANGE_DAYS: dict[str, int | None] = {"7d": 7, "30d": 30, "all": None}

BASELINE_TTF_HOURS = 12.0          # manual freeze baseline the proposal cites (>12h)
BASELINE_RECOVERY_RATE = 0.0476    # IASC recovery baseline (4.76%)

# Deterministic demo baseline — offsets in days from "now", so the dashboard
# is always populated and range filters behave. POC data, clearly stamped.
BASELINE_CASES: list[dict] = [
    {"case_id": "CASE-2026-0091", "title": "Peeling-chain investment scam — TRON cash-out",
     "crime_type": "investment", "status": "frozen", "days_ago": 26,
     "at_risk_idr": 1_400_750_000, "frozen_idr": 1_120_600_000, "ttf_minutes": 14.2},
    {"case_id": "CASE-2026-0104", "title": "PT A2Z judol deposit network (4,656 accounts)",
     "crime_type": "judol_deposit", "status": "in_progress", "days_ago": 19,
     "at_risk_idr": 3_215_400_000, "frozen_idr": 0, "ttf_minutes": None},
    {"case_id": "CASE-2026-0117", "title": "QRIS shell-merchant mule ring — cluster C3",
     "crime_type": "judol_deposit", "status": "frozen", "days_ago": 12,
     "at_risk_idr": 845_200_000, "frozen_idr": 612_800_000, "ttf_minutes": 22.7},
    {"case_id": "CASE-2026-0125", "title": "Romance scam USDT drain — Telegram honeypot",
     "crime_type": "romance", "status": "in_progress", "days_ago": 8,
     "at_risk_idr": 512_300_000, "frozen_idr": 0, "ttf_minutes": None},
    {"case_id": "CASE-2026-0131", "title": "Crypto phishing wallet cluster — BSC bridge",
     "crime_type": "crypto_phishing", "status": "frozen", "days_ago": 4,
     "at_risk_idr": 998_100_000, "frozen_idr": 703_500_000, "ttf_minutes": 9.8},
    {"case_id": "CASE-2026-0142", "title": "Investment scam — fixture peeling chain (demo)",
     "crime_type": "investment", "status": "in_progress", "days_ago": 1,
     "at_risk_idr": 86_200 * IDR_PER_USDT, "frozen_idr": 0, "ttf_minutes": None},
]

# Honeypot demo baseline (INFILTRATE lands in P4 — deterministic stand-ins).
BASELINE_HONEYPOT = {"active_sessions": 3, "entities_confirmed": 17}


class CaseRow(BaseModel):
    case_id: str
    title: str
    crime_type: str
    status: Literal["in_progress", "frozen"]
    opened_at: datetime
    at_risk_idr: float
    frozen_idr: float
    time_to_freeze_minutes: float | None = None
    source: Literal["baseline", "action"] = "baseline"


class TimeToFreeze(BaseModel):
    avg_minutes: float | None
    baseline_hours: float = BASELINE_TTF_HOURS
    improvement_factor: float | None       # baseline / current


class Funds(BaseModel):
    at_risk_idr: float
    frozen_idr: float
    at_risk_usdt: float
    frozen_usdt: float
    recovery_rate: float                    # frozen / at_risk
    baseline_recovery_rate: float = BASELINE_RECOVERY_RATE


class Honeypot(BaseModel):
    active_sessions: int
    entities_confirmed: int


class ActionStats(BaseModel):
    bundles_generated: int
    bundles_dispatched: int
    documents_generated: int
    notifications_mock: int


class TrendPoint(BaseModel):
    date: str                               # ISO date (bucket start)
    cases: int
    frozen_idr: float
    avg_ttf_minutes: float | None


class ResponseMetrics(BaseModel):
    range: RangeKey
    data_mode: str = "poc"
    generated_at: datetime
    cases_in_progress: int
    cases_total: int
    time_to_freeze: TimeToFreeze
    funds: Funds
    honeypot: Honeypot
    wallets_scored: int
    actions: ActionStats
    trend: list[TrendPoint]
    cases: list[CaseRow] = Field(default_factory=list)


def _baseline_rows(now: datetime) -> list[CaseRow]:
    return [
        CaseRow(
            case_id=c["case_id"], title=c["title"], crime_type=c["crime_type"],
            status=c["status"] if c["status"] == "frozen" else "in_progress",
            opened_at=now - timedelta(days=c["days_ago"]),
            at_risk_idr=float(c["at_risk_idr"]), frozen_idr=float(c["frozen_idr"]),
            time_to_freeze_minutes=c["ttf_minutes"], source="baseline",
        )
        for c in BASELINE_CASES
    ]


async def _action_rows(now: datetime, *, repo: UncoverRepository) -> list[CaseRow]:
    """Every generated action bundle surfaces as a live case row."""
    rows = []
    for b in await service.all_bundles(repo=repo):
        dispatched = b.status == "dispatched" and b.dispatched_at is not None
        ttf = (
            max((b.dispatched_at - b.created_at).total_seconds() / 60.0, 0.05)
            if dispatched else None
        )
        rows.append(CaseRow(
            case_id=b.case_id, title=f"Action bundle {b.id} ({b.crime_type})",
            crime_type=b.crime_type,
            status="frozen" if dispatched else "in_progress",
            opened_at=b.created_at,
            at_risk_idr=b.totals.at_risk_idr,
            frozen_idr=b.totals.at_risk_idr if dispatched else 0.0,
            time_to_freeze_minutes=round(ttf, 2) if ttf is not None else None,
            source="action",
        ))
    return rows


async def _combined_rows(now: datetime, *, repo: UncoverRepository) -> list[CaseRow]:
    """One row per case_id. A live action row supersedes the baseline row for
    the same case (dispatching flips the case to frozen — no duplicates);
    repeated bundles for one case collapse to the best/newest row."""
    best_action: dict[str, CaseRow] = {}
    for r in await _action_rows(now, repo=repo):
        cur = best_action.get(r.case_id)
        if cur is None:
            best_action[r.case_id] = r
            continue
        # prefer a frozen row over in_progress; otherwise keep the newest
        if (r.status == "frozen", r.opened_at) > (cur.status == "frozen", cur.opened_at):
            best_action[r.case_id] = r
    baseline = [r for r in _baseline_rows(now) if r.case_id not in best_action]
    return baseline + list(best_action.values())


def _trend(rows: list[CaseRow], now: datetime, weeks: int = 6) -> list[TrendPoint]:
    points: list[TrendPoint] = []
    for w in range(weeks - 1, -1, -1):
        start = now - timedelta(days=(w + 1) * 7)
        end = now - timedelta(days=w * 7)
        bucket = [r for r in rows if start < r.opened_at <= end]
        ttfs = [r.time_to_freeze_minutes for r in bucket if r.time_to_freeze_minutes]
        points.append(TrendPoint(
            date=end.date().isoformat(),
            cases=len(bucket),
            frozen_idr=round(sum(r.frozen_idr for r in bucket), 2),
            avg_ttf_minutes=round(sum(ttfs) / len(ttfs), 2) if ttfs else None,
        ))
    return points


async def compute_metrics(range_key: RangeKey = "30d", *, repo: UncoverRepository) -> ResponseMetrics:
    now = datetime.now(timezone.utc)
    rows = await _combined_rows(now, repo=repo)

    days = RANGE_DAYS[range_key]
    if days is not None:
        cutoff = now - timedelta(days=days)
        rows = [r for r in rows if r.opened_at >= cutoff]
    rows.sort(key=lambda r: r.opened_at, reverse=True)

    ttfs = [r.time_to_freeze_minutes for r in rows if r.time_to_freeze_minutes is not None]
    avg_ttf = round(sum(ttfs) / len(ttfs), 2) if ttfs else None
    at_risk = sum(r.at_risk_idr for r in rows)
    frozen = sum(r.frozen_idr for r in rows)

    bundles = await service.all_bundles(repo=repo)
    dispatched = [b for b in bundles if b.status == "dispatched"]
    fixture_wallets = {
        a for t in _load_fixture_transfers() for a in (t.from_addr, t.to_addr)
    }
    action_wallets = {
        e.value for b in bundles for e in b.entities if e.type == "crypto_wallet"
    }

    return ResponseMetrics(
        range=range_key,
        data_mode="poc",
        generated_at=now,
        cases_in_progress=sum(1 for r in rows if r.status == "in_progress"),
        cases_total=len(rows),
        time_to_freeze=TimeToFreeze(
            avg_minutes=avg_ttf,
            improvement_factor=(
                round(BASELINE_TTF_HOURS * 60 / avg_ttf, 1) if avg_ttf else None
            ),
        ),
        funds=Funds(
            at_risk_idr=round(at_risk, 2),
            frozen_idr=round(frozen, 2),
            at_risk_usdt=round(at_risk / IDR_PER_USDT, 2),
            frozen_usdt=round(frozen / IDR_PER_USDT, 2),
            recovery_rate=round(frozen / at_risk, 4) if at_risk else 0.0,
        ),
        honeypot=Honeypot(**BASELINE_HONEYPOT),
        wallets_scored=len(fixture_wallets | action_wallets),
        actions=ActionStats(
            bundles_generated=len(bundles),
            bundles_dispatched=len(dispatched),
            documents_generated=sum(len(b.documents) for b in bundles),
            notifications_mock=sum(
                1 for b in bundles for n in b.notifications if n.status == "mock"
            ),
        ),
        trend=_trend(rows, now),
        cases=rows,
    )
