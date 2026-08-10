# British Shorthair

Codename British Shorthair is a project to experiment and understand more about Singapore's Public Transport, specifically the bus network, through urban data science.

This repository runs a containerised collector that pulls from Singapore's open transport and environment APIs on a schedule and archives the results for analysis.

Some of the use cases of this project may include:
- Analysis and insights of bus routes, loading and trip times for planning
- Improved bus arrival timing estimations
- Optimisation of bus schedules, etc.
- Democratisation of open data - Insights allowing citizens to understand more about the city

## Datasets collected

**LTA DataMall** (needs an API key)

| Job | Cadence | Data |
|---|---|---|
| `bus_arrival` | on demand | Real-time arrivals, queried one bus stop at a time |
| `bus_essentials` | daily | Bus stops, routes, services |
| `planned_bus_routes` | daily | Announced upcoming route changes |
| `carpark` | 1m | HDB / LTA / URA carpark availability |
| `train_alerts` | 5m | Train disruptions, free bus and shuttle status |
| `crowd_density` | 10m | Real-time MRT/LRT station crowding, 11 lines |
| `crowd_forecast` | daily | Forecast station crowding, 30-minute intervals |
| `ev_charging` | 5m | Island-wide EV charging point availability |
| `gtfs_trip_updates` | 5m | GTFS-Realtime train trip predictions (protobuf) |
| `gtfs_schedule` | daily | Static GTFS train schedule |
| `datamall_pv` | monthly | Passenger volume: bus stops, train stations, and both O-D matrices |

**NEA via data.gov.sg** (no key required) — `mss`, nightly, 11 datasets: rainfall, wind direction, wind speed, air temperature, relative humidity, PSI, PM2.5, UV index, 2-hour forecast, 24-hour forecast, 4-day outlook.

Two of NEA's 13 published real-time services, **Lightning** and **WBGT**, return HTTP 403 on both the v1 and v2 endpoints and are not collected — they appear to need authorised access.

## Design notes

**Bus arrival is collected every 20 seconds**, matching the API's refresh rate — but by a local-only collector that retrieves the whole island in a single request, not by the `bus_arrival` job in this repository.

The `bus_arrival` job here queries one bus stop at a time, which means ~5,091 requests per snapshot. On a 20s schedule that is roughly 22 million calls a day, far beyond the daily quota that applies to this API, so it is registered **on demand only**. It remains useful for spot checks, for debugging a single stop, and as a fallback. If you schedule it, give it a hard sub-20s deadline: stops not fetched in time are dropped and counted rather than allowed to overrun, and a lock skips a slow tick instead of stacking it.

**Weather is collected nightly, not polled.** Every NEA endpoint serves a full past day for `?date=YYYY-MM-DD`, so one nightly call captures everything. The LTA real-time feeds have no such history, which is why they are polled at their update frequency instead — a missed carpark poll is gone for good.

**Retries cover wrong answers, not just failures.** A 200 with the wrong bus stop, the wrong weather date, or a passenger-volume link pointing at the wrong month is retried on the same exponential backoff as a 503. Backoff uses full jitter, which matters when ~2500 bus stop requests would otherwise resynchronise onto the same retry instant.

**Missed weather days heal themselves.** The nightly job re-checks a 14-day trailing window and re-fetches anything missing, so an outage is recovered without manual intervention.

## Output layout

Full reference — every feed's path, file format, how to query it, and the archival
policy — is in [docs/DATA.md](docs/DATA.md). Summary:

Every feed uses one shape, so a single glob covers all of them:

```
<data dir>/
  feed=<name>/date=YYYY-MM-DD/            daily feeds
  feed=<name>/date=YYYY-MM-DD/hour=HH/    sub-daily feeds
  feed=passenger_volume/month=YYYYMM/     monthly datasets
  logs/date=YYYY-MM-DD/                   all.log, <job>.log, events.jsonl, runs.jsonl
  state/                                  locks and cooldowns
  busstop_current.json                    pointer to the newest stop list
```

These are Hive-style partitions, so query engines recover `feed`, `date` and `hour` as real columns — `date` arrives typed as `DATE`, not text:

```sql
SELECT feed, date, count(*)
FROM read_csv_auto('feed=*/date=*/readings.csv',
                   hive_partitioning=true, union_by_name=true)
WHERE date >= DATE '2026-07-01'
GROUP BY feed, date;
```

Jobs never build paths themselves — they call `storage.feed_path()`, which enforces the convention, so a new job cannot drift from it. The archive job relies on this, discovering work by globbing `feed=*/date=<target>` rather than tracking a list of feeds.

High-frequency feeds append to an hourly NDJSON rather than writing a file per poll — at a one-minute cadence that would otherwise be 1440 files a day per feed.

## Setup

Deploying to a server? See **[docs/DEPLOY.md](docs/DEPLOY.md)** — publishing the image,
configuring the host, and Watchtower updates. The steps below are for running locally.

1. Clone this repository.
2. Copy `.env.example` to `.env` in the repository root and fill it in:
   - `LTA_API_KEYS` — a JSON array. Get keys from [LTA DataMall](https://datamall.lta.gov.sg/content/datamall/en.html). More than one key spreads the 20s bus arrival fan-out across accounts.
   - `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` — optional; leave blank to disable notifications.
   - `BSH_DATA_PATH` — host directory for collected data. Keep it off OneDrive; this grows fast.
3. Start it:

```bash
docker compose -f docker/docker-compose.yml up -d --build
docker logs -f british-shorthair
```

The container generates its own crontab from the job registry on startup and bootstraps the bus stop list if the data volume is empty.

## Running jobs by hand

```bash
docker exec british-shorthair python /app/scripts/run_job.py --list
docker exec british-shorthair python /app/scripts/run_job.py mss --date 2026-08-01
docker exec british-shorthair python /app/scripts/run_job.py mss_backfill --days 120
docker exec british-shorthair python /app/scripts/run_job.py --crontab
```

## Adding a job

1. Write `scripts/bsh/jobs/<name>.py` with a `@job(...)`-decorated function taking `(logger, record, settings)`.
2. Import it in `scripts/bsh/jobs/__init__.py`.

The crontab is generated from the registry, so the schedule lives on the decorator beside the code and the two cannot drift apart. Nothing else needs editing.

## Notifications

Failures alert immediately, deduplicated by key with a 30-minute cooldown so an outage sends one message rather than hundreds. A daily digest at 23:55 SGT reports per-job run counts, items collected, retries, bytes written and distinct errors.

## Updates

Watchtower (`nickfedor/watchtower`) runs alongside and updates labelled containers hourly.

**Caveat:** Watchtower updates images by comparing digests against a **registry**. The collector image is built locally and is not pushed anywhere, so Watchtower cannot update it — it will keep itself current, but rebuilding the collector is a manual `docker compose up -d --build`. To get automatic collector updates, push the image to a registry; if your deployment includes any local-only modules (see below), that registry must be **private**.

## Notes

- All schedules, filenames and date comparisons are Asia/Singapore, independent of the host clock.
- A deployment may include local-only modules that are gitignored but copied into the image at build time. Where that is the case, a build from a fresh clone will not reproduce the running image — build locally. `bsh/jobs/__init__.py` imports such modules optionally, so a clean checkout still runs.
- Collected data before 2026-08-09 used a different layout (`export/<date>/`, `export_mss/<date>/`) and is not migrated.
