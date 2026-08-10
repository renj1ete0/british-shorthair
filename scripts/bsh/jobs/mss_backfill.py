"""On-demand MSS weather backfill.

Replays past dates against the data.gov.sg environment APIs to fill gaps left by
downtime. Not scheduled — backfills are triggered deliberately:

    python run_job.py mss_backfill --days 120
    python run_job.py mss_backfill --from 2026-05-01 --days 30

Each date is validated the same way the nightly job validates, so a backfill cannot
quietly write the wrong day's readings into a gap.
"""

from datetime import date as date_cls
from datetime import timedelta

from ..http import Fetcher
from ..logging_setup import today
from ..registry import job
from .mss import collect_date


@job(
    "mss_backfill",
    schedule=None,  # on demand only
    description="Backfill past MSS weather dates (--from YYYY-MM-DD --days N)",
)
def collect(logger, record, settings, start=None, days=120):
    days = int(days)
    if days < 1:
        raise ValueError("--days must be at least 1")

    if start is None:
        # Default offset of two days: the most recent full day is yesterday, and
        # skipping one more avoids racing the nightly job for the same date.
        offset = today() - timedelta(days=2)
    elif isinstance(start, str):
        offset = date_cls.fromisoformat(start)
    else:
        offset = start

    dates = [offset - timedelta(days=i) for i in range(days)]
    logger.info(
        "backfilling %d dates from %s back to %s",
        len(dates), dates[0].isoformat(), dates[-1].isoformat(),
    )

    failed_dates = []
    with Fetcher(logger=logger, record=record) as fetcher:
        for index, target in enumerate(dates, start=1):
            failures = collect_date(fetcher, target, logger, record, settings)
            if failures:
                failed_dates.append(target.isoformat())
            if index % 10 == 0:
                logger.info("progress: %d/%d dates", index, len(dates))

    record.notes["dates_requested"] = len(dates)
    record.notes["dates_with_failures"] = failed_dates[:20]
    logger.info(
        "backfill complete: %d dates, %d with failures", len(dates), len(failed_dates)
    )
