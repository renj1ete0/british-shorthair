# Deploying to a new server

The collector runs as one container driven by supercronic, with Watchtower alongside to
pull updates. The server never builds the image — it pulls a published one.

**Why the server cannot build:** the image includes local-only modules that are
gitignored on purpose (see the README). A clone of this repository does not contain
them, so a server-side `docker compose build` would produce an image missing the batch
collector. Builds happen on your machine, where those files exist.

## The flow at a glance

```
  your machine                       GHCR (private)                server
  ────────────                       ──────────────                ──────
  docker buildx build --push  ──▶   british-shorthair:latest  ◀──  docker compose pull / up --no-build
  (step 1, again per change)                                ◀──  Watchtower checks hourly, pulls, restarts
```

- **Built here, run there.** You build and push from your machine. The server never
  builds and never needs the source code.
- **The server needs only two files:** `docker/docker-compose.yml` and a filled-in `.env`,
  in the same layout as the repository (step 3).
- **Updates are automatic.** After the first launch you never touch the server to deploy:
  push a new image and Watchtower rolls it out within the hour (step 5).

---

## 1. Publish the image (once, from your machine)

The package must be **private**. The image contains a module whose API terms forbid
redistribution, and anyone who can pull the image can read it.

GHCR packages are private by default, have no per-account private-repo limit, and no
pull rate limits.

```bash
# One-off: log in with a GitHub personal access token (classic) that has
# write:packages. Paste the token as the password.
echo $GITHUB_TOKEN | docker login ghcr.io -u renj1ete0 --password-stdin

# Build for the server's architecture and push. --platform matters: an image built
# on an amd64 workstation will not run on an arm64 server.
docker buildx build \
  --platform linux/arm64 \
  -f docker/Dockerfile \
  -t ghcr.io/renj1ete0/british-shorthair:2.2.0 \
  -t ghcr.io/renj1ete0/british-shorthair:latest \
  --push .
```

**Every push carries two tags:** the version from `scripts/bsh/__init__.py` and
`latest`. The server and Watchtower follow `latest`; the version tag is a fixed point
to roll back to. Before each push, bump `__version__` and add a `CHANGELOG.md` entry.
On boot the container announces the version it is running (see CHANGELOG 2.2.0).

With Podman (`podman login ghcr.io` first), build once and push each tag:

```bash
V=2.2.0
podman build --platform linux/amd64 -f docker/Dockerfile \
  -t ghcr.io/renj1ete0/british-shorthair:$V -t ghcr.io/renj1ete0/british-shorthair:latest .
podman push ghcr.io/renj1ete0/british-shorthair:$V
podman push ghcr.io/renj1ete0/british-shorthair:latest
```

Then confirm the package is **Private** under
`github.com/users/renj1ete0/packages/container/british-shorthair/settings`. As the
owner you already have pull access; nothing else needs granting for a single-user
setup.

Building both architectures at once, if you ever want the same tag to run anywhere:

```bash
docker buildx build --platform linux/amd64,linux/arm64 \
  -t ghcr.io/renj1ete0/british-shorthair:latest --push .
```

---

## 2. Prepare the server

Install Docker Engine and the compose plugin, then:

```bash
sudo mkdir -p /srv/british-shorthair
sudo chown 1000:1000 /srv/british-shorthair    # container runs as uid 1000
```

The ownership step matters: the container is unprivileged, and a root-owned bind mount
gives permission errors on the first write rather than at startup.

**Disk:** budget ~3.3 GB/day (~1.2 TB/year) before archival — bus arrival ~1.8 GB,
EV charging ~0.9 GB, carpark ~0.6 GB. Nightly archival compresses a completed day
heavily, so steady-state usage is far lower, but the volume must hold the raw current
day plus however many archives you keep.

---

## 3. Configure

The compose file refers to `../.env` and `../data`, so keep the repository's layout on
the server: a folder holding `.env`, with the compose file in a `docker/` subfolder.

```bash
# on the server
mkdir -p ~/british-shorthair/docker

# from your machine, in the repository root
scp docker/docker-compose.yml server:~/british-shorthair/docker/
scp .env.example              server:~/british-shorthair/.env
```

Result:

```
~/british-shorthair/
├── .env                      ← secrets and settings
└── docker/
    └── docker-compose.yml
```

Edit `~/british-shorthair/.env` and fill in:

| Variable | Notes |
|---|---|
| `API_KEY` | Your LTA DataMall key. The only variable strictly required to collect. |
| `LTA_API_KEYS` | Optional. Several keys, to spread load. Overridden by `API_KEY`. |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Optional; blank disables notifications. |
| `BSH_DATA_PATH` | Set to `/srv/british-shorthair` (the directory from step 2). If left unset, data goes to `~/british-shorthair/data`. The commands below assume `/srv/british-shorthair`. |
| `BSH_IMAGE` | `ghcr.io/renj1ete0/british-shorthair:latest` |
| `REGISTRY_USER` | Your GitHub login — must match the image namespace exactly. |
| `REGISTRY_TOKEN` | PAT with **`read:packages` only**. Never put a `write:packages` or `repo`-scoped token on a server. |

Write `KEY=value` with **no spaces around `=`**. Docker's env-file parser rejects
`KEY = value` outright and the stack will not start.

```bash
chmod 600 .env       # it holds API keys and a registry token
```

The server also needs to authenticate for the first pull:

```bash
echo $GITHUB_TOKEN | docker login ghcr.io -u renj1ete0 --password-stdin
```

---

## 3a. Telegram (optional but recommended)

Without this the collector still runs and still logs; you just find out about failures
by looking rather than by being told.

