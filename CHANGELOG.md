# Changelog

Every image pushed to `ghcr.io/renj1ete0/british-shorthair` is tagged twice: with its
version (for example `2.2.0`) and with `latest`, which the server and Watchtower follow.
The version is set in `scripts/bsh/__init__.py`. Bump it and add an entry here for
every push.

## 2.2.0 - 2026-11-01

### Added
- On every boot the collector logs and sends (via Telegram) a startup notice that
  names its version: "British Shorthair updated 2.1.0 → 2.2.0" after a Watchtower
  update, "… 2.2.0 restarted" on a plain restart, "… 2.2.0 started" on a fresh volume.
  Watchtower's own notice names only the `:latest` tag, so it can't say which version
  is live. The last announced version is kept in `state/last_version.json`.
  Run it by hand with `python run_job.py --announce`.
- `Fetcher.download` takes a per-call timeout, so jobs fetching small files on a
  tight cadence fail fast instead of holding their lock for the global download timeout.
- This changelog.

### Fixed
- The container no longer crash-loops when built from a Windows checkout with CRLF
  line endings (`exec … entrypoint.sh: no such file or directory`). The build strips
  CRs and `.gitattributes` pins `*.sh` to LF.
- The healthcheck watches `feed=carpark` (written every minute) instead of the
  pre-rewrite bus arrival path, which never matched and left the container
  permanently unhealthy.
- `__version__` in code was still `2.0.0` while the published image was `2.1.0`.
  Fixed by this bump; manifests now record the real version.

### Docs
- DEPLOY.md: build-here/run-there overview, the server file layout, pull +
  `up --no-build` launch, carpark-based checks, `--env-file .env` on every compose
  command, and the version-tagging build step.

## 2.1.0 - 2026-08-25

- First published image of the rewrite: a containerised, self-monitoring collector
  scheduled by supercronic, with Telegram alerts, a daily digest and Watchtower
  auto-updates.
