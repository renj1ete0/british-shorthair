"""Real-time LTA feeds: carpark, train alerts, station crowd density, EV chargers.

These differ fundamentally from the NEA weather datasets. None accepts a date
parameter, so there is no history to fall back on — a poll that is missed is data
that no longer exists. That drives two decisions:

* Each feed is polled at (or slightly under) its published update frequency.
* Failures retry with backoff inside the poll rather than waiting for a nightly
  gap-fill, because there will be nothing to gap-fill from.

Snapshots are appended to an hourly NDJSON file per feed rather than written as one
file per poll: at a one-minute cadence the latter would create 1440 files a day per
feed, and the hourly file is also the natural input to the planned Parquet compaction.

    export/carpark/date=2026-08-09/hour=14.ndjson
"""

from .. import endpoints, storage
from ..http import Deadline, Fetcher, FetchError, RetryPolicy
from ..logging_setup import now, today
from ..registry import job

# Fraction of a feed's refresh interval a run may spend retrying. These feeds keep no
# history, so a failed request is worth retrying right up to the point the data would
# refresh anyway - after that the attempt is pointless, because the next scheduled run
# will fetch the newer state instead.
WINDOW_FRACTION = 0.85


def _window(seconds):
    """Retry budget for a feed refreshing every ``seconds``.

    Attempts are set high deliberately: the deadline is meant to be what stops the
    retrying, not an arbitrary attempt count. Giving up after four tries and waiting
    for the next tick wastes most of the window - on a five-minute feed that is five
    minutes lost to a blip lasting seconds.
    """
    budget = seconds * WINDOW_FRACTION
    return (
        RetryPolicy(attempts=20, base_delay=1.0, max_delay=min(30.0, budget / 3),
                    timeout=min(30.0, budget)),
        Deadline(budget),
    )


def _hourly_path(settings, feed):
    stamp = now()
    directory = storage.feed_path(settings, feed, date=today(), hour=stamp.strftime("%H"))
    return directory / "snapshots.ndjson"


def _snapshot(settings, feed, payload, **extra):
    """Append one timestamped observation to the current hour's file."""
    return storage.append_ndjson(
        _hourly_path(settings, feed),
        {"observed_at": now().isoformat(), **extra, "data": payload},
    )


def _headers(settings):
    if not settings.lta_api_keys:
        raise RuntimeError("LTA_API_KEYS is empty; cannot call the DataMall API")
    return {"AccountKey": settings.lta_api_keys[0], "accept": "application/json"}


def _download_linked(fetcher, settings, feed, url, suffix, logger, record, hourly=True,
                     empty_below=0, policy=None, deadline=None):
    """Fetch a short-lived download link and immediately retrieve the file.

    EVCBatch and the GTFS feeds return a pre-signed link valid for 15 minutes, so the
    download follows straight away and the pair is retried together on failure.
    """
    payload = fetcher.get_json(url, headers=_headers(settings), label=feed,
                               policy=policy, deadline=deadline)
    entry = ((payload or {}).get("value") or [{}])[0]
    # Key casing is not consistent across DataMall: EVCBatch and the passenger volume
    # endpoints return "Link", the GTFS-Realtime feeds return "link".
    link = entry.get("Link") or entry.get("link")
    if not link:
        raise FetchError(f"{feed}: response contained no link (keys: {sorted(entry)})")

    stamp = now()
    if hourly:
        # Sub-daily feed: hour partition, filename carries the time.
        directory = storage.feed_path(settings, feed, date=today(), hour=stamp.strftime("%H"))
        destination = directory / f"{stamp.strftime('%H%M%S')}{suffix}"
    else:
        # Daily feed: no hour level, filename carries the content.
        directory = storage.feed_path(settings, feed, date=today())
        destination = directory / f"schedule{suffix}"
    written = fetcher.download(link, destination, label=f"{feed}{suffix}")
    record.bytes_written += written

    if empty_below and written < empty_below:
        # A structurally valid payload carrying no records - e.g. a GTFS-Realtime
        # FeedMessage with a header and zero entities. Counted separately so the
        # archive manifest does not report empty feeds as collected data.
        record.items_empty += 1
        logger.info("%s: %s -> %s (no entities)", feed,
                    storage.human_bytes(written), destination.name)
        return

    record.items_ok += 1
    logger.info("%s: %s -> %s", feed, storage.human_bytes(written), destination.name)


@job(
    "carpark",
    schedule="@every 1m",
    description="Carpark availability across HDB, LTA and URA carparks (updates every minute)",
)
def carpark(logger, record, settings):
    policy, deadline = _window(60)
    with Fetcher(logger=logger, record=record) as fetcher:
        records = fetcher.get_paginated(
            endpoints.CARPARK_AVAILABILITY, headers=_headers(settings), label="carpark",
            policy=policy, deadline=deadline,
        )
    if not records:
        record.items_empty = 1
        logger.warning("carpark returned no records")
        return
    record.items_ok = len(records)
    record.bytes_written = _snapshot(settings, "carpark", records, count=len(records))
    logger.info("carpark: %d lots (%s)", len(records), storage.human_bytes(record.bytes_written))