**Create the bot.** Message [@BotFather](https://t.me/BotFather) → `/newbot` → give it a
display name, then a username ending in `bot`. It replies with a token like
`8123456789:AAH...`. That token is a credential — treat it like a password.

**Get the chat id.** A bot cannot open a conversation with you, so you must message it
first or it will never be able to reply:

1. Open your new bot and send it anything (`/start`).
2. Fetch the id:

```bash
curl -s "https://api.telegram.org/bot<TOKEN>/getUpdates" \
  | grep -o '"chat":{"id":[-0-9]*' | head -1
```

Your personal chat id is a positive number. For a group, add the bot to the group,
send a message there, and use the **negative** id that appears instead.

**Configure and verify:**

```bash
# in .env
TELEGRAM_BOT_TOKEN=8123456789:AAH...
TELEGRAM_CHAT_ID=123456789

docker exec british-shorthair python /app/scripts/run_job.py notify_test
```

That sends one alert and one digest — both paths, since they behave differently
(alerts are deduplicated with a cooldown, digests are not). Two messages arriving means
failure alerts and the 23:55 daily summary will both reach you.

If nothing arrives, the cause is almost always one of: you never messaged the bot, the
chat id belongs to a different conversation, or the token was copied with surrounding
whitespace.

---

## 4. Start

```bash
cd ~/british-shorthair
docker compose --env-file .env -f docker/docker-compose.yml pull
docker compose --env-file .env -f docker/docker-compose.yml up -d --no-build
docker logs -f british-shorthair
```

- `--env-file .env` is required. Compose otherwise looks for `.env` next to the compose
  file (in `docker/`), finds nothing, and quietly falls back to defaults. Watchtower then
  has no registry credentials and `BSH_DATA_PATH` is ignored.
- `--no-build` stops Compose from trying to build. The file has a `build:` section for
  your machine, and there is no source on the server to build from.

This is the only time you start it by hand. Both containers use
`restart: unless-stopped`, so they come back after a reboot or a Docker restart.
Stop the stack with `docker compose --env-file .env -f docker/docker-compose.yml down`.

On first start with an empty volume the container:

1. generates its crontab from the job registry,
2. validates it with `supercronic -test` and refuses to start if it is malformed,
3. bootstraps the bus stop list (`bus_essentials`), since the arrival jobs read it
   every run,
4. hands over to supercronic.

### Checking it worked

```bash
# Jobs firing?
docker logs british-shorthair 2>&1 | grep "job succeeded" | tail

# Data landing? Carpark runs every minute, so this should list a file.
find /srv/british-shorthair/feed=carpark -name '*.ndjson' -mmin -5

# Healthcheck status (runs the same carpark test; "starting" for the first few minutes)
docker inspect --format '{{.State.Health.Status}}' british-shorthair

# Health of every run today
cat /srv/british-shorthair/logs/date=$(date +%F)/runs.jsonl | tail
```

Carpark appends to an hourly `feed=carpark/date=.../hour=HH/snapshots.ndjson`, so that
file should have changed in the last few minutes.

**Bus arrival:** snapshots every 20 seconds (`feed=bus_arrival_batch/.../HHMMSS.txt.gz`)
come only from the local-only collector module. If your image doesn't include it, you
won't see those files, and that's expected. The `bus_arrival` job in this repository is
on demand only and writes nothing unless you run it by hand.

---

## 5. Updates

Watchtower polls GHCR hourly, and pulls and restarts the collector when the digest of
`:latest` changes. To ship a change, re-run the `docker buildx build ... --push` from
step 1 on your machine. The server picks it up within the hour, with nothing to run
there.

A change to `docker-compose.yml` itself is the exception. Watchtower updates images,
not compose files, so copy the new file over and re-run the `up -d --no-build` command
from step 4.

Two consequences worth being deliberate about:

- **A broken push deploys itself.** Rolling back means pushing a fixed image, so test
  locally before pushing. If that risk is unwanted, point servers at a `:stable` tag
  and promote by retagging once you are satisfied.
- **Watchtower needs `REPO_USER`/`REPO_PASS` for a private package.** Without them it
  cannot see the image and silently never updates — no error, just nothing happening.

Force an immediate check:

```bash
docker restart british-shorthair-watchtower
```

---

## 6. Migrating older data

Not required to start. The collector begins collecting forward from an empty volume.

When you want the pre-2026-08 history alongside new data, copy the legacy tree to the
server and run the migration — a dry run first, which writes nothing:

```bash
docker exec british-shorthair python /app/scripts/run_job.py \
  migrate_legacy --from /legacy
docker exec british-shorthair python /app/scripts/run_job.py \
  migrate_legacy --from /legacy --days 1     # apply
```

It copies rather than moves, so the legacy tree is untouched and a mistake costs only
disk. See `docs/DATA.md` for what it converts and what it deliberately leaves alone.

---

## Troubleshooting

| Symptom | Cause |
|---|---|
| Container restart-loops at startup | Generated crontab failed validation; the offending line is printed above the error. |
| `LTA_API_KEYS is empty` | `.env` not loaded. It must sit one level above `docker/docker-compose.yml`. |
| `docker ps` shows `unhealthy` | No carpark write in 10 minutes. Check `runs.jsonl` for carpark errors (API key, network). |
| Compose tries to build, or errors about the build context | `--no-build` was left off on the server. |
| Permission denied writing `/data` | Bind mount not owned by uid 1000. |
| Watchtower never updates | Missing/expired `REGISTRY_TOKEN`, or the server was never `docker login`-ed to ghcr.io. |
| `exec format error` | Image architecture does not match the server; rebuild with the right `--platform`. |
| Arrival files sparse or absent | Check `runs.jsonl` for that job — validation failures and retries are recorded there. |
