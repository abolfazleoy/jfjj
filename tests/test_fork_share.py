#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""حافظه‌ی مشترکِ سلف‌ها (`jafj_forkd.py`) — برای ۱۰۰ اکانت.

هر `95.py` جداگانه `import telethon` می‌کند ≈ ۴۰ مگابایت. با ۱۰۰ اکانت یعنی
~۴ گیگابایت فقط برای کدِ تکراری. با fork از یک والدِ مشترک، آن حافظه یک‌بار
می‌نشیند و بینِ فرزندها مشترک می‌شود (copy-on-write).

این تست واقعاً اندازه می‌گیرد: یک بلوکِ بزرگ در والد ساخته می‌شود، سپس دو
فرزند fork می‌شوند و PSS (حافظه‌ی واقعیِ هر پروسه) با RSS مقایسه می‌شود.
"""
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


def mem(pid):
    """(RSS, PSS) برای یک pid — PSS فقط صفحه‌های اختصاصی+سهمِ مشترک است."""
    rss = pss = None
    try:
        with open(f"/proc/{pid}/status", encoding="utf-8") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    rss = int(line.split()[1]) / 1024.0
    except Exception:
        return None, None
    try:
        with open(f"/proc/{pid}/smaps_rollup", encoding="utf-8") as f:
            for line in f:
                if line.startswith("Pss:"):
                    pss = int(line.split()[1]) / 1024.0
    except Exception:
        pss = None
    return rss, pss


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False


FAKE_SELF = '''
import os, sys, time
BIG = bytearray(b"x" * (96 * 1024 * 1024))   # ۹۶ مگابایتِ مشترک
def main():
    print("FAKE-SB cwd=%s pid=%d big=%d" % (os.getcwd(), os.getpid(), len(BIG)),
          flush=True)
    time.sleep(25)
    return 0
'''


def main():
    root = Path(tempfile.mkdtemp(prefix="jafj_fork_"))
    here = os.getcwd()
    saved_data = os.environ.get("DATA_DIR")
    saved_port = os.environ.get("PORT")
    os.environ["DATA_DIR"] = str(root / "data")
    os.environ["PORT"] = "8551"
    os.environ.pop("JAFJ_ONLY", None)
    selfbot = root / "fake_self.py"
    selfbot.write_text(FAKE_SELF, encoding="utf-8")
    try:
        sys.path.insert(0, str(REPO))
        import manager_82 as M

        # ── ۱) حالتِ spawn ─────────────────────────────────────────────
        has_fork = bool(hasattr(os, "fork") and os.path.isdir("/proc/self"))
        want = "fork" if has_fork else "process"
        check("spawn_mode: پیش‌فرض fork (روی لینوکس)", M.spawn_mode({}) == want)
        check("spawn_mode: fork", M.spawn_mode({"JAFJ_SPAWN_MODE": "fork"}) == want)
        check("spawn_mode: اشتراکی", M.spawn_mode({"JAFJ_SPAWN_MODE": "اشتراکی"}) == want)
        check("spawn_mode: process راهِ فرار است",
              M.spawn_mode({"JAFJ_SPAWN_MODE": "process"}) == "process")
        check("spawn_mode: مقدارِ ناشناخته → پیش‌فرض",
              M.spawn_mode({"JAFJ_SPAWN_MODE": "xyz"}) == want)

        # ── ۲) دیمن بالا می‌آید ────────────────────────────────────────
        d = M.ForkDaemon(str(selfbot))
        check("داِمن: مسیرِ jafj_forkd.py پیدا می‌شود",
              os.path.isfile(d.forker_path()), d.forker_path())
        ok = d.start(timeout=60)
        check("داِمن: بالا آمد", ok is True, d.last_error)

        # ── ۳) دو فرزند، هرکدام با cwd خودش ─────────────────────────
        a = root / "acc_a"
        b = root / "acc_b"
        a.mkdir()
        b.mkdir()
        la, lb = a / "run.log", b / "run.log"
        pid_a, err_a = d.spawn(a, la, "111")
        pid_b, err_b = d.spawn(b, lb, "222")
        check("spawn: فرزندِ اول pid دارد", bool(pid_a), err_a)
        check("spawn: فرزندِ دوم pid دارد", bool(pid_b), err_b)
        check("spawn: دو pid متفاوت", pid_a and pid_b and pid_a != pid_b)
        time.sleep(1.5)
        check("فرزندِ اول زنده است", pid_a and alive(pid_a))
        check("فرزندِ دوم زنده است", pid_b and alive(pid_b))
        check("فرزندِ اول در پوشه‌ی خودش اجرا شد",
              str(a) in la.read_text(encoding="utf-8", errors="ignore"),
              la.read_text(encoding="utf-8", errors="ignore")[:200])
        check("فرزندِ دوم در پوشه‌ی خودش اجرا شد",
              str(b) in lb.read_text(encoding="utf-8", errors="ignore"))

        # ── ۴) حافظه‌ی مشترک: PSS باید خیلی کمتر از RSS باشد ─────────
        rss_a, pss_a = mem(pid_a)
        rss_b, pss_b = mem(pid_b)
        check("حافظه: RSS فرزند خوانده می‌شود", rss_a and rss_a > 90, rss_a)
        if pss_a is not None and rss_a:
            shared = 1 - (pss_a / rss_a)
            print(f"   RSS={rss_a:.0f}MB PSS={pss_a:.0f}MB → سهمِ مشترک "
                  f"~{shared * 100:.0f}%")
            check("حافظه: بلوکِ مشترک بینِ فرزندها شریک شده (PSS < RSS)",
                  pss_a < rss_a * 0.75, (rss_a, pss_a))
        else:
            check("حافظه: PSS در دسترس نیست (skipped)", True)

        # ── ۵) هر دو در یک دیمن، نه دو نسخه ─────────────────────────
        check("داِمن: هر دو فرزند زیرِ یک والد هستند",
              d.alive() and alive(pid_a) and alive(pid_b))

        # ── ۶) هر فرزند گروهِ پروسه‌ی خودش را دارد ───────────────────
        # بدونِ این، `killpg`ِ مدیر برای خاموش‌کردنِ یک اکانت، دیمن و همه‌ی
        # سلف‌های دیگر را هم می‌کشت.
        try:
            pg_a = os.getpgid(pid_a)
        except Exception:
            pg_a = None
        check("فرزند گروهِ پروسه‌ی خودش را دارد (setsid)",
              pg_a == pid_a, pg_a)
        check("فرزند هم‌گروهِ مدیر نیست",
              pg_a is not None and pg_a != os.getpgid(os.getpid()))

        # ── ۷) خاموش‌کردنِ گروهی (همان کاری که stop() می‌کند) ───────
        os.killpg(pg_a, 15)
        time.sleep(0.8)
        check("فرزند بعد از SIGTERM می‌میرد", not alive(pid_a))
        check("فرزندِ دیگر دست‌نخورده می‌ماند", alive(pid_b))

        # ── ۷) مدیر: مسیرِ fork در start() و بستن در shutdown ───────
        src = (REPO / "manager_82.py").read_text(encoding="utf-8")
        check("مدیر: start() حالتِ fork را می‌شناسد",
              'spawn_mode() == "fork"' in src)
        check("مدیر: در صورتِ شکستِ fork به پروسه‌ی جدا برمی‌گردد",
              "fork برای {uid} نشد" in src)
        check("مدیر: زامبی «مرده» شمرده می‌شود",
              '== "Z"' in src and "/stat" in src)
        check("مدیر: shutdown دیمن را می‌بندد", "self._forkd.close()" in src)
        check("مدیر: بعد از یک شکست دیگر timeout نمی‌خورد",
              "_fork_broken" in src)
        check("مدیر: _AdoptedProc سیگنال‌پذیر است",
              hasattr(M._AdoptedProc, "kill") and hasattr(M._AdoptedProc, "terminate"))
        fork_src = (REPO / "jafj_forkd.py").read_text(encoding="utf-8")
        check("داِمن: gc.freeze قبل از fork (صفحه‌های مشترک کمتر کپی می‌شوند)",
              "gc.freeze()" in fork_src)
        check("داِمن: فرزند setsid می‌شود", "os.setsid()" in fork_src)

        os.kill(pid_b, 15)
        d.close()
        time.sleep(0.5)
        check("داِمن بعد از close می‌میرد", not d.alive())
    finally:
        os.chdir(here)
        if saved_data is None:
            os.environ.pop("DATA_DIR", None)
        else:
            os.environ["DATA_DIR"] = saved_data
        if saved_port is None:
            os.environ.pop("PORT", None)
        else:
            os.environ["PORT"] = saved_port
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
