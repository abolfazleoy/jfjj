#!/usr/bin/env python3
"""رگرسیونِ «بعد از آپدیت، سرویس‌هایی که روشن بودند درجا روشن شوند».

سناریوی گزارش‌شده: مدیر کد را آپدیت می‌کند (دیپلوی) و اطلاعات را هم برمی‌گرداند،
ولی بعد از آن هیچ سرویسی بالا نمی‌آید و باید برای تک‌تک مشتری‌ها دستی
«روشن کن» بزند.

علت ریشه‌ای که این تست قفل می‌کند:

  * `watchdog` فقط سرویس‌هایی را بلند می‌کرد که از قبل در `self.procs` بودند
    (`if uid in self.procs`). هر سرویسی که موقع بوت بالا نیامده بود، تا ابد
    خاموش می‌ماند.
  * `restore_from_backup` اطلاعات را برمی‌گرداند ولی هیچ سرویسی را روشن
    نمی‌کرد.

الان «نیتِ روشن‌بودن» روی دیسک ذخیره می‌شود (`clients.want_on`) و
`Supervisor.resume_wanted()` / `boot_all()` همان را دوباره اجرا می‌کنند.
همچنین پروسه‌ی سلفی که بعد از ری‌استارتِ manager زنده مانده «پذیرفته»
می‌شود تا نسخه‌ی دوم روی همان سشن اجرا نشود.

اجرا: `python3 tests/test_resume_after_update.py` → باید `ALL: PASS` بدهد.
"""
import importlib.util
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
ROOT = os.path.join(tempfile.gettempdir(), "jafj_resume_run")
DATA = os.path.join(ROOT, "data")
FAKE_SELF = os.path.join(ROOT, "fake_selfbot.py")

# قبل از ایمپورت: داده‌ها داخل پوشه‌ی موقت، نه کنار کد
shutil.rmtree(ROOT, ignore_errors=True)
os.makedirs(DATA, exist_ok=True)
os.environ["DATA_DIR"] = DATA
os.environ["JAFJ_SELFBOT_REF"] = os.path.join(ROOT, "ref_95.py")

with open(FAKE_SELF, "w", encoding="utf-8") as f:
    f.write("import time\nVERSION='3.0-test'\ntime.sleep(120)\n")

spec = importlib.util.spec_from_file_location("m82", os.path.join(REPO, "manager_82.py"))
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)

M.SELFBOT = FAKE_SELF          # سلفِ واقعی لازم نیست؛ فقط یک پروسه‌ی زنده
CFG = dict(M.DEFAULTS)
CFG["auto_restart"] = True


def new_db(name):
    """دیتابیس جدا برای هر سناریو — وگرنه کلاینت‌های سناریوی قبل هم بالا می‌آیند."""
    return M.DB(os.path.join(DATA, "db_%s.db" % name))


def fresh_sup(db):
    """Supervisor تازه — مثل بوتِ بعد از آپدیت (procs خالی، دیسک پر)."""
    s = M.Supervisor(M.Config(), db)
    s.mgr = None
    return s


def add_client(db, uid, want=1):
    db.add(uid, "u%s" % uid, "user%s" % uid, 0)
    db.set(uid, status="active", session="x" * 40, phone="0912", want_on=want)
    folder = os.path.join(DATA, "clients", str(uid))
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "jafj.session"), "wb") as f:
        f.write(b"fake-session")
    return uid


def kill_all(sup):
    for uid in list(sup.procs):
        try:
            sup.stop(uid)
        except Exception:
            pass


def scenario_schema():
    print("--- 1: ستون want_on + مهاجرت دیتابیسِ قدیمی ---")
    db = new_db("schema")
    cols = {r[1] for r in db.c.execute("PRAGMA table_info(clients)")}
    assert "want_on" in cols, cols
    # رکوردِ قدیمی که ستون را ندارد باید «باید روشن بماند» حساب شود
    db.x("INSERT INTO clients (uid,status,session,created_at) VALUES (?,?,?,?)",
         (999001, "active", "y" * 40, int(time.time())))
    db.x("UPDATE clients SET want_on=1 WHERE uid=?", (999001,))
    assert db.want_on(999001) is True
    db.set_want(999001, False)
    assert db.want_on(999001) is False
    db.x("DELETE FROM clients WHERE uid=?", (999001,))
    db.close()
    print("scenario1: PASS")


def scenario_boot_after_update():
    print("--- 2: بعد از آپدیت، سرویس‌های «روشن» خودکار بالا می‌آیند ---")
    db = new_db("boot")
    a, b = add_client(db, 700001), add_client(db, 700002)
    sup = fresh_sup(db)
    n = sup.boot_all()
    assert n == 2, n
    assert sup.is_running(a) and sup.is_running(b)
    pid_a = sup.procs[a].pid
    print("boot_all=%d pids=%s" % (n, [sup.procs[u].pid for u in (a, b)]))

    # ── ری‌استارتِ manager (بدون کشته‌شدنِ کانتینر) ──
    sup2 = fresh_sup(db)          # procs خالی، ولی پروسه‌ها زنده‌اند
    assert sup2.is_running(a), "پروسه‌ی زندهٔ قبلی پذیرفته نشد"
    n2 = sup2.boot_all()
    assert n2 == 2, n2
    assert sup2.procs[a].pid == pid_a, "سلفِ دوم روی همان سشن اجرا شد!"
    print("after manager restart: adopted pid=%s (same), boot_all=%d"
          % (sup2.procs[a].pid, n2))

    # ── watchdog باید همان‌ها را روشن نگه دارد، نه دوباره اجرا کند ──
    started, failed, skipped = sup2.resume_wanted()
    assert started == [] and failed == [], (started, failed)
    kill_all(sup2)
    db.close()
    print("scenario2: PASS")


