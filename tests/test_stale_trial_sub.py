#!/usr/bin/env python3
"""مُهرِ کهنهٔ تست رایگان نباید اشتراکِ ماهانه را پنهان کند.

گزارش کاربر: «اشتراک ماهانه دارم ولی بعد از ۶ تا ۱۲ ساعت سرویس خودش
خاموش می‌شود».

علت: مشتری یک بار تست رایگان گرفته بود؛ موقع انقضای تست، مُهرِ
`trial_expires_at` روی رکورد مانده بود (صفر نمی‌شد). بعد از خرید اشتراک،
`has_sub` به‌خاطر همان مُهرِ کهنه False برمی‌گشت:

  • `points_loop` مشترک را «امتیازی» می‌پنداشت و هر ساعت ۱ امتیاز از
    موجودیِ قدیمی‌اش می‌سوزاند؛ صفر که شد سرویس خاموش می‌شد (همان
    «چند ساعت بعد خاموش می‌شود»).
  • `charge_start` برای روشن‌کردن دستی هم از او ۲۰ امتیاز می‌خواست.
  • `can_run` به‌خاطر همان شرطِ امتیاز، ری‌استارتِ خودکار را بی‌صدا رد
    می‌کرد (`no_credit`).

آنچه این تست قفل می‌کند:

  ۱. اشتراکِ فعال + مُهرِ کهنهٔ تست (در گذشته) → `has_sub=True`، پلن پیدا
     می‌شود، `can_run → sub`، از او هزینهٔ روشن‌کردن کم نمی‌شود.
  ۲. تستِ «در حال اجرا» (مُهر در آینده) مثل قبل بر اشتراک اولویت دارد.
  ۳. اشتراکِ منقضی با مُهرِ کهنه همچنان اشتراک حساب نمی‌شود (کنترلِ منفی).
  ۴. انقضای تست در `trial_loop` مُهر را صفر می‌کند — دیگر رکوردِ کهنه
     ساخته نمی‌شود.
  ۵. هر سه مسیرِ اعطای اشتراک (/ok، خرید امتیاز، پنلِ «فعال‌سازی به‌ازای
     روز») مُهرِ تست را پاک می‌کنند.

روش اجرا مثل بقیهٔ تست‌ها: سورس واقعی manager_82 با telethon قلابی و
دیتابیس واقعی (فایلی) اجرا می‌شود.

    python3 tests/test_stale_trial_sub.py  →  ALL: PASS
"""
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap

