"""Monthly passenger volume archives.

LTA publishes the previous month's passenger volume by the 10th, so this runs on the
16th. The API returns a pre-signed S3 link rather than the data itself, and that link
**expires 15 minutes after issue** — so the download follows immediately, and on
failure the whole request/download pair is retried to obtain a fresh link rather than
retrying the stale one.

The month in the link path is checked against the month requested. That check is what
stops a stale or wrong-month file being archived under a correct-looking filename;
the old code wrote whatever came back, which is how ``PV_OD_BUSSTOPS_None.zip`` ended
up in the archive.
"""

from datetime import timedelta

from .. import endpoints, storage
from ..http import Fetcher, FetchError, RetryPolicy
from ..logging_setup import today
from ..registry import job
from ..validation import validate_pv_link

# LTA serves passenger volume files "up to last three months", so a month missed
# because of a failed run can be picked up by a later one. Without this the job would
# be the only collector with no recovery at all: it runs once a month for the previous
# month, so a single bad night would cost a month of data permanently.
HISTORY_MONTHS = 3


def previous_month(reference=None):
    """Return the previous calendar month as ``YYYYMM``."""
    reference = reference or today()
    last_day_of_prev = reference.replace(day=1) - timedelta(days=1)
    return last_day_of_prev.strftime("%Y%m")


def recent_months(count=HISTORY_MONTHS, reference=None):
    """The last ``count`` complete months, newest first, as ``YYYYMM``."""
    cursor = (reference or today()).replace(day=1)
    months = []
    for _ in range(count):
        cursor = cursor - timedelta(days=1)      # step into the previous month
        months.append(cursor.strftime("%Y%m"))
        cursor = cursor.replace(day=1)
    return months


def _fetch_one(fetcher, name, url, yyyymm, settings, logger, record):
    """Request a link and download it. Retried as a unit because links expire."""
    policy = RetryPolicy(
        attempts=settings.retry_attempts,
        base_delay=settings.retry_base_delay,
        max_delay=settings.retry_max_delay,
        timeout=settings.request_timeout,
    )
    # Monthly dataset, so it partitions by month rather than date.
    destination = storage.feed_path(
        settings, "passenger_volume", month=yyyymm
    ) / f"{name}.zip"

    last_error = None
    for attempt in range(1, policy.attempts + 1):
        try:
            link = fetcher.get_json(
                url,
                params={"Date": yyyymm},
                headers={"AccountKey": settings.lta_api_keys[0], "accept": "application/json"},
                validator=lambda payload, n=name: validate_pv_link(payload, yyyymm, n),
                policy=RetryPolicy(attempts=2, base_delay=policy.base_delay,
                                   max_delay=policy.max_delay, timeout=policy.timeout),
                label=f"{name}:link:{yyyymm}",
            )
            # Fresh link in hand; download now, well inside the 15-minute expiry.
            written = fetcher.download(
                link,
                destination,
                policy=RetryPolicy(attempts=2, base_delay=policy.base_delay,
                                   max_delay=policy.max_delay, timeout=policy.timeout),
                label=f"{name}_{yyyymm}.zip",
            )
            return written
        except FetchError as exc:
            last_error = exc
            logger.warning("%s attempt %d/%d failed: %s", name, attempt, policy.attempts, exc)

    raise FetchError(f"{name}: {last_error}")


@job(
    "datamall_pv",
    schedule="0 2 16 * *",
    description="Monthly passenger volume archives for bus stops and train stations",
)
def collect(logger, record, settings, month=None):
    if not settings.lta_api_keys:
        raise RuntimeError("LTA_API_KEYS is empty; cannot call the DataMall API")

    if month:
        months = [str(month)]
    else:
        # Newest first, so the current target is collected before older gaps.
        months = recent_months()

    for yyyymm in months:
        if len(yyyymm) != 6 or not yyyymm.isdigit():
            raise ValueError(f"month must be YYYYMM, got {yyyymm!r}")

    record.notes["months"] = months

    with Fetcher(logger=logger, record=record) as fetcher:
        for index, yyyymm in enumerate(months):
            directory = storage.feed_path(settings, "passenger_volume", month=yyyymm)
            missing = {n: u for n, u in endpoints.PV_DATASETS.items()
                       if not (directory / f"{n}.zip").exists()}
            if not missing:
                continue
            if index:
                logger.info("gap-filling %s: %d dataset(s) missing", yyyymm, len(missing))
            else:
                logger.info("collecting passenger volume for %s", yyyymm)

            for name, url in missing.items():
                try:
                    written = _fetch_one(fetcher, name, url, yyyymm, settings, logger, record)
                except FetchError as exc:
                    record.items_failed += 1
                    record.add_error(str(exc))
                    logger.error("%s %s failed: %s", name, yyyymm, exc)
                    continue

                record.items_ok += 1
                record.bytes_written += written
                logger.info("%s/%s.zip: %s", yyyymm, name, storage.human_bytes(written))

    if record.items_ok == 0 and record.items_failed == 0:
        record.items_empty = 1
        logger.info("all %d recent month(s) already collected", len(months))
