#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ایندکس‌های سرعت‌دهنده نباید نتیجه‌ی کوئری‌ها را عوض کنند.

سه چیز چک می‌شود، همه روی کلاسِ `DB` واقعیِ `95.py`:

1. `next_pending` / `list_pending` (که با `INDEXED BY idx_q_pick` اجرا
   می‌شوند) دقیقاً همان ردیفی را برمی‌گردانند که کوئریِ ساده‌ی قبلی
   برمی‌گرداند — روی داده‌ی تصادفی با tier/زمان‌بندیِ مختلف.
2. `ex_reminder_due` با و بدونِ `idx_ex_rem` همان نتیجه را می‌دهد.
3. اگر ایندکس نبود (دیتابیسِ دست‌کاری‌شده)، کد خطا نمی‌دهد و بی‌ایندکس
   جواب می‌دهد؛ و خودِ ایندکس‌ها هنگامِ باز شدنِ دیتابیس ساخته می‌شوند.
"""
import os
import random
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAILS = []


def check(name, ok, extra=""):
    if ok:
        print("PASS", name)
    else:
        FAILS.append(name)
        print("FAIL", name, "" if extra == "" else "→ %r" % (extra,))
    return ok


def load_db():
    path = os.path.join(REPO, "95.py")
    src = open(path, encoding="utf-8").read()
    ns = {"__name__": "jafj_idx_test", "__file__": path,
          "__builtins__": __builtins__}
    exec(compile(src, path, "exec"), ns)
    return ns["DB"]


def indexes(db, table):
    return {r[0] for r in db.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name=?",
        (table,))}


def main():
    DB = load_db()
    tmp = tempfile.mkdtemp(prefix="jafj_idx_")
    db = DB(os.path.join(tmp, "t.db"))
    now = int(time.time())
    rnd = random.Random(1234)

    check("ایندکسِ صف هنگامِ باز شدن ساخته می‌شود",
          "idx_q_pick" in indexes(db, "queue"), indexes(db, "queue"))
    check("ایندکسِ یادآور هنگامِ باز شدن ساخته می‌شود",
          "idx_ex_rem" in indexes(db, "exchange"), indexes(db, "exchange"))
    check("ایندکسِ قدیمیِ صف (idx_q) حذف شده",
          "idx_q" not in indexes(db, "queue"), indexes(db, "queue"))

    # ── داده‌ی تصادفی: هم tier های مختلف، هم زمان‌بندیِ گذشته/آینده ──
    rows = []
    for i in range(3000):
        tier = rnd.choice(["standard", "vip", "news"])
        target = "" if rnd.random() < 0.15 else "u%d" % rnd.randint(1, 9)
        sched = now + rnd.randint(-4000, 4000)
        status = "pending" if rnd.random() < 0.8 else "sent"
        rows.append((target, "t%d" % i, tier, status, now - i, sched))
    with db.conn:
        db.conn.executemany(
            "INSERT INTO queue(target,text,tier,status,created_at,scheduled_at)"
            " VALUES(?,?,?,?,?,?)", rows)

    PLAIN = ("SELECT * FROM queue WHERE status='pending' AND tier=?"
             " AND target<>'' AND scheduled_at<=? ORDER BY id LIMIT 1")
    FORCED = ("SELECT * FROM queue INDEXED BY idx_q_pick WHERE status='pending'"
              " AND tier=? AND target<>'' AND scheduled_at<=? ORDER BY id LIMIT 1")
    bad = 0
    for _ in range(300):
        tier = rnd.choice(["standard", "vip", "news", "nope"])
        t = now + rnd.randint(-5000, 5000)
        a = db._x(PLAIN, (tier, t), "one")
        b = db._x(FORCED, (tier, t), "one")
        if (a or {}).get("id") != (b or {}).get("id"):
            bad += 1
    check("next_pending با ایندکس همان ردیف را می‌دهد", bad == 0, bad)

    PLAIN_L = "SELECT * FROM queue WHERE status='pending' ORDER BY id LIMIT ?"
    FORCED_L = ("SELECT * FROM queue INDEXED BY idx_q_pick"
                " WHERE status='pending' ORDER BY id LIMIT ?")
    bad = 0
    for n in (1, 2, 5, 10, 50, 200):
        if ([r["id"] for r in db._x(PLAIN_L, (n,), "all")]
                != [r["id"] for r in db._x(FORCED_L, (n,), "all")]):
            bad += 1
    check("list_pending با ایندکس همان ردیف‌ها را می‌دهد", bad == 0, bad)

    # ── یادآورها: با و بدونِ ایندکس ──
    with db.conn:
        db.conn.executemany(
            "INSERT INTO exchange(peer_id,peer_name,link,status,created_at,"
            "last_check,next_check,next_reminder,direction,reminders)"
            " VALUES(?,?,?,?,?,?,?,?,?,?)",
            [(1000 + i, "p%d" % i, "https://t.me/c/%d" % i,
              rnd.choice(["pending", "joined", "left"]), now - i, now, 0,
              now + rnd.randint(-6000, 6000), 0, 0) for i in range(2500)])
    REM = ("SELECT * FROM exchange WHERE status IN ('pending','joined')"
           " AND peer_id IS NOT NULL AND next_reminder>0 AND next_reminder<=?"
           " ORDER BY next_reminder LIMIT ?")
    bad = 0
    for _ in range(40):
        t = now + rnd.randint(-6000, 6000)
        lim = rnd.choice([1, 5, 20, 100])
        with_idx = [r["id"] for r in db._x(REM, (t, lim), "all")]
        db.conn.execute("DROP INDEX IF EXISTS idx_ex_rem")
        without = [r["id"] for r in db._x(REM, (t, lim), "all")]
        db.conn.execute("CREATE INDEX IF NOT EXISTS idx_ex_rem "
                        "ON exchange(status, next_reminder)")
        if with_idx != without:
            bad += 1
    check("ex_reminder_due با ایندکس همان نتیجه را می‌دهد", bad == 0, bad)

    # ── ex_by_peer: با و بدونِ idx_ex_peer ──
    check("ایندکسِ peer_id هنگامِ باز شدن ساخته می‌شود",
          "idx_ex_peer" in indexes(db, "exchange"), indexes(db, "exchange"))
    bad = 0
    for pid in (1000, 1010, 2400, 999999):
        with_idx = db.ex_by_peer(pid)
        db.conn.execute("DROP INDEX IF EXISTS idx_ex_peer")
        without = db.ex_by_peer(pid)
        db.conn.execute("CREATE INDEX IF NOT EXISTS idx_ex_peer "
                        "ON exchange(peer_id)")
        if (with_idx or {}).get("id") != (without or {}).get("id"):
            bad += 1
    check("ex_by_peer با ایندکس همان رکورد را می‌دهد", bad == 0, bad)

    # ── بدونِ ایندکس هم نباید خطا بدهد (دیتابیسِ دست‌کاری‌شده) ──
    db.conn.execute("DROP INDEX idx_q_pick")
    db.conn.commit()
    ok = True
    try:
        db.next_pending("vip")
        db.list_pending(5)
    except Exception as e:                    # noqa: BLE001
        ok = False
        check("بدونِ ایندکس، کوئریِ صف خطا نمی‌دهد", False, e)
    if ok:
        check("بدونِ ایندکس، کوئریِ صف خطا نمی‌دهد", True)

    db.conn.close()
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)

    if FAILS:
        print("\nFAILED:", FAILS)
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
