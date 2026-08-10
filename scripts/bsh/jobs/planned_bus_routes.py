"""Daily archive of planned new/updated bus routes.

LTA publishes this ad hoc and only on or after each change's ``EffectiveDate``, so
there is no event to react to — polling daily and keeping a dated copy is what builds
the history of *when* a route change was announced, which is not otherwise recoverable
once the change takes effect.

An empty response is normal (most days have no announced changes) and is recorded
rather than treated as a failure.
"""

from .. import endpoints, storage
from ..http import Fetcher
from ..logging_setup import today
from ..registry import job
from ..validation import validate_planned_bus_routes


@job(
    "planned_bus_routes",
    schedule="30 4 * * *",
    description="Daily archive of announced upcoming bus route changes",
)
def collect(logger, record, settings):
    if not settings.lta_api_keys:
        raise RuntimeError("LTA_API_KEYS is empty; cannot call the DataMall API")

    headers = {"AccountKey": settings.lta_api_keys[0], "accept": "application/json"}

    with Fetcher(logger=logger, record=record) as fetcher:
        records = fetcher.get_paginated(
            endpoints.PLANNED_BUS_ROUTES, headers=headers, label="planned_bus_routes"
        )

    validate_planned_bus_routes(records)

    if not records:
        record.items_empty = 1
        logger.info("no planned route changes published today")
        return

    directory = storage.feed_path(settings, "planned_bus_routes", date=today())
    record.bytes_written = storage.write_json(directory / "routes.json", records)
    record.items_ok = len(records)

    effective = sorted({row.get("EffectiveDate", "") for row in records if row.get("EffectiveDate")})
    services = sorted({row.get("ServiceNo", "") for row in records if row.get("ServiceNo")})
    record.notes["services"] = len(services)
    record.notes["effective_dates"] = effective[:10]

    logger.info(
        "%d rows across %d services; effective dates %s",
        len(records), len(services), ", ".join(effective[:5]) or "n/a",
    )
