"""Nightly archival to cold storage.

Three treatments, because the feeds are not alike (measurements in ``docs/DATA.md``):

* **Solid daily** - most feeds. ``tar`` + ``zstd -19 --long=31``, one archive per day.
  Consecutive snapshots are near-identical, and long-range matching across the whole
  day is where the compression comes from: 40x with per-file gzip, 121x solid.
* **Solid monthly** - reference datasets that barely change. A second daily copy of the
  bus stop list costs 0.4% of the first when compressed alongside it, so a year of them
  costs about what one costs. Bundling monthly is nearly free; per-day is not.
* **Verbatim** - payloads that arrive already compressed. Recompressing a zip measured
  +0.0%: pure CPU for nothing. These are checksummed and left alone.

Gzipped snapshots are **decompressed before archiving**. Compressing them as-is leaves
the ratio at 40x, because gzip's 32 KB window has already consumed exactly the
cross-snapshot redundancy the solid archiver would otherwise exploit. Decompression is
streamed one file at a time, so this needs no temporary space for the day.

Every archive carries a ``_MANIFEST.json`` (see :mod:`bsh.manifest`) so a restore years
later can tell completeness and errors from the archive alone, and every archive also
appends a line to ``_archive_index.jsonl`` at the data root so those questions can be
answered without decompressing anything at all.

Sources are deleted only after the archive is written, integrity-checked and indexed.
"""

import gzip
import io
import json
import shutil
import subprocess
import tarfile
from datetime import date as date_cls
from datetime import timedelta

from .. import manifest, metrics, storage
from ..logging_setup import today
from ..registry import all_jobs, job

# Payloads that are already compressed. Never recompressed.
VERBATIM_FEEDS = frozenset({"passenger_volume", "gtfs_schedule"})
# Slow-changing reference data, bundled a month at a time.
MONTHLY_FEEDS = frozenset({"essentials", "planned_bus_routes"})
# Feeds whose files arrive gzipped and must be expanded before solid compression.
GZIPPED_FEEDS = frozenset({"bus_arrival_batch"})

ZSTD_LEVEL = "-19"
ZSTD_LONG = "--long=31"
INDEX_NAME = "_archive_index.jsonl"


def _cadences():
    """Data cadence per job, which drives the manifest's expected-file arithmetic."""
    return {j.name: j.data_cadence for j in all_jobs()}


# Feeds whose directory name differs from the job that writes them. Manifests match
# run records on the job name, so a missing entry here shows up as a spurious
# "no run records found" warning on every archive of that feed.
FEED_TO_JOB = {
    "passenger_volume": "datamall_pv",
    "essentials": "bus_essentials",
}


def job_for_feed(feed):
    """The job that produces a feed.

    Usually identical, with three exceptions: one ``mss`` run writes eleven
    ``weather_*`` feeds, and two feeds are named for their contents rather than their
    job.
    """
    if feed.startswith("weather_"):
        return "mss"
    return FEED_TO_JOB.get(feed, feed)


def _write_tar_zst(sources, destination, expand_gzip, logger):
    """Stream a tar into zstd. Returns (bytes written, uncompressed bytes archived).

    Members are fed one at a time and gzip members are expanded in memory (a single
    snapshot is a few MB), so a day of ~18 GB never lands on disk uncompressed.
    """
    expanded = 0
    process = subprocess.Popen(
        ["zstd", ZSTD_LEVEL, ZSTD_LONG, "-T0", "-q", "-f", "-o", str(destination)],
        stdin=subprocess.PIPE,
    )
    try:
        with tarfile.open(fileobj=process.stdin, mode="w|") as archive:
            for root, path in sources:
                arcname = str(path.relative_to(root.parent)).replace("\\", "/")
                if expand_gzip and path.suffix == ".gz":
                    with gzip.open(path, "rb") as handle:
                        payload = handle.read()
                    info = tarfile.TarInfo(name=arcname[: -len(".gz")])
                    info.size = len(payload)
                    info.mtime = int(path.stat().st_mtime)
                    archive.addfile(info, io.BytesIO(payload))
                    expanded += len(payload)
                else:
                    archive.add(path, arcname=arcname)
                    expanded += path.stat().st_size
        process.stdin.close()
    except Exception:
        process.stdin.close()
        process.wait()
        destination.unlink(missing_ok=True)
        raise

    if process.wait() != 0:
        destination.unlink(missing_ok=True)
        raise RuntimeError(f"zstd exited {process.returncode} writing {destination.name}")
    return destination.stat().st_size, expanded


