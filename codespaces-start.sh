#!/bin/sh
# ═══════════════════════════════════════════════════════════════════════════
#  GitHub Codespaces entrypoint for the JAFJ manager.
#
#  Codespaces is a host like Render/Railway/Hostless — but with two
#  differences that this script has to handle:
#
#    1) THERE IS NO IMMUTABLE IMAGE. On Render/Railway the code lives in
#       /opt/jafj and only data goes on the volume. In a codespace the code
#       IS the git checkout (/workspaces/<repo>) — so JAFJ_IMAGE_DIR is the
#       repo root and the manager runs straight from the working tree.
#
#    2) THERE IS NO /data VOLUME. A codespace's disk survives Stop/Start
#       (it only disappears when the codespace itself is deleted), so
#       DATA_DIR = $HOME/jafj-data keeps manager.db, shop.db, the sessions
#       in clients/<uid>/ and manager_config.json alive between restarts.
#       For real durability, also set DATA_GITHUB_TOKEN (backup in GitHub).
#
#  Usage:
#    sh codespaces-start.sh            # foreground — same contract as the
#                                     # other hosts (Render/Railway/Hostless)
#    sh codespaces-start.sh --daemon   # background + pidfile + log; this is
#                                     # what devcontainer.json's
#                                     # postStartCommand uses, so the bot
#                                     # comes back up on every container start
# ═══════════════════════════════════════════════════════════════════════════
set -eu

HERE="$(cd "$(dirname "$0")" 2>/dev/null && pwd)" || HERE="."

log() { echo "CODESPACES: $*"; }

MODE="${1:-}"
[ "$MODE" = "--daemon" ] && shift || true

# ── 1) where is the code? (the git checkout is the "image" here) ────────────
if [ -n "${JAFJ_IMAGE_DIR:-}" ] && [ -f "$JAFJ_IMAGE_DIR/manager_82.py" ]; then
    :                                    # از قبل درست تنظیم شده
elif [ -f "$HERE/manager_82.py" ]; then
    JAFJ_IMAGE_DIR="$HERE"               # همین ریپو
elif [ -f "/workspaces/jfjj/manager_82.py" ]; then
    JAFJ_IMAGE_DIR="/workspaces/jfjj"    # مسیرِ پیش‌فرضِ codespaces
else
    echo "ERROR: manager_82.py پیدا نشد (JAFJ_IMAGE_DIR=${JAFJ_IMAGE_DIR:-unset}, here=$HERE)" >&2
    exit 1
fi
export JAFJ_IMAGE_DIR
export JAFJ_SELFBOT_REF="${JAFJ_SELFBOT_REF:-$JAFJ_IMAGE_DIR/95.py}"

# ── 2) where does the data live? (دیسکِ codespace بین Stop/Start می‌ماند) ──
if [ -z "${DATA_DIR:-}" ]; then
    for d in "${HOME:-}/jafj-data" "/data" "/tmp/jafj-data"; do
        [ -n "$d" ] || continue
        if mkdir -p "$d" 2>/dev/null && [ -w "$d" ]; then
            DATA_DIR="$d"
            break
        fi
    done
fi
[ -n "${DATA_DIR:-}" ] || { echo "ERROR: no writable data dir" >&2; exit 1; }
mkdir -p "$DATA_DIR" 2>/dev/null || true
_abs="$(cd "$DATA_DIR" 2>/dev/null && pwd)" && DATA_DIR="$_abs"
export DATA_DIR
export JAFJ_APP_DIR="${JAFJ_APP_DIR:-$DATA_DIR}"

# ── 3) hosted defaults ─────────────────────────────────────────────────────
# Codespaces is a host: the process must never stay dead (a crashed bot =
# dead service), and the health server must listen on 0.0.0.0:$PORT so the
# codespace's port forwarding can see it.
export JAFJ_HOSTED="${JAFJ_HOSTED:-1}"
export JAFJ_HOST_LABEL="${JAFJ_HOST_LABEL:-codespaces}"
export PORT="${PORT:-8080}"
# The codespace can be stopped at any moment (idle timeout) → keep the
# automatic backup short (120s) so at most the last two minutes are lost.
if [ -z "${BACKUP_EVERY:-}" ] && [ -z "${JAFJ_APP_SLEEPS:-}" ]; then
    JAFJ_APP_SLEEPS=1
    export JAFJ_APP_SLEEPS
