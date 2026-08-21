"""Daily Telegram digest.

The counterpart to the immediate alerts in :mod:`bsh.notify`: those say something
broke *now*, this says whether the day as a whole was sound.

Written to be read on a phone, in seconds. Two rules shape the format:

* **A healthy day is short.** Five lines, no detail. Detail appears only when there is
  something to act on, so length itself signals whether to look closer.
* **Lead with the verdict.** The first line answers "do I need to do anything?"; the
  numbers below it explain why.

Coverage is the metric that matters and the one a run count cannot give: 1,438 runs
all succeeding still hides two lost hours if each run collected nothing. That comes
from the archive manifests, which already compute expected-vs-actual, read back via
``_archive_index.jsonl`` so nothing has to be decompressed.
"""

import html
import json
from collections import defaultdict
from datetime import timedelta

from .. import metrics, notify, storage
from ..logging_setup import today
from ..registry import job

OK, WARN, BAD = "✅", "⚠️", "❌"
INDEX_NAME = "_archive_index.jsonl"


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
        for key, field in (("items_ok", "items_ok"), ("items_failed", "items_failed"),
                           ("items_empty", "items_empty"), ("retries", "retries"),
                           ("bytes", "bytes_written")):
            bucket[key] += entry.get(field, 0)
        for message in entry.get("errors", []):
            if message not in bucket["errors"] and len(bucket["errors"]) < 3:
                bucket["errors"].append(message)
    return summary


def read_coverage(settings, date):
    """Yesterday's per-feed coverage, from the archive index. Newest entry per feed."""
    path = settings.data_dir / INDEX_NAME
    if not path.is_file():
        return []
    wanted = date.isoformat()
    found = {}
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("date") == wanted:
                found[entry.get("feed")] = entry
    return [found[k] for k in sorted(found)]


def _rows(pairs, width=None):
    """Left-aligned label/value lines inside a monospace block."""
    if not pairs:
        return []
    width = width or max(len(label) for label, _ in pairs)
    return [f"{label.ljust(width)}  {value}" for label, value in pairs]


def build_message(date, summary, coverage, disk, archive):
    failed = sum(b["failed"] + b["crashed"] for b in summary.values())
    partial = sum(b["partial"] for b in summary.values())
    collected = sum(b["bytes"] for b in summary.values())

    broken = sorted(n for n, b in summary.items() if b["failed"] or b["crashed"])
    degraded = sorted(n for n, b in summary.items() if b["partial"] and n not in broken)

    lines = [f"<b>British Shorthair</b> · {date.strftime('%a %d %b')}", ""]

    # Verdict first: one line that decides whether the rest needs reading.
    if failed:
        lines.append(f"{BAD} <b>{failed} failed run(s)</b> · {', '.join(broken)}")
    elif partial:
        lines.append(f"{WARN} <b>{partial} partial run(s)</b> · {', '.join(degraded)}")
    else:
        lines.append(f"{OK} <b>All healthy</b>")

    facts = [storage.human_bytes(collected) + " collected"]
    if disk:
        # Low disk is the one number that turns a healthy-looking day into an urgent
        # one, so it is marked here rather than left to be inferred from a percentage.
        mark = "" if disk["pct"] > 15 else (f" {BAD} LOW" if disk["pct"] <= 5 else f" {WARN} low")
        facts.append(f"{storage.human_bytes(disk['free'])} free ({disk['pct']:.0f}%){mark}")
    lines.append(" · ".join(html.escape(f) if BAD not in f and WARN not in f else f
                            for f in facts))

    # Problems, with the first error verbatim - a message is more use than a count.
    if broken or degraded:
        block = []
        for name in broken + degraded:
            bucket = summary[name]
            count = bucket["failed"] + bucket["crashed"] or bucket["partial"]
            block.append(f"{name}  {count} of {bucket['runs']} runs")
            for message in bucket["errors"][:2]:
                block.append(f"  {str(message)[:110]}")
        lines += ["", "<b>Problems</b>",
                  "<pre>" + html.escape("\n".join(block)) + "</pre>"]

    if coverage:
        pairs = []
        for entry in coverage:
            feed = entry.get("feed", "?")
            pct = entry.get("coverage_pct")
            if pct is None:
                value = f"{entry.get('files', 0)} files"
            else:
                value = (f"{pct:5.1f}%  {entry.get('files', 0)}"
                         f"/{entry.get('expected_files', 0)}")
            gap = entry.get("largest_gap_seconds") or 0
            if gap >= 300:
                value += f"   gap {gap // 60}m"
            pairs.append((feed, value))
        lines += ["", f"<b>Coverage</b> · {(date - timedelta(days=1)).strftime('%d %b')}",
                  "<pre>" + html.escape("\n".join(_rows(pairs))) + "</pre>"]

    if archive:
        raw, packed, count = archive
        ratio = (raw / packed) if packed else 0
        lines += ["", "<b>Archive</b>",
                  html.escape(f"{count} feed(s) · {storage.human_bytes(raw)} "
                              f"→ {storage.human_bytes(packed)} ({ratio:.0f}×)")]

    return "\n".join(lines)


def _archive_totals(coverage):
    """Raw and compressed totals across yesterday's archives."""
    if not coverage:
        return None
    raw = sum(e.get("raw_bytes", 0) for e in coverage)
    packed = sum(e.get("archive_bytes", 0) for e in coverage)
    return (raw, packed, len(coverage)) if raw else None


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
            "British Shorthair",
            f"{BAD} <b>No jobs ran today</b>\nCollection may be down.",
            logger=logger,
        )
        record.items_empty = 1
        return

    summary = _aggregate(records)
    coverage = read_coverage(settings, target - timedelta(days=1))

    disk = None
    try:
        free, total, pct = storage.disk_free(settings.data_dir)
        disk = {"free": free, "total": total, "pct": pct}
    except OSError as exc:
        logger.warning("could not read disk usage: %s", exc)

    message = build_message(target, summary, coverage, disk, _archive_totals(coverage))
    logger.info("digest for %s: %d runs, %d feeds with coverage",
                target.isoformat(), len(records), len(coverage))

    if not notify.digest("British Shorthair", message, logger=logger):
        logger.warning("digest not delivered (Telegram unconfigured or send failed)")

    record.items_ok = len(records)
    record.notes["jobs"] = sorted(summary)
