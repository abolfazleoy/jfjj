#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""پشتیبانیِ Hostless (hostless.cloud) — همان «The process stopped soon after
it started · Exit code 0».

این گزارش دقیقاً چه معنایی دارد و اینجا چه چیزی تضمین می‌شود:

  * «Exit code 0» یعنی پروسه **موفق** تمام شد، نه اینکه خطا داد. پس مشکل
    «کرش» نبود؛ چیزی باعث می‌شد ربات خودش را تمام‌شده بداند. تا نسخه‌ی
    قبل، `Manager.run()` بعد از `run_until_disconnected()` مستقیم
    `return 0` می‌داد: هر قطعیِ اتصالِ تلگرام (نمونه‌ی دوم با همان توکن،
    پرشِ شبکه، FloodWait) یعنی مرگِ پروسه و «سرویس خاموش».

  سه چیزی که این تست قفل می‌کند:

    ۱) `Manager.serve_forever()` فقط با درخواستِ خاموشی (SIGTERM/دیپلوی)
       با کد ۰ برمی‌گردد؛ قطعیِ اتصال → تلاشِ دوباره.
    ۲) ناظر (`railway-start.sh`) روی میزبان، خروجِ ۰ را هم کرش می‌شمارد
       (`JAFJ_KEEP_ALIVE`، پیش‌فرض روشن با `JAFJ_HOSTED=1`) و اگر تکرار
       شد با کدِ **غیرصفر** به میزبان برمی‌گرداند تا «Exit code 0» گمراه‌کننده
       تکرار نشود.
    ۳) `hostless-start.sh` + وب‌سرور سلامت: پورتِ `$PORT` روی `0.0.0.0`
       و پوشه‌ی داده‌ی درست.
