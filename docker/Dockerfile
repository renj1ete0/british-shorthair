# British Shorthair collector.
#
# Runs its own schedule via supercronic, which unlike crond logs job output to
# stdout (so `docker logs` works), handles signals properly as a container process,
# and does not need root.
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Singapore \
    BSH_DATA_DIR=/data

# zstd drives archival: measured 121x on a day of snapshots against 40x for per-file
# gzip, and its long-range matcher survives multithreading where xz's block splitting
# does not. tzdata is required for Asia/Singapore - every schedule and filename is SGT.
RUN apt-get update && apt-get install -y --no-install-recommends \
        zstd \
        tzdata \
        ca-certificates \
        curl \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

# supercronic ships per-architecture binaries. TARGETARCH is supplied by buildx, so
# the same Dockerfile builds for an amd64 workstation and an arm64 server without
# edits. Checksums verified against the published binaries on 2026-08-10; a wrong or
# substituted download fails the build rather than shipping silently.
ARG TARGETARCH
ARG SUPERCRONIC_VERSION=v0.2.48
ARG SUPERCRONIC_SHA1_AMD64=016b7c9aebfc8d9fd9526e8ba33b191fc524485f
ARG SUPERCRONIC_SHA1_ARM64=2ab9b3bdcf290f60b59700aad876b6e68f3a6b06
RUN set -eu; \
    case "${TARGETARCH}" in \
      amd64) sha="${SUPERCRONIC_SHA1_AMD64}" ;; \
      arm64) sha="${SUPERCRONIC_SHA1_ARM64}" ;; \
      *) echo "unsupported TARGETARCH: ${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    binary="supercronic-linux-${TARGETARCH}"; \
    curl -fsSLO "https://github.com/aptible/supercronic/releases/download/${SUPERCRONIC_VERSION}/${binary}"; \
    echo "${sha}  ${binary}" | sha1sum -c -; \
    chmod +x "${binary}"; \
    mv "${binary}" /usr/local/bin/supercronic

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY scripts/ /app/scripts/
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Unprivileged. UID 1000 so bind-mounted data stays writable by the usual host user.
# The chmod normalises modes carried over from the build host: directories copied from
# a Windows/OneDrive checkout arrive as read-only (555), which is harmless here but
# confusing to debug.
RUN useradd --create-home --uid 1000 bsh \
    && mkdir -p /data \
    && chown -R bsh:bsh /app /data \
    && chmod -R u+rwX /app
USER bsh

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["supercronic", "-passthrough-logs", "/tmp/crontab"]
