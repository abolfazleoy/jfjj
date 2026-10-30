#!/bin/sh
# ═══════════════════════════════════════════════════════════════════════════
#  Hostless entrypoint for the JAFJ manager.
#
#  Hostless (hostless.cloud) runs a Docker image — or, if you pick the
#  detected build instead of Docker, a plain Python app — and says two things
#  very explicitly:
#
#    * "A web service must listen on the PORT variable and on 0.0.0.0"
#    * "The process finished and exited. A service must keep running."
#
#  Both are handled here and in the shared entrypoint:
#
#    1. the manager's health server binds 0.0.0.0:$PORT at import time
#       (before the Telegram login), so /healthz answers 200 immediately;
#    2. this wrapper never lets the manager "finish": the code always runs
#       from an immutable directory, the crash supervisor restarts it in
#       place, and a clean exit on a host counts as a crash too
#       (JAFJ_KEEP_ALIVE, see railway-start.sh);
#    3. the bot itself reconnects instead of returning 0 when Telegram
#       drops the connection (a second instance with the same token, a
#       network flap, a FloodWait…).
#
#  Start command on Hostless (Docker build):   sh /opt/jafj/hostless-start.sh
#  Start command on Hostless (Python build):   sh hostless-start.sh
#  Leaving the start command empty also works with the Docker build — the
#  image's own CMD (blitz-start.sh) ends up in exactly the same place.
#
#  PORT is provided by Hostless; do not set it yourself.
# ═══════════════════════════════════════════════════════════════════════════
set -eu

HERE="$(cd "$(dirname "$0")" 2>/dev/null && pwd)" || HERE="."

log() { echo "HOSTLESS: $*"; }

# ── 1) where is the code? (immutable copy first, repo root second) ─────────
if [ -n "${JAFJ_IMAGE_DIR:-}" ] && [ -f "$JAFJ_IMAGE_DIR/manager_82.py" ]; then
    :                                   # از قبل درست تنظیم شده
elif [ -f "/opt/jafj/manager_82.py" ]; then
    JAFJ_IMAGE_DIR="/opt/jafj"          # همان لایه‌ی ایمیجِ این ریپو
else
    JAFJ_IMAGE_DIR="$HERE"              # بیلدِ پایتونی (بدون Dockerfile)
fi
export JAFJ_IMAGE_DIR

# ── 2) Hostless is a host: never let a transient error kill the process ────
export JAFJ_HOSTED="${JAFJ_HOSTED:-1}"

# ── 3) data directory ──────────────────────────────────────────────────────
# Everything the bot must remember (manager.db, shop.db, clients/<uid>/,
# manager_bot.string) lives here. Prefer a persistent mount at /data;
# otherwise fall back to a writable directory and say so loudly, because on a
# host without a persistent disk the data is wiped on every deploy — in that
# case set DATA_GITHUB_TOKEN so tools/gh_data_sync.py can restore it.
if [ -z "${DATA_DIR:-}" ]; then
    for d in /data "${JAFJ_DATA_MOUNT:-}" "$HOME/jafj-data" "$HERE"; do
        [ -n "$d" ] || continue
        if mkdir -p "$d" 2>/dev/null && [ -w "$d" ]; then
            DATA_DIR="$d"
            break
        fi
    done
fi
if [ -z "${DATA_DIR:-}" ]; then
    DATA_DIR="/tmp/jafj-data"
    mkdir -p "$DATA_DIR" 2>/dev/null || true
fi
export DATA_DIR
if [ "$(cd "$DATA_DIR" 2>/dev/null && pwd)" = "$JAFJ_IMAGE_DIR" ]; then
    log "WARNING: data is living next to the code ($DATA_DIR) — it will be wiped on every deploy; mount a disk at /data or set DATA_GITHUB_TOKEN"
fi

# ── 4) hosted defaults ─────────────────────────────────────────────────────
# Hostless' free tier does not sleep, so the 120s emergency backup of the
# "sleepy" plans is not forced here; an explicit BACKUP_EVERY always wins.
export JAFJ_HOST_LABEL="${JAFJ_HOST_LABEL:-hostless}"

log "code=$JAFJ_IMAGE_DIR data=$DATA_DIR port=${PORT:-8080}"

exec sh "$JAFJ_IMAGE_DIR/railway-start.sh" "$@"