@job(
    "train_alerts",
    schedule="@every 5m",
    description="Train service alerts and disruptions (ad hoc updates)",
)
def train_alerts(logger, record, settings):
    policy, deadline = _window(300)
    with Fetcher(logger=logger, record=record) as fetcher:
        payload = fetcher.get_json(
            endpoints.TRAIN_SERVICE_ALERTS, headers=_headers(settings),
            label="train_alerts", policy=policy, deadline=deadline,
        )

    value = (payload or {}).get("value")
    # Status 1 is normal service. Recorded regardless: knowing the network was healthy
    # at a given minute is what makes a disruption's start and end recoverable.
    status = value.get("Status") if isinstance(value, dict) else None
    record.items_ok = 1
    record.bytes_written = _snapshot(settings, "train_alerts", value, status=status)

    if status == 2:
        logger.warning("train service disrupted (Status=2)")
    else:
        logger.info("train alerts recorded (Status=%s)", status)


@job(
    "crowd_density",
    schedule="@every 10m",
    description="Real-time MRT/LRT station crowd density for all 11 lines (updates every 10m)",
)
def crowd_density(logger, record, settings):
    headers = _headers(settings)
    by_line = {}
    # One budget shared across all 11 lines, so a slow line cannot push the run past
    # the point where the data would have refreshed anyway.
    policy, deadline = _window(600)
    with Fetcher(logger=logger, record=record) as fetcher:
        for line in endpoints.TRAIN_LINES:
            try:
                payload = fetcher.get_json(
                    endpoints.PCD_REALTIME,
                    params={"TrainLine": line},
                    headers=headers,
                    label=f"crowd_density[{line}]",
                    policy=policy,
                    deadline=deadline,
                )
            except FetchError as exc:
                record.items_failed += 1
                record.add_error(f"{line}: {exc}")
                logger.error("crowd density failed for %s: %s", line, exc)
                continue
            by_line[line] = (payload or {}).get("value", [])
            record.items_ok += 1

    if by_line:
        record.bytes_written = _snapshot(settings, "crowd_density", by_line, lines=len(by_line))
        logger.info("crowd density: %d/%d lines", len(by_line), len(endpoints.TRAIN_LINES))


@job(
    "crowd_forecast",
    schedule="30 3 * * *",
    description="Forecast station crowd density at 30-minute intervals (updates daily)",
)
def crowd_forecast(logger, record, settings):
    headers = _headers(settings)
    by_line = {}
    with Fetcher(logger=logger, record=record) as fetcher:
        for line in endpoints.TRAIN_LINES:
            try:
                payload = fetcher.get_json(
                    endpoints.PCD_FORECAST,
                    params={"TrainLine": line},
                    headers=headers,
                    label=f"crowd_forecast[{line}]",
                )
            except FetchError as exc:
                record.items_failed += 1
                record.add_error(f"{line}: {exc}")
                logger.error("crowd forecast failed for %s: %s", line, exc)
                continue
            by_line[line] = (payload or {}).get("value", [])
            record.items_ok += 1

    if not by_line:
        raise RuntimeError("crowd forecast returned nothing for any line")

    directory = storage.feed_path(settings, "crowd_forecast", date=today())
    record.bytes_written = storage.write_json(directory / "forecast.json", by_line)
    logger.info("crowd forecast: %d/%d lines", len(by_line), len(endpoints.TRAIN_LINES))


@job(
    "ev_charging",
    schedule="@every 5m",
    description="EV charging point availability, whole-island batch (updates every 5m)",
)
def ev_charging(logger, record, settings):
    policy, deadline = _window(300)
    with Fetcher(logger=logger, record=record) as fetcher:
        _download_linked(fetcher, settings, "ev_charging", endpoints.EVC_BATCH,
                         ".json", logger, record, policy=policy, deadline=deadline)


@job(
    "gtfs_trip_updates",
    schedule="@every 5m",
    description="GTFS-Realtime train trip updates: per-trip arrival/departure predictions",
)
def gtfs_trip_updates(logger, record, settings):
    """Archive the raw protobuf feed.

    Trip updates carry per-trip arrival and departure predictions, which nothing else
    in this collection provides - they are the train counterpart of the bus arrival
    job. The companion GTFS service-alerts feed is deliberately *not* collected: it
    reports the same disruptions as the ``train_alerts`` job above, in a format that
    needs a protobuf decoder and omits LTA's free-bus and shuttle fields.

    Stored as bytes rather than decoded. Decoding needs the GTFS-Realtime schema,
    which is an analysis-time concern, and keeping the feed verbatim preserves fields
    a decoder of ours might drop. Resolve trip_id/stop_id against the static feed
    collected by the ``gtfs_schedule`` job.
    """
    with Fetcher(logger=logger, record=record) as fetcher:
        # An entity-free feed is ~15 bytes: a FeedHeader carrying version,
        # incrementality and a timestamp, and nothing else. Anything at or below that
        # is a valid but empty publication, which is common outside disruptions.
        policy, deadline = _window(300)
        _download_linked(fetcher, settings, "gtfs_trip_updates",
                         endpoints.GTFS_TRAIN_TRIP_UPDATES, ".pb", logger, record,
                         empty_below=32, policy=policy, deadline=deadline)


@job(
    "gtfs_schedule",
    schedule="15 4 * * *",
    description="Static GTFS train schedule; needed to interpret trip updates",
)
def gtfs_schedule(logger, record, settings):
    """Daily copy of the static GTFS feed.

    Without this, the trip_id and stop_id values in the trip updates feed cannot be
    resolved to real routes and stations, and a schedule that changes is not
    recoverable after the fact.
    """
    with Fetcher(logger=logger, record=record) as fetcher:
        # Daily feed, so no hour partition.
        _download_linked(fetcher, settings, "gtfs_schedule",
                         endpoints.GTFS_SCHEDULE_TRAIN, ".zip", logger, record, hourly=False)
