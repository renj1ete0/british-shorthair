"""Job execution wrapper.

Every job runs through :func:`run`, which gives it a per-day logger, a metrics record,
an optional single-instance lock, and failure alerting. Jobs themselves therefore
contain only collection logic — they do not set up logging, catch their own crashes,
or decide when to message Telegram.
"""

import os
import sys

from . import metrics, notify
from .logging_setup import setup
from .registry import get


class LockBusy(Exception):
    """Another instance of this job is still running."""


class JobLock:
    """Single-instance lock.

    Uses ``flock`` where available (Linux, i.e. the container) and falls back to an
    exclusive-create pidfile elsewhere so the jobs remain runnable on Windows for
    development.
    """

    def __init__(self, name, state_dir):
        state_dir.mkdir(parents=True, exist_ok=True)
        self.path = state_dir / f"{name}.lock"
        self._handle = None

    def __enter__(self):
        try:
            import fcntl

            self._handle = open(self.path, "w")
            try:
                fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                self._handle.close()
                self._handle = None
                raise LockBusy(str(exc)) from exc
            self._handle.write(str(os.getpid()))
            self._handle.flush()
        except ImportError:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError as exc:
                raise LockBusy("lock file present") from exc
            self._handle = os.fdopen(fd, "w")
            self._handle.write(str(os.getpid()))
            self._handle.flush()
        return self

    def __exit__(self, *exc_info):
        if self._handle is not None:
            self._handle.close()
            self._handle = None
        if os.name != "posix":
            # flock releases on close; the fallback pidfile must be removed by hand.
            try:
                self.path.unlink(missing_ok=True)
            except OSError:
                pass
        return False


def run(name, **kwargs):
    """Run a registered job. Returns a process exit code."""
    from .config import get_settings

    definition = get(name)
    logger = setup(name)
    settings = get_settings()

    lock = None
    if definition.singleton:
        try:
            lock = JobLock(name, settings.state_dir).__enter__()
        except LockBusy:
            # Expected under load rather than exceptional: the previous tick is still
            # going, so skipping keeps the cadence honest instead of stacking runs.
            logger.warning("skipped: previous run still in progress")
            return 0

    try:
        with metrics.track(name) as record:
            logger.info("started")
            try:
                definition.fn(logger=logger, record=record, settings=settings, **kwargs)
            except Exception as exc:
                record.status = "failed"
                record.add_error(f"{type(exc).__name__}: {exc}")
                logger.exception("failed: %s", exc)
                if definition.alert_on_failure:
                    notify.alert(
                        f"{name} failed",
                        f"{type(exc).__name__}: {exc}",
                        key=f"{name}:{type(exc).__name__}",
                        logger=logger,
                    )
                return 1

            if record.status == "partial" and definition.alert_on_failure:
                notify.alert(
                    f"{name} partially failed",
                    f"{record.items_failed} of "
                    f"{record.items_ok + record.items_failed} items failed. "
                    f"First errors: {'; '.join(record.errors[:3])}",
                    key=f"{name}:partial",
                    logger=logger,
                )
            logger.info(
                "finished status=%s ok=%d failed=%d empty=%d retries=%d",
                record.status, record.items_ok, record.items_failed,
                record.items_empty, record.retries,
            )
            return 0
    finally:
        if lock is not None:
            lock.__exit__(*sys.exc_info())
