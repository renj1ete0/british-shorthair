"""Per-day logging.

Logs are written under ``<log_dir>/date=<YYYY-MM-DD>/`` in SGT:

    date=2026-08-09/bus_arrival.log   human-readable, one file per job
    date=2026-08-09/all.log           every job interleaved, for "what happened at 03:14"
    date=2026-08-09/events.jsonl      structured events, machine-read by the daily summary

The ``date=`` prefix matches the partition convention used for collected data, so
``runs.jsonl`` can be queried across days with the date recovered as a column rather
than parsed out of the path.

Cron spawns a fresh process per tick, so the date is normally fixed for the life of
the process. Long-running jobs (backfills) can cross midnight though, so the handler
re-resolves the date on every record and reopens into the new day's directory.
"""

import json
import logging
import sys
from datetime import datetime

from .config import SGT, get_settings


def today():
    """Current date in SGT. All foldering and date maths uses this, never the host TZ."""
    return datetime.now(SGT).date()


def now():
    return datetime.now(SGT)


class DailyDirectoryHandler(logging.Handler):
    """Writes each record into the current SGT day's directory.

    Reopens automatically when the date rolls over, so a job running across midnight
    lands its later records in the new day rather than appending to yesterday.
    """

    def __init__(self, filename, formatter=None):
        super().__init__()
        self._filename = filename
        self._date = None
        self._stream = None
        if formatter:
            self.setFormatter(formatter)

    def _target(self):
        current = today()
        if current != self._date or self._stream is None:
            self.close_stream()
            directory = get_settings().log_dir / f"date={current.isoformat()}"
            directory.mkdir(parents=True, exist_ok=True)
            self._stream = open(directory / self._filename, "a", encoding="utf-8")
            self._date = current
        return self._stream

    def emit(self, record):
        try:
            stream = self._target()
            stream.write(self.format(record) + "\n")
            stream.flush()
        except Exception:  # never let logging break a collection run
            self.handleError(record)

    def close_stream(self):
        if self._stream is not None:
            try:
                self._stream.close()
            finally:
                self._stream = None

    def close(self):
        self.close_stream()
        super().close()


class JsonlFormatter(logging.Formatter):
    """One JSON object per line, so the summary job can aggregate without parsing prose."""

    def __init__(self, job):
        super().__init__()
        self.job = job

    def format(self, record):
        payload = {
            "ts": datetime.fromtimestamp(record.created, SGT).isoformat(),
            "level": record.levelname,
            "job": self.job,
            "msg": record.getMessage(),
        }
        extra = getattr(record, "fields", None)
        if isinstance(extra, dict):
            payload["fields"] = extra
        if record.exc_info:
            payload["error"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup(job):
    """Configure and return the logger for a job run.

    Safe to call twice in one process (the backfill wrapper does); handlers are
    replaced rather than stacked, so lines are never duplicated.
    """
    logger = logging.getLogger("bsh")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    human = logging.Formatter(
        fmt="%(asctime)s %(levelname)-7s [" + job + "] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    human.converter = lambda timestamp: datetime.fromtimestamp(timestamp, SGT).timetuple()

    # stdout so `docker logs` and supercronic show job output live
    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(human)
    logger.addHandler(stream)

    logger.addHandler(DailyDirectoryHandler(f"{job}.log", human))
    logger.addHandler(DailyDirectoryHandler("all.log", human))

    jsonl = DailyDirectoryHandler("events.jsonl", JsonlFormatter(job))
    jsonl.setLevel(logging.INFO)
    logger.addHandler(jsonl)

    return logger


def log_fields(logger, level, msg, **fields):
    """Log a message carrying structured fields for the JSONL sink."""
    logger.log(level, msg, extra={"fields": fields})
