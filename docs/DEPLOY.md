# Deploying to a new server

The collector runs as one container driven by supercronic, with Watchtower alongside to
pull updates. The server never builds the image — it pulls a published one.

**Why the server cannot build:** the image includes local-only modules that are
gitignored on purpose (see the README). A clone of this repository does not contain
them, so a server-side `docker compose build` would produce an image missing the batch
collector. Builds happen on your machine, where those files exist.

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

# One-off: create a multi-arch buildx builder (the default driver cannot push
# multi-platform images).
docker buildx create --use --name multi --driver docker-container

# Build for amd64 and arm64, then push. Run from the repository root.
docker compose -f docker/docker-compose.yml build
docker compose -f docker/docker-compose.yml push
```

Then confirm the package is **Private** under
`github.com/users/renj1ete0/packages/container/british-shorthair/settings`. As the
owner you already have pull access; nothing else needs granting for a single-user
setup.

---

## 2. Prepare the server

Install Docker Engine and the compose plugin, then:

```bash
sudo mkdir -p /srv/british-shorthair
```

No ownership fix needed: the entrypoint starts as root, chowns the data volume to the
unprivileged `bsh` user, then drops privileges before handing over to supercronic.

**Disk:** budget ~3.3 GB/day (~1.2 TB/year) before archival — bus arrival ~1.8 GB,
EV charging ~0.9 GB, carpark ~0.6 GB. Nightly archival compresses a completed day
heavily, so steady-state usage is far lower, but the volume must hold the raw current
day plus however many archives you keep.

---

## 3. Configure

Copy `docker/docker-compose.yml` and `.env.example` to the server. Rename the latter to
`.env` and fill in:

| Variable                                 | Notes                                                                                                                                  |
| ---------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| `API_KEY`                                | Your LTA DataMall key. The only variable strictly required to collect.                                                                 |
| `LTA_API_KEYS`                           | Optional. Several keys, to spread load. Overridden by `API_KEY`.                                                                       |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Optional; blank disables notifications.                                                                                                |
| `BSH_DATA_PATH`                          | Optional. Defaults to `./data` beside the compose file. Set it to put data on a bigger disk, or when the repo sits in a synced folder. |
| `BSH_IMAGE`                              | `ghcr.io/renj1ete0/british-shorthair:latest`                                                                                           |
| `REGISTRY_USER`                          | Your GitHub login — must match the image namespace exactly.                                                                            |
| `REGISTRY_TOKEN`                         | PAT with **`read:packages` only**. Never put a `write:packages` or `repo`-scoped token on a server.                                    |

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
docker compose -f docker-compose.yml up -d
docker logs -f british-shorthair
```

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

# Data landing?
find /srv/british-shorthair -name '*.txt.gz' | tail -5

# Health of every run today
cat /srv/british-shorthair/logs/date=$(date +%F)/runs.jsonl | tail
```

Bus arrival snapshots should appear about every 20 seconds, named `HHMMSS.txt.gz`.
A healthy series has filenames 20 seconds apart.

---

## 5. Updates

Watchtower polls GHCR hourly, and pulls and restarts the collector when the digest of
`:latest` changes. To ship a change: build and push from your machine, and the server
picks it up within the hour.

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

| Symptom                            | Cause                                                                                   |
| ---------------------------------- | --------------------------------------------------------------------------------------- |
| Container restart-loops at startup | Generated crontab failed validation; the offending line is printed above the error.     |
| `LTA_API_KEYS is empty`            | `.env` not loaded — check `env_file` path is relative to the compose file.              |
| Permission denied writing `/data`  | Bind mount not owned by uid 1000.                                                       |
| Watchtower never updates           | Missing/expired `REGISTRY_TOKEN`, or the server was never `docker login`-ed to ghcr.io. |
| `exec format error`                | Image architecture does not match the server; rebuild with the right `--platform`.      |
| Arrival files sparse or absent     | Check `runs.jsonl` for that job — validation failures and retries are recorded there.   |
