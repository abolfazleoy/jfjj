#!/bin/sh
# ═══════════════════════════════════════════════════════════════════════════
#  بوت‌استرَپ جفج روی Wispbyte — فقط همین یک فایل رو آپلود کن.
#
#  این فایل خودش کدِ تازه را از گیتهاب می‌کشد، وابستگی‌ها را نصب می‌کند
#  و ربات را بالا می‌آورد. دیگه نیازی به آپلود manager_82.py / 95.py /
#  requirements.txt / tools/ نیست.
#
#  ⚙️ تنظیمات در Wispbyte (Startup & Environment Variables):
#
#     Docker Image  : Python 3.11
#     Startup Command: sh start.sh
#     Environment Variables (الزامی/اختیاری):
#       BOT_TOKEN            (الزامی)   توکن ربات از @BotFather
#       API_ID / API_HASH    (برای سلف) از my.telegram.org
#       DATA_GITHUB_TOKEN    (شدیداً پیشنهاد می‌شود) بکاپ خودکار داده روی گیت‌هاب
#       DATA_GITHUB_REPO     ریپوی خصوصی برای بکاپ (پیش‌فرض: djskkskw/jfjj-data)
#       JAFJ_REPO            (اختیاری) ریپوی کد — پیش‌فرض: abolfazleoy/jfjj
#       JAFJ_BRANCH          (اختیاری) شاخه، پیش‌فرض: main
#
#  روی Wispbyte فایل‌سیستم پایدار است، پس داده (manager.db، shop.db،
#  clients/*) در پوشهٔ /home/container/data می‌ماند و هر ری‌استارت/استاپ باقی
#  است. برای مهاجرت از بکاپ /restore استفاده کن.
# ═══════════════════════════════════════════════════════════════════════════
set -eu

# ── کجاییم؟ (Wispbyte معمولاً در /home/container است) ──────────────────
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

REPO_URL_TEMPLATE="https://github.com/${JAFJ_REPO:-abolfazleoy/jfjj}.git"
BRANCH="${JAFJ_BRANCH:-main}"

CODE_DIR="$HERE/code"
DATA_DIR="$HERE/data"
VENV_DIR="$HERE/venv"

log() { echo "JAFJ-BOOT: $*"; }

# ── 1) پوشه‌ها ─────────────────────────────────────────────────────────
mkdir -p "$DATA_DIR"
mkdir -p "$CODE_DIR"

# ── 2) کشیدن/به‌روز کردن کد از گیتهاب ─────────────────────────────────
PY=""
if [ ! -d "$CODE_DIR/.git" ]; then
    log "کلون کردن $REPO_URL_TEMPLATE (شاخه $BRANCH) → $CODE_DIR"
    rm -rf "$CODE_DIR"
    git clone --depth 1 --branch "$BRANCH" "$REPO_URL_TEMPLATE" "$CODE_DIR"
else
    log "به‌روز کردن کد از گیتهاب (git pull) …"
    (cd "$CODE_DIR" && git fetch origin "$BRANCH" && git reset --hard "origin/$BRANCH") \
        || log "هشدار: git pull ناموفق بود — از نسخهٔ موجود استفاده می‌شود"
fi

# ── 3) ساخت/فعال‌کردن venv + نصب وابستگی‌ها ──────────────────────────
if [ ! -d "$VENV_DIR" ]; then
    log "ساخت محیط مجازی پایتون …"
    python3 -m venv "$VENV_DIR" 2>/dev/null || python -m venv "$VENV_DIR"
    PY="$VENV_DIR/bin/python"
    log "نصب وابستگی‌ها از requirements.txt …"
    "$PY" -m pip install --upgrade pip >/dev/null 2>&1 || true
    "$PY" -m pip install -r "$CODE_DIR/requirements.txt"
else
    PY="$VENV_DIR/bin/python"
    # فقط اگر requirements.txt عوض شده باشد دوباره نصب می‌کنیم
    REQ_HASH_NEW="$("$PY" -c "import hashlib;print(hashlib.sha256(open('$CODE_DIR/requirements.txt','rb').read()).hexdigest())" 2>/dev/null || echo "")"
    REQ_HASH_OLD="$(cat "$VENV_DIR/.reqhash" 2>/dev/null || echo "")"
    if [ "$REQ_HASH_NEW" != "$REQ_HASH_OLD" ]; then
        log "requirements.txt عوض شده — در حال نصب نسخه‌های تازه …"
        "$PY" -m pip install -r "$CODE_DIR/requirements.txt"
        echo "$REQ_HASH_NEW" > "$VENV_DIR/.reqhash"
    fi
fi

# ── 4) اجرا از همان مسیر، با داده در $DATA_DIR ───────────────────────
export JAFJ_HOSTED="${JAFJ_HOSTED:-1}"
export JAFJ_HOST_LABEL="${JAFJ_HOST_LABEL:-wispbyte}"
export DATA_DIR="$DATA_DIR"
export JAFJ_APP_DIR="$DATA_DIR"
export JAFJ_IMAGE_DIR="$CODE_DIR"
export JAFJ_SELFBOT_REF="$CODE_DIR/95.py"
export PORT="${PORT:-8080}"

log "code=$CODE_DIR data=$DATA_DIR python=$PY port=$PORT"
exec "$PY" "$CODE_DIR/manager_82.py"
