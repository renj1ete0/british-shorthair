"""HTTP with retry, backoff and deadlines.

Every outbound call in this project goes through :class:`Fetcher`. A request is
retried when it fails *or* when it succeeds with the wrong payload — validation
failures (see :mod:`bsh.validation`) are retried on the same backoff as a 503, which
is what makes "check the response is actually for the date/stop we asked for"
useful rather than merely informative.

Backoff is exponential with full jitter. Jitter matters here because bus arrival
fans out ~2500 concurrent requests: without it, a single upstream blip would
resynchronise every worker into the same retry instant and hammer the API.
"""

import random
import time
from dataclasses import dataclass

import requests
from requests.adapters import HTTPAdapter

from .config import get_settings
from .validation import ValidationError

# Transient by nature: worth another go.
RETRY_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


class FetchError(Exception):
    """A request failed after exhausting its retry budget or deadline."""


@dataclass(frozen=True)
class RetryPolicy:
    attempts: int = 4
    base_delay: float = 0.5
    max_delay: float = 20.0
    timeout: float = 30.0

    @classmethod
    def default(cls):
        settings = get_settings()
        return cls(
            attempts=settings.retry_attempts,
            base_delay=settings.retry_base_delay,
            max_delay=settings.retry_max_delay,
            timeout=settings.request_timeout,
        )


class Deadline:
    """An absolute time budget shared across a fan-out of requests."""

    def __init__(self, seconds=None):
        self.seconds = seconds
        self._start = time.monotonic()

    def remaining(self):
        if self.seconds is None:
            return float("inf")
        return self.seconds - (time.monotonic() - self._start)

    def expired(self):
        return self.remaining() <= 0

    def elapsed(self):
        return time.monotonic() - self._start


def _backoff(attempt, policy):
    """Full-jitter exponential backoff for a 1-indexed attempt number."""
    ceiling = min(policy.max_delay, policy.base_delay * (2 ** (attempt - 1)))
    return random.uniform(0, ceiling)


def _retry_after(response):
    """Honour a server-supplied Retry-After, in seconds, when present and sane."""
    raw = response.headers.get("Retry-After")
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if 0 <= value <= 300 else None


