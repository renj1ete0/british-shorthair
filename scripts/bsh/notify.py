"""Telegram notifications.

Two channels, deliberately different in volume:

* :func:`alert` fires immediately when something is broken. It is deduplicated by key
  with a cooldown, so a five-hour API outage sends one message rather than 900.
* :func:`digest` is the once-a-day summary sent by the ``daily_summary`` job.

This module talks to Telegram with plain ``requests`` rather than :mod:`bsh.http`, so
that a failure in the retry layer can still be reported instead of recursing into it.
"""

import html
import json
import time

import requests

from .config import get_settings
from .logging_setup import now

API_ROOT = "https://api.telegram.org"
MAX_LEN = 4096
DEFAULT_COOLDOWN = 1800  # seconds a repeated alert key stays suppressed


def _cooldown_path():
    settings = get_settings()
    settings.state_dir.mkdir(parents=True, exist_ok=True)
    return settings.state_dir / "alert_cooldown.json"


def _load_cooldowns():
    path = _cooldown_path()
    if not path.is_file():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_cooldowns(data):
    try:
        with open(_cooldown_path(), "w", encoding="utf-8") as handle:
            json.dump(data, handle)
    except OSError:
        pass


def _suppressed(key, cooldown):
    """True if this alert key fired recently. Records the send time when it does not."""
    if not key:
        return False
    data = _load_cooldowns()
    stamp = time.time()
    last = data.get(key)
    if isinstance(last, (int, float)) and stamp - last < cooldown:
        return True
    # Drop entries older than a day so the file cannot grow without bound.
    data = {k: v for k, v in data.items() if isinstance(v, (int, float)) and stamp - v < 86400}
    data[key] = stamp
    _save_cooldowns(data)
    return False


def _chunks(text):
    """Split to Telegram's 4096-char limit, preferring line boundaries."""
    while len(text) > MAX_LEN:
        cut = text.rfind("\n", 0, MAX_LEN)
        if cut <= 0:
            cut = MAX_LEN
        yield text[:cut]
        text = text[cut:].lstrip("\n")
    if text:
        yield text


def _post(text, logger=None):
    settings = get_settings()
    url = f"{API_ROOT}/bot{settings.telegram_token}/sendMessage"
    for chunk in _chunks(text):
        payload = {
            "chat_id": settings.telegram_chat_id,
            "text": chunk,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        for attempt in range(3):
            try:
                response = requests.post(url, json=payload, timeout=15)
                if response.status_code == 429:
                    retry_after = 5
                    try:
                        retry_after = int(response.json()["parameters"]["retry_after"])
                    except (ValueError, KeyError, TypeError):
                        pass
                    time.sleep(min(retry_after, 60))
                    continue
                if response.ok:
                    break
                if logger and attempt == 2:
                    logger.warning(
                        "Telegram send failed: HTTP %s %s", response.status_code, response.text[:200]
                    )
            except requests.RequestException as exc:
                if logger and attempt == 2:
                    logger.warning("Telegram send failed: %s", exc)
                time.sleep(1 + attempt)
        else:
            return False
    return True


def _enabled(logger):
    if get_settings().has_telegram():
        return True
    if logger:
        logger.debug("Telegram not configured; skipping notification")
    return False


def discover_chat_ids(token=None, logger=None):
    """Chat ids that have recently messaged this bot.

    Telegram has no notion of a bot's "owner": ``sendMessage`` requires an explicit
    ``chat_id``, and a bot cannot start a conversation. The id therefore has to come
    from somewhere, and the only way it becomes known is for you to message the bot
    first - at which point it shows up here.

    Returns a list of ``(chat_id, label, type)``. Note ``getUpdates`` only reports
    roughly the last 24 hours, and returns nothing at all if a webhook is set.
    """
    token = token or get_settings().telegram_token
    if not token:
        return []
    try:
        response = requests.get(f"{API_ROOT}/bot{token}/getUpdates", timeout=15)
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        if logger:
            logger.warning("could not query getUpdates: %s", exc)
        return []

    if not payload.get("ok"):
        if logger:
            logger.warning("Telegram rejected getUpdates: %s", payload.get("description"))
        return []

    found = {}
    for update in payload.get("result", []):
        for container in ("message", "edited_message", "channel_post", "my_chat_member"):
            chat = (update.get(container) or {}).get("chat")
            if not chat:
                continue
            label = chat.get("title") or " ".join(
                filter(None, [chat.get("first_name"), chat.get("last_name")])
            ) or chat.get("username") or "?"
            found[chat["id"]] = (label, chat.get("type", "?"))
    return [(cid, label, kind) for cid, (label, kind) in found.items()]


def alert(title, body="", key=None, cooldown=DEFAULT_COOLDOWN, logger=None):
    """Send an immediate failure alert, suppressed if ``key`` fired within ``cooldown``."""
    if not _enabled(logger):
        return False
    if _suppressed(key, cooldown):
        if logger:
            logger.debug("Alert %r suppressed by cooldown", key)
        return False
    text = f"\U0001f6a8 <b>{html.escape(str(title))}</b>\n{html.escape(str(body))}".strip()
    text += f"\n\n<i>{now().strftime('%Y-%m-%d %H:%M:%S')} SGT</i>"
    return _post(text, logger)


def digest(title, body, logger=None):
    """Send the daily summary. Never suppressed."""
    if not _enabled(logger):
        return False
    text = f"\U0001f4ca <b>{html.escape(str(title))}</b>\n\n{body}"
    return _post(text, logger)
