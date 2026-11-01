#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""«دو نسخه روی یک اکانت» — همان چیزی که «سلف بالا نمی‌آید» را می‌ساخت.

گزارشِ کاربر بعد از یک تغییرِ من: «سلف روی اکانت ران بود، حالا می‌گوید دوباره
ران کنن.» و پیامِ مدیر: «علت: به تلگرام وصل نمی‌شود» با لاگِ
«🔄 اتصال قطع شد … (پیام‌های صف حفظ شده‌اند)».

ریشه: اگر **دو پروسه** روی یک سشن اجرا شوند، تلگرام هر دو اتصال را می‌بندد؛
نتیجه‌اش همین حلقه است و کاربر فکر می‌کند سلف بالا نیامده. این تست سه لایه‌ی
محافظ را قفل می‌کند:

  ۱) `95.py` قفلِ `jafj.run.lock` دارد: نسخه‌ی دومِ همان پوشه اجرا نمی‌شود و
     با کدِ ۷۶ خارج می‌شود (قفلِ مرده خودکار آزاد می‌شود).
  ۲) مدیر کدِ ۷۶ و نشانه‌های `AUTH_KEY_DUPLICATED` را «نسخه‌ی تکراری»
     می‌شناسد: نه سشن را قرنطینه می‌کند، نه «نیاز به لاگین» می‌زند، نه
     امتیازِ مشتری را کسر می‌کند.
  ۳) پیامِ «نتوانست وصل شود» می‌گوید اول باید مطمئن شد فقط یک نسخه بالاست.
