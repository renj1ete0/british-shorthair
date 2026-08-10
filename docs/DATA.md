# Data layout and archival

How collected data is stored, how to read it back, and how it is compressed for cold
storage. All dates and times are Asia/Singapore.

---

## 1. The convention

Every collected dataset uses one shape:

```
<data>/feed=<name>/date=YYYY-MM-DD[/hour=HH]/<file>
```

with two variations, each for a stated reason:

| Path | When |
|---|---|
| `feed=<name>/date=YYYY-MM-DD/` | daily feeds — one write per day |
| `feed=<name>/date=YYYY-MM-DD/hour=HH/` | sub-daily feeds — `hour=` only where a day holds many files |
| `feed=<name>/month=YYYYMM/` | monthly datasets (passenger volume) |

Alongside them:

| Directory | Contents |
|---|---|
| `logs/date=YYYY-MM-DD/` | Per-day logs and run metrics |
| `state/` | Lock files, alert cooldowns — runtime only, not data |
| `busstop_current.json` | Newest bus stop list; a pointer to current state, not a dated observation, so deliberately unpartitioned |

### Why `key=value`

These are **Hive-style partitions**. Query engines parse the path segments into real
columns, so `feed`, `date` and `hour` are queryable without a directory walk or any
string parsing. Verified with DuckDB — `date` arrives typed as `DATE`, not text.

### How it stays consistent

Jobs do not build paths. They call `storage.feed_path()`, which is the only function
that constructs an output directory and which **enforces** the rules — exactly one of
`date`/`month`, and `hour` only alongside `date`. A new job cannot invent its own
layout without deliberately bypassing it.

This is also what lets the archive job discover work by globbing `feed=*/date=<target>`
rather than maintaining a list of feeds: add a job, and it is archived automatically.

### File naming

- **Several files per partition** → name for the time: `HHMMSS.json`
- **One file per partition** → name for the content: `readings.csv`, `routes.json`

---

## 2. Feed reference

### LTA DataMall

| Feed | Partition | File | Format | Cadence |
|---|---|---|---|---|
| `bus_arrival_batch` | `date/hour` | `HHMMSS.txt.gz` | gzipped CSV variant | 20s |
| `bus_arrival` | `date/hour` | `HHMMSS.json` | JSON | on demand |
| `carpark` | `date/hour` | `snapshots.ndjson` | NDJSON, one line per poll | 1m |
| `train_alerts` | `date/hour` | `snapshots.ndjson` | NDJSON | 5m |
| `crowd_density` | `date/hour` | `snapshots.ndjson` | NDJSON | 10m |
| `ev_charging` | `date/hour` | `HHMMSS.json` | JSON | 5m |
| `gtfs_trip_updates` | `date/hour` | `HHMMSS.pb` | GTFS-RT protobuf | 5m |
| `gtfs_schedule` | `date` | `schedule.zip` | GTFS static zip | daily |
| `crowd_forecast` | `date` | `forecast.json` | JSON | daily |
| `essentials` | `date` | `busstop.json`, `busroute.json`, `busservice.json` | JSON | daily |
| `planned_bus_routes` | `date` | `routes.json` | JSON | daily |
| `passenger_volume` | `month` | `PV_BUSSTOPS.zip` etc. | zip | monthly |

### NEA weather

`feed=weather_<dataset>/date=YYYY-MM-DD/`, collected nightly for the previous day. All
CSVs carry a header row.

Flat naming (`weather_rainfall`) rather than nesting under a shared root, so every feed
in the project sits at the same depth and one glob covers all of them.
`feed=weather_*` still selects the weather feeds alone.

| Dataset | Files |
|---|---|
| `rainfall`, `winddir`, `windspeed`, `airtemp`, `rh` | `stations.csv`, `readings.csv` |
| `psi`, `pm25` | `regions.csv`, `readings.csv` |
| `uvidx` | `readings.csv` |
| `24hrforecast` | `general.csv`, `periods.csv` |
| `2hrforecast` | `areas.csv`, `forecasts.csv` |
| `4dayoutlook` | `forecasts.csv` |

`psi` and `pm25` readings are **long form** — `timestamp, update_timestamp, measure,
region, value`. PSI has 11 measures; wide form made "all pollutants for a day" an
11-way join.

Not collected: **Lightning** and **WBGT** return HTTP 403 on both API versions.

