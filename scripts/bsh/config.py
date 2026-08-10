"""Environment-driven settings.

Everything the collector needs is read from the environment so the same image can
run against different data volumes and API keys without a rebuild. In Docker these
come from the compose ``env_file``; outside Docker a ``.env`` beside this package is
loaded as a fallback so scripts still work when run by hand.
"""

import json
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import dotenv_values

# Singapore Standard Time. Every schedule, filename and date comparison in this
# project is SGT, regardless of the host clock.
SGT = ZoneInfo("Asia/Singapore")


def _env(key, default=None):
    """Read from the real environment first, then fall back to a local .env."""
    if key in os.environ:
        return os.environ[key]
    return _dotenv().get(key, default)


@lru_cache(maxsize=1)
def _dotenv():
    for candidate in (Path.cwd() / ".env", Path(__file__).resolve().parent.parent / ".env"):
        if candidate.is_file():
            return dotenv_values(candidate)
    return {}


def _env_int(key, default):
    raw = _env(key)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(key, default):
    raw = _env(key)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_keys(key):
    """Parse an API key list, accepting either a JSON array or a comma-separated string."""
    raw = _env(key, "")
    if not raw:
        return []
    raw = raw.strip()
    if raw.startswith("["):
        try:
            return [str(k).strip() for k in json.loads(raw) if str(k).strip()]
        except json.JSONDecodeError:
            pass
    return [part.strip() for part in raw.split(",") if part.strip()]


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    log_dir: Path
    state_dir: Path

    lta_api_keys: list = field(default_factory=list)
    telegram_token: str = ""
    telegram_chat_id: str = ""

    # Retry defaults, overridable per call site.
    retry_attempts: int = 4
    retry_base_delay: float = 0.5
    retry_max_delay: float = 20.0

    # Bus arrival tuning. The API refreshes every 20s, so a tick that cannot finish
    # inside its window is dropped rather than allowed to pile up.
    #
    # Sizing: there is no batch endpoint - BusStopCode is mandatory and singular, so a
    # tick is one request per stop, ~5,091 of them. Workers needed is roughly
    #     stops * per_request_latency / deadline
    # The previous 60s/50-process setup implies ~590ms per request, which at an 18s
    # deadline needs ~167 workers. 160 is the default for that reason; too low simply
    # abandons most of each tick (counted and logged, never silent).
    #
    # The trade-off is request rate: 5,091 every 20s is ~255 req/s against ~85 req/s
    # before. If LTA starts returning 429, lower this rather than raising the deadline.
    arrival_deadline: float = 18.0
    arrival_workers: int = 160
    arrival_timeout: float = 6.0

    request_timeout: float = 30.0
    download_timeout: float = 300.0

    @property
    def stop_list_path(self):
        """Newest bus stop list, read by the arrival jobs on every tick.

        Deliberately unpartitioned: it is a pointer to current state rather than a
        dated observation, and a tick should not have to find the latest partition to
        read it. It is a copy of the newest ``feed=essentials/date=*/busstop.json``.
        """
        return self.data_dir / "busstop_current.json"

    def has_telegram(self):
        return bool(self.telegram_token and self.telegram_chat_id)


@lru_cache(maxsize=1)
def get_settings():
    data_dir = Path(_env("BSH_DATA_DIR", "/data")).resolve()
    return Settings(
        data_dir=data_dir,
        log_dir=Path(_env("BSH_LOG_DIR", str(data_dir / "logs"))).resolve(),
        state_dir=Path(_env("BSH_STATE_DIR", str(data_dir / "state"))).resolve(),
        # A single API_KEY is the normal case. The plural forms remain accepted so
        # several keys can share the load if one ever gets rate-limited, and so older
        # .env files keep working.
        lta_api_keys=(_env_keys("API_KEY") or _env_keys("LTA_API_KEYS")
                      or _env_keys("API_KEYS")),
        telegram_token=_env("TELEGRAM_BOT_TOKEN", "") or "",
        telegram_chat_id=_env("TELEGRAM_CHAT_ID", "") or "",
        retry_attempts=_env_int("BSH_RETRY_ATTEMPTS", 4),
        retry_base_delay=_env_float("BSH_RETRY_BASE_DELAY", 0.5),
        retry_max_delay=_env_float("BSH_RETRY_MAX_DELAY", 20.0),
        arrival_deadline=_env_float("BSH_ARRIVAL_DEADLINE", 18.0),
        arrival_workers=_env_int("BSH_ARRIVAL_WORKERS", 60),
        arrival_timeout=_env_float("BSH_ARRIVAL_TIMEOUT", 6.0),
        request_timeout=_env_float("BSH_REQUEST_TIMEOUT", 30.0),
        download_timeout=_env_float("BSH_DOWNLOAD_TIMEOUT", 300.0),
    )
