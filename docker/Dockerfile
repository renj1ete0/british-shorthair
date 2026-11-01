# British Shorthair collector.
#
# Runs its own schedule via supercronic, which unlike crond logs job output to
# stdout (so `docker logs` works), handles signals properly as a container process,
# and does not need root.
#
# Alpine rather than Debian slim: a much smaller image and fewer OS packages to carry
# CVEs. Everything here is musl-safe - requests and python-dotenv are pure Python,
# supercronic is a static Go binary, and archival uses Python's tarfile plus zstd.
FROM python:3.14-alpine3.24

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Singapore \
    BSH_DATA_DIR=/data

# zstd drives archival: measured 121x on a day of snapshots against 40x for per-file
# gzip, and its long-range matcher survives multithreading where xz's block splitting
# does not. tzdata is required for Asia/Singapore - every schedule and filename is SGT.
# `apk upgrade` picks up OS security fixes released after the base image was built.
RUN apk upgrade --no-cache \
    && apk add --no-cache zstd tzdata ca-certificates \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# supercronic ships per-architecture binaries. TARGETARCH is supplied by buildx, so
# the same Dockerfile builds for an amd64 workstation and an arm64 server without
# edits. Checksums are the SHA1SUMs published with the v0.2.51 release (2026-10-21);
# a wrong or substituted download fails the build rather than shipping silently.
# curl is needed only for this download, so it is removed again in the same layer.
ARG TARGETARCH
ARG SUPERCRONIC_VERSION=v0.2.51
ARG SUPERCRONIC_SHA1_AMD64=1692066e350a88ff4d7d6474fe3c7a6c41ec5e89
ARG SUPERCRONIC_SHA1_ARM64=9d4c2000493215a1898502b2fc2dada3e8ea8c7a
RUN set -eu; \
    apk add --no-cache --virtual .fetch curl; \
    case "${TARGETARCH}" in \
      amd64) sha="${SUPERCRONIC_SHA1_AMD64}" ;; \
      arm64) sha="${SUPERCRONIC_SHA1_ARM64}" ;; \
      *) echo "unsupported TARGETARCH: ${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    binary="supercronic-linux-${TARGETARCH}"; \
    curl -fsSLO "https://github.com/aptible/supercronic/releases/download/${SUPERCRONIC_VERSION}/${binary}"; \
    echo "${sha}  ${binary}" | sha1sum -c -; \
    chmod +x "${binary}"; \
    mv "${binary}" /usr/local/bin/supercronic; \
    apk del .fetch

WORKDIR /app

COPY requirements.txt ./
# pip is removed once the dependencies are in: nothing installs packages at runtime,
# and pip carries its own vendored (older) urllib3, msgpack and setuptools, which
# image scanners flag even though the app's own urllib3 is current.
RUN pip install --no-cache-dir --root-user-action=ignore -r requirements.txt \
    && pip uninstall -y --root-user-action=ignore pip \
    && rm -rf /usr/local/lib/python3.*/ensurepip

COPY scripts/ /app/scripts/
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
# Strip CRs: a Windows checkout with core.autocrlf turns the shebang into "/bin/sh\r",
# and the container then dies with "exec ... entrypoint.sh: no such file or directory".
RUN sed -i 's/\r$//' /usr/local/bin/entrypoint.sh \
    && chmod +x /usr/local/bin/entrypoint.sh

# Unprivileged. UID 1000 so bind-mounted data stays writable by the usual host user.
# The chmod normalises modes carried over from the build host: directories copied from
# a Windows/OneDrive checkout arrive as read-only (555), which is harmless here but
# confusing to debug.
RUN adduser -D -u 1000 bsh \
    && mkdir -p /data \
    && chown -R bsh:bsh /app /data \
    && chmod -R u+rwX /app
USER bsh

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["supercronic", "-passthrough-logs", "/tmp/crontab"]
