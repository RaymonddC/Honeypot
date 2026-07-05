"""Fiat boundary adapters — POC (synthetic PT A2Z) and LIVE (bank feed stub).

Registered in the core adapter registry under ``("fiat", "poc"/"live")``.
Both implement the ``FiatDataAdapter`` protocol (app/core/adapters.py) with
identical signatures + Pydantic return models, and stamp ``data_mode``.
"""

from app.core.adapters import register
from app.core.config import Mode, Settings
from app.fiat.generator import generate_dataset
from app.fiat.schemas import FiatDataset, FiatGenParams, FiatTransactionOut


@register("fiat", "poc")
class SyntheticA2ZAdapter:
    """POC: deterministic synthetic PT A2Z generator (offline, seeded)."""

    data_mode: Mode = "poc"

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings

    async def load_dataset(self, params: FiatGenParams | None = None) -> FiatDataset:
        return generate_dataset(params)

    async def load_transactions(
        self, params: FiatGenParams | None = None
    ) -> list[FiatTransactionOut]:
        return (await self.load_dataset(params)).transactions


@register("fiat", "live")
class BankFeedAdapter:
    """LIVE: real bank + QRIS feed. Placeholder until bank MoUs land —
    fiat stays simulated even in early LIVE (docs/TRACE-Design.md, POC↔LIVE).
    """

    data_mode: Mode = "live"

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings

    async def load_dataset(self, params: FiatGenParams | None = None) -> FiatDataset:
        raise NotImplementedError(
            "LIVE fiat feed requires bank/QRIS MoU credentials — not available "
            "in this build. Run TRACE in POC mode (ITTU_MODE=poc)."
        )

    async def load_transactions(
        self, params: FiatGenParams | None = None
    ) -> list[FiatTransactionOut]:
        raise NotImplementedError(
            "LIVE fiat feed requires bank/QRIS MoU credentials — not available "
            "in this build. Run TRACE in POC mode (ITTU_MODE=poc)."
        )
