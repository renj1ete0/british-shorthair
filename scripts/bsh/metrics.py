"""Per-run metrics.

Each job run appends one JSON line to ``<log_dir>/<date>/runs.jsonl``. The daily
summary job reads that file to build the Telegram digest, so this is the contract
between "a job ran" and "you got told about it".
"""

import json
import time
from contextlib import contextmanager
from datetime import timedelta

from .config import get_settings
from .logging_setup import now, today


class RunRecord:
    """Mutable tally for one job run."""

    def __init__(self, job):
        self.job = job
        self.started = now()
        self.status = "ok"
        self.items_ok = 0
        self.items_failed = 0
        self.items_empty = 0
        self.retries = 0
        self.bytes_written = 0
        self.errors = []
        self.notes = {}

    def add_error(self, message):
        text = str(message)
        # Keep the file small when an outage produces thousands of identical errors.
        if len(self.errors) < 25 and text not in self.errors:
            self.errors.append(text)

    def to_dict(self, ended, duration):
        return {
            "job": self.job,
            "started": self.started.isoformat(),
            "ended": ended.isoformat(),
            "duration_s": round(duration, 3),
            "status": self.status,
            "items_ok": self.items_ok,
            "items_failed": self.items_failed,
            "items_empty": self.items_empty,
            "retries": self.retries,
            "bytes_written": self.bytes_written,
            "errors": self.errors,
            **({"notes": self.notes} if self.notes else {}),
        }


def _runs_path():
    directory = get_settings().log_dir / f"date={today().isoformat()}"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / "runs.jsonl"


def append(record, ended, duration):
    try:
        with open(_runs_path(), "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record.to_dict(ended, duration), ensure_ascii=False) + "\n")
    except OSError:
        # A metrics write must never be the reason a successful collection is
        # reported as failed.
        pass


def read_window(date, days_after=2):
    """Run records for ``date`` plus the following days.

    A run record is filed under the day the job *ran*, which is not the day it
    collected: the nightly jobs run after midnight for the previous date. Anything
    correlating data with its collection record therefore has to look forward a little
    and match on ``notes.data_date``.
    """
    records = []
    for offset in range(days_after + 1):
        records.extend(read_day(date + timedelta(days=offset)))
    return records


def read_day(date):
    """Return all run records for a date, skipping any partially written line."""
    path = get_settings().log_dir / f"date={date.isoformat()}" / "runs.jsonl"
    if not path.is_file():
        return []
    records = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


@contextmanager
def track(job):
    """Wrap a job run so its outcome is always recorded, success or crash."""
    record = RunRecord(job)
    start = time.monotonic()
    try:
        yield record
    except BaseException as exc:
        record.status = "crashed"
        record.add_error(f"{type(exc).__name__}: {exc}")
        append(record, now(), time.monotonic() - start)
        raise
    else:
        if record.status == "ok" and record.items_failed:
            record.status = "partial"
        append(record, now(), time.monotonic() - start)