ROOT = os.path.join(tempfile.gettempdir(), "jafj_stale_trial_run")
APP = os.path.join(ROOT, "app")
DATA = os.path.join(ROOT, "data")
SRC_REPO = os.environ.get("REPO", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# قلاب‌های telethon از تستِ پنلِ تستِ رایگان قرض گرفته می‌شوند.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_trial_admin import FAKE_TELETHON, FAKE_SESSIONS, FAKE_ERRORS  # noqa: E402


INNER = textwrap.dedent('''
    import os, sys, asyncio
    sys.path.insert(0, os.getcwd())
    import manager_82 as M

    U_STALE = 301     # تستِ کهنه + اشتراکِ فعال ← هستهٔ باگ
    U_TRIAL = 302     # تستِ در حال اجرا + اشتراکِ فعال (مُهر در آینده)
    U_GONE  = 303     # اشتراکِ منقضی + مُهرِ کهنه → باید امتیازی بماند
    U_END   = 304     # تستی که همین حالا تمام شده ← برای trial_loop

    results = []

    def check(cond, name):
        results.append((name, bool(cond)))

    async def main():
        m = M.Manager()
        now = M.now()
        day = 86400
        src = open("manager_82.py", encoding="utf-8").read()

        # ═══ T1 — هستهٔ فیکس ═══
        m.db.add(U_STALE, "a", "الف", 0)
        m.db.set(U_STALE, status="active", expires_at=now + 30 * day,
                 trial_expires_at=now - 7200, current_plan_id=0)
        check(m.has_sub(U_STALE),
              "T1: اشتراکِ فعال با مُهرِ کهنهٔ تست دیده می‌شود (has_sub=True)")
        check(m.effective_plan(U_STALE) is not None,
              "T1: پلنِ مشترک پیدا می‌شود (effective_plan)")
        ok, why = m.can_run(U_STALE)
        check(ok and why == "sub",
              "T1: can_run → sub (نه «امتیاز نداری»)")
        m.shop.p_add(U_STALE, 8)
        paid, fee = m.charge_start(U_STALE, first=False)
        check(paid and not fee and m.shop.p_balance(U_STALE) == 8,
              "T1: از مشترکِ ماهانه هزینهٔ روشن‌کردن کم نمی‌شود")
        # نقشِ points_loop: معاف از کسرِ ساعتی = دیگر «X ساعت بعد خاموش» ندارد
        check(m.has_sub(U_STALE),
              "T1: points_loop مشترک را از کسرِ ساعتی معاف می‌کند")

        # ═══ T2 — تستِ در حال اجرا مثل قبل اولویت دارد ═══
        m.db.add(U_TRIAL, "b", "ب", 0)
        m.db.set(U_TRIAL, status="active", expires_at=now + 30 * day,
                 trial_expires_at=now + 1800, current_plan_id=0)
        check((not m.has_sub(U_TRIAL)) and m.trial_active(U_TRIAL),
              "T2: تستِ در حال اجرا هنوز بر has_sub مقدم است")

        # ── T2b — مرزِ دقیق: مُهر = همین لحظه و مُهر = ۱ ثانیهٔ دیگر ──
        # مُهر = now یعنی تست همین ثانیه تمام شده (مثل trial_loop که
        # left<=0 را «تمام‌شده» می‌گیرد) → باید مشترک شناخته شود.
        m.db.add(305, "e", "ه", 0)
        m.db.set(305, status="active", expires_at=now + 30 * day,
                 trial_expires_at=now, current_plan_id=0)
        check(m.has_sub(305) and not m.trial_active(305),
              "T2b: مُهر = همین‌ثانیه → مشترک (هم‌راستا با trial_loop)")
        m.db.set(305, trial_expires_at=now + 1)
        check((not m.has_sub(305)) and m.trial_active(305),
              "T2b: مُهر = ۱ ثانیهٔ دیگر → هنوز در تست")

        # ═══ T3 — کنترلِ منفی ═══
        m.db.add(U_GONE, "c", "ج", 0)
        m.db.set(U_GONE, status="active", expires_at=now - day,
                 trial_expires_at=now - 7200, current_plan_id=0)
        check(not m.has_sub(U_GONE),
              "T3: اشتراکِ منقضی با مُهرِ کهنه اشتراک حساب نمی‌شود")

        # ═══ T4 — انقضای تست مُهر را صفر می‌کند ═══
        m.db.add(U_END, "d", "د", 0)
        m.db.set(U_END, status="active", expires_at=now - 60,
                 trial_expires_at=now - 60, trial_warning_sent=0)
        t = asyncio.create_task(m.trial_loop())
        await asyncio.sleep(1.0)
        t.cancel()
        try:
            await t
        except asyncio.CancelledError:
            pass
        c4 = m.db.get(U_END)
        check(c4["status"] == "expired" and int(c4["trial_expires_at"] or 0) == 0,
              "T4: trial_loop موقع انقضا مُهرِ تست را صفر می‌کند")

        # ═══ T5/T6 — هر سه مسیرِ اعطای اشتراک مُهر را پاک می‌کنند ═══
        check('status="expired", trial_expires_at=0' in src,
              "T5: شاخهٔ انقضای تست مُهر را صفر می‌کند (سورس)")
        check(src.count("current_plan_id=0, trial_expires_at=0") >= 3,
              "T6: /ok، خرید امتیاز و پنلِ روزها مُهر را پاک می‌کنند (سورس)")

        print("RESULTS " + repr(results))

    asyncio.run(main())
''')


def reset():
    shutil.rmtree(ROOT, ignore_errors=True)
    os.makedirs(APP, exist_ok=True)
    os.makedirs(DATA, exist_ok=True)
    for f in ("manager_82.py", "95.py"):
        shutil.copy2(os.path.join(SRC_REPO, f), APP)
    tel = os.path.join(APP, "telethon")
    os.makedirs(tel, exist_ok=True)
    for name, body in (("telethon/__init__.py", FAKE_TELETHON),
                       ("telethon/sessions.py", FAKE_SESSIONS),
                       ("telethon/errors.py", FAKE_ERRORS)):
        with open(os.path.join(APP, name), "w", encoding="utf-8") as f:
            f.write(body)


def run_inner(port=8197):
    env = dict(os.environ)
    env["DATA_DIR"] = DATA
    env["PORT"] = str(port)
    env["JAFJ_PORT"] = str(port)
    for k in ("RAILWAY_ENVIRONMENT", "RAILWAY_SERVICE_ID", "RAILWAY_PROJECT_ID",
              "JAFJ_HOSTED", "JAFJ_LOGIN_RETRY", "BACKUP_CHAT", "BACKUP_EVERY",
              "BOT_TOKEN", "API_ID", "API_HASH", "ADMIN_IDS"):
        env.pop(k, None)
    p = subprocess.run([sys.executable, "-c", INNER], cwd=APP, env=env,
                       capture_output=True, text=True, timeout=180)
    return p.stdout + p.stderr


if __name__ == "__main__":
    print("--- مُهرِ کهنهٔ تست رایگان نباید اشتراکِ ماهانه را پنهان کند ---")
    reset()
    out = run_inner()
    line = [ln for ln in out.splitlines() if ln.startswith("RESULTS ")]
    if not line:
        print(out[-4000:])
        print("ALL: FAIL")
        sys.exit(1)
    results = eval(line[0][len("RESULTS "):])
    bad = [(n, ok) for n, ok in results if not ok]
    print("%d checks, %d failed" % (len(results), len(bad)))
    for n, _ok in bad:
        print("FAIL", n)
    if bad:
        print("ALL: FAIL")
        sys.exit(1)
    print("ALL: PASS")
    sys.exit(0)