"""
import asyncio
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ROOT = Path(tempfile.gettempdir()) / "jafj_hostless_run"
FAILS = []


def check(cond, label):
    print(("PASS  " if cond else "FAIL  ") + label)
    if not cond:
        FAILS.append(label)
    return bool(cond)


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def clean_env():
    env = dict(os.environ)
    for k in ("JAFJ_HOSTED", "JAFJ_KEEP_ALIVE", "JAFJ_RECONNECT_TRIES",
              "JAFJ_LOGIN_RETRY", "JAFJ_APP_SLEEPS", "JAFJ_HOST_LABEL",
              "RAILWAY_ENVIRONMENT", "RAILWAY_SERVICE_ID", "RENDER",
              "RENDER_SERVICE_NAME", "BLITZ", "BLITZ_APP_NAME",
              "HOSTLESS", "HOSTLESS_APP_NAME", "FLY_APP_NAME",
              "HEROKU_APP_NAME", "KOYEB_APP_NAME", "DATA_GITHUB_TOKEN",
              "BACKUP_EVERY", "BACKUP_CHAT", "BOT_TOKEN"):
        env.pop(k, None)
    return env


# ── ۱) فایل‌ها و تنظیمات ─────────────────────────────────────────────────────
def check_files():
    print("--- 1: hostless-start.sh و Dockerfile ---")
    p = REPO / "hostless-start.sh"
    if not check(p.exists(), "hostless-start.sh در ریشه‌ی ریپو هست"):
        return
    sh = subprocess.run(["sh", "-n", str(p)], capture_output=True, text=True)
    check(sh.returncode == 0, "سینتکس sh سالم است (%s)" % sh.stderr.strip()[:80])
    t = p.read_text(encoding="utf-8")
    check("JAFJ_HOSTED" in t, "میزبان را hosted اعلام می‌کند (پروسه نباید بمیرد)")
    check('exec sh "$JAFJ_IMAGE_DIR/railway-start.sh"' in t,
          "جریانِ بوت/ناظر از railway-start.sh می‌آید (یک نقطه‌ی حقیقت)")
    check("JAFJ_IMAGE_DIR" in t and "/opt/jafj" in t,
          "کد را از نسخه‌ی غیرقابل‌تغییر ایمیج می‌خواند")
    check("DATA_DIR" in t and "/data" in t,
          "پوشه‌ی داده را انتخاب می‌کند (پیش‌فرض /data)")

    docker = (REPO / "Dockerfile").read_text(encoding="utf-8")
    check("hostless-start.sh" in docker, "Dockerfile آن را داخل ایمیج می‌برد")
    check("EXPOSE 8080" in docker and "PORT=8080" in docker,
          "پورت پیش‌فرض اعلام شده (Hostless خودش PORT می‌دهد)")
    check("JAFJ_HOSTED=1" in docker,
          "JAFJ_HOSTED=1 پیش‌فرض ایمیج است → keep-alive روشن")

    rs = (REPO / "railway-start.sh").read_text(encoding="utf-8")
    check("JAFJ_KEEP_ALIVE" in rs, "ناظر سوییچِ keep-alive دارد")
    check('log "manager exited cleanly"' in rs,
          "مسیرِ «خروجِ تمیز» هنوز برای اجرای دستی هست")


# ── ۲) Manager.serve_forever: قطعیِ اتصال = تلاشِ دوباره، نه exit 0 ─────────
DRIVER = textwrap.dedent(r'''
    import asyncio, os, sys
    sys.path.insert(0, os.environ["JAFJ_CODE_DIR"])
    import manager_82 as M

    # انتظارِ واقعی (۵/۱۰/۱۵s) لازم نیست؛ تست باید سریع باشد.
    M.login_retry_wait = lambda n, base=20, cap=300: 0

    MODE = os.environ["MODE"]
    print("RECONNECT_LIMIT", M.reconnect_limit(), flush=True)
    print("HEALTH_PORT", M._health_port(), flush=True)

    class FakeBot:
        def __init__(self):
            self.calls = 0
            self.connected = True
            self.starts = 0
        async def run_until_disconnected(self):
            self.calls += 1
            self.connected = False
            # قطعیِ واقعی: همان لحظه اتصال می‌افتد (Relay closed / Conflict)
            raise ConnectionError("Server closed the connection")
        def is_connected(self):
            return self.connected
        async def connect(self):
            self.connected = True
        async def is_user_authorized(self):
            return True
        async def start(self, bot_token=None):
            self.starts += 1
            self.connected = True
            return self

    class Fake:
        pass

    Fake.serve_forever = M.Manager.serve_forever

    async def main():
        f = Fake()
        f.bot = FakeBot()
        f.cfg = {"admin_ids": [], "bot_token": "123:abc"}
        f._stopping = False
        async def say(*a, **k):
            return None
        f.say = say

        # «SIGTERMِ دیپلوی» وسطِ تلاشِ دوم می‌رسد
        orig_run = f.bot.run_until_disconnected
        async def run_until_disconnected():
            try:
                return await orig_run()
            finally:
                if MODE == "stop_after_two" and f.bot.calls >= 2:
                    f._stopping = True
        f.bot.run_until_disconnected = run_until_disconnected

        rc = await f.serve_forever()
        print("RC", rc, flush=True)
        print("DISCONNECTS", f.bot.calls, flush=True)

    asyncio.run(main())
''')


def run_driver(mode, extra_env, timeout=120):
    code_dir = ROOT / "code"
    data = ROOT / "data"
    for d in (code_dir, data):
        d.mkdir(parents=True, exist_ok=True)
    for f in ("manager_82.py", "95.py"):
        shutil.copy2(REPO / f, code_dir / f)
    env = clean_env()
    env.update({"JAFJ_CODE_DIR": str(code_dir), "DATA_DIR": str(data),
                "PORT": str(free_port()), "MODE": mode,
                "JAFJ_SELFBOT_REF": str(code_dir / "95.py")})
    env.update(extra_env)
    p = subprocess.run([sys.executable, "-c", DRIVER], cwd=str(data), env=env,
                       capture_output=True, text=True, timeout=timeout)
    return p.stdout + p.stderr


def parse(out):
    got = {}
    for line in out.splitlines():
        parts = line.split(" ", 1)
        if parts[0] in ("RECONNECT_LIMIT", "HEALTH_PORT", "RC", "DISCONNECTS"):
            got[parts[0]] = parts[1].strip() if len(parts) > 1 else ""
    return got


def check_manager():
    print("--- 2: قطعیِ اتصال مدیر را نمی‌کُشد ---")
    shutil.rmtree(ROOT, ignore_errors=True)

    # تلاش‌ها تا سقف ادامه می‌یابد و بعد کدِ غیرصفر (ناظر از صفر بالا می‌آورد)
    out = run_driver("never_stop", {"JAFJ_HOSTED": "1"})
    got = parse(out)
    print("\n".join(l for l in out.splitlines() if l.startswith(("RC", "DISCONNECTS",
                                                                "RECONNECT_LIMIT"))))
    check("قطع شد" in out and "پروسه زنده می‌ماند" in out,
          "قطعیِ اتصال لاگ می‌شود و پروسه زنده می‌ماند (نه exit 0 خاموش)")
    check(got.get("RC") == "1",
          "اتصالِ ترمیم‌نشده با کدِ غیرصفر گزارش می‌شود (میزبان خطا را می‌بیند)")
    check(got.get("RECONNECT_LIMIT") == "3",
          "پیش‌فرضِ تلاش‌ها محدود است تا هندلرها با ری‌استارتِ کامل برگردند")

    # درخواستِ خاموشی (SIGTERM/دیپلوی) = خروجِ تمیز با کد ۰
    shutil.rmtree(ROOT, ignore_errors=True)
    out = run_driver("stop_after_two", {"JAFJ_HOSTED": "1", "JAFJ_RECONNECT_TRIES": "inf"})
    got = parse(out)
    check(got.get("RC") == "0", "با درخواستِ خاموشی، کدِ خروج ۰ است")
    check(got.get("RECONNECT_LIMIT") == "0", "JAFJ_RECONNECT_TRIES=inf یعنی بی‌نهایت")

    # اجرای دستی: بعد از سقفِ تلاش‌ها کدِ غیرصفر (تا مشکل دیده شود)
    shutil.rmtree(ROOT, ignore_errors=True)
    out = run_driver("never_stop", {"JAFJ_RECONNECT_TRIES": "2"})
    got = parse(out)
    print("\n".join(l for l in out.splitlines() if l.startswith(("RC", "DISCONNECTS",
                                                                "RECONNECT_LIMIT"))))
    check(got.get("RC") == "1", "بی‌نتیجه‌بودنِ تلاش‌ها با کد غیرصفر گزارش می‌شود")
    check(got.get("RECONNECT_LIMIT") == "2", "سقفِ تلاش از JAFJ_RECONNECT_TRIES خوانده شد")


def check_health_port():
    print("--- 3: پورتِ سلامت (Hostless: باید روی PORT و 0.0.0.0 باشد) ---")
    shutil.rmtree(ROOT, ignore_errors=True)
    out = run_driver("stop_after_two", {"JAFJ_HOSTED": "1", "PORT": "not-a-port"})
    got = parse(out)
    check(got.get("HEALTH_PORT") == "8080",
          "PORT ناخوانا → 8080 (به‌جای مردنِ وب‌سرور)")
    shutil.rmtree(ROOT, ignore_errors=True)
    out = run_driver("stop_after_two", {"JAFJ_HOSTED": "1",
                                        "PORT": "tcp://0.0.0.0:9123"})
    got = parse(out)
    check(got.get("HEALTH_PORT") == "9123", "شکلِ URL-مانندِ PORT هم خوانده می‌شود")


# ── ۴) ناظر: خروجِ ۰ روی میزبان = کرش ──────────────────────────────────────
def build_image(manager_body):
    img = ROOT / "img"
    img.mkdir(parents=True, exist_ok=True)
    for name in ("railway-start.sh", "hostless-start.sh"):
        shutil.copy2(REPO / name, img / name)
    (img / "95.py").write_text("VERSION='3.0'\n", encoding="utf-8")
    (img / "manager_82.py").write_text(manager_body, encoding="utf-8")
    return img


def run_entrypoint(img, extra_env, script="railway-start.sh", timeout=120):
    data = ROOT / "data"
    data.mkdir(parents=True, exist_ok=True)
    env = clean_env()
    env.update({"JAFJ_IMAGE_DIR": str(img), "JAFJ_APP_DIR": str(data),
                "DATA_DIR": str(data), "PORT": str(free_port()),
                "JAFJ_NAP_BASE": "0"})
    env.update(extra_env)
    p = subprocess.run(["sh", str(img / script)], env=env, cwd=str(data),
                       capture_output=True, text=True, timeout=timeout)
    return p.returncode, p.stdout + p.stderr


def check_supervisor():
    print("--- 4: ناظر روی میزبان، خروجِ ۰ را کرش می‌شمارد ---")
    shutil.rmtree(ROOT, ignore_errors=True)
    img = build_image("import sys\nprint('RUN', flush=True)\nsys.exit(0)\n")

    rc, out = run_entrypoint(img, {"JAFJ_HOSTED": "1", "JAFJ_MAX_CRASHES": "2"})
    print("\n".join(out.strip().splitlines()[-6:]))
    check(rc != 0, "خروجِ ۰ دیگر با کد ۰ به میزبان تحویل داده نمی‌شود (rc=%s)" % rc)
    check("counts as a crash" in out, "لاگ صریح می‌گوید چرا ری‌استارت شد")
    check("giving up" in out, "بعد از تکرار، خطا به میزبان گزارش می‌شود")
    check(out.count("RUN") >= 2, "پروسه دوباره اجرا شد (سرویس خاموش نماند)")

    shutil.rmtree(ROOT / "data", ignore_errors=True)
    img = build_image("import sys\nprint('RUN', flush=True)\nsys.exit(0)\n")
    rc, out = run_entrypoint(img, {"JAFJ_KEEP_ALIVE": "0"})
    check(rc == 0 and "exited cleanly" in out,
          "با JAFJ_KEEP_ALIVE=0 رفتارِ قبلی (اجرای دستی) حفظ می‌شود")


def check_hostless_start():
    print("--- 5: hostless-start.sh در عمل ---")
    shutil.rmtree(ROOT, ignore_errors=True)
    img = build_image("import os, sys\nprint('RUN cwd', os.getcwd(), flush=True)\n"
                      "sys.exit(0)\n")
    data = ROOT / "data"
    data.mkdir(parents=True, exist_ok=True)
    rc, out = run_entrypoint(img, {"JAFJ_KEEP_ALIVE": "0", "DATA_DIR": str(data)},
                             script="hostless-start.sh")
    print("\n".join(out.strip().splitlines()[:4]))
    check(rc == 0, "hostless-start.sh با موفقیت کد را اجرا می‌کند")
    check("HOSTLESS: code=" in out, "خلاصه‌ی بوت (کد/داده/پورت) لاگ می‌شود")
    check(str(data) in out, "پوشه‌ی داده همان DATA_DIR است")


def main():
    shutil.rmtree(ROOT, ignore_errors=True)
    ROOT.mkdir(parents=True, exist_ok=True)
    check_files()
    check_manager()
    check_health_port()
    check_supervisor()
    check_hostless_start()
    print("ALL:", "PASS" if not FAILS else "FAIL")
    if FAILS:
        for f in FAILS:
            print("  -", f)
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
