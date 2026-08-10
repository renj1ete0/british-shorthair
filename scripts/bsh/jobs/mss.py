"""NEA weather collection from the data.gov.sg environment APIs.

Covers the 11 openly accessible NEA real-time datasets. Two of the 13 published
services, **Lightning** and **WBGT**, return HTTP 403 on both v1 and v2 and are not
collected; they need authorised access that this project does not have.

Frequency: nightly, for the previous day. Every one of these endpoints serves a whole
past day retrospectively when given ``?date=YYYY-MM-DD`` (verified 2026-08-09: PM2.5
returns 23 hourly items, the 2-hour forecast 56 issues, the 4-day outlook 2), so
polling live would gain nothing — a single nightly call captures the full day.

"Pull until success" is handled by :func:`gapfill` rather than by unbounded retries
inside one run: because the API serves history, any date missed during an outage can
simply be re-fetched later, and the nightly job re-checks a trailing window every
night until every dataset/date pair is on disk.

Output layout (Hive-partitioned, see :func:`bsh.storage.partition`)::

    weather/dataset=rainfall/date=2026-08-09/readings.csv
                                            /stations.csv
"""

from datetime import timedelta

from .. import endpoints, storage
from ..http import Fetcher, FetchError
from ..logging_setup import today
from ..registry import job
from ..validation import validate_mss

# How many trailing days the nightly run re-checks for missing files.
GAPFILL_WINDOW_DAYS = 14

STATION_HEADER = ["station_id", "device_id", "name", "latitude", "longitude"]
READING_HEADER = ["timestamp", "station_id", "value"]
REGION_HEADER = ["name", "latitude", "longitude"]


def _station_rows(payload):
    rows = []
    for station in (payload.get("metadata") or {}).get("stations", []):
        location = station.get("location") or {}
        rows.append([
            station.get("id", ""), station.get("device_id", ""), station.get("name", ""),
            location.get("latitude", ""), location.get("longitude", ""),
        ])
    return rows


def _reading_rows(payload):
    rows = []
    for item in payload.get("items", []):
        stamp = item.get("timestamp", "")
        for reading in item.get("readings", []):
            rows.append([stamp, reading.get("station_id", ""), reading.get("value", "")])
    return rows


def _label_region_rows(payload, key):
    """Shared by PSI and PM2.5, which both publish ``region_metadata``."""
    rows = []
    for region in payload.get(key, []):
        location = region.get("label_location") or {}
        rows.append([
            region.get("name", ""), location.get("latitude", ""), location.get("longitude", ""),
        ])
    return rows


def _psi_region_rows(payload):
    return _label_region_rows(payload, "region_metadata")


def _nested_region_reading_rows(payload):
    """Flatten ``readings: {measure: {region: value}}`` into long form.

    Long form rather than one file per measure: PSI alone has 11 measures, and the old
    collector wrote each to its own CSV, which made "all pollutants for a day" a join
    across 11 files.
    """
    rows = []
    for item in payload.get("items", []):
        readings = item.get("readings") or {}
        for measure, regions in readings.items():
            if not isinstance(regions, dict):
                continue
            for region, value in regions.items():
                rows.append([
                    item.get("timestamp", ""), item.get("update_timestamp", ""),
                    measure, region, value,
                ])
    return rows


def _uv_rows(payload):
    rows = []
    for item in payload.get("items", []):
        for entry in item.get("index", []):
            rows.append([
                item.get("timestamp", ""), item.get("update_timestamp", ""),
                entry.get("timestamp", ""), entry.get("value", ""),
            ])
    return rows


def _forecast_general_rows(payload):
    rows = []
    for item in payload.get("items", []):
        general = item.get("general") or {}
        humidity = general.get("relative_humidity") or {}
        temperature = general.get("temperature") or {}
        wind = general.get("wind") or {}
        speed = wind.get("speed") or {}
        period = item.get("valid_period") or {}
        rows.append([
            item.get("update_timestamp", ""), item.get("timestamp", ""),
            period.get("start", ""), period.get("end", ""), general.get("forecast", ""),
            humidity.get("low", ""), humidity.get("high", ""),
            temperature.get("low", ""), temperature.get("high", ""),
            speed.get("low", ""), speed.get("high", ""), wind.get("direction", ""),
        ])
    return rows


def _forecast_period_rows(payload):
    rows = []
    for item in payload.get("items", []):
        for period in item.get("periods", []):
            regions = period.get("regions") or {}
            time = period.get("time") or {}
            rows.append([
                item.get("update_timestamp", ""), item.get("timestamp", ""),
                time.get("start", ""), time.get("end", ""),
                regions.get("west", ""), regions.get("east", ""), regions.get("central", ""),
                regions.get("south", ""), regions.get("north", ""),
            ])
    return rows


def _twohr_area_rows(payload):
    return _label_region_rows(payload, "area_metadata")


def _twohr_forecast_rows(payload):
    rows = []
    for item in payload.get("items", []):
        period = item.get("valid_period") or {}
        for forecast in item.get("forecasts", []):
            rows.append([
                item.get("update_timestamp", ""), item.get("timestamp", ""),
                period.get("start", ""), period.get("end", ""),
                forecast.get("area", ""), forecast.get("forecast", ""),
            ])
    return rows


def _fourday_rows(payload):
    rows = []
    for item in payload.get("items", []):
        for forecast in item.get("forecasts", []):
            wind = forecast.get("wind") or {}
            speed = wind.get("speed") or {}
            temperature = forecast.get("temperature") or {}
            humidity = forecast.get("relative_humidity") or {}
            rows.append([
                item.get("update_timestamp", ""), item.get("timestamp", ""),
                forecast.get("date", ""), forecast.get("timestamp", ""),
                forecast.get("forecast", ""),
                temperature.get("low", ""), temperature.get("high", ""),
                humidity.get("low", ""), humidity.get("high", ""),
                speed.get("low", ""), speed.get("high", ""), wind.get("direction", ""),
            ])
    return rows


