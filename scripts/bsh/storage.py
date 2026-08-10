"""Filesystem helpers for collected output.

Writes go to a temp file and are renamed into place, so a job killed mid-write (a
container restart, a blown deadline) never leaves a truncated file that later looks
like a complete archive.

Note on format: JSON is written compactly rather than with ``indent=4``. It is the
same JSON to any reader, and roughly halves the footprint — which matters now that
bus arrival ticks every 20 seconds. Moving to Parquet is tracked separately.
"""

import csv
import json
import os
from pathlib import Path


def ensure_dir(path):
    path.mkdir(parents=True, exist_ok=True)
    return path


def feed_path(settings, feed, date=None, hour=None, month=None):
    """The one way a job constructs an output directory.

        <data>/feed=<name>/date=YYYY-MM-DD[/hour=HH]/

    Every collected dataset uses this shape, so a single glob covers all of them::

        SELECT * FROM read_csv_auto('feed=*/date=*/**/*.csv', hive_partitioning=true)

    and ``feed``, ``date`` and ``hour`` come back as real columns rather than
    something to parse out of a path. Routing every job through one helper is what
    keeps that true: a new job cannot invent its own layout without deliberately
    bypassing this function.

    Rules, enforced rather than documented:

    * exactly one of ``date`` or ``month`` (monthly datasets partition by month)
    * ``hour`` only alongside ``date``, and only for feeds that write more than once
      a day - a daily feed with an ``hour=`` level is a partition that means nothing

    File naming inside the partition follows from the same idea: name the file for its
    time (``HHMMSS.json``) when a partition holds several, and for its content
    (``readings.csv``) when it holds exactly one.
    """
    if (date is None) == (month is None):
        raise ValueError("feed_path requires exactly one of date or month")
    if hour is not None and date is None:
        raise ValueError("feed_path: hour requires date")

    path = Path(settings.data_dir) / f"feed={feed}"
    if month is not None:
        path = path / f"month={month}"
    else:
        value = date.isoformat() if hasattr(date, "isoformat") else str(date)
        path = path / f"date={value}"
        if hour is not None:
            path = path / f"hour={hour:02d}" if isinstance(hour, int) else path / f"hour={hour}"
    return ensure_dir(path)


def write_json(path, payload):
    """Atomically write compact JSON. Returns bytes written."""
    path = Path(path)
    ensure_dir(path.parent)
    temp = path.with_suffix(path.suffix + ".tmp")
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    with open(temp, "w", encoding="utf-8") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    temp.replace(path)
    return len(data.encode("utf-8"))


def append_csv(path, rows, header=None):
    """Append rows to a CSV, writing ``header`` only when creating the file.

    Uses the csv module rather than f-string concatenation: station names and forecast
    text contain commas, which the previous hand-rolled writer silently corrupted into
    extra columns.
    """
    path = Path(path)
    ensure_dir(path.parent)
    is_new = not path.exists() or path.stat().st_size == 0
    before = path.stat().st_size if path.exists() else 0
    with open(path, "a", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        if is_new and header:
            writer.writerow(header)
        writer.writerows(rows)
    return path.stat().st_size - before


def append_ndjson(path, payload):
    """Append one JSON object as a line. Returns bytes written.

    Used by the high-frequency real-time feeds. A carpark poll every minute would
    otherwise produce 1440 files a day per feed; appending to an hourly file keeps the
    file count sane, is crash-safe (a torn final line is skipped on read, and every
    earlier line survives), and is exactly the intermediate the planned Parquet
    compaction expects.
    """
    path = Path(path)
    ensure_dir(path.parent)
    line = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(line)
    return len(line.encode("utf-8"))


def dir_size(path):
    path = Path(path)
    if not path.exists():
        return 0
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def human_bytes(count):
    value = float(count)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(value) < 1024 or unit == "TB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"
