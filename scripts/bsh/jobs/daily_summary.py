"""Daily Telegram digest.

Aggregates ``runs.jsonl`` for the day and sends one message: what ran, how much it
collected, and what failed. This is the counterpart to the immediate alerts in
:mod:`bsh.notify` — alerts tell you something broke now, this tells you whether the
day as a whole was healthy.

Runs late enough to cover the day's collection but before midnight, so the digest is
about the day it is named after.
"""

import html
from collections import defaultdict

from .. import metrics, notify, storage
from ..logging_setup import today
from ..registry import job

STATUS_ICON = {"ok": "✅", "partial": "⚠️", "failed": "❌", "crashed": "\U0001f4a5"}


def _aggregate(records):
    summary = defaultdict(lambda: {
        "runs": 0, "ok": 0, "partial": 0, "failed": 0, "crashed": 0,
        "items_ok": 0, "items_failed": 0, "items_empty": 0,
        "retries": 0, "bytes": 0, "errors": [],
    })
    for entry in records:
        bucket = summary[entry.get("job", "unknown")]
        bucket["runs"] += 1
        status = entry.get("status", "ok")
        if status in bucket:
            bucket[status] += 1
        bucket["items_ok"] += entry.get("items_ok", 0)
        bucket["items_failed"] += entry.get("items_failed", 0)
        bucket["items_empty"] += entry.get("items_empty", 0)
        bucket["retries"] += entry.get("retries", 0)
        bucket["bytes"] += entry.get("bytes_written", 0)
        for message in entry.get("errors", []):
            if message not in bucket["errors"] and len(bucket["errors"]) < 5:
                bucket["errors"].append(message)
    return summary


def build_message(date, summary, disk_lines):
    lines = []
    total_bytes = sum(b["bytes"] for b in summary.values())
    bad = sum(b["failed"] + b["crashed"] for b in summary.values())
    partial = sum(b["partial"] for b in summary.values())

    if bad:
        headline = f"{STATUS_ICON['failed']} {bad} failed run(s)"
    elif partial:
        headline = f"{STATUS_ICON['partial']} {partial} partial run(s)"
    else:
        headline = f"{STATUS_ICON['ok']} all runs healthy"
    lines.append(f"<b>{date.isoformat()}</b> - {headline}")
    lines.append(f"Collected {storage.human_bytes(total_bytes)} across "
                 f"{sum(b['runs'] for b in summary.values())} runs")
    lines.append("")

    for name in sorted(summary):
        bucket = summary[name]
        if bucket["crashed"] or bucket["failed"]:
            icon = STATUS_ICON["failed"]
        elif bucket["partial"]:
            icon = STATUS_ICON["partial"]
        else:
            icon = STATUS_ICON["ok"]

        detail = [f"{bucket['runs']} run(s)"]
        if bucket["failed"] or bucket["crashed"]:
            detail.append(f"{bucket['failed'] + bucket['crashed']} failed")
        if bucket["partial"]:
            detail.append(f"{bucket['partial']} partial")
        if bucket["items_ok"]:
            detail.append(f"{bucket['items_ok']:,} ok")
        if bucket["items_failed"]:
            detail.append(f"{bucket['items_failed']:,} items failed")
        if bucket["retries"]:
            detail.append(f"{bucket['retries']:,} retries")
        if bucket["bytes"]:
            detail.append(storage.human_bytes(bucket["bytes"]))

        lines.append(f"{icon} <b>{html.escape(name)}</b>: {html.escape(', '.join(detail))}")
        for message in bucket["errors"][:3]:
            lines.append(f"    • <i>{html.escape(str(message)[:180])}</i>")

    if disk_lines:
        lines.append("")
        lines.append("<b>On disk</b>")
        lines.extend(html.escape(line) for line in disk_lines)

    return "\n".join(lines)


@job(
    "daily_summary",
    schedule="55 23 * * *",
    description="Send the day's collection summary to Telegram",
    alert_on_failure=False,  # a failed digest must not itself page you
)
def collect(logger, record, settings, date=None):
    target = date or today()
    records = metrics.read_day(target)

    if not records:
        logger.warning("no run records for %s", target.isoformat())
        notify.digest(
            f"British Shorthair - {target.isoformat()}",
            f"{STATUS_ICON['failed']} No jobs recorded a run today. Collection may be down.",
            logger=logger,
        )
        record.items_empty = 1
        return

    summary = _aggregate(records)

    # Report the largest feeds by name rather than one opaque total, so a feed that
    # suddenly balloons is visible in the digest.
    sizes = sorted(
        ((p.name.split("=", 1)[1], storage.dir_size(p))
         for p in settings.data_dir.glob("feed=*") if p.is_dir()),
        key=lambda item: item[1],
        reverse=True,
    )
    disk_lines = [f"{name}: {storage.human_bytes(size)}" for name, size in sizes[:6]]
    if sizes:
        disk_lines.append(f"total: {storage.human_bytes(sum(s for _, s in sizes))}")

    message = build_message(target, summary, disk_lines)
    logger.info("digest for %s covering %d runs", target.isoformat(), len(records))

    if not notify.digest(f"British Shorthair - {target.isoformat()}", message, logger=logger):
        logger.warning("digest not delivered (Telegram unconfigured or send failed)")

    record.items_ok = len(records)
    record.notes["jobs"] = sorted(summary)
