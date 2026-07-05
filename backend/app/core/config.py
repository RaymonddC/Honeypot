"""Settings + MODE resolution (see docs/Adapter-MODE-Framework.md).

Env vars use the ``ITTU_`` prefix, e.g.::

    ITTU_MODE=poc
    ITTU_MODULE_MODES={"takedown":"live"}
    ITTU_DATABASE_URL=postgresql+asyncpg://ittu:ittu@localhost:5432/ittu
    ITTU_REDIS_URL=redis://localhost:6379/0
"""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

Mode = Literal["poc", "live"]

MODULES = ("infiltrate", "trace", "takedown", "uncover", "intel")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ITTU_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # POC is the safe default; LIVE requires explicit config + credentials.
    mode: Mode = "poc"
    # Per-module override, e.g. ITTU_MODULE_MODES='{"takedown":"live"}'
    module_modes: dict[str, Mode] = {}

    database_url: str = "postgresql+asyncpg://ittu:ittu@localhost:5432/ittu"
    redis_url: str = "redis://localhost:6379/0"


class ModeResolver:
    """Resolve the effective MODE for a module: override or global default."""

    def __init__(self, settings: "Settings") -> None:
        self._settings = settings

    def effective_mode(self, module: str) -> Mode:
        return self._settings.module_modes.get(module, self._settings.mode)


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def get_mode_resolver() -> ModeResolver:
    return ModeResolver(get_settings())