def scenario_manual_off_is_remembered():
    print("--- 3: خاموشیِ عمدی بعد از آپدیت «خودکار روشن» نمی‌شود ---")
    db = new_db("off")
    on_uid, off_uid = add_client(db, 700011), add_client(db, 700012)
    sup = fresh_sup(db)
    sup.boot_all()
    assert sup.is_running(off_uid)
    sup.stop(off_uid, remember_off=True)      # مشتری خودش خاموش کرد
    assert db.want_on(off_uid) is False
    assert db.want_on(on_uid) is True

    sup2 = fresh_sup(db)                       # آپدیت/ری‌استارت
    started, failed, _ = sup2.resume_wanted()
    assert off_uid not in started, started
    n = sup2.boot_all()
    assert not sup2.is_running(off_uid), "سرویسِ خاموش‌شده خودکار روشن شد"
    assert n == 1, n

    # روشن‌کردنِ دستی، نیت را برمی‌گرداند
    ok, _msg = sup2.start(off_uid)
    assert ok and db.want_on(off_uid) is True
    kill_all(sup2)
    db.close()
    print("scenario3: PASS")


def scenario_resume_missing():
    print("--- 4: سرویسی که در procs نیست ولی باید روشن باشد بلند می‌شود ---")
    db = new_db("missing")
    uid = add_client(db, 700021)
    sup = fresh_sup(db)
    # دقیقاً همان باگِ قدیمی: پروسه هیچ‌وقت در جدول نبود
    assert uid not in sup.procs
    started, failed, _ = sup.resume_wanted()
    assert started == [uid] and not failed, (started, failed)
    assert sup.is_running(uid)
    kill_all(sup)
    db.close()
    print("scenario4: PASS")


def scenario_code_change_restarts():
    print("--- 5: اگر 95.py تازه‌تر از پروسه باشد، ری‌استارت می‌شود ---")
    db = new_db("code")
    uid = add_client(db, 700031)
    sup = fresh_sup(db)
    sup.boot_all()
    pid1 = sup.procs[uid].pid
    time.sleep(1.1)
    with open(FAKE_SELF, "a", encoding="utf-8") as f:
        f.write("# new build\n")               # نسخه‌ی تازه‌ی سلف
    os.utime(FAKE_SELF, None)
    assert sup._code_changed_since_start(uid) is True

    sup2 = fresh_sup(db)
    sup2.boot_all()
    pid2 = sup2.procs[uid].pid
    assert pid2 != pid1, (pid1, pid2)
    print("pid %s -> %s (restarted for new code)" % (pid1, pid2))
    kill_all(sup2)
    db.close()
    print("scenario5: PASS")


def scenario_restore_forces_restart():
    print("--- 7: بعد از بازیابی، سرویسِ در حال اجرا هم با داده‌ی تازه بالا می‌آید ---")
    db = new_db("force")
    uid = add_client(db, 700051)
    sup = fresh_sup(db)
    sup.boot_all()
    pid1 = sup.procs[uid].pid
    # boot_all عادی نباید دست بزند (کد عوض نشده)
    sup.boot_all()
    assert sup.procs[uid].pid == pid1, "بوتِ عادی سرویسِ سالم را ری‌استارت کرد"
    # بعد از بازیابی باید ری‌استارت شود
    sup.boot_all(force_restart=True)
    pid2 = sup.procs[uid].pid
    assert pid2 != pid1, (pid1, pid2)
    print("pid %s -> %s (forced after restore)" % (pid1, pid2))
    kill_all(sup)
    db.close()
    print("scenario7: PASS")


def scenario_restore_hook():
    print("--- 6: بعد از بازیابی، سرویس‌ها خودکار بالا می‌آیند ---")
    db = new_db("restore")
    a = add_client(db, 700041)
    m = M.Manager()
    m.db = db
    m.sup.db = db
    called = {}
    def _fake_boot(force_restart=False):
        called["boot"] = True
        called["force"] = force_restart
        return 1
    m.sup.boot_all = _fake_boot
    n = m._resume_after_restore("تست")
    for _ in range(50):                    # بوت در thread جدا اجرا می‌شود
        if called.get("boot"):
            break
        time.sleep(0.1)
    assert n == 1 and called.get("boot") is True, (n, called)
    assert called.get("force") is True, called
    db.close()
    print("scenario6: PASS")


def main():
    scenario_schema()
    scenario_boot_after_update()
    scenario_manual_off_is_remembered()
    scenario_resume_missing()
    scenario_code_change_restarts()
    scenario_restore_forces_restart()
    scenario_restore_hook()
    print("ALL: PASS")


if __name__ == "__main__":
    try:
        main()
    finally:
        # هیچ پروسه‌ای جا نماند
        try:
            import subprocess
            subprocess.call(["pkill", "-f", "fake_selfbot.py"])
        except Exception:
            pass
        shutil.rmtree(ROOT, ignore_errors=True)
