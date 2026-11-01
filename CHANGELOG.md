# Changelog

Every image pushed to `ghcr.io/renj1ete0/british-shorthair` is tagged twice: with its
version (for example `2.2.0`) and with `latest`, which the server and Watchtower follow.
The version is set in `scripts/bsh/__init__.py`. Bump it and add an entry here for
every push.

## 2.3.0 - 2026-11-01

### Changed
- Base image moved from `python:3.13-slim` (Debian) to `python:3.14-alpine3.24`
  (Python 3.14.10). The image shrinks from 162 MB to 76 MB.
- supercronic v0.2.48 → v0.2.51 (Go and dependency updates, refreshed CA certs).
  Checksums are the SHA1SUMs published with the release.
- python-dotenv 1.2.2 → 1.2.4. requests 2.34.2 was already the latest. The transitive
  dependencies resolve to urllib3 2.8.0, certifi 2026.10.23, idna 3.20 and
  charset-normalizer 3.5.2.

### Security
- Trivy scan of the image: 0 vulnerabilities (OS packages, Python packages and the
  supercronic binary). pip-audit: no known vulnerabilities.
- pip is removed from the final image. Nothing installs packages at runtime, and
  pip's own vendored urllib3 2.7.0, msgpack 1.1.2 and setuptools 70.3.0 carried
  5 HIGH CVEs (including CVE-2026-97687, CVE-2026-114613 and CVE-2025-47273).
- curl is only used to download supercronic during the build and isn't in the
  final image.
- `apk upgrade` at build time picks up OS fixes released after the base image.

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
