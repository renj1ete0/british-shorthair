"""Job registry.

Adding a scheduled job is two steps and no more:

1. Write ``bsh/jobs/<name>.py`` with a ``@job(...)``-decorated function.
2. Import it in ``bsh/jobs/__init__.py``.

The crontab is *generated* from this registry (``run_job.py --crontab``), so a job's
schedule lives next to its code and the two cannot drift apart. Jobs registered with
``schedule=None`` are on-demand only and never appear in the crontab.
"""

import re
from dataclasses import dataclass

_REGISTRY = {}

# Schedules are authored as "@every 20s" because that says what is meant. supercronic
# does not accept that form - it rejects the line outright - so it is translated to
# 6-field cron (with a leading seconds column) when the crontab is generated.
_EVERY = re.compile(r"^@every\s+(\d+)\s*([smh])$", re.IGNORECASE)
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600}


def interval_seconds(schedule):
    """Seconds between runs for an ``@every`` schedule, else None.

    Cron expressions are deliberately not interpreted: a guessed run count reported as
    fact is worse than reporting none.
    """
    if not schedule:
        return None
    match = _EVERY.match(schedule.strip())
    return int(match.group(1)) * _UNIT_SECONDS[match.group(2).lower()] if match else None


def to_cron(schedule):
    """Translate a schedule into a form supercronic accepts.

    Cron expressions pass through unchanged; ``@every`` becomes standard 5-field cron.

    **One minute is the floor.** Verified against supercronic v0.2.48: it rejects
    ``@every`` outright (parsing it as a one-field expression), and its six-field form
    is ``minute hour dom month dow year`` - the extra field is a *year*, not seconds.
    A job needing a faster cadence must be scheduled every minute and poll internally;
    see ``cadence_seconds`` on :class:`Job`.
    """
    if not schedule:
        return schedule
    match = _EVERY.match(schedule.strip())
    if not match:
        return schedule

    count, unit = int(match.group(1)), match.group(2).lower()
    if unit == "s":
        raise ValueError(
            f"'@every {count}s' cannot be scheduled: supercronic has no sub-minute "
            "granularity. Schedule the job '@every 1m' and poll internally, declaring "
            "the real data cadence with cadence_seconds."
        )
    if unit == "m":
        if count < 1 or 60 % count:
            raise ValueError(f"@every {count}m does not divide an hour evenly")
        return "* * * * *" if count == 1 else f"*/{count} * * * *"
    if count < 1 or 24 % count:
        raise ValueError(f"@every {count}h does not divide a day evenly")
    return f"0 */{count} * * *"


@dataclass(frozen=True)
class Job:
    name: str
    fn: callable
    schedule: str = None
    description: str = ""
    singleton: bool = True
    alert_on_failure: bool = True
    # Seconds between observations in the data, which is not always the seconds
    # between runs: a feed refreshing faster than once a minute is run every minute
    # and polls internally, because cron cannot go below a minute. Archive manifests
    # use this, not the schedule, to work out how many files a day should hold.
    cadence_seconds: int = None

    @property
    def scheduled(self):
        return bool(self.schedule)

    @property
    def data_cadence(self):
        return self.cadence_seconds or interval_seconds(self.schedule)


def job(name, schedule=None, description="", singleton=True, alert_on_failure=True,
        cadence_seconds=None):
    """Register a job.

    ``schedule`` is supercronic syntax: either five-field cron (``"0 4 * * *"``) or a
    duration descriptor (``"@every 20s"``). ``singleton`` takes a lock file so a slow
    run is skipped rather than stacked on top of itself.
    """

    def decorator(fn):
        if name in _REGISTRY:
            raise ValueError(f"duplicate job name: {name}")
        _REGISTRY[name] = Job(
            name=name,
            fn=fn,
            schedule=schedule,
            description=description or (fn.__doc__ or "").strip().splitlines()[0:1] and
            (fn.__doc__ or "").strip().splitlines()[0] or "",
            singleton=singleton,
            alert_on_failure=alert_on_failure,
            cadence_seconds=cadence_seconds,
        )
        return fn

    return decorator


def get(name):
    if name not in _REGISTRY:
        raise KeyError(name)
    return _REGISTRY[name]


def all_jobs():
    return [_REGISTRY[name] for name in sorted(_REGISTRY)]


def scheduled_jobs():
    return [j for j in all_jobs() if j.scheduled]
