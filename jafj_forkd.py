#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""jafj_forkd — «همه‌ی سلف‌ها یک نسخه‌ی تلگرام در رم داشته باشند».

مشکل: هر `95.py` یک پروسه‌ی جدا است و فقط `import telethon` حدودِ ۴۰ مگابایت
رم می‌گیرد (اندازه‌گیری‌شده). با ۱۰۰ اکانت یعنی ~۴ گیگابایت فقط برای کدِ
تلگرام که ۱۰۰ بار تکرار شده.

راه‌حل: این دیمن یک‌بار `95.py` و `telethon` را لود می‌کند و بعد برای هر اکانت
`fork` می‌زند. صفحه‌های حافظه‌ی تلگرام بینِ همه‌ی فرزندها **مشترک** می‌شوند
(copy-on-write)، پس در حافظه‌ی واقعی (PSS/cgroup) یک‌بار حساب می‌شوند.

پروتکل: خط‌به‌خط JSON روی stdin/stdout.

    {"cmd":"run","cwd":"/…/clients/123","log":"/…/run.log","uid":"123"}
      → {"ok":true,"pid":4567,"uid":"123"}
    {"cmd":"ping"}          → {"ok":true,"alive":[…]}
    {"cmd":"quit"}          → خروج
    رویداد: {"event":"exit","pid":4567,"code":0}

نکته‌ی ایمنی: این دیمن عمداً **تک‌رشته‌ای** است و تنها کاری که می‌کند fork
است؛ fork از یک پروسه‌ی چندرشته‌ای (مدیر) می‌تواند قفل‌ها را در حالتِ نامعلوم
به ارث بدهد.
"""
import argparse
import importlib.util
import json
import os
import sys


def _load_selfbot(path):
    spec = importlib.util.spec_from_file_location("jafj_selfbot", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _reply(obj):
    try:
        sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
        sys.stdout.flush()
    except Exception:
        pass


def _child_main(mod, cwd, log_path):
    """بدنه‌ی فرزند — هرگز برنگردد؛ با os._exit تمام شود."""
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
    code = 1
    try:
        code = mod.main()
        if hasattr(code, "__await__"):        # اگر روزی main() async شد
            import asyncio
            code = asyncio.run(code)
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

    mod = _load_selfbot(os.path.abspath(args.selfbot))
    has_main = callable(getattr(mod, "main", None))
    if str(args.preload_telethon).strip() not in ("0", "false", "no", "نه"):
        try:
            import telethon            # noqa: F401  (عمداً برای اشتراکِ حافظه)
        except Exception:
            pass
    for name in [x.strip() for x in (args.preload_extra or "").split(",") if x.strip()]:
        try:
            __import__(name)
        except Exception:
            pass

    # اشیای لود‌شده (کدِ تلگرام و 95.py) را از چرخه‌ی GC بیرون بگذار: هم
    # جست‌وجوی GC ارزان‌تر می‌شود، هم فرزندها کمتر دست به صفحه‌های
    # copy-on-write می‌زنند — یعنی همان حافظه‌ی مشترک واقعاً مشترک می‌ماند.
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
                if not has_main:
                    # سلفی که main() ندارد را با fork نمی‌شود اجرا کرد؛ مدیر
                    # خودش به پروسه‌ی جدا برمی‌گردد (به‌جای خطای بی‌معنی).
                    _reply({"ok": False, "error": "selfbot main() ندارد"})
                    continue
                try:
                    pid = os.fork()
                except Exception as e:
                    _reply({"ok": False, "error": f"fork: {type(e).__name__}: {e}"})
                    continue
                if pid == 0:                      # ── فرزند ──
                    _child_main(mod, cwd, log_path)
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