### Logs

`logs/date=YYYY-MM-DD/` — the `date=` prefix matches the data convention, so
`runs.jsonl` is queryable across days with the date recovered as a column.

| File | Purpose |
|---|---|
| `<job>.log` | One job's output |
| `all.log` | Every job interleaved |
| `events.jsonl` | Structured events |
| `runs.jsonl` | One record per run — status, counts, retries, bytes. Source for the daily digest |

---

## 3. Reading it back

```sql
-- Every feed that publishes readings, in one glob.
-- 'feed' and 'date' come back as columns; date is typed DATE.
SELECT feed, date, count(*) AS rows
FROM read_csv_auto('feed=*/date=*/readings.csv',
                   hive_partitioning=true, union_by_name=true)
GROUP BY feed, date;

-- Filter on the partition column - no path parsing, and non-matching
-- partitions are never opened.
SELECT feed, count(*) FROM read_csv_auto('feed=weather_*/date=*/readings.csv',
                                         hive_partitioning=true, union_by_name=true)
WHERE date >= DATE '2026-07-01' GROUP BY feed;

-- One day of carpark snapshots
SELECT * FROM read_json_auto('feed=carpark/date=2026-08-09/hour=*/snapshots.ndjson');

-- How healthy was collection?
SELECT job, status, count(*) FROM read_json_auto('logs/date=*/runs.jsonl',
                                                 hive_partitioning=true)
GROUP BY job, status;
```