fi

# ── 4) dependencies (pip may have been skipped if postCreateCommand failed) ─
if ! python3 -c "import telethon" >/dev/null 2>&1; then
    if [ -f "$JAFJ_IMAGE_DIR/.devcontainer/setup.sh" ]; then
        log "telethon نصب نیست — .devcontainer/setup.sh را اجرا می‌کنم"
        sh "$JAFJ_IMAGE_DIR/.devcontainer/setup.sh" || true
    fi
fi

log "code=$JAFJ_IMAGE_DIR data=$DATA_DIR port=$PORT mode=${MODE:-foreground}"

# ── 5) daemon mode: the bot runs in the background, we only start it ────────
if [ "$MODE" = "--daemon" ]; then
    PIDFILE="$DATA_DIR/jafj.pid"
    LOGFILE="$DATA_DIR/bot.log"

    if [ -f "$PIDFILE" ]; then
        old="$(cat "$PIDFILE" 2>/dev/null || true)"
        if [ -n "$old" ] && kill -0 "$old" 2>/dev/null; then
            log "ربات از قبل بالاست (pid=$old) — نمونهٔ دوم ساخته نمی‌شود"
            exit 0
        fi
        rm -f "$PIDFILE" 2>/dev/null || true
    fi

    # log را بزرگ نگه ندار
    if [ -f "$LOGFILE" ]; then
        sz="$(wc -c < "$LOGFILE" 2>/dev/null || echo 0)"
        [ "${sz:-0}" -gt 5242880 ] && : > "$LOGFILE"
    fi

    nohup sh "$JAFJ_IMAGE_DIR/codespaces-start.sh" >> "$LOGFILE" 2>&1 &
    child=$!
    echo "$child" > "$PIDFILE"
    log "ربات در پس‌زمینه بالا آمد (pid=$child) — لاگ: $LOGFILE"

    # تا ۳۰ ثانیه منتظرِ وب‌سرورِ سلامت می‌مانیم
    i=0
    while [ "$i" -lt 30 ]; do
        if python3 - "http://127.0.0.1:${PORT}/healthz" <<'PY' >/dev/null 2>&1
import sys, urllib.request
try:
    urllib.request.urlopen(sys.argv[1], timeout=2).read()
except Exception:
    sys.exit(1)
PY
        then
            log "وب‌سرورِ سلامت جواب داد (http://127.0.0.1:${PORT}/healthz)"
            break
        fi
        sleep 1
        i=$((i + 1))
    done

    # پورت را عمومی کن تا از بیرون هم قابل‌دسترسی باشد (فقط متنِ سلامت
    # و /version را نشان می‌دهد — هیچ دادهٔ مشتری‌ای اینجا نیست).
    if [ "${JAFJ_PUBLIC_PORT:-1}" != "0" ] \
            && command -v gh >/dev/null 2>&1 \
            && [ -n "${CODESPACE_NAME:-}" ]; then
        if gh codespace ports visibility "${PORT}:public" -c "$CODESPACE_NAME" >/dev/null 2>&1; then
            log "پورت $PORT عمومی شد (visibility=public)"
        else
            log "پورت $PORT را از پنلِ Ports در codespace خودت public کن"
        fi
    fi

    if [ -n "${CODESPACE_NAME:-}" ]; then
        domain="${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN:-app.github.dev}"
        log "آدرسِ عمومی: https://${CODESPACE_NAME}-${PORT}.${domain}/healthz"
        log "نسخهٔ اجراشده: https://${CODESPACE_NAME}-${PORT}.${domain}/version"
    fi
    exit 0
fi

# ── 6) foreground: the shared boot + crash supervisor does the rest ────────
exec sh "$JAFJ_IMAGE_DIR/railway-start.sh" "$@"
