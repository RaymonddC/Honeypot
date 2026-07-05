"""Adapter registry + factory — the POC↔LIVE MODE backbone.

See docs/Adapter-MODE-Framework.md. Every external boundary (llm, channel_text,
channel_voice, stt, tts, blockchain, fiat, notification, tags) gets:

- a ``Protocol`` interface with identical signatures + Pydantic return models
  across implementations,
- a POC and a LIVE class registered via ``@register(boundary, mode)``,
- resolution through ``get_adapter(boundary, module)`` (module MODE decides).

P0 ships the machinery only — concrete adapters arrive with their modules
(P1+). Routers/services never construct adapters directly; they receive them
via FastAPI ``Depends``.
"""

from typing import Any, Protocol, runtime_checkable

from app.core.config import Mode, Settings, get_mode_resolver, get_settings

# (boundary, mode) -> adapter class
_REGISTRY: dict[tuple[str, str], type] = {}


class AdapterNotRegisteredError(LookupError):
    """No implementation registered for (boundary, mode)."""


def register(boundary: str, mode: Mode):
    """Class decorator: register an adapter implementation for a boundary+mode.

    Example (P1)::

        @register("blockchain", "poc")
        class CachedTronAdapter:
            data_mode: Mode = "poc"
            ...
    """

    def deco(cls: type) -> type:
        _REGISTRY[(boundary, mode)] = cls
        return cls

    return deco


def get_adapter(boundary: str, module: str, settings: Settings | None = None) -> Any:
    """Resolve + instantiate the adapter for `boundary` under `module`'s MODE."""
    settings = settings or get_settings()
    mode = get_mode_resolver().effective_mode(module)
    try:
        impl = _REGISTRY[(boundary, mode)]
    except KeyError:
        raise AdapterNotRegisteredError(
            f"No adapter registered for boundary={boundary!r} mode={mode!r} "
            f"(module={module!r}). POC is the safe default — never fall through "
            f"to a LIVE implementation implicitly."
        ) from None
    return impl(settings)


def registered() -> dict[tuple[str, str], str]:
    """Introspection helper: (boundary, mode) -> class name."""
    return {key: cls.__name__ for key, cls in _REGISTRY.items()}


# --- Example boundary interface (concrete impls land in P1) -----------------


@runtime_checkable
class ChainDataAdapter(Protocol):
    """Blockchain boundary. POC: cached TRON fixtures; LIVE: TRONSCAN/TronGrid.

    Implementations stamp produced rows with ``data_mode`` (evidentiary
    isolation — LIVE views never read POC rows).
    """

    data_mode: Mode

    async def fetch_transfers(self, address: str, cursor: str | None = None) -> Any: ...

    async def balance(self, address: str) -> Any: ...


@runtime_checkable
class FiatDataAdapter(Protocol):
    """Fiat boundary. POC: synthetic PT A2Z generator; LIVE: bank/QRIS feed (post-MoU).

    ``load_dataset`` returns a full ``FiatDataset`` (accounts + transactions +,
    in POC, the synthetic on-ramp deposits). Rows are stamped ``data_mode``.
    """

    data_mode: Mode

    async def load_dataset(self, params: Any | None = None) -> Any: ...

    async def load_transactions(self, params: Any | None = None) -> Any: ...
