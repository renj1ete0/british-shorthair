"""Response validators.

A 200 is not proof the response is the one we asked for. These validators answer
"is this the right payload for this request?" — the correct bus stop, the requested
weather date, the requested passenger-volume month — and raise
:class:`ValidationError` when it is not, which :mod:`bsh.http` treats as a retryable
failure and backs off on.

All date reasoning is SGT (see :data:`bsh.config.SGT`).
"""

from datetime import datetime, timedelta

from .config import SGT

# Bus arrival estimates outside this window relative to now are treated as stale.
# Generous on purpose: buses legitimately run late, and terminal departures can be
# published well ahead of time.
ARRIVAL_PAST_TOLERANCE = timedelta(hours=1)
ARRIVAL_FUTURE_TOLERANCE = timedelta(hours=6)

NEXT_BUS_KEYS = ("NextBus", "NextBus2", "NextBus3")


class ValidationError(Exception):
    """Response was structurally or semantically wrong. Retryable by default."""

    retryable = True


class PermanentValidationError(ValidationError):
    """Response is wrong in a way retrying cannot fix."""

    retryable = False


def parse_sgt_timestamp(value):
    """Parse an ISO-8601 timestamp into SGT, or return None if unparseable/blank."""
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=SGT)
    return parsed.astimezone(SGT)


def validate_bus_arrival(payload, expected_stop, reference=None):
    """Validate a v3 BusArrival response for one stop.

    Returns the ``Services`` list, which may legitimately be empty: the LTA guide
    states that when buses are not in service the API returns no attribute tags at
    all. Treating that as an error would trigger a retry storm every night, so an
    empty payload is accepted and reported as "empty" rather than "failed".
    """
    if payload is None:
        return []
    if not isinstance(payload, dict):
        raise ValidationError(f"expected object, got {type(payload).__name__}")

    # Out-of-service / maintenance: no tags returned at all. Valid, just empty.
    if "BusStopCode" not in payload and "Services" not in payload:
        return []

    stop = payload.get("BusStopCode")
    if stop and str(stop) != str(expected_stop):
        raise ValidationError(f"response is for stop {stop}, requested {expected_stop}")

    services = payload.get("Services", [])
    if not isinstance(services, list):
        raise ValidationError("Services is not a list")

    seen, fresh = 0, 0
    now = reference or datetime.now(SGT)
    for service in services:
        if not isinstance(service, dict):
            raise ValidationError("service entry is not an object")
        if not service.get("ServiceNo"):
            raise ValidationError("service entry missing ServiceNo")
        for key in NEXT_BUS_KEYS:
            bus = service.get(key)
            if not isinstance(bus, dict):
                continue
            arrival = parse_sgt_timestamp(bus.get("EstimatedArrival"))
            if arrival is None:
                continue  # blank is normal when fewer than 3 buses are inbound
            seen += 1
            if -ARRIVAL_PAST_TOLERANCE <= (arrival - now) <= ARRIVAL_FUTURE_TOLERANCE:
                fresh += 1

    # One odd estimate is noise; every estimate being out of window means the whole
    # payload is stale or the clock is wrong, which a retry may well fix.
    if seen and fresh == 0:
        raise ValidationError(f"all {seen} arrival estimates outside freshness window")

    return services


def validate_mss(payload, expected_date, dataset):
    """Validate a data.gov.sg environment response is for the requested date."""
    if not isinstance(payload, dict):
        raise ValidationError(f"{dataset}: expected object, got {type(payload).__name__}")

    status = (payload.get("api_info") or {}).get("status")
    if status != "healthy":
        raise ValidationError(f"{dataset}: api_info.status={status!r}, expected 'healthy'")

    items = payload.get("items")
    if not isinstance(items, list):
        raise ValidationError(f"{dataset}: missing items list")
    if not items:
        raise ValidationError(f"{dataset}: no items returned for {expected_date}")

    # The requested date must actually appear in the payload; otherwise we would
    # silently archive the wrong day under the right filename.
    dates = set()
    for item in items:
        stamp = parse_sgt_timestamp(item.get("timestamp")) if isinstance(item, dict) else None
        if stamp:
            dates.add(stamp.date().isoformat())
    if not dates:
        raise ValidationError(f"{dataset}: no parseable timestamps for {expected_date}")
    if expected_date not in dates:
        raise ValidationError(
            f"{dataset}: requested {expected_date} but payload covers {sorted(dates)}"
        )
    return payload


def validate_pv_link(payload, expected_yyyymm, dataset):
    """Validate a Passenger Volume response and return its download link.

    LTA returns a pre-signed S3 link whose path carries the month, e.g.
    ``.../201803/transport_node_bus_201803.zip?x-amz-...``. Checking the month in the
    path is what stops a stale link being archived under the wrong filename.
    """
    if not isinstance(payload, dict):
        raise ValidationError(f"{dataset}: expected object, got {type(payload).__name__}")

    values = payload.get("value")
    if not isinstance(values, list) or not values:
        raise ValidationError(f"{dataset}: no value entries for {expected_yyyymm}")

    link = (values[0] or {}).get("Link") if isinstance(values[0], dict) else None
    if not link:
        raise ValidationError(f"{dataset}: empty Link for {expected_yyyymm}")

    path = link.split("?", 1)[0]
    if expected_yyyymm not in path:
        raise ValidationError(
            f"{dataset}: link does not reference {expected_yyyymm} (path {path[-80:]!r})"
        )
    return link


def validate_records(records, dataset, minimum=1):
    """Validate a paginated dataset returned enough records to be plausible."""
    if not isinstance(records, list):
        raise ValidationError(f"{dataset}: expected list, got {type(records).__name__}")
    if len(records) < minimum:
        raise ValidationError(f"{dataset}: got {len(records)} records, expected >= {minimum}")
    return records


def validate_planned_bus_routes(records):
    """Planned Bus Routes is ad hoc and may legitimately be empty; check shape only."""
    if not isinstance(records, list):
        raise ValidationError(f"planned_bus_routes: expected list, got {type(records).__name__}")
    for row in records[:50]:
        if not isinstance(row, dict):
            raise ValidationError("planned_bus_routes: row is not an object")
        missing = [f for f in ("ServiceNo", "BusStopCode") if not row.get(f)]
        if missing:
            raise ValidationError(f"planned_bus_routes: row missing {missing}")
    return records
