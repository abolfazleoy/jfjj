#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""jafj_forkd — «همه‌ی سلف‌ها یک نسخه‌ی تلگرام در رم داشته باشند».

مشکل: هر `95.py` یک پروسه‌ی جدا است و فقط `import telethon` حدودِ ۴۰ مگابایت
رم می‌گیرد (اندازه‌گیری‌شده). با ۱۰۰ اکانت یعنی چند گیگابایت فقط برای کدِ
تلگرام که ۱۰۰ بار تکرار شده.

راه‌حل: این دیمن یک‌بار کتابخانه‌ها را لود می‌کند و بعد برای هر اکانت `fork`
می‌زند. صفحه‌های حافظه‌ی تلگرام بینِ همه‌ی فرزندها **مشترک** می‌شوند
(copy-on-write)، پس در حافظه‌ی واقعی (PSS/cgroup) یک‌بار حساب می‌شوند.

اندازه‌گیریِ واقعی با همان `95.py` (۳ اکانت): پروسه‌ی جدا ۶۲MB برای هر اکانت،
fork ~۲۰MB — جزئیات در `WISPBYTE_FA.md` §۱۲.

پروتکل: خط‌به‌خط JSON روی stdin/stdout.

    {"cmd":"run","cwd":"/…/clients/123","log":"/…/run.log","uid":"123"}
      → {"ok":true,"pid":4567,"uid":"123"}
    {"cmd":"ping"}          → {"ok":true,"alive":[…]}
    {"cmd":"quit"}          → خروج
    رویداد: {"event":"exit","pid":4567,"uid":"123","code":0}

نکته‌های ایمنی:

* دیمن عمداً **تک‌رشته‌ای** است و تنها کاری که می‌کند fork است؛ fork از یک
  پروسه‌ی چندرشته‌ای (مدیر) می‌تواند قفل‌ها را در حالتِ نامعلوم به ارث بدهد.
* دیمن **هرگز** فایلِ سلف را import نمی‌کند: import یعنی اجرای بدنه‌ی ماژول
  در دیمن؛ اگر آن بدنه بلوکه شود (مثلِ اسکریپتی که همان اول صبر می‌کند)
  دیگر هیچ اکانتی بالا نمی‌آمد. فرزند خودش فایل را مثلِ `python 95.py`
  اجرا می‌کند.
