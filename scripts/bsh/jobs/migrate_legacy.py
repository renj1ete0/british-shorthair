"""One-shot migration of pre-2026-08 data into the current layout.

    python run_job.py migrate_legacy --from /legacy --days 0        # dry run
    python run_job.py migrate_legacy --from /legacy --days 1        # execute

Copies, never moves: the legacy tree is left untouched, so a bad migration costs
nothing but disk. Run it twice and it skips what it already converted.

What it handles, and what it deliberately does not:

* **Passenger volume zips, reference JSON** - pure relocation.
* **Weather CSVs** - relocation plus a header row. The old writer used raw f-strings
  and wrote no header, and left a stray space in two places
  (``S77, S77,Alexandra Road``), which is stripped here.
* **PSI and PM2.5** - a real reshape. The old layout was 11 wide files, one per
  measure, each carrying five region columns; the current layout is one long file,
  ``timestamp,update_timestamp,measure,region,value``.
* **Bus arrival** is *not* migrated, by design. The old per-stop JSON has no
  counterpart in the current layout, and much of 2023-11-26 is error stubs from an
  inverted error branch in the old client. Old batch snapshots are also left alone:
  they predate the ``Monitored`` attribute and carry 9 fields per bus where current
  files carry 10, so a parser must branch on field count. Leaving them in the legacy
  tree keeps that decision with whoever writes the parser rather than baking a guess
  into a copy.
"""

import csv
import shutil
from datetime import date as date_cls

from .. import storage
from ..registry import job

# Old wide PSI/PM2.5 files put regions in this column order after the two timestamps.
PSI_REGIONS = ("west", "east", "central", "south", "north")

STATION_HEADER = ["station_id", "device_id", "name", "latitude", "longitude"]
READING_HEADER = ["timestamp", "station_id", "value"]
LONG_HEADER = ["timestamp", "update_timestamp", "measure", "region", "value"]

# Legacy file stem -> (new feed suffix, new filename, header)
SIMPLE = {
    "rainfall_readings": ("rainfall", "readings.csv", READING_HEADER),
    "rainfall_stations": ("rainfall", "stations.csv", STATION_HEADER),
    "airtemp_readings": ("airtemp", "readings.csv", READING_HEADER),
    "airtemp_stations": ("airtemp", "stations.csv", STATION_HEADER),
    "rh_readings": ("rh", "readings.csv", READING_HEADER),
    "rh_stations": ("rh", "stations.csv", STATION_HEADER),
    "winddir_readings": ("winddir", "readings.csv", READING_HEADER),
    "winddir_stations": ("winddir", "stations.csv", STATION_HEADER),
    "uvidx_readings": ("uvidx", "readings.csv",
                       ["timestamp", "update_timestamp", "index_timestamp", "value"]),
    "psi_regions": ("psi", "regions.csv", ["name", "latitude", "longitude"]),
    "24hrforecast_general": ("24hrforecast", "general.csv",
                             ["update_timestamp", "timestamp", "valid_start", "valid_end",
                              "forecast", "humidity_low", "humidity_high", "temp_low",
                              "temp_high", "wind_speed_low", "wind_speed_high",
                              "wind_direction"]),
}

PV_PREFIXES = ("PV_BUSSTOPS", "PV_OD_BUSSTOPS", "PV_TRAINSTNS", "PV_OD_TRAIN")
ESSENTIALS = ("busstop", "busroute", "busservice")


def _clean(row):
    """Strip the stray whitespace the old f-string writer left after commas."""
    return [cell.strip() for cell in row]


def _write_csv(destination, header, rows, apply_changes):
    if not apply_changes:
        return len(rows)
    with open(destination, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)
    return len(rows)


def _migrate_simple(path, feed_suffix, filename, header, settings, date, apply_changes):
    with open(path, "r", encoding="utf-8", newline="") as handle:
        rows = [_clean(r) for r in csv.reader(handle) if r]
    if not rows:
        return 0
    directory = storage.feed_path(settings, f"weather_{feed_suffix}", date=date)
    return _write_csv(directory / filename, header, rows, apply_changes)


def _migrate_psi_like(paths, feed_suffix, settings, date, apply_changes):
    """Pivot the old wide per-measure files into one long readings.csv."""
    rows = []
    for measure, path in sorted(paths.items()):
        with open(path, "r", encoding="utf-8", newline="") as handle:
            for raw in csv.reader(handle):
                cells = _clean(raw)
                if len(cells) < 2 + len(PSI_REGIONS):
                    continue
                timestamp, updated = cells[0], cells[1]
                for region, value in zip(PSI_REGIONS, cells[2:2 + len(PSI_REGIONS)]):
                    rows.append([timestamp, updated, measure, region, value])
    if not rows:
        return 0
    rows.sort(key=lambda r: (r[0], r[2], r[3]))
    directory = storage.feed_path(settings, f"weather_{feed_suffix}", date=date)
    return _write_csv(directory / "readings.csv", LONG_HEADER, rows, apply_changes)


