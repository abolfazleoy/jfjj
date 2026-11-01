#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""شنونده‌ی PORT در ثانیه‌ی اولِ بوت (فایلِ `main.py`).

چرا این تست وجود دارد: کاربر گفت «مشکل از همین `main.py`ی است که در سایت
می‌گذارم» و فایلِ قدیمی را پیست کرد. ایرادِ واقعیِ آن فایل همین بود:

    پنل (Wispbyte) فقط نگاه می‌کند «روی PORT کسی گوش می‌دهد؟». فایلِ قدیمی
    تا وقتی `git clone` + ساختِ venv + `pip install` تمام نشود هیچ شنونده‌ای
    نداشت (چند دقیقه). پنل اپ را «مرده» می‌دید و ری‌استارت می‌کرد → کانتینرِ
    تازه با IPِ تازه، در حالی که کانتینرِ قبلی هنوز زنده بود → همان
    `AuthKeyDuplicatedError: ... two different IP addresses ...` که کلیدِ
    سشن را برای همیشه سوزاند.

این تست سه چیز را قفل می‌کند: (۱) شنونده واقعاً ۲۰۰ می‌دهد، (۲) پیش از
اجرای مدیر بسته می‌شود تا مدیر خودش پورت را بگیرد، (۳) اگر پورت مشغول بود
هیچ‌چیز نمی‌شکند.
"""
import importlib.util
import os
import socket
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
FAILS = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name
          + (f"   [{extra}]" if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def load_main():
    spec = importlib.util.spec_from_file_location("jafjboot_t", str(REPO / "main.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def get(url, timeout=3):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.status, r.read().decode("utf-8", "ignore")


def main():
    here = os.getcwd()
    saved_port = os.environ.get("PORT")
    saved_only = os.environ.get("JAFJ_ONLY")
    M = None
    try:
        os.environ.pop("JAFJ_ONLY", None)
        M = load_main()
        os.chdir(here)                       # ماژول خودش chdir می‌کند؛ برگردان

        check("main.py: BOOT_VERSION دارد", bool(getattr(M, "BOOT_VERSION", "")),
              getattr(M, "BOOT_VERSION", ""))
        src = (REPO / "main.py").read_text(encoding="utf-8")
        check("main.py: نسخه در لاگِ بوت چاپ می‌شود",
              "boot={BOOT_VERSION}" in src)
        i_boot = src.find("boot_listener()          #")
        i_sync = src.find("    sync_code()", src.find("def main():"))
        check("main.py: شنونده پیش از sync_code بالا می‌آید",
              i_boot > 0 and i_sync > i_boot, (i_boot, i_sync))
        check("main.py: هر سه مسیر اجرا شنونده را می‌بندند",
              src.count("boot_listener_stop()") >= 4,
              src.count("boot_listener_stop()"))

        # ── ۱) شنونده واقعاً جواب می‌دهد ──
        port = free_port()
        os.environ["PORT"] = str(port)
        srv = M.boot_listener()
        check("boot_listener: سرور ساخته شد", srv is not None)
        st, body = get(f"http://127.0.0.1:{port}/")
        check("boot_listener: GET / → 200", st == 200, st)
        check("boot_listener: بدنه JSON با «boot: true»",
              '"boot": true' in body, body[:120])
        check("boot_listener: نسخه در بدنه هست",
              M.BOOT_VERSION.split(" ")[0] in body, body[:160])
        st2, body2 = get(f"http://127.0.0.1:{port}/healthz")
        check("boot_listener: هر مسیری ۲۰۰ می‌دهد (/healthz)", st2 == 200, st2)
        check("boot_listener: دوباره صدا زدن سرورِ دوم نمی‌سازد",
              M.boot_listener() is srv)

        # ── ۲) بستن، پورت را آزاد می‌کند ──
        M.boot_listener_stop()
        freed = False
        for _ in range(30):
            try:
                get(f"http://127.0.0.1:{port}/", timeout=0.5)
            except Exception:
                freed = True
                break
        check("boot_listener_stop: پورت آزاد می‌شود (مدیر می‌تواند بگیرد)",
              freed)
        check("boot_listener_stop: دوباره صدا زدن بی‌خطر است",
              M.boot_listener_stop() is None)

        # بعد از بستن، پورت باید دوباره قابلِ bind باشد (همان چیزی که مدیر می‌کند)
        again = socket.socket()
        again.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            again.bind(("0.0.0.0", port))
            ok_bind = True
        except OSError:
            ok_bind = False
        finally:
            again.close()
        check("بعد از بستن، پورت برای مدیر آزاد است", ok_bind)

        # ── ۳) پورتِ مشغول نباید اجرا را بشکند ──
        busy = socket.socket()
        busy.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        busy.bind(("0.0.0.0", free_port()))
        busy.listen(5)
        bport = busy.getsockname()[1]
        os.environ["PORT"] = str(bport)
        r = M.boot_listener()
        check("boot_listener: پورتِ مشغول → None (بدونِ استثنا)", r is None)
        busy.close()

        # ── ۴) بدونِ PORT اصلاً کاری نمی‌کند ──
        os.environ.pop("PORT", None)
        check("boot_listener: بدونِ PORT → None", M.boot_listener() is None)

        # ── ۵) اگر بعداً مدیر پورت را بگیرد، شنونده چیزی را نمی‌شکند ──
        port2 = free_port()
        os.environ["PORT"] = str(port2)
        s1 = M.boot_listener()
        check("boot_listener: روی پورتِ آزاد ساخته می‌شود", s1 is not None)
        M.boot_listener_stop()
        check("boot_listener: بستنِ دوباره هم امن است",
              M.boot_listener_stop() is None and M.boot_listener_stop() is None)
    finally:
        try:
            if M is not None:
                M.boot_listener_stop()
        except Exception:
            pass
        os.chdir(here)
        if saved_port is None:
            os.environ.pop("PORT", None)
        else:
            os.environ["PORT"] = saved_port
        if saved_only is not None:
            os.environ["JAFJ_ONLY"] = saved_only

    print()
    if FAILS:
        print("FAILED:", ", ".join(FAILS))
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
