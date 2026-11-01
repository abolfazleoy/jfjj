#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""«هر آپدیت سشن‌ها را می‌سوزاند» — مهلتِ بوت.

گزارشِ کاربر: «نسخه‌ی قبل درست بود، از وقتی این را آوردی سشن‌ها می‌سوزند.»
لاگِ خودش علت را نشان داد: هنگامِ دیپلوی، کانتینرِ تازه در ثانیه‌ی صفر همه‌ی
سشن‌ها را وصل کرد و کانتینرِ قبلی ۷ ثانیه بعد خاموش شد:

    [17:33:17] Server marked as running
    [17:33:17] ♻️ بالا آوردنِ سرویس‌ها (بوت): 5 سرویس روشن
    [17:33:24] Server marked as stopping

دو IP روی یک کلید = AuthKeyDuplicated = سشنِ مرده. این تست مهلتِ بوت را
قفل می‌کند (هم در مدیر، هم مهلتِ قفلِ ۹۵.py) تا دیگر هیچ سشنی در ثانیه‌ی
صفرِ بوت وصل نشود.
"""
import importlib.util
import json
import os
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
FAILS = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name
          + (f"   [{extra}]" if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def load95():
    spec = importlib.util.spec_from_file_location("sb95_grace", str(REPO / "95.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    root = Path(tempfile.mkdtemp(prefix="jafj_grace_"))
    here = os.getcwd()
    saved = {k: os.environ.get(k) for k in
             ("DATA_DIR", "PORT", "JAFJ_ONLY", "JAFJ_RESUME_DELAY",
              "JAFJ_NO_RESUME_DELAY", "JAFJ_LOCK_GRACE")}
    os.environ["DATA_DIR"] = str(root / "data")
    os.environ["PORT"] = "8477"
    os.environ.pop("JAFJ_ONLY", None)
    os.environ.pop("JAFJ_NO_RESUME_DELAY", None)
    os.environ.pop("JAFJ_RESUME_DELAY", None)
    data = Path(os.environ["DATA_DIR"])
    data.mkdir(parents=True, exist_ok=True)
    try:
        sys.path.insert(0, str(REPO))
        import manager_82 as M

        # ── ۱) پیش‌فرض: ۱۲۰ ثانیه ─────────────────────────────────────
        d, why = M.resume_grace_plan(data, {})
        check("grace: پیش‌فرض ۱۲۰ ثانیه", d == 120.0, d)
        check("grace: دلیلِ روشن دارد", "مهلتِ بوت" in why, why)

        # ── ۲) خاموش‌کردن ───────────────────────────────────────────────
        d, _ = M.resume_grace_plan(data, {"JAFJ_RESUME_DELAY": "0"})
        check("grace: JAFJ_RESUME_DELAY=0 → بدونِ مهلت", d == 0.0, d)
        os.environ["JAFJ_NO_RESUME_DELAY"] = "1"
        d, why = M.resume_grace_plan(data, {})
        check("grace: JAFJ_NO_RESUME_DELAY=1 → خاموش", d == 0.0, why)
        os.environ.pop("JAFJ_NO_RESUME_DELAY", None)

        # ── ۳) خروجِ ناگهانی (OOM/SIGKILL) → مهلت دو برابر ────────────
        (data / M.LAST_EXIT_NAME).write_text(
            json.dumps({"code": 137, "uptime": 900, "ts": int(time.time())}),
            encoding="utf-8")
        d, why = M.resume_grace_plan(data, {})
        check("grace: خروجِ ۱۳۷ → ۲۴۰ ثانیه", d == 240.0, d)
        check("grace: دلیل «خروجِ ناگهانی» را می‌گوید", "ناگهانی" in why, why)
        (data / M.LAST_EXIT_NAME).write_text(json.dumps({"code": 0}),
                                             encoding="utf-8")
        d, _ = M.resume_grace_plan(data, {})
        check("grace: خروجِ تمیز → همان ۱۲۰", d == 120.0, d)

        # ── ۴) اتصالِ خیلی تازه (دیپلوی روی هم‌افتاده) → حداقل ۱۸۰ ─────
        (data / M.RESUME_AT_NAME).write_text(
            json.dumps({"ts": time.time() - 30}), encoding="utf-8")
        d, why = M.resume_grace_plan(data, {})
        check("grace: اتصالِ ۳۰ ثانیه پیش → حداقل ۱۸۰ ثانیه", d >= 180.0, d)
        check("grace: دلیل «شاید نسخه‌ی قبلی زنده است»",
              "نسخه‌ی قبلی" in why, why)

        # ── ۵) سقف ─────────────────────────────────────────────────────
        (data / M.LAST_EXIT_NAME).write_text(json.dumps({"code": 137}),
                                             encoding="utf-8")
        d, _ = M.resume_grace_plan(data, {"JAFJ_RESUME_DELAY": "600"})
        check("grace: سقف ۹۰۰ ثانیه (۶۰۰ × ۲ مهار می‌شود)", d == 900.0, d)
        (data / M.LAST_EXIT_NAME).unlink()

        # ── ۶) ثبتِ زمانِ اتصال روی دیسک ──────────────────────────────
        sup = M.Supervisor(M.Config(), M.DB())
        t0 = time.time()
        sup.mark_connected(1234)
        rec = json.loads((data / M.RESUME_AT_NAME).read_text(encoding="utf-8"))
        check("mark_connected: فایلِ .jafj_resume_at نوشته شد",
              abs(float(rec.get("ts") or 0) - t0) < 5, rec)
        check("mark_connected: uid ثبت شد", rec.get("uid") == 1234, rec)

        # ── ۷) در مهلت، هیچ سرویسی بالا نمی‌آید ────────────────────────
        sup._grace_until = time.time() + 60
        check("grace_left: مقدارِ مثبت در مهلت", sup.grace_left() > 50)
        started, failed, skipped = sup.resume_wanted()
        check("resume_wanted در مهلت: هیچ سرویسی شروع نمی‌شود",
              (started, failed) == ([], []) and not sup.procs,
              (started, failed))
        sup._grace_until = 0.0
        check("grace_left: بعد از مهلت صفر است", sup.grace_left() == 0.0)

        # ── ۸) پیامِ مهلت در مسیرِ بوت ────────────────────────────────
        src = (REPO / "manager_82.py").read_text(encoding="utf-8")
        check("مدیر: پیامِ «مهلتِ سشن‌ها» در بوت هست",
              "مهلتِ سشن‌ها" in src and "JAFJ_RESUME_DELAY=0" in src)

        # ── ۹) مهلتِ قفل در ۹۵.py ─────────────────────────────────────
        client = root / "client"
        client.mkdir(parents=True, exist_ok=True)
        os.chdir(client)
        SB = load95()
        check("95.py: پیش‌فرضِ مهلتِ قفل ۹۰ ثانیه است",
              SB._lock_grace() == 90.0, SB._lock_grace())
        check("95.py: بدونِ فایلِ قفل، سن None است", SB._lock_age() is None)
        os.environ["JAFJ_LOCK_GRACE"] = "0"
        check("95.py: با مهلتِ صفر فوری عبور می‌کند",
              SB._wait_for_lock_grace() is True)
        (client / SB.RUN_LOCK).write_text("999999", encoding="utf-8")
        check("95.py: قفلِ تازه، سنِ کوچک دارد", (SB._lock_age() or 99) < 5)
        os.environ["JAFJ_LOCK_GRACE"] = "1"
        t = time.time()
        SB._wait_for_lock_grace()
        spent = time.time() - t
        check("95.py: با مهلتِ ۱ ثانیه واقعاً صبر می‌کند", spent >= 0.7, spent)
        check("95.py: بعد از مهلت، قفلِ مرده آزاد می‌شود",
              SB.acquire_run_lock()[0] is True)
        SB.release_run_lock()

        # مهلتِ قفل نباید اجرای عادی را قفل کند
        os.environ["JAFJ_LOCK_GRACE"] = "0"
        ok, other = SB.acquire_run_lock()
        check("95.py: بدونِ قفلِ قبلی، بلافاصله قفل می‌گیرد",
              ok is True and other == "")
        SB.release_run_lock()
        os.chdir(here)

        # ── ۱۰) ثبتِ IP با زمان (برای تشخیصِ تغییرِ IP) ────────────────
        src95 = (REPO / "95.py").read_text(encoding="utf-8")
        check("95.py: jafj_ip.txt با زمان ذخیره می‌شود",
              'f.write(f"{ip} {int(time.time())}' in src95)
        check("95.py: هشدارِ تغییرِ IP به سشن اشاره می‌کند",
              "این اکانت سشن دارد و IP عوض شده" in src95)
    finally:
        os.chdir(here)
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        import shutil
        shutil.rmtree(root, ignore_errors=True)

    print()
    if FAILS:
        print("FAILED:", ", ".join(FAILS))
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
