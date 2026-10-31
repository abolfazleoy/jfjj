#!/bin/sh
# ═══════════════════════════════════════════════════════════════════════════
#  نصبِ وابستگی‌های پایتون برای codespaces (postCreateCommand).
#
#  این اسکریپت هرگز با خطا از پیچ‌و‌خم خارج نمی‌شود. دلیلش ساده است: اگر
#  postCreateCommand خطا بدهد، طبقِ spec دیگر postStartCommand اجرا نمی‌شود
#  و ربات بالا نمی‌آید. پس «نصبِ ناموفق» باید هشدار بدهد، نه اینکه کلِ بوت را
#  خراب کند — ناظرِ (supervisor) کرش‌ها را خودش مدیریت می‌کند.
# ═══════════════════════════════════════════════════════════════════════════
set -u

cd "$(dirname "$0")/.." 2>/dev/null || cd .

if python3 -c "import telethon" >/dev/null 2>&1; then
    echo "setup: telethon از قبل نصب است"
    exit 0
fi

echo "setup: در حالِ نصبِ requirements.txt …"
if pip install --no-cache-dir -r requirements.txt; then
    echo "setup: نصب کامل شد"
    exit 0
fi

# cryptg یک افزونهٔ C است و ممکن است روی بعضی معماری‌ها ساخته نشود؛
# تلگرام بدونِ آن هم کار می‌کند (کمی سنگین‌تر).
echo "setup: نصبِ کامل نشد — تلاشِ دوم فقط با telethon + tzdata"
if pip install --no-cache-dir telethon tzdata; then
    echo "setup: telethon نصب شد (بدون cryptg)"
    exit 0
fi

echo "setup: WARNING — هیچ‌کدام نصب نشد؛ ربات احتمالاً کرش می‌کند"
exit 0
