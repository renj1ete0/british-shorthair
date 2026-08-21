#!/bin/sh
# Container entrypoint: fix data-volume ownership, generate schedule, bootstrap, hand off.
set -eu

DATA_DIR="${BSH_DATA_DIR:-/data}"

# Fix the bind-mounted volume so bsh can write regardless of host ownership.
mkdir -p "${DATA_DIR}/logs" "${DATA_DIR}/state"
chown -R bsh:bsh "${DATA_DIR}"

cd /app/scripts

# The crontab is generated from the job registry rather than kept as a checked-in
# file, so a job's schedule cannot drift from the code that defines it.
python run_job.py --crontab > /tmp/crontab
echo "--- schedule ---"
cat /tmp/crontab
echo "----------------"

# Validate before handing over. supercronic exits fatally on a bad line, and a
# schedule that only fails at startup means a container that restart-loops while
# collecting nothing - so fail here, loudly, with the offending line visible above.
if ! supercronic -test /tmp/crontab; then
    echo "FATAL: generated crontab is not valid supercronic syntax" >&2
    exit 1
fi

# bus_arrival reads the stop list on every tick. Without it, a fresh volume would
# fail every 20 seconds until bus_essentials next runs at 04:00, so publish it now.
if [ ! -f "${DATA_DIR}/busstop_current.json" ]; then
    echo "bus stop list missing; running bus_essentials to bootstrap..."
    if ! gosu bsh python run_job.py bus_essentials; then
        echo "WARNING: bootstrap failed - bus_arrival will fail until bus_essentials succeeds"
    fi
fi

exec gosu bsh "$@"
