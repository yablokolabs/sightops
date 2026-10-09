"""Runtime configuration for the SightOps backend.

Secrets are loaded from the environment. Two optional files are consulted, in
order of increasing precedence:

1. ``<repo>/.env``              — project-local overrides (never committed).
2. ``$SIGHTOPS_ENV_FILE``       — defaults to ``~/.hermes/.env``, the shared
   credential store referenced by ``AGENTS.md``.

Only the three keys SightOps actually needs are read out of the shared store;
the rest of that file is ignored rather than copied into the process
environment. Secret values are never logged — :meth:`Settings.describe`
reports presence, not content.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_HERMES_ENV = Path.home() / ".hermes" / ".env"

#: The only variables SightOps reads from the shared Hermes credential store.
ALLOWED_HERMES_KEYS = ("NEBIUS_API_KEY", "ELEVENLABS_API_KEY", "TAVILY_API_KEY")

#: "Beth" — the brief's preferred young adult British female voice. A library
#: voice, so it needs a paid plan to be spoken over the API. Kept here because
#: the choice is a product decision, not an implementation detail.
LIBRARY_VOICE_ID = "zH7TN9vEZAsEway9xWev"


def _read_env_file(path: Path) -> dict[str, str]:
    """Parse a ``KEY=value`` file without mutating ``os.environ``."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def load_secrets() -> dict[str, str]:
    """Resolve provider credentials from environment or the shared store."""
    secrets: dict[str, str] = {}
    for key in ALLOWED_HERMES_KEYS:
        env_value = os.environ.get(key)
        if env_value:
            secrets[key] = env_value

    hermes_path = Path(os.environ.get("SIGHTOPS_ENV_FILE", DEFAULT_HERMES_ENV))
    hermes_values = _read_env_file(hermes_path)
    for key in ALLOWED_HERMES_KEYS:
        if key not in secrets and hermes_values.get(key):
            secrets[key] = hermes_values[key]
    return secrets


class Settings(BaseSettings):
    """Application settings, overridable with ``SIGHTOPS_`` env vars."""

    model_config = SettingsConfigDict(
        env_prefix="SIGHTOPS_",
        env_file=str(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # -- Storage ------------------------------------------------------------
    data_dir: Path = Field(default=REPO_ROOT / "data")
    db_filename: str = "sightops.db"
    max_upload_bytes: int = 12 * 1024 * 1024
    max_image_pixels: int = 40_000_000

    # -- Providers ----------------------------------------------------------
    nebius_base_url: str = "https://api.studio.nebius.com/v1"
    nebius_model: str = "Qwen/Qwen3.5-397B-A17B"
    nebius_vision_model: str = "openbmb/MiniCPM-V-4_5"
    elevenlabs_base_url: str = "https://api.elevenlabs.io/v1"
    #: "Alice" — British female, premade. Premade voices are served to every
    #: plan, so this default speaks on the account this project actually runs on.
    #:
    #: The brief's preferred voice is "Beth" (:data:`LIBRARY_VOICE_ID`), a young
    #: adult British female. Beth is a *library* voice and the API refuses those
    #: on the free plan with ``HTTP 402 paid_plan_required``, verified on
    #: 2026-10-09. Setting it here on an upgraded plan works; the provider falls
    #: back to Alice rather than failing if the plan still refuses it.
    elevenlabs_voice_id: str = "Xb7hH8MSUJpSbSDYk0k2"
    elevenlabs_model_id: str = "eleven_turbo_v2_5"
    provider_timeout_seconds: float = 60.0
    provider_max_retries: int = 2

    # -- Agent bounds -------------------------------------------------------
    max_agent_steps: int = 8
    max_tool_calls: int = 12
    max_reinspection_rounds: int = 2
    agent_step_timeout_seconds: float = 90.0

    # -- Vision thresholds (documented in docs/evaluation/methodology.md) ---
    blur_threshold: float = 0.35
    dark_exposure_threshold: float = 0.20
    bright_exposure_threshold: float = 0.88
    min_region_pixels: int = 400
    #: A component crop is a small window, so the frame-level short-edge rule
    #: does not apply to it; this is the size below which the crop itself is
    #: genuinely too small to measure.
    min_region_short_edge: int = 24
    indicator_confidence_floor: float = 0.55
    gauge_confidence_floor: float = 0.60

    # -- HTTP ---------------------------------------------------------------
    #: Browser origins allowed to call the API. Defaults cover the Vite dev
    #: server and the compiled frontend served from the same host.
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
        "http://localhost:8080",
        "http://127.0.0.1:8080",
    ]

    # -- Demo ---------------------------------------------------------------
    demo_mode: bool = False

    @property
    def db_path(self) -> Path:
        return self.data_dir / self.db_filename

    @property
    def evidence_dir(self) -> Path:
        return self.data_dir / "evidence"

    def ensure_dirs(self) -> None:
        self.evidence_dir.mkdir(parents=True, exist_ok=True)

    def provider_status(self) -> dict[str, bool]:
        """Report which providers are configured, without revealing values."""
        secrets = load_secrets()
        return {key: bool(secrets.get(key)) for key in ALLOWED_HERMES_KEYS}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings
