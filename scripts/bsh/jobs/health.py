"""Disk headroom and the external heartbeat.

Two things the rest of the collector cannot do for itself.

**Disk.** Collection writes roughly 3.3 GB/day. Every other job would eventually
notice a full volume - as write failures, after data was already lost - so this checks
headroom directly and warns while there is still time to act.

**Heartbeat.** The collector cannot report its own death: if the container stops, so
does the job that would have told you. Silence from a healthy system and silence from a
stopped one look identical. Pinging an outside service on a schedule inverts that -
*that* service alerts on the absence of a ping. Configure ``HEARTBEAT_URL`` with a
dead-man's-switch endpoint (healthchecks.io or similar); without it this is a no-op and
the blind spot remains.
"""

import requests

from .. import notify, storage
from ..registry import job

# Measured daily growth before archival, used only to turn "N GB free" into "about M
# days left", which is the part that tells you whether to act now or later.
DAILY_GROWTH_BYTES = 3.3 * 1024 ** 3


def _days_left(free_bytes):
    return free_bytes / DAILY_GROWTH_BYTES if DAILY_GROWTH_BYTES else float("inf")


def check_disk(settings, logger, record):
    """Report headroom, and alert when it runs short. Returns the percent free."""
    free, total, pct = storage.disk_free(settings.data_dir)
    days = _days_left(free)
    record.notes["disk_free_pct"] = round(pct, 1)
    record.notes["disk_free_bytes"] = free
    record.notes["disk_days_left"] = round(days, 1)

    summary = (f"{storage.human_bytes(free)} free of {storage.human_bytes(total)} "
               f"({pct:.0f}%), about {days:.0f} days left")

    if pct <= settings.disk_alert_pct:
        logger.error("disk critically low: %s", summary)
        notify.alert(
            "Disk almost full",
            f"{pct:.0f}% free - {storage.human_bytes(free)} of "
            f"{storage.human_bytes(total)}.\n"
            f"Collection writes ~3.3 GB/day, so this fills in about {days:.0f} days.\n"
            f"Check that the archive job is running: it is what reclaims space.",
            key="disk:critical",
            logger=logger,
        )
        record.items_failed += 1
    elif pct <= settings.disk_warn_pct:
        logger.warning("disk low: %s", summary)
        notify.alert(
            "Disk getting low",
            f"{pct:.0f}% free - {storage.human_bytes(free)} of "
            f"{storage.human_bytes(total)}, about {days:.0f} days left.",
            key="disk:warning",
            # Once a day is plenty for a slow-moving trend.
            cooldown=86400,
            logger=logger,
        )
    else:
        logger.info("disk ok: %s", summary)
    return pct


def send_heartbeat(settings, logger, record):
    """Ping the external dead-man's switch. Absence of this ping is the alarm."""
    if not settings.heartbeat_url:
        record.notes["heartbeat"] = "not configured"
        logger.debug("HEARTBEAT_URL not set; external liveness monitoring is off")
        return False
    try:
        response = requests.get(settings.heartbeat_url, timeout=15)
        response.raise_for_status()
    except requests.RequestException as exc:
        # Deliberately not an alert. A failed ping means the monitor is unreachable,
        # not that collection is broken - and the monitor will raise the alarm itself
        # when pings stop arriving.
        record.notes["heartbeat"] = "failed"
        logger.warning("heartbeat ping failed: %s", exc)
        return False
    record.notes["heartbeat"] = "ok"
    logger.info("heartbeat sent")
    return True


@job(
    "health",
    schedule="0 * * * *",
    description="Check disk headroom and ping the external heartbeat",
)
def collect(logger, record, settings):
    check_disk(settings, logger, record)
    send_heartbeat(settings, logger, record)
    record.items_ok = 1