class Fetcher:
    """A pooled session that retries, validates and respects a deadline."""

    def __init__(self, logger=None, record=None, pool_size=64):
        self.logger = logger
        self.record = record
        self.session = requests.Session()
        adapter = HTTPAdapter(
            pool_connections=pool_size,
            pool_maxsize=pool_size,
            max_retries=0,  # retries are handled here, with validation in the loop
        )
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def close(self):
        self.session.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.close()
        return False

    def _note_retry(self):
        if self.record is not None:
            self.record.retries += 1

    def _sleep(self, delay, deadline, label):
        """Sleep for the backoff unless the deadline would be blown; report which."""
        if deadline is not None:
            remaining = deadline.remaining()
            if remaining <= 0:
                raise FetchError(f"{label}: deadline exceeded")
            if delay >= remaining:
                raise FetchError(f"{label}: deadline would be exceeded by {delay:.1f}s backoff")
        time.sleep(delay)

    def get_json(self, url, params=None, headers=None, validator=None, policy=None, deadline=None,
                 label=None):
        """GET, parse JSON, validate, retrying transient failures with backoff.

        ``validator`` receives the parsed payload and returns the value to hand back
        (so it can narrow, e.g. to a ``Services`` list). Raising
        :class:`~bsh.validation.ValidationError` triggers a retry;
        :class:`~bsh.validation.PermanentValidationError` does not.
        """
        policy = policy or RetryPolicy.default()
        label = label or url
        last = "no attempt made"

        for attempt in range(1, policy.attempts + 1):
            if deadline is not None and deadline.expired():
                raise FetchError(f"{label}: deadline exceeded before attempt {attempt}")

            timeout = policy.timeout
            if deadline is not None:
                timeout = max(0.1, min(timeout, deadline.remaining()))

            try:
                response = self.session.get(url, params=params, headers=headers, timeout=timeout)
            except requests.RequestException as exc:
                last = f"{type(exc).__name__}: {exc}"
            else:
                if response.status_code in RETRY_STATUS:
                    last = f"HTTP {response.status_code}"
                    pause = _retry_after(response)
                    if pause is not None and attempt < policy.attempts:
                        self._note_retry()
                        self._log_retry(label, attempt, policy, last, pause)
                        self._sleep(pause, deadline, label)
                        continue
                elif not response.ok:
                    # 4xx other than the transient set: a retry will fail identically.
                    raise FetchError(f"{label}: HTTP {response.status_code} {response.text[:200]}")
                else:
                    try:
                        payload = response.json() if response.content else None
                    except ValueError as exc:
                        last = f"invalid JSON: {exc}"
                    else:
                        if validator is None:
                            return payload
                        try:
                            return validator(payload)
                        except ValidationError as exc:
                            if not exc.retryable:
                                raise FetchError(f"{label}: {exc}") from exc
                            last = f"validation failed: {exc}"

            if attempt >= policy.attempts:
                break
            self._note_retry()
            delay = _backoff(attempt, policy)
            self._log_retry(label, attempt, policy, last, delay)
            self._sleep(delay, deadline, label)

        raise FetchError(f"{label}: giving up after {policy.attempts} attempts ({last})")

    def _log_retry(self, label, attempt, policy, reason, delay):
        if self.logger:
            self.logger.warning(
                "retry %d/%d for %s in %.1fs (%s)", attempt, policy.attempts, label, delay, reason
            )

    def get_paginated(self, url, headers=None, page_size=500, policy=None, deadline=None,
                      label=None, max_pages=200):
        """Collect every record from a ``$skip``-paginated LTA dataset.

        The old implementation used a bare ``except`` as its stop condition, so a
        transient error midway silently truncated the dataset and still reported
        success. Here a failed page raises, and only a genuinely short page ends
        the loop.
        """
        label = label or url
        records = []
        for page in range(max_pages):
            skip = page * page_size
            payload = self.get_json(
                url,
                params={"$skip": skip},
                headers=headers,
                policy=policy,
                deadline=deadline,
                label=f"{label}[$skip={skip}]",
            )
            batch = (payload or {}).get("value", [])
            if not isinstance(batch, list):
                raise FetchError(f"{label}: page at $skip={skip} has no value list")
            records.extend(batch)
            if len(batch) < page_size:
                return records
        raise FetchError(f"{label}: exceeded {max_pages} pages; refusing to loop further")

    def download(self, url, destination, policy=None, deadline=None, label=None, chunk=1 << 20):
        """Stream a file to disk with retries, writing via a temp file.

        Written to ``.part`` and renamed on success so a truncated download can never
        be mistaken for a complete archive.
        """
        policy = policy or RetryPolicy.default()
        label = label or destination.name
        temp = destination.with_suffix(destination.suffix + ".part")
        last = "no attempt made"

        for attempt in range(1, policy.attempts + 1):
            if deadline is not None and deadline.expired():
                raise FetchError(f"{label}: deadline exceeded before attempt {attempt}")
            try:
                destination.parent.mkdir(parents=True, exist_ok=True)
                written = 0
                with self.session.get(url, stream=True,
                                      timeout=get_settings().download_timeout) as response:
                    if response.status_code in RETRY_STATUS:
                        last = f"HTTP {response.status_code}"
                        raise requests.RequestException(last)
                    response.raise_for_status()
                    with open(temp, "wb") as handle:
                        for block in response.iter_content(chunk_size=chunk):
                            if block:
                                handle.write(block)
                                written += len(block)
                if written == 0:
                    last = "empty download"
                    raise requests.RequestException(last)
                temp.replace(destination)
                return written
            except (requests.RequestException, OSError) as exc:
                last = f"{type(exc).__name__}: {exc}"
                temp.unlink(missing_ok=True)
                if attempt >= policy.attempts:
                    break
                self._note_retry()
                delay = _backoff(attempt, policy)
                self._log_retry(label, attempt, policy, last, delay)
                self._sleep(delay, deadline, label)

        raise FetchError(f"{label}: download failed after {policy.attempts} attempts ({last})")
