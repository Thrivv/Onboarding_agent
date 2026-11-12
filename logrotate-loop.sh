#!/bin/sh
# logrotate-loop.sh
#
# There is no cron daemon in this image, and logrotate itself does not run
# on a schedule — it only evaluates and (if due) rotates when invoked. This
# script is what supervisord's [program:logrotate] runs instead of a real
# cron job: call logrotate against logrotate-thrivv.conf, then sleep, forever.
# logrotate itself decides whether anything is actually due to rotate on
# each invocation (via the `daily` and `size 50M` thresholds in that file and
# its own state file) — running it more often than that is a harmless no-op,
# so the exact interval below is not sensitive.
set -eu

STATE_FILE=/var/lib/logrotate/thrivv.state
CONF_FILE=/etc/logrotate.d/thrivv-app.conf
INTERVAL_SECONDS=1800

mkdir -p "$(dirname "$STATE_FILE")"

echo "[logrotate-loop] starting — checking every ${INTERVAL_SECONDS}s against ${CONF_FILE}"

while true; do
    logrotate --state "$STATE_FILE" "$CONF_FILE" \
        || echo "[logrotate-loop] logrotate exited non-zero — will retry next cycle"
    sleep "$INTERVAL_SECONDS"
done
