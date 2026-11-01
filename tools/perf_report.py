#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""گزارشِ کاراییِ مسیرِ تبادل — آیا کارهای حافظه چیزی را کند کرده؟

سه چیز اندازه‌گیری می‌شود، همه با **کدِ واقعیِ** `95.py` (کلاسِ `DB` و همان
کوئری‌ها)، نه شبیه‌سازی:

1. زمانِ کوئری‌های داغِ تبادل/صف روی یک دیتابیسِ واقعی (۲۰٬۰۰۰ + ۲۰٬۰۰۰ رکورد)،
   با `cache_size` های مختلف — تا اثرِ کم‌کردنِ کشِ sqlite دیده شود.
2. مقیاس‌پذیریِ رشته‌ها: همان کارِ هر پیام (پارسِ متن + JSON + دو کوئری)
   یک بار در ۱ رشته و یک بار در N رشته‌ی هم‌زمان — تا اثرِ GIL در حالتِ
   shard (چند اکانت در یک پروسه) معلوم شود.
3. تأخیرِ هر پیام (median/p95).

اجرا:

    python3 tools/perf_report.py                 # پیش‌فرض: ۲۰ هزار رکورد، ۸ رشته
    python3 tools/perf_report.py --rows 50000 --workers 16
"""
import argparse
import json
import os
import re
import statistics
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SELFBOT = REPO / "95.py"

MSG = ("سلام دوست عزیز، لینک کانال من: https://t.me/example_channel — "
       "قوانین: ۱) عضو بمان ۲) پیام بده @user1 @user2 ")
LINK_RE = re.compile(r"https?://t\.me/\S+|@[A-Za-z0-9_]{4,}")


def load_db_class():
    src = SELFBOT.read_text(encoding="utf-8")
    ns = {"__name__": "jafj_perf", "__file__": str(SELFBOT),
          "__builtins__": __builtins__}
    exec(compile(src, str(SELFBOT), "exec"), ns)
    return ns["DB"]


def make_db(DB, path, rows):
    db = DB(path)
    now = int(time.time())
    with db.conn:
        db.conn.executemany(
            "INSERT INTO exchange(peer_id,peer_name,link,status,created_at,"
            "last_check,next_check,direction,reminders,joined_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            # next_reminder ستونِ نهم است؛ مقدارِ غیرِصفر می‌گذاریم تا
            # ex_reminder_due بدترین حالت (همه‌ی رکوردها سررسید) را بسنجد.
            [(100000 + i, "peer%d" % i, "https://t.me/c/%d" % i, "joined",
              now - i, now, now - i, now - i, 0, now - i) for i in range(rows)])
        db.conn.executemany(
            "INSERT INTO queue(target,text,tier,status,created_at,scheduled_at) "
            "VALUES(?,?,?,?,?,?)",
            [("u1", "hello %d" % i, "vip", "pending", now - i, now - i)
             for i in range(rows)])
    db.conn.commit()
    return db


def timeit(fn, n=300):
    for _ in range(10):
        fn()
    ts = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        ts.append((time.perf_counter() - t0) * 1e6)
    return statistics.median(ts), sorted(ts)[int(len(ts) * 0.95)]


def db_section(DB, rows, caches):
    out = {}
    for cache in caches:
        tmp = tempfile.mkdtemp(prefix="jafj_perf_")
        path = os.path.join(tmp, "p.db")
        db = make_db(DB, path, rows)
        db.conn.execute("PRAGMA cache_size = %s" % cache)
        db.conn.commit()
        now = int(time.time())
        cases = {
            "ex_counts": lambda: db.ex_counts(),
            "ex_due": lambda: db.ex_due(now, 15),
            "ex_by_peer": lambda: db.ex_by_peer(100000 + rows // 2),
            # بدترین حالت: طرفی که هیچ رکوردی ندارد → کلِ جدول پیمایش می‌شد
            "ex_by_peer (ناشناس)": lambda: db.ex_by_peer(10 ** 12),
            "ex_set (write)": lambda: db.ex_set(1, next_check=now + 60),
            "next_pending (داغ)": lambda: db.next_pending("vip"),
            "list_pending": lambda: db.list_pending(10),
            "ex_reminder_due": lambda: db.ex_reminder_due(now, 20),
            "log (write)": lambda: db.log("u1", "perf", "x"),
        }
        out[cache] = {k: timeit(f) for k, f in cases.items()}
        try:
            db.conn.close()
        except Exception:
            pass
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    return out


def one_message(db):
    """کارِ تقریبیِ یک پیامِ ورودی در مسیرِ تبادل."""
    refs = LINK_RE.findall(MSG)
    d = {"refs": refs, "text": MSG[:120], "n": len(refs)}
    json.loads(json.dumps(d, ensure_ascii=False))
    db.ex_by_peer(100000)
    db.ex_set(1, next_check=int(time.time()) + 60)


def thread_section(DB, workers, iters):
    tmp = tempfile.mkdtemp(prefix="jafj_perf_thr_")

    def run(prefix, n):
        lat = []
        dbs = []
        for i in range(n):
            db = DB(os.path.join(tmp, "%s%d.db" % (prefix, i)))
            db.ex_add(100000, "x", "https://t.me/c/t%d" % i)
            dbs.append(db)
        done = [False] * n

        def work(db, idx):
            for _ in range(iters):
                t0 = time.perf_counter()
                one_message(db)
                lat.append((time.perf_counter() - t0) * 1000)
            done[idx] = True

        t0 = time.perf_counter()
        if n == 1:
            work(dbs[0], 0)
        else:
            ths = [threading.Thread(target=work, args=(dbs[i], i))
                   for i in range(n)]
            for t in ths:
                t.start()
            for t in ths:
                t.join()
        wall = time.perf_counter() - t0
        for db in dbs:
            try:
                db.conn.close()
            except Exception:
                pass
        return wall, lat

    single_wall, single_lat = run("s", 1)
    many_wall, many_lat = run("m", workers)
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)
    return {
        "workers": workers, "iters": iters,
        "single_wall": single_wall, "single_median": statistics.median(single_lat),
        "many_wall": many_wall,
        "median": statistics.median(many_lat),
        "p95": sorted(many_lat)[int(len(many_lat) * 0.95)],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, default=20000)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--iters", type=int, default=60)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    DB = load_db_class()
    caches = ["-2000", "-400"]
    rep = {"rows": args.rows}
    rep["db"] = db_section(DB, args.rows, caches)
    rep["threads"] = thread_section(DB, args.workers, args.iters)

    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
        return 0

    print(f"دیتابیس: {args.rows} رکورد تبادل + {args.rows} صف")
    print("\n── کوئری‌های مسیرِ تبادل (median / p95، میکروثانیه) ──")
    names = list(rep["db"]["-2000"].keys())
    print("  %-24s %14s %14s %8s" % ("کوئری", "cache=-2000", "cache=-400", "اختلاف"))
    for n in names:
        a, _ = rep["db"]["-2000"][n]
        b, _ = rep["db"]["-400"][n]
        print("  %-24s %8.0f/%8.0f %8.0f/%8.0f %+7.1f%%"
              % (n, rep["db"]["-2000"][n][0], rep["db"]["-2000"][n][1], b,
                 rep["db"]["-400"][n][1], (b - a) / a * 100 if a else 0))

    t = rep["threads"]
    print(f"\n── مقیاس‌پذیری: {t['iters']} پیام در هر اکانت ──")
    print("  ۱ اکانت (۱ رشته):        wall=%.3fs  median=%.2fms"
          % (t["single_wall"], t["single_median"]))
    print("  %d اکانت هم‌زمان (۱ پروسه): wall=%.3fs  median=%.2fms  p95=%.2fms"
          % (t["workers"], t["many_wall"], t["median"], t["p95"]))
    ideal = t["single_wall"] * t["workers"]
    print("  کاراییِ موازی: %.0f%% (ایده‌آل %.2fs، واقعی %.2fs)"
          % (min(100.0, ideal / t["many_wall"] * 100) if t["many_wall"] else 0,
             ideal, t["many_wall"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
