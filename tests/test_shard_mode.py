#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""حالتِ shard — چند اکانت در یک پروسه (`jafj_shardd.py`).

چرا: در fork هر اکانت یک پروسه‌ی جداست و صفحه‌هایی که دست می‌زند خصوصی
می‌شوند (~۱۱.۲MB برای هر اکانت). در shard همه‌ی اکانت‌ها در یک پروسه‌اند،
هر کدام در namespace و رشته‌ی خودش با مسیرهای مطلق → ~۳.۳MB برای هر اکانت.

این تست چیزهایی را می‌سنجد که اگر بشکنند فاجعه است: لاگِ هر اکانت جدا،
مسیرهای هر اکانت جدا (سشن/دیتابیس)، بستنِ یک اکانت بقیه را نمی‌کشد، و
محدودیتِ تعداد.
"""
import json
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
    print(("PASS " if cond else "FAIL ") + name
          + (f"   [{extra}]" if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


FAKE_SELF = '''
import os, sys, time

DB_FILE = "jafj.db"
LOG_FILE = "jafj.log"
SESSION = "jafj"
RUN_LOCK = "jafj.run.lock"

def main():
    open(DB_FILE, "a").write("x")
    open(RUN_LOCK, "a").write(str(os.getpid()))
    print("ACC-START %s" % os.path.abspath(DB_FILE))
    for _ in range(120):
        time.sleep(0.25)
    return 0
'''


def rpc(p, obj, timeout=30):
    p.stdin.write((json.dumps(obj) + "\n").encode())
    p.stdin.flush()
    end = time.time() + timeout
    while time.time() < end:
        line = p.stdout.readline()
        if not line:
            return None
        msg = json.loads(line.decode())
        if "event" in msg and "ok" not in msg:
            continue
        return msg
    return None


def main():
    root = Path(tempfile.mkdtemp(prefix="jafj_shard_"))
    selfbot = root / "fake_self.py"
    selfbot.write_text(FAKE_SELF, encoding="utf-8")
    try:
        sys.path.insert(0, str(REPO))
        import manager_82 as M
        import jafj_shardd as S

        # ── ۱) مسیرها مطلق می‌شوند (وگرنه سشنِ همه یکی می‌شود) ──────
        out = S._rewrite(FAKE_SELF, "/tmp/accX")
        check("rewrite: DB_FILE مطلق شد", 'DB_FILE = "/tmp/accX/jafj.db"' in out, out)
        check("rewrite: SESSION مطلق شد", 'SESSION = "/tmp/accX/jafj"' in out)
        check("rewrite: RUN_LOCK مطلق شد",
              'RUN_LOCK = "/tmp/accX/jafj.run.lock"' in out)

        # ── ۲) اندازه‌ی شارد ─────────────────────────────────────────
        check("shard_size: پیش‌فرض ۸", M.shard_size({}) == 8, M.shard_size({}))
        check("shard_size: مقدارِ صریح", M.shard_size({"JAFJ_SHARD_SIZE": "3"}) == 3)
        check("shard_size: بی‌معنی → پیش‌فرض", M.shard_size({"JAFJ_SHARD_SIZE": "x"}) == 8)
        check("shard_size: سقفِ ۶۴", M.shard_size({"JAFJ_SHARD_SIZE": "999"}) == 64)
        check("shard_size: کفِ ۱", M.shard_size({"JAFJ_SHARD_SIZE": "0"}) == 1)

        # ── ۳) حالتِ spawn ──────────────────────────────────────────
        want = "shard" if M.fork_supported() else "process"
        check("spawn_mode: shard", M.spawn_mode({"JAFJ_SPAWN_MODE": "shard"}) == want)
        check("spawn_mode: شارد", M.spawn_mode({"JAFJ_SPAWN_MODE": "شارد"}) == want)

        # ── ۴) دیمنِ shard: دو اکانت در یک پروسه ────────────────────
        p = subprocess.Popen(
            [sys.executable, str(REPO / "jafj_shardd.py"),
             "--selfbot", str(selfbot), "--max-accounts", "2"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, bufsize=0)
        ready = rpc(p, {"cmd": "ping"}, timeout=60) or {}
        check("شارد: بالا آمد", bool(ready.get("ok")), ready)

        a, b = root / "acc_a", root / "acc_b"
        a.mkdir()
        b.mkdir()
        r1 = rpc(p, {"cmd": "run", "cwd": str(a), "log": str(a / "run.log"),
                     "uid": "111"}) or {}
        r2 = rpc(p, {"cmd": "run", "cwd": str(b), "log": str(b / "run.log"),
                     "uid": "222"}) or {}
        check("شارد: اکانتِ اول اجرا شد", r1.get("ok"), r1)
        check("شارد: اکانتِ دوم اجرا شد", r2.get("ok"), r2)
        check("شارد: هر دو در یک پروسه‌اند", r1.get("pid") == r2.get("pid") == p.pid,
              (r1.get("pid"), r2.get("pid"), p.pid))
        time.sleep(2.0)

        la = (a / "run.log").read_text(encoding="utf-8", errors="ignore")
        lb = (b / "run.log").read_text(encoding="utf-8", errors="ignore")
        check("لاگِ اکانتِ اول به فایلِ خودش رفت", "ACC-START" in la and str(a) in la, la[:200])
        check("لاگِ اکانتِ دوم به فایلِ خودش رفت", "ACC-START" in lb and str(b) in lb, lb[:200])
        check("لاگ‌ها قاطی نشدند", str(b) not in la and str(a) not in lb)
        check("دیتابیس/سشنِ هر اکانت در پوشه‌ی خودش",
              (a / "jafj.db").exists() and (b / "jafj.db").exists()
              and (a / "jafj.run.lock").exists() and (b / "jafj.run.lock").exists())

        ping = rpc(p, {"cmd": "ping"}) or {}
        check("ping: هر دو اکانت زنده‌اند",
              sorted(str(x) for x in ping.get("accounts") or []) == ["111", "222"], ping)

        # ── ۵) محدودیتِ تعداد ──────────────────────────────────────
        r3 = rpc(p, {"cmd": "run", "cwd": str(root), "log": str(root / "x.log"),
                     "uid": "333"}) or {}
        check("شاردِ پر، اکانتِ سوم را قبول نمی‌کند",
              r3.get("ok") is False and "full" in str(r3.get("error")), r3)

        # ── ۶) بستنِ یک اکانت، بقیه را نمی‌کشد ──────────────────────
        st = rpc(p, {"cmd": "stop", "uid": "111"}) or {}
        check("stop: اکانتِ اول بسته شد", st.get("ok") is True, st)
        time.sleep(1.5)
        ping2 = rpc(p, {"cmd": "ping"}) or {}
        accs = [str(x) for x in ping2.get("accounts") or []]
        check("stop: اکانتِ دوم زنده ماند", "222" in accs, accs)
        check("stop: اکانتِ اول رفت", "111" not in accs, accs)
        check("stop: خودِ پروسه زنده است", p.poll() is None)

        # ── ۷) wiring در مدیر ──────────────────────────────────────
        src = (REPO / "manager_82.py").read_text(encoding="utf-8")
        check("مدیر: کلاسِ ShardDaemon", "class ShardDaemon" in src)
        check("مدیر: دستگیره‌ی _ShardProc", "class _ShardProc" in src)
        check("مدیر: انتخابِ شاردِ خالی", "def pick_shard" in src)
        check("مدیر: بستنِ اکانت از داخلِ شارد", "remote_stop" in src)
        check("مدیر: شاردها در shutdown بسته می‌شوند", "self._shards" in src)
        check("مدیر: PSSِ شارد بینِ اکانت‌ها تقسیم می‌شود",
              "len(getattr(_d, \"uids\"" in src)

        rpc(p, {"cmd": "quit"}, timeout=10)
        time.sleep(1)
        try:
            p.kill()
        except Exception:
            pass
    finally:
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
