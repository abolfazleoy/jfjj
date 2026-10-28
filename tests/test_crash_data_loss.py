#!/usr/bin/env python3
"""رگرسیونِ «اطلاعات گرفته می‌شد ولی با هر کرش می‌پرید».

سناریوی گزارش‌شده: ربات اطلاعات را بازیابی می‌کرد، ولی هنوز کرش می‌کرد و
داده‌ها می‌رفتند. علت‌های واقعی که این تست قفل می‌کند:

  ۱) تنها نسخه‌ی بیرونی، پشتیبانِ دوره‌ای بود (هر ۲ تا ۱۵ دقیقه). هر چیزی
     که بین دو پشتیبان ثبت می‌شد، با یک کرش می‌رفت. → حالا هر تغییرِ مهم
     (سشن، اشتراک، امتیاز، تنظیمات) با debounceِ کوتاه بیرون فرستاده می‌شود.
  ۲) هنگامِ مرگِ غیرمنتظره (استثنا/OOM) هیچ ذخیره‌ای انجام نمی‌شد. → حالا
     excepthook + threading.excepthook + atexit + مسیرِ main() هر کدام
     «ذخیره‌ی نجات» می‌زنند، و ناظرِ shell (railway-start.sh) بعد از خروجِ
     غیرصفر هم یک push می‌کند و دلیلِ خروج را می‌نویسد.
  ۳) هیچ‌جا ثبت نمی‌شد که «چرا» مرد؛ مدیر فقط می‌دید «اطلاعات پرید».
     → crash.log + .jafj_last_exit + `/diag` + هشدار در پیامِ «بالا آمد».

اجرا: `python3 tests/test_crash_data_loss.py` → باید `ALL: PASS` بدهد.
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
ROOT = os.path.join(tempfile.gettempdir(), "jafj_crashsafe_run")
DATA = os.path.join(ROOT, "data")
APP = os.path.join(ROOT, "app")
IMG = os.path.join(ROOT, "image")

shutil.rmtree(ROOT, ignore_errors=True)
os.makedirs(DATA, exist_ok=True)
os.makedirs(APP, exist_ok=True)
os.makedirs(IMG, exist_ok=True)

os.environ["DATA_DIR"] = DATA
os.environ["PORT"] = "8391"
os.environ["JAFJ_SELFBOT_REF"] = os.path.join(ROOT, "ref_95.py")
os.environ["JAFJ_FLUSH_SEC"] = "2"
os.environ.pop("DATA_GITHUB_TOKEN", None)

spec = importlib.util.spec_from_file_location("m82", os.path.join(REPO, "manager_82.py"))
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)

RESULTS = {}


def check(name, cond, extra=""):
    RESULTS[name] = bool(cond)
    print("%s %s" % (name, "PASS" if cond else "FAIL  " + str(extra)))


def scenario_crash_log():
    print("--- 1: crash.log نوشته و چرخش می‌شود، بلوک‌ها پارس می‌شوند ---")
    M.log_crash("uncaught", "ValueError: boom\n  File 'x.py', line 1")
    M.log_crash("thread", "RuntimeError: thread died")
    txt = M.read_crash_log()
    blocks = M.crash_blocks()
    check("C1a_log_written", "boom" in txt and "thread died" in txt, txt[-200:])
    check("C1b_blocks_parsed", len(blocks) >= 2 and blocks[-1][1] == "thread",
          [(b[1], b[2][:20]) for b in blocks])
    check("C1c_blocks_since_filter",
          len(M.crash_blocks(within_secs=60)) >= 2)
    # چرخش: فایل نباید بی‌نهایت رشد کند
    for _ in range(40):
        M.log_crash("bulk", "X" * 8000)
    sz = os.path.getsize(M.CRASH_LOG_FILE)
    check("C1d_rotates", sz <= M._CRASH_MAX_BYTES + 8192, sz)


def scenario_last_exit():
    print("--- 2: آخرین خروجِ ناظر ثبت/خوانده می‌شود ---")
    M.write_last_exit(137, uptime=42, note="oom?")
    ex = M.last_exit_info()
    check("C2_last_exit_roundtrip",
          ex.get("code") == 137 and ex.get("uptime") == 42, ex)


def scenario_touch_triggers_flush():
    print("--- 3: تغییرِ مهم (سشن/اشتراک) یک flush بیرونی می‌سازد ---")
    m = M.Manager()
    calls = []
    m._flush_durable = lambda why="", timeout=180, force=False: (
        calls.append((why, int(time.time()))) or True)
    M._DATA_TOUCH[0] = m._touch_data
    m.db.add(555001, "u", "U", 0)
    m.db.set(555001, session="S" * 40, status="active")   # ← تغییرِ مهم
    deadline = time.time() + 8
    while time.time() < deadline and not calls:
        time.sleep(0.2)
    check("C3a_critical_change_flushes", len(calls) == 1, calls)

    # سه تغییرِ پشتِ‌سرهم در یک پنجره → فقط یک flush
    calls.clear()
    for _ in range(3):
        m.db.set(555001, expires_at=int(time.time()) + 3600)
    deadline = time.time() + 8
    while time.time() < deadline and not calls:
        time.sleep(0.2)
    check("C3b_debounced", len(calls) == 1, calls)

    # ستون‌های پرتکرارِ watchdog نباید flush بسازند
    calls.clear()
    for _ in range(3):
        m.db.set(555001, restarts=7, started_at=int(time.time()))
    time.sleep(3.5)
    check("C3c_noise_columns_ignored", calls == [], calls)

    # تنظیمات هم تغییرِ مهم است
    calls.clear()
    m.cfg["welcome"] = "salam"
    m.cfg.save()
    deadline = time.time() + 8
    while time.time() < deadline and not calls:
        time.sleep(0.2)
    check("C3d_config_change_flushes", len(calls) == 1, calls)


def scenario_flush_paths():
    print("--- 4: flush بدون توکن/بدون اتصال امن است؛ با توکن push می‌کند ---")
    m = M.Manager()
    check("C4a_no_token_no_bot_is_safe",
          m._flush_durable("x", force=True) is False)
    # با توکنِ جعلی و ابزارِ جعلی → push اجرا می‌شود
    marker = os.path.join(ROOT, "push.marker")
    tool = os.path.join(ROOT, "fakepush.py")
    with open(tool, "w", encoding="utf-8") as f:
        f.write("import sys\nopen(%r,'a').write(' '.join(sys.argv[1:])+'\\n')\n"
                % marker)
    os.environ["DATA_GITHUB_TOKEN"] = "dummy"
    m._gh_sync_cmd = lambda: [sys.executable, tool, "push"]
    ok = m._flush_durable("تست", timeout=30, force=True)
    check("C4b_push_runs", ok and os.path.isfile(marker)
          and "push" in open(marker).read(), ok)
    # throttle: بدون force و زیر ۴۵ ثانیه → رد
    m._last_flush = time.time()
    check("C4c_throttled", m._flush_durable("دوباره") is False)
    os.environ.pop("DATA_GITHUB_TOKEN", None)


def scenario_thread_crash_hook():
    print("--- 5: استثنای یک thread در crash.log ثبت می‌شود ---")
    m = M.Manager()
    m._install_crash_hooks()
    before = len(M.crash_blocks())

    def _boom():
        raise RuntimeError("thread-crash-marker")
    t = threading.Thread(target=_boom)
    t.start()
    t.join()
    time.sleep(0.5)
    after = len(M.crash_blocks())
    check("C5_thread_exception_logged", after > before, (before, after))
    check("C5b_hook_reason", M.crash_blocks()[-1][1] == "thread",
          M.crash_blocks()[-1][:2])
    check("C5c_hook_wired", M._DATA_TOUCH[0] is not None)


def scenario_startup_notices_and_diag():
    print("--- 6: هشدارِ بوت و /diag وضعیت دیسک/کرش/نسخه‌ی بیرونی را می‌گویند ---")
    m = M.Manager()
    m.boot_at = time.time() - 300
    notices = m._startup_notices()
    joined = " | ".join(notices)
    check("C6a_notice_mentions_crash_or_exit",
          ("آخرین خروج" in joined) or ("کرش" in joined) or ("بوت سرد" in joined),
          joined)
    check("C6b_notice_warns_without_token",
          ("DATA_GITHUB_TOKEN" in joined) or ("Disk" in joined), joined)
    d = m.diag_text()
    for token in ("عیب‌یابی", "داده", "گیت‌هاب", "حافظه"):
        check("C6c_diag_has_%s" % token, token in d, d[:200])
    check("C6d_diag_mentions_crash", "کرش" in d)


def scenario_supervisor_script():
    print("--- 7: ناظرِ shell بعد از کرش، دلیل را ثبت و pushِ نجات می‌زند ---")
    # ابزارِ سینکِ جعلی در «ایمیج»
    os.makedirs(os.path.join(IMG, "tools"), exist_ok=True)
    with open(os.path.join(IMG, "manager_82.py"), "w", encoding="utf-8") as f:
        f.write("# placeholder\n")
    shutil.copy2(os.path.join(REPO, "railway-start.sh"),
                 os.path.join(IMG, "railway-start.sh"))

    marker = os.path.join(ROOT, "supervisor_push.marker")
    sync_py = os.path.join(IMG, "tools", "gh_data_sync.py")
    with open(sync_py, "w", encoding="utf-8") as f:
        f.write("import sys\n")

    # پایتونِ جعلی: manager فوراً با کد ۳ می‌میرد، push/loop را ثبت می‌کند
    fake_py = os.path.join(ROOT, "fakepython.sh")
    with open(fake_py, "w", encoding="utf-8") as f:
        f.write("#!/bin/sh\n"
                'case "$*" in\n'
                '  *gh_data_sync.py*push*) echo PUSH >> "%s"; exit 0;;\n'
                '  *gh_data_sync.py*loop*) sleep 30; exit 0;;\n'
                '  *gh_data_sync.py*pull*) exit 0;;\n'
                '  *manager_82.py*) echo BOOT >> "%s"; exit 3;;\n'
                'esac\nexit 0\n' % (marker, marker))
    os.chmod(fake_py, 0o755)

    data2 = os.path.join(ROOT, "data_sup")
    os.makedirs(data2, exist_ok=True)
    env = dict(os.environ)
    env.update({
        "DATA_DIR": data2, "PYTHON": fake_py, "JAFJ_IMAGE_DIR": IMG,
        "JAFJ_SUPERVISE": "1", "JAFJ_MAX_CRASHES": "1",
        "JAFJ_NAP_BASE": "0", "JAFJ_CRASH_WINDOW": "20",
        "DATA_GITHUB_TOKEN": "dummy-token",
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
    })
    p = subprocess.run(["sh", os.path.join(IMG, "railway-start.sh")],
                       env=env, capture_output=True, text=True, timeout=120)
    out = (p.stdout or "") + (p.stderr or "")
    marks = ""
    if os.path.isfile(marker):
        marks = open(marker).read()
    crash = ""
    cpath = os.path.join(data2, "crash.log")
    if os.path.isfile(cpath):
        crash = open(cpath, encoding="utf-8", errors="ignore").read()
    last_exit = {}
    lpath = os.path.join(data2, ".jafj_last_exit")
    if os.path.isfile(lpath):
        try:
            last_exit = json.load(open(lpath))
        except Exception:
            last_exit = {}
    check("C7a_boot_attempted", "BOOT" in marks, marks)
    check("C7b_emergency_push_after_crash", "PUSH" in marks, marks)
    check("C7c_crash_logged_by_shell",
          "supervisor" in crash and "exit=3" in crash, crash[:300])
    check("C7d_last_exit_recorded", last_exit.get("code") == 3, last_exit)
    check("C7e_supervisor_gives_up", p.returncode != 0 or "crashed" in out,
          "rc=%s out=%s" % (p.returncode, out[-300:]))


def main():
    try:
        scenario_crash_log()
        scenario_last_exit()
        scenario_touch_triggers_flush()
        scenario_flush_paths()
        scenario_thread_crash_hook()
        scenario_startup_notices_and_diag()
        scenario_supervisor_script()
    except Exception as e:
        import traceback
        traceback.print_exc()
        RESULTS["EXCEPTION"] = "%s: %s" % (type(e).__name__, e)
    finally:
        shutil.rmtree(ROOT, ignore_errors=True)
    good = all(v is True for v in RESULTS.values()) and "EXCEPTION" not in RESULTS
    print("ALL:", "PASS" if good else "FAIL")
    sys.exit(0 if good else 1)


if __name__ == "__main__":
    main()