NESTED_READING_HEADER = ["timestamp", "update_timestamp", "measure", "region", "value"]
STATION_SET = [("stations", STATION_HEADER, _station_rows),
               ("readings", READING_HEADER, _reading_rows)]

# dataset -> [(output file stem, header, extractor)]
EXTRACTORS = {
    "rainfall": STATION_SET,
    "winddir": STATION_SET,
    "windspeed": STATION_SET,
    "airtemp": STATION_SET,
    "rh": STATION_SET,
    "uvidx": [
        ("readings", ["timestamp", "update_timestamp", "index_timestamp", "value"], _uv_rows),
    ],
    "psi": [
        ("regions", REGION_HEADER, _psi_region_rows),
        ("readings", NESTED_READING_HEADER, _nested_region_reading_rows),
    ],
    "pm25": [
        ("regions", REGION_HEADER, _psi_region_rows),
        ("readings", NESTED_READING_HEADER, _nested_region_reading_rows),
    ],
    "24hrforecast": [
        ("general", ["update_timestamp", "timestamp", "valid_start", "valid_end", "forecast",
                     "humidity_low", "humidity_high", "temp_low", "temp_high",
                     "wind_speed_low", "wind_speed_high", "wind_direction"],
         _forecast_general_rows),
        ("periods", ["update_timestamp", "timestamp", "period_start", "period_end",
                     "west", "east", "central", "south", "north"], _forecast_period_rows),
    ],
    "2hrforecast": [
        ("areas", REGION_HEADER, _twohr_area_rows),
        ("forecasts", ["update_timestamp", "timestamp", "valid_start", "valid_end",
                       "area", "forecast"], _twohr_forecast_rows),
    ],
    "4dayoutlook": [
        ("forecasts", ["update_timestamp", "timestamp", "forecast_date", "forecast_timestamp",
                       "forecast", "temp_low", "temp_high", "humidity_low", "humidity_high",
                       "wind_speed_low", "wind_speed_high", "wind_direction"], _fourday_rows),
    ],
}


def _dataset_dir(settings, name, date):
    """Weather datasets are feeds like any other: ``feed=weather_rainfall/date=...``.

    Flat rather than nested under a shared ``weather/`` root, so every dataset in the
    project sits at the same depth and one glob covers all of them. ``feed=weather_*``
    still selects the weather feeds alone.
    """
    return storage.feed_path(settings, f"weather_{name}", date=date)


def _is_collected(settings, name, date):
    """A dataset/date counts as collected once its primary output file exists."""
    primary = EXTRACTORS[name][-1][0]
    return (_dataset_dir(settings, name, date) / f"{primary}.csv").exists()


def collect_one(fetcher, name, url, date, logger, record, settings):
    """Fetch and write a single dataset for a single date."""
    date_str = date.isoformat()
    payload = fetcher.get_json(
        url,
        params={"date": date_str},
        validator=lambda data, n=name: validate_mss(data, date_str, n),
        label=f"weather:{name}:{date_str}",
    )

    directory = _dataset_dir(settings, name, date)
    written = 0
    for stem, header, extractor in EXTRACTORS[name]:
        rows = extractor(payload)
        if rows:
            written += storage.append_csv(directory / f"{stem}.csv", rows, header=header)

    record.bytes_written += written
    logger.info("%s %s: %s", name, date_str, storage.human_bytes(written))
    return written


def collect_date(fetcher, date, logger, record, settings, only_missing=False):
    """Collect all datasets for one date. Returns the list of dataset names that failed."""
    failed = []
    for name, url in endpoints.MSS_DATASETS.items():
        if only_missing and _is_collected(settings, name, date):
            continue
        try:
            collect_one(fetcher, name, url, date, logger, record, settings)
            record.items_ok += 1
        except FetchError as exc:
            failed.append(name)
            record.items_failed += 1
            record.add_error(str(exc))
            logger.error("%s failed for %s: %s", name, date.isoformat(), exc)
    return failed


def gapfill(fetcher, logger, record, settings, window=GAPFILL_WINDOW_DAYS):
    """Re-fetch anything missing in the trailing window.

    This is what makes collection eventually consistent: a night when the API was down
    is simply retried tomorrow, and the night after, until it lands.
    """
    filled = 0
    for offset in range(2, window + 1):
        date = today() - timedelta(days=offset)
        missing = [n for n in endpoints.MSS_DATASETS if not _is_collected(settings, n, date)]
        if not missing:
            continue
        logger.info("gapfill %s: %d dataset(s) missing", date.isoformat(), len(missing))
        failures = collect_date(fetcher, date, logger, record, settings, only_missing=True)
        filled += len(missing) - len(failures)
    if filled:
        logger.info("gapfill recovered %d dataset/date pairs", filled)
    record.notes["gapfilled"] = filled
    return filled


@job(
    "mss",
    schedule="0 3 * * *",
    description="Nightly NEA weather collection for yesterday, plus gap-fill of recent days",
)
def collect(logger, record, settings, date=None):
    target = date or (today() - timedelta(days=1))
    # The date collected, which is not the date this ran: archival manifests match on
    # this to correlate data with the run that produced it.
    record.notes["data_date"] = target.isoformat()
    logger.info("collecting weather for %s (%d datasets)", target.isoformat(),
                len(endpoints.MSS_DATASETS))

    with Fetcher(logger=logger, record=record) as fetcher:
        collect_date(fetcher, target, logger, record, settings)
        if date is None:
            # Only sweep for gaps on the scheduled run, not on an explicit re-run.
            gapfill(fetcher, logger, record, settings)