The bus arrival batch file is a CSV variant rather than standard CSV and needs a
purpose-built parser; writing one is the first step of any Parquet migration. Its
layout is documented in `docs/DATA.local.md`, which is not published — see
[Local-only feeds](#5-local-only-feeds).

---

## 4. Archival policy

Measured on 20 consecutive 1-minute island snapshots, 609.5 MB raw:

| Method | Size | Ratio | Compress | Decompress |
|---|---|---|---|---|
| per-file gzip -9 | 15.3 MB | 40× | 16.6s | 11.8s |
| tar + gzip -9 | 15.3 MB | 40× | 12.9s | 2.0s |
| tar + zstd -12 `--long=31` | 7.1 MB | 85× | 14.7s | 1.8s |
| **tar + zstd -19 `--long=31`** | **5.0 MB** | **121×** | 26.8s | 1.6s |
| tar + xz -9e | 4.3 MB | 143× | 106.0s | 1.0s |
| 7z -mx=9 solid | 5.3 MB | 114× | 38.8s | 1.6s |

Per-file gzip and tar+gzip tie at 40×, which is the point: gzip's 32 KB window cannot
match across files, so everything above that line earns its ratio purely from
**cross-snapshot redundancy**. Consecutive snapshots are ~99% identical.

**zstd -19 `--long=31` is the default.** xz gives 18% better ratio, but a day is ~18 GB
and `xz -T0` splits input into independent blocks, destroying the very cross-block
matching that produced 143×. zstd's long-range matcher survives threading.

### Three treatments

| Group | Feeds | Method | Unit |
|---|---|---|---|
| High-cadence snapshots | `bus_arrival_batch`*, `carpark`, `ev_charging`, `crowd_density`, `train_alerts`, `gtfs_trip_updates` | `tar` + `zstd -19 --long=31` | per day |
| Low-cadence text | `weather_*` | same | per day |
| Slow-changing | `essentials`, `planned_bus_routes` | same | per month |
| **Pre-compressed** | `passenger_volume/*.zip`, `gtfs_schedule/*.zip` | **none** — verbatim + SHA-256 | as-is |

\* `bus_arrival_batch` files arrive gzipped and **must be decompressed before
archiving**. Compressed as-is they stay at 40×; decompressed first they reach 121×.

Measurements behind those choices:

- **Recompressing a zip gains exactly 0.0%.** `PV_OD_BUSSTOPS_202310.zip`: 37.2 MB →
  37.2 MB. Pre-compressed payloads are pure CPU cost.
- **Slow-changing snapshots are nearly free to keep.** Two `busstop.json` 34 days apart
  differ (759,485 vs 761,483 bytes), but compressed together the second costs **0.4%**
  of the first. A year of daily reference snapshots costs about what one costs — so
  bundle monthly and skip content-hash dedup; the compressor does it better.
- **Bundling weather beyond a day buys nothing.** 30 days: per-day summed 3.40 MB (22×)
  vs one monthly archive 3.49 MB (21×) — monthly is 3% *worse*. Weather values genuinely
  differ day to day, so choose per-day for restore granularity.

The cross-snapshot redundancy that makes solid compression pay comes from **cadence**,
not from the feed. Snapshots 20 seconds apart are near-identical; weather readings a
day apart are not.

### Knowing what you restored

An archive opened years later has to answer for itself: seeing 4,180 files says nothing
about whether the feed was down, the night was quiet, or the collector crashed. So
every archive carries a **`_MANIFEST.json`** at its root, written before compression:

```json
{
  "feed": "bus_arrival_batch", "date": "2026-08-08",
  "status": "warnings",
  "warnings": ["2 collection gap(s), largest 340s"],
  "completeness": {
    "files": 13, "expected_files": 4320, "coverage_pct": 0.3,
    "expected_basis": "schedule @every 20s",
    "first": "03:00:00", "last": "03:11:40",
    "gaps": [{"after": "03:01:40", "before": "03:07:20",
              "seconds": 340, "missing_estimate": 16}]
  },
  "runs": {"records_found": 1, "ok": 1, "failed": 0, "retries": 0, "errors": []},
  "quality": {"zero_byte_files": [], "undersized_files": []},
  "integrity": {"algorithm": "sha256", "files": [{"name": "...", "sha256": "..."}]}
}
```

Points worth knowing:

- **Gaps are enumerated, not counted.** "140 missing" could be one 47-minute outage or
  140 scattered blips, and those mean very different things for analysis. The manifest
  gives the intervals.
- **`expected_files` is derived from the job's schedule**, not hardcoded — `@every 20s`
  implies 4,320/day. Feeds on cron schedules report no expectation rather than a
  guessed one.
- **Errors travel with the data.** The day's run records for that feed are embedded, so
  the archive is self-contained; log archives are separate files.
- **`status` is a single field to check** before trusting the contents: `clean` or
  `warnings`.
- Run records are matched on `notes.data_date`, because a nightly job runs after
  midnight and its record is filed under the *following* day. A backfill archived long
  afterwards will honestly report `no run records found` rather than inventing them.

### Finding problems without unpacking

Every archive also appends a line to **`_archive_index.jsonl`** at the data root, so
"which days have gaps?" is answerable without decompressing anything — the difference
between a minute and a week once there is a year of cold storage.

```sql
SELECT feed, date, coverage_pct, gap_count, largest_gap_seconds
FROM read_json_auto('_archive_index.jsonl')
WHERE status <> 'clean' ORDER BY date;
```

The manifest is the source of truth; the index is a cache of it. If they disagree,
believe the manifest — it travels with the bytes.

### Rules

1. Never recompress already-compressed bytes.
2. Always decompress `.gz` snapshots before solid-archiving them.
3. Archive the **original bytes**, never a parsed form. A cold archive is the only
   copy; it must carry no schema decisions or parser bugs, because those are exactly
   what you want to be able to fix later.
4. Verify (`zstd -t`) and check the SHA-256 manifest **before** deleting sources.

### Parquet

Parquet belongs to the **analysis** tier — derive it from cold storage when needed and
treat it as a disposable cache. It is not a smaller archival format: the source is
already densely compressed, and Parquet cannot exploit cross-snapshot redundancy the
way solid compression does. Its value is column pruning and predicate pushdown at query
time.

---

## 5. Local-only feeds

A deployment may collect feeds whose API terms prohibit republishing their
specification. Those collectors live in gitignored modules, are baked into the image at
build time, and their format details are documented in `docs/DATA.local.md`, which is
also gitignored.

`bus_arrival_batch` is one such feed. It appears in the tables above because the
archival policy has to account for it — but its endpoint, access terms and file layout
are deliberately absent from this document. If you are setting up a fresh deployment
and that module is not present, every other feed still runs; see the README.

---

## 6. Legacy data

Data collected before 2026-08-09 used a different layout (`export/<date>/`,
`export_mss/<date>/`) and is **not** migrated. Note also that the `2023-11-26` bus
arrival files are largely unusable: an inverted error branch in the old client recorded
successful HTTP 200 responses as error stubs. Verify other early dates before trusting
them.
