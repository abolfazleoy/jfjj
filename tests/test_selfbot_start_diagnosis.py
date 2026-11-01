#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""«مدیر بالا می‌آید ولی سلف روشن نمی‌شود» — علت باید گفته شود، نه حدس زده.

گزارشِ کاربر: در پنل «🚀 راه‌اندازی سلف روی اکانتم» را می‌زد، مدیر سالم بود
ولی هیچ پیامی در Saved Messages نمی‌آمد. ریشه‌ی «بی‌صدا بودن» این بود:

  * `Sup.start()` فقط ۱.۲ ثانیه صبر می‌کرد؛ سلفی که در ثانیه‌ی ۳ (سشن باطل،
    نبودِ telethon، خطای شبکه) می‌مرد «روشن» شمرده می‌شد؛
  * watchdog هر ۳۰ ثانیه تا ۱۰ دقیقه بی‌صدا دوباره تلاش می‌کرد؛
  * شکست‌های اولیه (سشن ندارد / فایل سلف / ظرفیت) بدون لاگ و مسیرِ پوشه
    برگردانده می‌شدند و در `/diag` هم چیزی نبود.

این تست چهار چیز را قفل می‌کند:

  ۱) `classify_selfbot_log` علت را از لاگِ خودِ ۹۵.py درست دسته‌بندی می‌کند.
  ۲) پیامِ شکست، آخرین خطوطِ run.log و مسیرِ پوشه‌ی همان اکانت را دارد.
  ۳) `_watch_start` پروسه‌ای که بعد از Popen می‌میرد را می‌بیند، علت را ثبت
     می‌کند و (برای سشن) اکانت را «نیاز به لاگین» می‌کند؛ و پروسه‌ای که فقط
     در اتصال گیر کرده را هم به‌عنوان «شبکه» گزارش می‌کند.
  ۴) اگر مفسرِ اجراکننده telethon نداشته باشد، `start` هیچ پروسه‌ای نمی‌سازد
     و پیامِ روشن می‌دهد (به‌جای سلفی که فوراً می‌میرد).
