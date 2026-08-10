"""Real-time bus arrival collection.

The LTA v3 BusArrival API refreshes every 20 seconds, so this job ticks at 20s and
treats that interval as a hard budget: work that cannot finish inside the window is
abandoned and counted, rather than allowed to run long and collide with the next tick
(the runner's singleton lock also skips a tick whose predecessor is still going).

Every stop is fetched independently, so one bad stop degrades a tick rather than
failing it.
"""

import json
import random
from concurrent.futures import ThreadPoolExecutor, as_completed

from .. import endpoints, storage
from ..http import Deadline, Fetcher, FetchError, RetryPolicy
from ..logging_setup import now, today
from ..registry import job
from ..validation import validate_bus_arrival


def load_stop_codes(settings):
    """Read the bus stop list published by the ``bus_essentials`` job."""
    path = settings.stop_list_path
    if not path.is_file():
        raise FileNotFoundError(
            f"{path} not found - run the bus_essentials job first to publish the stop list"
        )
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    codes = [row["BusStopCode"] for row in payload if isinstance(row, dict) and row.get("BusStopCode")]
    if not codes:
        raise ValueError(f"{path} contains no BusStopCode entries")
    return codes


def _fetch_one(fetcher, stop, settings, policy, deadline):
    key = random.choice(settings.lta_api_keys)
    return fetcher.get_json(
        endpoints.BUS_ARRIVAL,
        params={"BusStopCode": stop},
        headers={"AccountKey": key, "accept": "application/json"},
        validator=lambda payload: validate_bus_arrival(payload, stop),
        policy=policy,
        deadline=deadline,
        label=f"BusArrival[{stop}]",
    )


@job(
    "bus_arrival",
    # On demand only, and it should stay that way.
    #
    # This is the documented per-stop API: one request per bus stop, ~5,091 per tick.
    # On a 20s schedule that is ~22 million calls/day, against a daily quota of 100K
    # imposed on this API once whole-island batch access is held. Exceeding it risks
    # revocation of both. Use the batch collector for scheduled collection; keep this
    # for spot checks, debugging a single stop, or as a fallback if batch access ends.
    schedule=None,
    description="Per-stop bus arrivals; on demand only (quota-limited, ~5,091 req/tick)",
)
def collect(logger, record, settings):
    if not settings.lta_api_keys:
        raise RuntimeError("LTA_API_KEYS is empty; cannot call the DataMall API")

    stops = load_stop_codes(settings)
    deadline = Deadline(settings.arrival_deadline)
    started = now()

    # Retries must fit inside the 20s window, so the budget is deliberately tighter
    # than the project default: two quick attempts, then give the slot up.
    policy = RetryPolicy(
        attempts=2,
        base_delay=0.2,
        max_delay=2.0,
        timeout=settings.arrival_timeout,
    )

    results = {}
    abandoned = 0

    with Fetcher(logger=logger, record=record, pool_size=settings.arrival_workers) as fetcher:
        with ThreadPoolExecutor(max_workers=settings.arrival_workers) as pool:
            futures = {
                pool.submit(_fetch_one, fetcher, stop, settings, policy, deadline): stop
                for stop in stops
            }
            for future in as_completed(futures):
                stop = futures[future]
                try:
                    services = future.result()
                except FetchError as exc:
                    # Deadline overruns are the expected way a tick ends under load;
                    # they are counted separately from genuine API failures.
                    if "deadline" in str(exc):
                        abandoned += 1
                    else:
                        record.items_failed += 1
                        record.add_error(f"{stop}: {exc}")
                    continue
                except Exception as exc:  # noqa: BLE001 - one stop must not kill the tick
                    record.items_failed += 1
                    record.add_error(f"{stop}: {type(exc).__name__}: {exc}")
                    continue

                if services:
                    results[stop] = services
                    record.items_ok += 1
                else:
                    # Valid but empty: buses not in service at this stop right now.
                    record.items_empty += 1

    if abandoned:
        record.items_failed += abandoned
        record.add_error(f"{abandoned} stops abandoned at the {settings.arrival_deadline:.0f}s deadline")
        logger.warning("abandoned %d stops at deadline", abandoned)

    payload = {
        "collected_at": started.isoformat(),
        "completed_at": now().isoformat(),
        "cadence_seconds": 20,
        "stats": {
            "stops_total": len(stops),
            "stops_with_data": record.items_ok,
            "stops_empty": record.items_empty,
            "stops_failed": record.items_failed,
        },
        "stops": results,
    }

    # Partitioned by hour like every other sub-daily feed, and named for the second
    # it was taken - a minute-resolution name would collide at a 20s cadence.
    directory = storage.feed_path(
        settings, "bus_arrival", date=today(), hour=started.strftime("%H")
    )
    path = directory / f"{started.strftime('%H%M%S')}.json"
    record.bytes_written = storage.write_json(path, payload)

    logger.info(
        "wrote %s (%s) in %.1fs",
        path.name, storage.human_bytes(record.bytes_written), deadline.elapsed(),
    )

    # A tick that collects nothing at all means the API or our credentials are down,
    # not that the island has no buses.
    if record.items_ok == 0 and record.items_empty == 0:
        raise RuntimeError(f"no data collected from any of {len(stops)} stops")