def _verify(archive):
    """Integrity-check the archive before its source is deleted."""
    result = subprocess.run(["zstd", "-t", "--long=31", str(archive)],
                            capture_output=True, text=True, check=False)
    return result.returncode == 0, result.stderr.strip()[-200:]


def _append_index(settings, entry):
    path = settings.data_dir / INDEX_NAME
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _archive(settings, feed, partitions, destination, date, cadence, runs, logger, record):
    """Manifest, compress, verify, index, then remove sources."""
    if destination.exists():
        logger.info("%s already archived; skipping", destination.name)
        return False

    # The manifest is written into the first partition so compression captures it.
    payload = manifest.build(feed, date, partitions[0], cadence=cadence,
                             run_records=runs, job_name=job_for_feed(feed))
    manifest.write(partitions[0], payload)

    if payload["warnings"]:
        logger.warning("%s %s: %s", feed, date.isoformat(), "; ".join(payload["warnings"]))

    sources = [(p, f) for p in partitions for f in sorted(p.rglob("*")) if f.is_file()]
    raw = sum(f.stat().st_size for _, f in sources)

    written, expanded = _write_tar_zst(sources, destination, feed in GZIPPED_FEEDS, logger)
    ok, detail = _verify(destination)
    if not ok:
        destination.unlink(missing_ok=True)
        record.items_failed += 1
        record.add_error(f"{destination.name} failed integrity check: {detail}")
        logger.error("%s failed integrity check; sources kept", destination.name)
        return False

    _append_index(settings, manifest.index_entry(
        payload, str(destination.relative_to(settings.data_dir)).replace("\\", "/"), written))

    for partition in partitions:
        shutil.rmtree(partition, ignore_errors=True)

    record.items_ok += 1
    record.bytes_written += written

    # Two ratios, because for a gzipped feed they answer different questions: how much
    # disk this reclaims (against what was stored) and how well the data compressed
    # (against its true uncompressed size).
    detail = ""
    if expanded > raw:
        detail = f", {storage.human_bytes(expanded)} uncompressed = {expanded / written:.0f}x"
    logger.info("%s: %s -> %s (%.1fx on disk%s)%s", destination.name,
                storage.human_bytes(raw), storage.human_bytes(written),
                (raw / written) if written else 0, detail,
                f" [{payload['status']}]" if payload["warnings"] else "")
    return True


def _manifest_month_partitions(settings, runs, logger, record):
    """Describe ``month=`` partitions, which the daily pass never sees.

    Passenger volume partitions by month, so globbing ``date=`` skipped it entirely -
    those files were being collected with no manifest, no checksums and no index
    entry. Their payloads are pre-compressed zips, so they are described in place
    rather than archived.
    """
    for feed_dir in sorted(settings.data_dir.glob("feed=*")):
        if not feed_dir.is_dir():
            continue
        feed = feed_dir.name.split("=", 1)[1]
        for partition in sorted(p for p in feed_dir.glob("month=*") if p.is_dir()):
            if (partition / manifest.MANIFEST_NAME).exists():
                continue
            month = partition.name.split("=", 1)[1]
            try:
                # First of the month: a partition-level stand-in, since these datasets
                # describe a month rather than a day.
                as_date = date_cls(int(month[:4]), int(month[4:]), 1)
            except ValueError:
                logger.warning("skipping unparseable partition %s", partition.name)
                continue
            try:
                _verbatim(settings, feed, partition, as_date, runs, logger, record,
                          month=month)
            except Exception as exc:
                record.items_failed += 1
                record.add_error(f"{feed} {month}: {type(exc).__name__}: {exc}")
                logger.exception("%s %s failed to manifest", feed, month)