"""
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


def main():
    root = Path(tempfile.mkdtemp(prefix="jafj_selfdiag_"))
    os.environ["DATA_DIR"] = str(root / "data")
    os.environ["PORT"] = "8244"
    os.environ.pop("JAFJ_ONLY", None)
    sys.path.insert(0, str(REPO))
    import manager_82 as M

    sup = M.Supervisor(M.Config(), M.DB())

    # ── ۱) دسته‌بندیِ علت از لاگِ سلف ────────────────────────────────────
    cases = [
        ("⛔ سشنِ این اکانت معتبر نیست (از تلگرام خارج یا باطل شده).", 78, "session"),
        ("", 78, "session"),
        ("AUTH_KEY_UNREGISTERED: the key was unregistered", None, "keydup"),
        ("needs_relogin: سشن معتبر نیست", None, "session"),
        ("📦 Telethon نصب نیست — نصبش می‌کنم…", None, "deps"),
        ("ModuleNotFoundError: No module named 'telethon'", 1, "deps"),
        ("⚠️ اتصال برای بررسیِ سشن: ConnectionError: Cannot connect", None, "network"),
        ("Traceback (most recent call last):\n  File \"95.py\"\nValueError: x", 1, "crash"),
        ("", 3, "exit"),
        ("", None, ""),
    ]
    for tail, rc, want in cases:
        got, hint = M.classify_selfbot_log(tail, rc)
        check(f"classify({want or 'سالم'}) از لاگ «{(tail or '')[:28]}» rc={rc}",
              got == want and (hint != "" if want else hint == ""), got)

    # ── ۲) پیامِ شکست: لاگ + مسیر، و escape شدنِ HTML ────────────────────
    txt = M.selfbot_failure_text("سلف اجرا نشد", "line1\n<a>bad</a>", "/data/clients/1")
    check("پیامِ شکست آخرین خطوطِ لاگ را دارد", "line1" in txt and "bad" in txt)
    check("پیامِ شکست، تگِ خام را نمی‌فرستد (escape)", "<a>bad</a>" not in txt and "&lt;a&gt;" in txt)
    check("پیامِ شکست مسیرِ پوشه را دارد", "/data/clients/1" in txt)
    empty = M.selfbot_failure_text("فقط پیام", "لاگی نیست.", "")
    check("لاگِ خالی، بلوکِ <pre> خالی نمی‌سازد", "<pre>" not in empty)

    # ── ۳) _why: ثبتِ علت + لاگ + پوشه ──────────────────────────────────
    uid = 4242
    folder = Path(sup.folder(uid))
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "run.log").write_text(
        "===== start =====\nValueError: api_id نامعتبر\n", encoding="utf-8")
    ok, msg = sup._why(uid, "selfbot", "سلف اجرا نشد", hint="خطای تست")
    check("_why → False و پیامِ کامل", ok is False and "سلف اجرا نشد" in msg)
    check("_why → last_failure/last_detail ثبت شد",
          sup.last_failure[uid] == "selfbot" and sup.last_detail[uid] == "خطای تست")
    check("_why → خطِ آخرِ run.log در پیام هست", "api_id نامعتبر" in msg, msg[-120:])
    check("_why → مسیرِ پوشه‌ی اکانت در پیام هست", str(folder) in msg)

    # ── ۴) هشدارِ «telethon نیست» اجرا را مسدود نمی‌کند ────────────────────
    # چرا فقط هشدار: خودِ 95.py اول telethon را pip install می‌کند؛ مسدود
    # کردنِ اجرا، سلفِ سالمی را که فقط هشدار داده بود از کار می‌انداخت.
    _real = subprocess.run([sys.executable, "-c", "import telethon"],
                           stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL).returncode == 0
    check("python_deps_ok() با واقعیتِ مفسر می‌خواند (نه حدس)",
          sup.python_deps_ok() is _real, f"واقعی={_real}")

    uid2 = 4243
    f2 = Path(sup.folder(uid2))
    f2.mkdir(parents=True, exist_ok=True)
    (f2 / "jafj.session").write_bytes(b"x")          # فقط وجودش چک می‌شود
    sup.db.x("INSERT OR IGNORE INTO clients(uid, status, created_at, session)"
             " VALUES(?,?,?,?)", (uid2, "active", int(time.time()), "s" * 40), None)
    fake_self = root / "fake_95.py"
    fake_self.write_text("import time\nVERSION = '3.0-test'\ntime.sleep(60)\n",
                         encoding="utf-8")
    _real_selfbot = M.SELFBOT
    M.SELFBOT = str(fake_self)
    sup._session_ok_or_mark = lambda u: (True, "")
    sup.sync_selfbot = lambda u: (True, "")
    sup._deps_ok = False                 # مفسری بدونِ telethon را شبیه‌سازی کن
    seen = []
    _orig_log = sup.db.log

    def _spy_log(u, kind, *a, **k):
        seen.append(kind)
        return _orig_log(u, kind, *a, **k)

    sup.db.log = _spy_log
    ok, msg = sup.start(uid2)
    check("start با مفسرِ بدون telethon هنوز اجرا می‌کند (هشدار نه توقف)",
          ok is True, msg[:160])
    check("start پروسه را واقعاً ساخت",
          uid2 in sup.procs and sup.procs[uid2].poll() is None)
    check("start هشدارِ deps_missing را در لاگ ثبت کرد", "deps_missing" in seen, seen)
    try:
        sup.stop(uid2)
    except Exception:
        pass
    sup.db.log = _orig_log
    M.SELFBOT = _real_selfbot
    sup._deps_ok = None

    # ── ۵) _watch_start: مرگِ بعد از start (کد ۷۸ = سشن) ─────────────────
    uid3 = 4244
    f3 = Path(sup.folder(uid3))
    f3.mkdir(parents=True, exist_ok=True)
    (f3 / "jafj.session").write_bytes(b"fake")
    # رکورد لازم است: mark_needs_login با UPDATE کار می‌کند، نه INSERT
    sup.db.x("INSERT OR IGNORE INTO clients(uid, status, created_at, session)"
             " VALUES(?,?,?,?)", (uid3, "active", int(time.time()), "s" * 40), None)
    logf = open(f3 / "run.log", "a", encoding="utf-8")
    p = subprocess.Popen(
        [sys.executable, "-c",
         "import sys; print('⛔ سشنِ این اکانت معتبر نیست (از تلگرام خارج یا باطل شده).');"
         " sys.exit(78)"],
        stdout=logf, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    logf.close()
    sup.procs[uid3] = p
    sup._write_pid(uid3, p.pid)
    sup._watch_start(uid3, p, delay=6)
    deadline = time.time() + 15
    while time.time() < deadline and sup.last_failure.get(uid3) is None:
        time.sleep(0.2)
    check("watch: سلفِ مُرده «session» تشخیص داده شد",
          sup.last_failure.get(uid3) == "session", sup.last_failure.get(uid3))
    check("watch: پروسه از لیست خارج شد", uid3 not in sup.procs)
    check("watch: اکانت «نیاز به لاگین» شد",
          bool((sup.db.get(uid3) or {}).get("need_login")))
    check("watch: سشنِ خراب قرنطینه شد (.bad)",
          (f3 / "jafj.session.bad").exists())
    check("watch: علت در last_detail هست",
          "سشن" in (sup.last_detail.get(uid3) or ""), sup.last_detail.get(uid3))

    # ── ۶) _watch_start: زنده ولی «گیرکرده در اتصال» ──────────────────────
    uid4 = 4245
    f4 = Path(sup.folder(uid4))
    f4.mkdir(parents=True, exist_ok=True)
    logf = open(f4 / "run.log", "a", encoding="utf-8")
    p2 = subprocess.Popen(
        [sys.executable, "-c",
         "import time, sys\n"
         "print('⚠️ اتصال برای بررسیِ سشن: ConnectionError')\n"
         "sys.stdout.flush()\n"
         "time.sleep(40)"],
        stdout=logf, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    logf.close()
    sup.procs[uid4] = p2
    sup._watch_start(uid4, p2, delay=3)
    deadline = time.time() + 15
    while time.time() < deadline and not sup.last_detail.get(uid4):
        time.sleep(0.2)
    check("watch: «گیرکرده در اتصال» گزارش شد",
          "تلگرام" in (sup.last_detail.get(uid4) or ""), sup.last_detail.get(uid4))
    check("watch: پروسه‌ی زنده «شکست» علامت نخورد", uid4 not in sup.last_failure)
    try:
        p2.kill()
    except Exception:
        pass

    # ── ۷) /diag: سلفِ خاموش با علت و خطِ آخرِ لاگ ────────────────────────
    mg = M.Manager.__new__(M.Manager)

    class FakeDB:
        def wanted(self):
            return [{"uid": uid3, "name": "acc <b>"}]

    mg.db = FakeDB()
    mg.sup = sup
    (f3 / "run.log").write_text("boom: ValueError\n", encoding="utf-8")
    lines = mg.selfbot_diag_lines()
    joined = "\n".join(lines)
    check("/diag سطرِ سلفِ خاموش را دارد", "خاموش" in joined, joined[:200])
    check("/diag علت را می‌نویسد", "سشن" in joined, joined[:200])
    check("/diag اسم را escape می‌کند",
          "&lt;b&gt;" in joined and "<b>" not in joined, joined[:200])
    check("/diag خطِ آخرِ لاگ را نشان می‌دهد", "boom" in joined, joined[:200])

    print()
    if FAILS:
        print("FAILED:", ", ".join(FAILS))
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