"""
import importlib.util
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
FAILS = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + (f"   [{extra}]" if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def load95():
    spec = importlib.util.spec_from_file_location("sb95_t", str(REPO / "95.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    root = Path(tempfile.mkdtemp(prefix="jafj_dup_"))
    here = os.getcwd()
    saved_data = os.environ.get("DATA_DIR")
    os.environ["DATA_DIR"] = str(root / "data")
    os.environ["PORT"] = "8255"
    os.environ.pop("JAFJ_ONLY", None)
    try:
        # ── ۱) قفلِ یک‌نسخه‌ای در 95.py ───────────────────────────────────
        client = root / "clients" / "1"
        client.mkdir(parents=True)
        os.chdir(client)
        SB = load95()

        ok, other = SB.acquire_run_lock()
        check("95.py: اولین نسخه قفل را می‌گیرد", ok is True and other == "")
        check("95.py: فایلِ قفل ساخته شد", (client / SB.RUN_LOCK).is_file())
        check("95.py: pidِ خودمان داخلِ قفل است",
              (client / SB.RUN_LOCK).read_text().strip() == str(os.getpid()))
        SB.release_run_lock()
        check("95.py: آزادکردن، فایل را پاک می‌کند",
              not (client / SB.RUN_LOCK).exists())

        # قفلِ مرده (PID بازاستفاده‌شده/تمام‌شده) باید آزاد شود
        (client / SB.RUN_LOCK).write_text("999999", encoding="utf-8")
        ok, other = SB.acquire_run_lock()
        check("95.py: قفلِ مرده خودکار آزاد می‌شود", ok is True, other)
        SB.release_run_lock()

        # نسخه‌ی زنده‌ی همان پوشه → نسخه‌ی دوم نباید اجرا شود
        fake = client / "95.py"
        fake.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
        holder = subprocess.Popen([sys.executable, "95.py"], cwd=str(client),
                                  stdin=subprocess.DEVNULL)
        time.sleep(0.7)
        (client / SB.RUN_LOCK).write_text(str(holder.pid), encoding="utf-8")
        ok, other = SB.acquire_run_lock()
        check("95.py: با نسخه‌ی زنده‌ی همان پوشه، قفل داده نمی‌شود",
              ok is False and other == str(holder.pid), (ok, other))

        # main() در این حالت باید با کدِ ۷۶ خارج شود (بدونِ لمسِ شبکه)
        harness = ("import importlib.util, sys\n"
                   "spec = importlib.util.spec_from_file_location('s', "
                   f"{str(REPO / '95.py')!r})\n"
                   "m = importlib.util.module_from_spec(spec)\n"
                   "spec.loader.exec_module(m)\n"
                   "sys.exit(m.main())\n")
        r = subprocess.run([sys.executable, "-c", harness], cwd=str(client),
                           capture_output=True, text=True, timeout=60)
        check("95.py: نسخه‌ی دوم با کد ۷۶ خارج می‌شود", r.returncode == 76,
              r.returncode)
        check("95.py: پیامِ «نسخه‌ی دیگری» چاپ می‌شود",
              "نسخه‌ی دیگری" in r.stdout, r.stdout[-200:])
        holder.kill()
        holder.wait()
        # قفلِ پروسه‌ی مرده دوباره آزاد می‌شود
        ok, _ = SB.acquire_run_lock()
        check("95.py: بعد از مرگِ نسخه‌ی اول، قفل آزاد می‌شود", ok is True)
        SB.release_run_lock()
        os.chdir(here)

        # ── ۲) مدیر: تشخیصِ نسخه‌ی تکراری ─────────────────────────────────
        sys.path.insert(0, str(REPO))
        import manager_82 as M

        # توجه: AUTH_KEY_DUPLICATED عمداً این‌جا نیست — آن یعنی کلیدِ سوخته
        # (تستِ test_auth_key_burned.py) و درمانش لاگینِ دوباره است، نه
        # «سشن سالم است».
        for tail, rc in [("⛔ نسخه‌ی دیگری از همین اکانت همین حالا در حال اجراست",
                          None),
                         ("⛔ قفلِ jafj.run.lock گرفته شد", None),
                         ("", 76)]:
            kind, hint = M.classify_selfbot_log(tail, rc)
            check(f"classify → dup برای «{(tail or '')[:26]}» rc={rc}",
                  kind == "dup" and "نسخه‌ی" in hint, kind)

        # پیامِ «وصل نمی‌شود» باید راهنمای «فقط یک نسخه» داشته باشد
        body = M.selfbot_failure_notice("acc", 1, "network",
                                        "به تلگرام وصل نمی‌شود",
                                        "🔄 اتصال قطع شد")
        check("پیامِ شبکه: «فقط یک نسخه» را می‌گوید", "فقط یک نسخه" in body,
              body[-200:])
        body2 = M.selfbot_failure_notice("acc", 1, "dup", "نسخه‌ی تکراری")
        check("پیامِ dup: می‌گوید نسخه‌ی اضافه بسته شد",
              "نسخه‌ی اضافه" in body2, body2[-200:])
        check("پیام‌ها HTML را escape می‌کنند",
              "<b>سلف روی این اکانت بالا نیامد</b>" in body
              and "&lt;" not in body.split("🔎")[0])

        # ── ۳) مدیر: کدِ ۷۶ نباید «نیاز به لاگین» یا کسرِ امتیاز بدهد ─────
        sup = M.Supervisor(M.Config(), M.DB())
        uid = 4321
        folder = Path(sup.folder(uid))
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "jafj.session").write_bytes(b"session")
        (folder / "jafj_creds.json").write_text("{}", encoding="utf-8")
        sup.db.x("INSERT OR IGNORE INTO clients(uid, status, created_at, session)"
                 " VALUES(?,?,?,?)", (uid, "active", int(time.time()), "s" * 40), None)
        dup_self = root / "dup_95.py"
        dup_self.write_text(
            "import sys\n"
            "print('⛔ نسخه‌ی دیگری از همین اکانت همین حالا در حال اجراست')\n"
            "sys.exit(76)\n", encoding="utf-8")
        old_self = M.SELFBOT
        M.SELFBOT = str(dup_self)
        sup._session_ok_or_mark = lambda u: (True, "")
        sup.sync_selfbot = lambda u: (True, "")
        ok, msg = sup.start(uid)
        M.SELFBOT = old_self
        check("start با کد ۷۶ → False", ok is False)
        check("start با کد ۷۶ → نوعِ manager (امتیاز کسر نشود)",
              sup.last_failure.get(uid) == "manager", sup.last_failure.get(uid))
        check("start با کد ۷۶ → پیام «دو نسخه» می‌دهد", "دو نسخه" in msg,
              msg[:200])
        check("start با کد ۷۶ → سشن قرنطینه نمی‌شود",
              (folder / "jafj.session").exists()
              and not (folder / "jafj.session.bad").exists())
        check("start با کد ۷۶ → نیاز به لاگین علامت نمی‌خورد",
              not (sup.db.get(uid) or {}).get("need_login"),
              (sup.db.get(uid) or {}).get("need_login"))
    finally:
        os.chdir(here)
        if saved_data is None:
            os.environ.pop("DATA_DIR", None)
        else:
            os.environ["DATA_DIR"] = saved_data
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
