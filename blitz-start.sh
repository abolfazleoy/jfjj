#!/bin/sh
# ═══════════════════════════════════════════════════════════════════════════
#  blitz.cloud entrypoint for the JAFJ manager.
#
#  blitz.cloud builds this repo on every push, gives the container a PORT
#  (8080 by default) and keeps ONLY the folders the image declares with
#  VOLUME. The Dockerfile declares /data and DATA_DIR=/data, so the data
#  directory is already right before this script runs.
#
#  This wrapper only supplies the blitz-specific defaults; the whole boot +
#  fresh-code + crash-supervision flow stays in railway-start.sh (the
#  host-neutral entrypoint, kept under that name for backwards compatibility).
#
#  One thing a script cannot fix: on the FREE plan blitz.cloud sleeps an app
#  after 30 minutes without visitors. A sleeping container runs no bot, so set
#  up an external HTTP monitor on https://<app>.<you>.blitz.cloud/healthz every
#  5 minutes (README, «اجرا روی blitz.cloud»), or use the Pro plan where apps
#  stay online.
# ═══════════════════════════════════════════════════════════════════════════
set -eu

IMAGE_DIR="${JAFJ_IMAGE_DIR:-/opt/jafj}"

# The kept folder. blitz.cloud mounts it back on every restart/redeploy.
export JAFJ_APP_DIR="${JAFJ_APP_DIR:-/data}"
export DATA_DIR="${DATA_DIR:-/data}"

# A container that sleeps or restarts must not lose the last minutes of data:
# keep the automatic backup short unless the operator asked otherwise.
if [ -z "${BACKUP_EVERY:-}" ] && [ -z "${JAFJ_APP_SLEEPS:-}" ]; then
    JAFJ_APP_SLEEPS=1
    export JAFJ_APP_SLEEPS
fi

exec sh "$IMAGE_DIR/railway-start.sh" "$@"