"""
import argparse
import json
import os
import sys


def _reply(obj):
    try:
        sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
        sys.stdout.flush()
    except Exception:
        pass


def _child_exec(selfbot_path, cwd, log_path, code_obj=None):
    """بدنه‌ی فرزند — هرگز برنگردد؛ با os._exit تمام شود.

    دقیقاً همان کاری که `python 95.py` می‌کند: فایل به‌عنوان `__main__` اجرا
    می‌شود، پس `if __name__ == "__main__": sys.exit(main())` پایینِ فایل
    کارِ خودش را می‌کند و رفتارِ سلف با حالتِ پروسه‌ی جدا یکی است.
    """
    out = None
    # گروهِ پروسه‌ی مستقل: بدونِ این، `killpg`ِ مدیر برای خاموش‌کردنِ یک
    # اکانت، دیمن و همه‌ی سلف‌های دیگر را هم می‌کشت.
    try:
        os.setsid()
    except Exception:
        pass
    try:
        os.chdir(cwd)
    except Exception:
        pass
    try:
        devnull = os.open(os.devnull, os.O_RDONLY)
        os.dup2(devnull, 0)
        if devnull > 2:
            os.close(devnull)
    except Exception:
        pass
    if log_path:
        try:
            out = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
            os.dup2(out, 1)
            os.dup2(out, 2)
        except Exception:
            out = None
    try:
        sys.argv = [selfbot_path]
        d = os.path.dirname(os.path.abspath(selfbot_path))
        if d and d not in sys.path:
            sys.path.insert(0, d)
    except Exception:
        pass
    code = 1
    try:
        obj = code_obj
        if obj is None:
            with open(selfbot_path, encoding="utf-8", errors="replace") as f:
                src = f.read()
            obj = compile(src, selfbot_path, "exec")
        ns = {"__name__": "__main__", "__file__": selfbot_path,
              "__doc__": None, "__package__": None, "__spec__": None,
              "__builtins__": __builtins__}
        exec(obj, ns)               # کدِ کامپایل‌شده در دیمن → صفحه‌های مشترک
        code = 0
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    except KeyboardInterrupt:
        code = 0
    except BaseException:
        try:
            import traceback
            traceback.print_exc()
        except Exception:
            pass
        code = 1
    try:
        if out and out > 2:
            os.close(out)
    except Exception:
        pass
    os._exit(int(code or 0))


def main():
    ap = argparse.ArgumentParser(description="JAFJ forker daemon")
    ap.add_argument("--selfbot", required=True, help="مسیرِ 95.py")
    ap.add_argument("--preload-telethon", default="1",
                    help="۱ = تلگرام را قبل از fork لود کن (پیش‌فرض)")
    ap.add_argument("--preload-extra", default="",
                    help="ماژول‌های اضافی با کاما (مثلاً sqlite3,asyncio)")
    args = ap.parse_args()
    selfbot_path = os.path.abspath(args.selfbot)
    if not os.path.isfile(selfbot_path):
        _reply({"event": "ready", "pid": os.getpid(), "warning": "selfbot-missing"})
        return 2

    # فقط کتابخانه‌ها؛ خودِ فایلِ سلف عمداً لود نمی‌شود (بالا توضیح داده شد).
    if str(args.preload_telethon).strip() not in ("0", "false", "no", "نه"):
        try:
            import telethon            # noqa: F401  (عمداً برای اشتراکِ حافظه)
        except Exception:
            pass
    # کدِ 95.py را همین‌جا کامپایل می‌کنیم (اجرا نه): هم فرزندها دیگر
    # کامپایل نمی‌کنند، هم کد‌آبجکت‌ها بینِ آن‌ها مشترک می‌مانند.
    code_obj = None
    try:
        with open(selfbot_path, encoding="utf-8", errors="replace") as f:
            _src = f.read()
        code_obj = compile(_src, selfbot_path, "exec")
    except Exception:
        code_obj = None

    # وابستگی‌های 95.py را هم این‌جا لود کن تا در فرزندها **مشترک** باشند،
    # ولی خودِ بدنه‌ی فایل اجرا نمی‌شود (تنها import‌های سطحِ بالا).
    try:
        import ast
        _local = {os.path.splitext(x)[0]
                  for x in os.listdir(os.path.dirname(selfbot_path) or ".")
                  if x.endswith(".py")}
        _names = set()
        for _n in ast.walk(ast.parse(_src)):
            if isinstance(_n, ast.Import):
                for _a in _n.names:
                    _names.add(_a.name.split(".")[0])
            elif isinstance(_n, ast.ImportFrom) and _n.level == 0 and _n.module:
                _names.add(_n.module.split(".")[0])
        for _m in sorted(_names):
            if _m in _local or _m in ("__future__",):
                continue
            try:
                __import__(_m)
            except Exception:
                pass
    except Exception:
        pass

    _extra = (args.preload_extra
              or os.environ.get("JAFJ_PRELOAD_EXTRA") or "")
    for name in [x.strip() for x in _extra.split(",") if x.strip()]:
        try:
            __import__(name)
        except Exception:
            pass

    # اشیای لود‌شده را از چرخه‌ی GC بیرون بگذار: هم جست‌وجوی GC ارزان‌تر
    # می‌شود، هم فرزندها کمتر دست به صفحه‌های copy-on-write می‌زنند — یعنی
    # حافظه‌ی مشترک واقعاً مشترک می‌ماند.
    try:
        import gc
        gc.collect()
        if hasattr(gc, "freeze"):
            gc.freeze()
    except Exception:
        pass

    children = {}

    def reap():
        while True:
            try:
                pid, status = os.waitpid(-1, os.WNOHANG)
            except ChildProcessError:
                return
            except Exception:
                return
            if pid == 0:
                return
            code = None
            try:
                code = (os.waitstatus_to_exitcode(status)
                        if hasattr(os, "waitstatus_to_exitcode") else None)
            except Exception:
                code = None
            uid = children.pop(pid, None)
            _reply({"event": "exit", "pid": pid, "uid": uid, "code": code})

    def _on_sigchld(_signum, _frame):
        # بدونِ این، فرزندِ مرده «زامبی» می‌ماند و `kill(pid,0)` موفقی
        # برمی‌گرداند؛ یعنی مدیر فکر می‌کند سلف زنده است و دوباره اجرا نمی‌کند.
        reap()

    try:
        import signal as _signal
        _signal.signal(_signal.SIGCHLD, _on_sigchld)
    except Exception:
        pass

    _reply({"event": "ready", "pid": os.getpid()})

    try:
        for line in sys.stdin:
            line = (line or "").strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except Exception:
                _reply({"ok": False, "error": "bad-json"})
                continue
            cmd = (msg.get("cmd") or "").strip().lower()
            if cmd == "run":
                cwd = msg.get("cwd") or "."
                log_path = msg.get("log") or ""
                uid = str(msg.get("uid") or "")
                try:
                    pid = os.fork()
                except Exception as e:
                    _reply({"ok": False, "error": f"fork: {type(e).__name__}: {e}"})
                    continue
                if pid == 0:                      # ── فرزند ──
                    _child_exec(selfbot_path, cwd, log_path, code_obj)
                    os._exit(1)                   # هرگز نمی‌رسیم
                children[pid] = uid
                _reply({"ok": True, "pid": pid, "uid": uid})
            elif cmd == "ping":
                reap()
                _reply({"ok": True, "alive": sorted(children)})
            elif cmd == "quit":
                break
            else:
                _reply({"ok": False, "error": "unknown-cmd"})
    except KeyboardInterrupt:
        pass
    finally:
        for pid in list(children):
            try:
                os.kill(pid, 15)
            except Exception:
                pass
        try:
            sys.stdout.close()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
