#!/bin/sh
# ═══════════════════════════════════════════════════════════════════════════
#  Wispbyte entrypoint for the JAFJ manager.
#
#  Wispbyte (wispbyte.com) برای پایتون:
#    - Docker Image: Python 3.11
#    - Startup Command: sh start.sh
#    - Environment Variables: BOT_TOKEN (الزامی)، API_ID، API_HASH،
#      DATA_GITHUB_TOKEN، DATA_GITHUB_REPO، BACKUP_CHAT (اختیاری)
#
#  روی Wispbyte فایل‌ها بین ری‌استارت می‌مانند، پس DATA_DIR همان پوشهٔ کاری
#  است (نه مثل blitz که نیاز به VOLUME /data دارد). برای امنیت خاطر
#  DATA_GITHUB_TOKEN را ست کنید که هر ۳۰ دقیقه روی گیتهاب بکاپ بگیرد.
# ═══════════════════════════════════════════════════════════════════════════
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

export JAFJ_HOSTED="${JAFJ_HOSTED:-1}"
export JAFJ_HOST_LABEL="${JAFJ_HOST_LABEL:-wispbyte}"
export DATA_DIR="${DATA_DIR:-$HERE}"
export PORT="${PORT:-8080}"

PY="$(command -v python3 || command -v python || echo python3)"

echo "WISPBYTE: code=$HERE data=$DATA_DIR python=$PY port=$PORT"
exec "$PY" manager_82.py
