"""Self-describing archive manifests.

A cold archive is opened long after anyone remembers what happened the day it was
written. Restoring one and seeing 4,180 files answers nothing on its own: was the feed
down, was it a quiet night, did the collector crash, is the data trustworthy?

So every archive carries a ``_MANIFEST.json`` at its root, written before compression.
It answers four questions without reference to anything outside the archive:

1. **What is this?** Feed, date, collector version, timezone.
2. **Is it complete?** Expected vs actual, and *where* the gaps are.
3. **Did anything go wrong?** The day's run records for this feed, including errors.
4. **Did the bytes survive?** SHA-256 per file.

Gaps are enumerated, not merely counted. "140 snapshots missing" could be a single
47-minute outage or 140 scattered blips, and those mean very different things for
analysis. The manifest reports the intervals.

The underscore prefix keeps it sorting first and marks it as metadata rather than data.
"""

import hashlib
import json
import re
from datetime import datetime, timedelta

from . import __version__
from .config import SGT
from .registry import interval_seconds  # noqa: F401  (re-exported for callers)

MANIFEST_NAME = "_MANIFEST.json"
MANIFEST_VERSION = 1

# Filenames a sub-daily feed writes: HHMMSS.<ext>
_TIME_NAME = re.compile(r"^(\d{2})(\d{2})(\d{2})\.")


def _file_times(paths, date):
    """Parse HHMMSS filenames into datetimes, ignoring files that are not time-named."""
    stamps = []
    for path in paths:
        match = _TIME_NAME.match(path.name)
        if match:
            hh, mm, ss = (int(g) for g in match.groups())
            if hh < 24 and mm < 60 and ss < 60:
                stamps.append(datetime(date.year, date.month, date.day, hh, mm, ss, tzinfo=SGT))
    return sorted(stamps)