def _copy(source, destination, apply_changes):
    if destination.exists():
        return 0
    if apply_changes:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    return source.stat().st_size


def _migrate_weather_day(day_dir, settings, logger, record, apply_changes):
    date = date_cls.fromisoformat(day_dir.name)
    psi_like = {"psi": {}, "pm25": {}}

    for path in sorted(day_dir.glob("*.csv")):
        stem = path.stem
        suffix = f"_{date.isoformat()}"
        if not stem.endswith(suffix):
            continue
        stem = stem[: -len(suffix)]

        if stem in SIMPLE:
            feed_suffix, filename, header = SIMPLE[stem]
            _migrate_simple(path, feed_suffix, filename, header, settings, date, apply_changes)
            record.items_ok += 1
            continue

        # psi_<measure>_readings / pm25_<measure>_readings -> long form
        for family in ("psi", "pm25"):
            prefix, tail = f"{family}_", "_readings"
            if stem.startswith(prefix) and stem.endswith(tail):
                measure = stem[len(prefix): -len(tail)]
                psi_like[family][measure] = path
                break
        else:
            # 24hrforecast_periods carried two extra valid_period columns that the
            # current schema drops; they are recoverable from general.csv.
            if stem != "24hrforecast_periods":
                record.notes.setdefault("skipped", [])
                if path.name not in record.notes["skipped"][:20]:
                    record.notes["skipped"].append(path.name)

    for family, paths in psi_like.items():
        if paths:
            _migrate_psi_like(paths, family, settings, date, apply_changes)
            record.items_ok += 1


@job(
    "migrate_legacy",
    schedule=None,
    description="One-shot copy of pre-2026-08 data into the current layout (--from PATH)",
    alert_on_failure=False,
)
def collect(logger, record, settings, start=None, days=0):
    """``--from`` is the legacy root; ``--days 0`` (the default) is a dry run."""
    if not start:
        raise ValueError("--from PATH is required (the legacy data root)")

    from pathlib import Path

    source = Path(start)
    if not source.is_dir():
        raise FileNotFoundError(f"{source} is not a directory")

    apply_changes = bool(days)
    logger.info("%s migration from %s", "APPLYING" if apply_changes else "DRY RUN", source)

    # Passenger volume: pure relocation.
    for path in sorted((source / "export").glob("*.zip")):
        stem = path.stem
        for prefix in PV_PREFIXES:
            if stem.startswith(prefix + "_"):
                month = stem[len(prefix) + 1:]
                if not (len(month) == 6 and month.isdigit()):
                    continue  # e.g. the stray PV_OD_BUSSTOPS_None.zip
                destination = storage.feed_path(
                    settings, "passenger_volume", month=month
                ) / f"{prefix}.zip" if apply_changes else None
                if destination:
                    record.bytes_written += _copy(path, destination, apply_changes)
                record.items_ok += 1
                break

    # Reference datasets: pure relocation.
    for day_dir in sorted((source / "export").glob("[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]")):
        date = date_cls.fromisoformat(day_dir.name)
        for name in ESSENTIALS:
            path = day_dir / f"{name}_{day_dir.name}.json"
            if not path.is_file():
                continue
            if apply_changes:
                destination = storage.feed_path(settings, "essentials", date=date) / f"{name}.json"
                record.bytes_written += _copy(path, destination, apply_changes)
            record.items_ok += 1

    # Weather: relocation, header insertion, whitespace cleanup, PSI/PM2.5 reshape.
    mss_root = source / "export_mss"
    days_seen = 0
    if mss_root.is_dir():
        for day_dir in sorted(mss_root.glob("[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]")):
            _migrate_weather_day(day_dir, settings, logger, record, apply_changes)
            days_seen += 1

    record.notes["weather_days"] = days_seen
    record.notes["applied"] = apply_changes
    logger.info(
        "%s: %d item(s) across %d weather day(s)%s",
        "migrated" if apply_changes else "would migrate",
        record.items_ok, days_seen,
        "" if apply_changes else " - rerun with --days 1 to apply",
    )
    logger.info("bus arrival data is intentionally not migrated; see module docstring")
