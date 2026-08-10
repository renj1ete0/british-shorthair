"""Job modules.

Importing this package registers every job. To add one: create the module, give its
entry point a ``@job(...)`` decorator, and import it below — the crontab is generated
from the registry, so no schedule needs editing anywhere else.
"""

from . import (  # noqa: F401  (imported for registration side effects)
    archive,
    bus_arrival,
    bus_essentials,
    daily_summary,
    datamall_pv,
    migrate_legacy,
    mss,
    mss_backfill,
    notify_test,
    planned_bus_routes,
    realtime,
)

# Optional local-only modules. These are gitignored and exist only in a locally built
# image, so a checkout of this repository must still import cleanly without them.
try:
    from . import bus_arrival_batch  # noqa: F401
except ImportError:
    pass