def find_gaps(stamps, interval, tolerance=2.5):
    """Intervals where consecutive files are further apart than the cadence allows.

    ``tolerance`` guards against flagging normal jitter: a 20s feed whose snapshots
    land 24s apart is healthy, one with a 90s hole is not.
    """
    gaps = []
    if not stamps or not interval:
        return gaps
    limit = timedelta(seconds=interval * tolerance)
    for earlier, later in zip(stamps, stamps[1:]):
        delta = later - earlier
        if delta > limit:
            gaps.append({
                "after": earlier.strftime("%H:%M:%S"),
                "before": later.strftime("%H:%M:%S"),
                "seconds": int(delta.total_seconds()),
                "missing_estimate": max(0, int(delta.total_seconds() // interval) - 1),
            })
    return gaps


def _sha256(path, chunk=1 << 20):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(chunk), b""):
            digest.update(block)
    return digest.hexdigest()


def _size_anomalies(entries):
    """Files far smaller than the day's median - usually truncated or partial writes.

    Only meaningful when a partition holds many comparable files, so it is skipped for
    small partitions where a size spread is expected rather than suspicious.
    """
    sizes = sorted(e["bytes"] for e in entries)
    if len(sizes) < 20:
        return []
    median = sizes[len(sizes) // 2]
    if median == 0:
        return []
    floor = median * 0.25
    return [
        {"name": e["name"], "bytes": e["bytes"], "median_bytes": median}
        for e in entries if 0 < e["bytes"] < floor
    ][:25]


def summarise_runs(records, feed, date, month=None):
    """Condense the run records for one feed and one collected period.

    Matching accounts for the fact that a run record is filed under the day the job
    *ran*, which is rarely the period it collected:

    * monthly datasets match on ``notes.months`` containing this partition's month;
    * nightly jobs match on ``notes.data_date``, since they run after midnight and are
      filed under the following day;
    * everything else is assumed to have collected on the day it ran, which holds for
      the real-time feeds.
    """
    wanted = date.isoformat()
    mine = []
    for record in records:
        if record.get("job") != feed:
            continue
        notes = record.get("notes") or {}
        if month is not None:
            if month in (notes.get("months") or []):
                mine.append(record)
            continue
        data_date = notes.get("data_date")
        if data_date is not None:
            if data_date == wanted:
                mine.append(record)
        elif record.get("started", "").startswith(wanted):
            mine.append(record)
    summary = {
        "records_found": len(mine),
        "ok": 0, "partial": 0, "failed": 0, "crashed": 0,
        "retries": 0, "items_ok": 0, "items_failed": 0, "items_empty": 0,
        "errors": [],
    }
    if not mine:
        if feed == "logs":
            # The log archive is not produced by a job of its own, so there is nothing
            # to correlate and nothing to warn about.
            return summary
        # Absence of run records is itself a finding: the data exists but the
        # collection log for it does not, so completeness cannot be corroborated.
        summary["warning"] = "no run records found for this feed and date"
        return summary

    for record in mine:
        status = record.get("status", "ok")
        if status in summary:
            summary[status] += 1
        for key in ("retries", "items_ok", "items_failed", "items_empty"):
            summary[key] += record.get(key, 0)
        for message in record.get("errors", []):
            if message not in summary["errors"] and len(summary["errors"]) < 50:
                summary["errors"].append(message)
    return summary


def build(feed, date, directory, cadence=None, run_records=(), generated_at=None,
          job_name=None, month=None):
    """Assemble the manifest for one partition. Returns a plain dict.

    ``job_name`` is the job that produced the feed, which is not always the feed name -
    one ``mss`` run writes eleven ``weather_*`` feeds. Run records are matched on it.
    """
    job_name = job_name or feed
    files = sorted(
        p for p in directory.rglob("*")
        if p.is_file() and p.name != MANIFEST_NAME
    )

    entries = []
    for path in files:
        entries.append({
            "name": str(path.relative_to(directory)).replace("\\", "/"),
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
        })

    interval = cadence
    stamps = _file_times(files, date)
    gaps = find_gaps(stamps, interval)

    completeness = {
        "files": len(entries),
        "total_bytes": sum(e["bytes"] for e in entries),
    }
    if interval:
        expected = 86400 // interval
        completeness.update({
            "expected_files": expected,
            "expected_basis": f"cadence {interval}s",
            "coverage_pct": round(100.0 * len(entries) / expected, 2) if expected else None,
            "first": stamps[0].strftime("%H:%M:%S") if stamps else None,
            "last": stamps[-1].strftime("%H:%M:%S") if stamps else None,
            "gaps": gaps,
            "gap_count": len(gaps),
            "largest_gap_seconds": max((g["seconds"] for g in gaps), default=0),
        })
    else:
        completeness["expected_basis"] = "no declared cadence"

    quality = {
        "zero_byte_files": [e["name"] for e in entries if e["bytes"] == 0][:25],
        "undersized_files": _size_anomalies(entries),
    }

    runs = summarise_runs(list(run_records), job_name, date, month=month)
    runs["job"] = job_name

    warnings = []
    if quality["zero_byte_files"]:
        warnings.append(f"{len(quality['zero_byte_files'])} zero-byte file(s)")
    if quality["undersized_files"]:
        warnings.append(f"{len(quality['undersized_files'])} file(s) far below median size")
    if gaps:
        warnings.append(f"{len(gaps)} collection gap(s), largest "
                        f"{completeness.get('largest_gap_seconds', 0)}s")
    if runs.get("failed") or runs.get("crashed"):
        warnings.append(f"{runs.get('failed', 0) + runs.get('crashed', 0)} failed run(s)")
    if runs.get("warning"):
        warnings.append(runs["warning"])

    return {
        "manifest_version": MANIFEST_VERSION,
        "feed": feed,
        **({"month": month} if month else {}),
        "date": date.isoformat(),
        "collector_version": __version__,
        "timezone": "Asia/Singapore",
        "generated_at": (generated_at or datetime.now(SGT)).isoformat(),
        # A single field to check before trusting the contents.
        "status": "warnings" if warnings else "clean",
        "warnings": warnings,
        "completeness": completeness,
        "runs": runs,
        "quality": quality,
        "integrity": {"algorithm": "sha256", "files": entries},
    }


def write(directory, payload):
    """Write the manifest into the partition so it is captured by compression."""
    path = directory / MANIFEST_NAME
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=1)
    return path


def index_entry(payload, archive_path, archive_bytes):
    """The one-line summary appended to the archive index.

    Lets "which days have gaps?" be answered without decompressing anything, which is
    the difference between a minute and a week once there is a year of cold storage.
    """
    completeness = payload["completeness"]
    return {
        "feed": payload["feed"],
        "date": payload["date"],
        "archive": archive_path,
        "archive_bytes": archive_bytes,
        "status": payload["status"],
        "warnings": payload["warnings"],
        "files": completeness["files"],
        "expected_files": completeness.get("expected_files"),
        "coverage_pct": completeness.get("coverage_pct"),
        "gap_count": completeness.get("gap_count", 0),
        "largest_gap_seconds": completeness.get("largest_gap_seconds", 0),
        "raw_bytes": completeness["total_bytes"],
        "failed_runs": payload["runs"].get("failed", 0) + payload["runs"].get("crashed", 0),
        "generated_at": payload["generated_at"],
    }
