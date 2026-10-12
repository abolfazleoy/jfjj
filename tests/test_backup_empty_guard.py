#!/usr/bin/env python3
"""رگرسیون «بعد از آپدیت: فایل را می‌فرستم، می‌گوید صفر مشتری و هیچ اپی نمی‌گیرد».

دو علت، هر دو روی کد واقعی سنجیده می‌شوند:

  1) دیتابیسِ خالی (بوتِ تازه قبل از بازیابی) پشتیبانِ پُرِ تلگرام را با یک
     پشتیبانِ ۰ مشتری بازنویسی می‌کرد؛ بعدش `.restore` می‌گفت «0 مشتری».
     حالا backup_once وقتی دیتابیس خالی است و پشتیبانِ پُر هست، نمی‌فرستد.
  2) zipی که مدیر در پیوی فرستاده بود نادیده گرفته می‌شد و `.restore` دستی
     از پشتیبانِ قدیمیِ تلگرام می‌خواند. حالا `.restore` دستی اول از همان zip
     بازیابی می‌کند و بعد از موفقیت فایلش را مصرف می‌کند؛ بوتِ خودکار
     (force=False) همچنان رفتار قبلی را دارد.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import test_backup_taken as _T  # FAKE telethon + helpers (با __main__ محافظت‌شده)

ROOT = os.path.join(tempfile.gettempdir(), "jafj_backup_empty_guard_run")
APP = os.path.join(ROOT, "app")
DATA = os.path.join(ROOT, "data")
STORE = os.path.join(ROOT, "store")

DRIVER = textwrap.dedent('''
import os, sys, asyncio, shutil
sys.path.insert(0, os.getcwd())
import manager_82 as M
from telethon import TelegramClient, FakeMsg, FakeDoc, CHATS

results = {}

def check(name, cond, extra=""):
    results[name] = bool(cond)
    print(f"{name} {'PASS' if cond else 'FAIL ' + str(extra)}")

def checkpoint(m):
    for conn in (m.db, m.shop):
        try:
            conn.c.execute("PRAGMA wal_checkpoint(TRUNCATE)"); conn.c.commit()
        except Exception:
            pass

def tagged():
    return [m for m in CHATS.get("111", []) if "JAFJBACKUP1" in (m.caption or "")]

def clients_in_store():
    import re
    ms = tagged()
    if not ms:
        return None
    mm = re.search(r"clients=(\\d+)", ms[0].caption or "")
    return int(mm.group(1)) if mm else None

def n_clients(m):
    r = m.db.x("SELECT COUNT(*) c FROM clients", (), "one")
    return r["c"] if r else 0

async def main():
    os.environ["BACKUP_CHAT"] = "111"
    data = os.environ["DATA_DIR"]

    # ── مرحلهٔ ۱: داده‌ی واقعی و یک پشتیبان خوب ──
    m = M.Manager(); m.bot = TelegramClient(None, 1, "h"); m.cfg["admin_ids"] = [111]
    for uid in (7, 8):
        m.db.add(uid, "u", "U", 0)
        m.db.set(uid, session="SESSION_" + str(uid) * 60, phone="+98912000%04d" % uid,
                 status="active", phone_verified=1, tg_id=uid)
    checkpoint(m)
    ok, _ = await m.backup_once(force=True)
    check("G1_good_backup_sent", ok and clients_in_store() == 2, f"ok={ok} n={clients_in_store()}")
    good_zip = os.path.join(os.environ["FAKE_BACKUP_DIR"], "good_upload.zip")
    shutil.copy2(tagged()[0]._fpath, good_zip)

    # ── مرحلهٔ ۲: دیپلوی؛ دیتابیس خالی؛ بکاپ خودکار نباید پشتیبان خوب را بزند ──
    shutil.rmtree(data, ignore_errors=True); os.makedirs(data)
    m2 = M.Manager(); m2.bot = TelegramClient(None, 1, "h"); m2.cfg["admin_ids"] = [111]
    ok2, msg2 = await m2.backup_once(force=False)
    check("G2_empty_db_does_not_overwrite", (not ok2) and clients_in_store() == 2,
          f"ok={ok2} msg={msg2} n={clients_in_store()}")
    check("G3_empty_db_guard_message", "بازنویسی نشد" in (msg2 or ""), msg2)

    # ── مرحلهٔ ۳: مدیر zip خوب را در پیوی می‌فرستد، سپس `.restore` دستی ──
    inc = FakeMsg(77, "111", caption="", sender_id=111, fpath=good_zip,
                  media=FakeDoc("jafj_backup.zip"))
    class Ev:
        sender_id = 111
        message = inc
        document = inc.document
        raw_text = ""
        file = inc.document
    m3 = M.Manager(); m3.bot = TelegramClient(None, 1, "h"); m3.cfg["admin_ids"] = [111]; m3.fsm = {}
    took = await m3.accept_admin_backup_file(Ev())
    upload = os.path.join(M.BASE_DIR, "jafj_admin_upload.zip")
    check("G4_admin_zip_kept", took and os.path.isfile(upload), f"took={took}")

    m4 = M.Manager(); m4.bot = TelegramClient(None, 1, "h"); m4.cfg["admin_ids"] = [111]
    ok4, msg4 = await m4.restore_from_backup(force=True)
    check("G5_manual_restore_uses_admin_zip", ok4 and n_clients(m4) == 2 and "فایلی که فرستادی" in msg4,
          f"ok={ok4} msg={msg4} n={n_clients(m4)}")
    check("G6_admin_zip_consumed", not os.path.exists(upload))

    # ── مرحلهٔ ۴: بوت خودکار (force=False) همچنان از تلگرام می‌خواند ──
    shutil.rmtree(data, ignore_errors=True); os.makedirs(data)
    m5 = M.Manager(); m5.bot = TelegramClient(None, 1, "h"); m5.cfg["admin_ids"] = [111]
    ok5, msg5 = await m5.restore_from_backup(force=False)
    check("G7_boot_restore_still_telegram", ok5 and n_clients(m5) == 2, f"ok={ok5} msg={msg5}")

    # ── مرحلهٔ ۵: دیتابیسِ خالیِ واقعی (بدون پشتیبان قبلی) هنوز بک‌آپ می‌گیرد ──
    CHATS.clear()
    shutil.rmtree(data, ignore_errors=True); os.makedirs(data)
    m6 = M.Manager(); m6.bot = TelegramClient(None, 1, "h"); m6.cfg["admin_ids"] = [111]
    ok6, msg6 = await m6.backup_once(force=True)
    check("G8_no_prior_backup_still_creates", ok6 and clients_in_store() == 0, f"ok={ok6} msg={msg6}")

    good = all(results.values())
    print("ALL:", "PASS" if good else "FAIL")

asyncio.run(main())
''')


def main():
    shutil.rmtree(ROOT, ignore_errors=True)
    os.makedirs(APP); os.makedirs(DATA); os.makedirs(STORE)
    for name in ("manager_82.py", "95.py"):
        shutil.copy2(os.path.join(REPO, name), APP)
    tel = os.path.join(APP, "telethon")
    os.makedirs(tel)
    with open(os.path.join(tel, "__init__.py"), "w", encoding="utf-8") as f:
        f.write(_T.FAKE_INIT)
    with open(os.path.join(tel, "sessions.py"), "w", encoding="utf-8") as f:
        f.write(_T.FAKE_SESS)
    with open(os.path.join(tel, "errors.py"), "w", encoding="utf-8") as f:
        f.write("class FloodWaitError(Exception):\n    def __init__(self, seconds=0, *a, **k):\n        self.seconds = seconds\n")
    env = dict(os.environ)
    env["DATA_DIR"] = DATA
    env["FAKE_BACKUP_DIR"] = STORE
    env["PORT"] = "8367"
    env["BACKUP_CHAT"] = "111"
    for k in ("BOT_TOKEN", "API_ID", "API_HASH", "ADMIN_IDS", "BACKUP_EVERY"):
        env.pop(k, None)
    p = subprocess.run([sys.executable, "-c", DRIVER], cwd=APP, env=env,
                       capture_output=True, text=True, timeout=200)
    out = p.stdout + p.stderr
    print(out)
    return 0 if "ALL: PASS" in out else 1


if __name__ == "__main__":
    sys.exit(main())