def _verbatim(settings, feed, partition, date, runs, logger, record, month=None):
    """Already-compressed payloads: checksum and describe, but never recompress."""
    if (partition / manifest.MANIFEST_NAME).exists():
        return False
    payload = manifest.build(feed, date, partition, run_records=runs,
                             job_name=job_for_feed(feed), month=month)
    manifest.write(partition, payload)
    _append_index(settings, manifest.index_entry(
        payload, str(partition.relative_to(settings.data_dir)).replace("\\", "/"),
        payload["completeness"]["total_bytes"]))
    record.items_ok += 1
    logger.info("%s %s: kept verbatim, %s manifested (recompression measured +0.0%%)",
                feed, partition.name, storage.human_bytes(payload["completeness"]["total_bytes"]))
    return True


@job(
    "archive",
    schedule="0 5 * * *",
    description="Compress the previous day to zstd, manifest it, verify, and index",
)
def collect(logger, record, settings, date=None):
    target = date or (today() - timedelta(days=1))
    partition = f"date={target.isoformat()}"
    logger.info("archiving %s", target.isoformat())

    if shutil.which("zstd") is None:
        raise RuntimeError("zstd not found on PATH; install zstd in the image")

    cadences = _cadences()
    # Forward window: nightly jobs run after midnight, so the record for collecting
    # `target` is filed under a later date.
    runs = metrics.read_window(target)

    found = False
    for feed_dir in sorted(settings.data_dir.glob("feed=*")):
        if not feed_dir.is_dir():
            continue
        feed = feed_dir.name.split("=", 1)[1]
        if feed in MONTHLY_FEEDS:
            continue  # handled below, a month at a time

        day = feed_dir / partition
        if not day.is_dir():
            continue
        found = True

        try:
            if feed in VERBATIM_FEEDS:
                _verbatim(settings, feed, day, target, runs, logger, record)
            else:
                _archive(settings, feed, [day], feed_dir / f"{partition}.tar.zst",
                         target, cadences.get(job_for_feed(feed)), runs, logger, record)
        except Exception as exc:  # one feed must not abort the rest of the night
            record.items_failed += 1
            record.add_error(f"{feed}: {type(exc).__name__}: {exc}")
            logger.exception("%s failed to archive", feed)

    _archive_month(settings, target, runs, cadences, logger, record)
    _manifest_month_partitions(settings, runs, logger, record)

    # The day's logs are archived last, so they include this run's own record.
    log_day = settings.log_dir / partition
    if log_day.is_dir():
        found = True
        try:
            _archive(settings, "logs", [log_day], settings.log_dir / f"{partition}.tar.zst",
                     target, None, runs, logger, record)
        except Exception as exc:
            record.items_failed += 1
            record.add_error(f"logs: {type(exc).__name__}: {exc}")
            logger.exception("logs failed to archive")

    if not found:
        record.items_empty = 1
        logger.warning("nothing to archive for %s", target.isoformat())


def _archive_month(settings, target, runs, cadences, logger, record):
    """Bundle slow-changing feeds once their month is complete.

    Only runs when the previous month has ended, so a month is never archived while
    days are still being added to it.
    """
    first_of_month = target.replace(day=1)
    if target != first_of_month:
        return
    previous = first_of_month - timedelta(days=1)
    prefix = previous.strftime("%Y-%m")

    for feed in sorted(MONTHLY_FEEDS):
        feed_dir = settings.data_dir / f"feed={feed}"
        if not feed_dir.is_dir():
            continue
        partitions = sorted(p for p in feed_dir.glob(f"date={prefix}-*") if p.is_dir())
        if not partitions:
            continue
        try:
            _archive(settings, feed, partitions, feed_dir / f"month={prefix}.tar.zst",
                     previous, cadences.get(job_for_feed(feed)), runs, logger, record)
        except Exception as exc:
            record.items_failed += 1
            record.add_error(f"{feed} monthly: {type(exc).__name__}: {exc}")
            logger.exception("%s monthly archive failed", feed)
