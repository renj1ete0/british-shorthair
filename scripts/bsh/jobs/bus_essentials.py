"""Daily snapshot of the reference bus datasets.

Bus stops, routes and services change slowly, but the bus arrival job depends on an
up-to-date stop list, so this runs daily and republishes ``busstop_current.json``.

Each dataset is validated against a plausibility floor before it is published. The
previous implementation used a bare ``except`` as its pagination stop condition, so a
transient failure at page 7 quietly produced a truncated stop list and reported
success — which then silently shrank every subsequent arrival collection.
"""

from .. import endpoints, storage
from ..http import Fetcher
from ..logging_setup import today
from ..registry import job
from ..validation import validate_records

# Sanity floors: well below real counts (~5k stops, ~26k route rows, ~700 services)
# but high enough to catch a truncated or empty response.
DATASETS = (
    ("busstop", endpoints.BUS_STOPS, 1000),
    ("busroute", endpoints.BUS_ROUTES, 5000),
    ("busservice", endpoints.BUS_SERVICES, 100),
)


@job(
    "bus_essentials",
    schedule="0 4 * * *",
    description="Daily snapshot of bus stops, routes and services",
)
def collect(logger, record, settings):
    if not settings.lta_api_keys:
        raise RuntimeError("LTA_API_KEYS is empty; cannot call the DataMall API")

    headers = {"AccountKey": settings.lta_api_keys[0], "accept": "application/json"}
    directory = storage.feed_path(settings, "essentials", date=today())

    with Fetcher(logger=logger, record=record) as fetcher:
        for name, url, minimum in DATASETS:
            records = fetcher.get_paginated(url, headers=headers, label=name)
            validate_records(records, name, minimum=minimum)

            written = storage.write_json(directory / f"{name}.json", records)
            record.bytes_written += written
            record.items_ok += 1
            record.notes[name] = len(records)
            logger.info("%s: %d records (%s)", name, len(records), storage.human_bytes(written))

            if name == "busstop":
                # Published unpartitioned as well: bus_arrival reads it every tick and
                # should not have to locate the newest partition to do so.
                record.bytes_written += storage.write_json(settings.stop_list_path, records)
                logger.info("published busstop_current.json (%d stops)", len(records))
