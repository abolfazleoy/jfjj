#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""گزارشِ واقعیِ مصرفِ حافظه‌ی جفج — قابلِ تکرار، بدونِ حدس.

هر عددی که این اسکریپت چاپ می‌کند از `/proc/<pid>/status` (RSS) و
`/proc/<pid>/smaps_rollup` (PSS) خوانده می‌شود، در **پروسه‌های جدا**.

چرا PSS و نه RSS: با fork/shard صفحه‌های مشترک در RSSِ هر پروسه کامل حساب
می‌شوند؛ جمعِ RSS عددی چند برابرِ واقعیت می‌دهد. PSS سهمِ هر پروسه را
تقسیم می‌کند، پس **جمعِ PSSِ همه‌ی پروسه‌های یک درخت = حافظه‌ی واقعی**.

اجرا:

    python3 tools/mem_report.py                 # ۴ اکانت، همه‌ی حالت‌ها
    python3 tools/mem_report.py --accounts 8
    python3 tools/mem_report.py --mode shard
    python3 tools/mem_report.py --json          # برای CI/مقایسه

خروجی: جدولِ ثابت‌ها + جدولِ هر حالت + ظرفیتِ ۲۵۶/۵۱۲/۱۰۲۴ مگابایت.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SELFBOT = REPO / "95.py"
FORKD = REPO / "jafj_forkd.py"
SHARDD = REPO / "jafj_shardd.py"


# ─────────────────────────────────────────────── اندازه‌گیری ──
def _read(pid, path, key):
    try:
        with open(f"/proc/{pid}/{path}", encoding="utf-8") as f:
            for line in f:
                if line.startswith(key):
                    return int(line.split()[1]) / 1024.0
    except Exception:
        pass
    return 0.0


def mem_of(pid):
    """(RSS, PSS) یک پروسه به مگابایت."""
    return _read(pid, "status", "VmRSS:"), _read(pid, "smaps_rollup", "Pss:")


def children_of(pid):
    try:
        with open(f"/proc/{pid}/task/{pid}/children", encoding="utf-8") as f:
            return [int(x) for x in f.read().split()]
    except Exception:
        return []


def tree(pid):
    out, stack = [], [pid]
    while stack:
        p = stack.pop()
        out.append(p)
        stack.extend(children_of(p))
    return out


def tree_mem(pid):
    """(جمعِ RSS, جمعِ PSS, تعدادِ پروسه) برای کلِ درخت."""
    rss = pss = 0.0
    pids = tree(pid)
    for p in pids:
        r, s = mem_of(p)
        rss += r
        pss += s
    return rss, pss, len(pids)


def run_measured(argv, cwd, env, settle=8.0):
    """اجرا، صبر، اندازه‌گیریِ درخت، بستن. برمی‌گرداند (rss, pss, nproc)."""
    p = subprocess.Popen(argv, cwd=cwd, env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(settle)
        return tree_mem(p.pid)
    finally:
        try:
            for pid in tree(p.pid):
                try:
                    os.kill(pid, 15)
                except Exception:
                    pass
            time.sleep(0.6)
            p.kill()
        except Exception:
            pass


# ────────────────────────────────────────────── حالت‌ها ──
def measure_baseline(py, env):
    rows = []
    cases = [
        ("پایتونِ خالی", "import time; time.sleep(30)"),
        ("+ telethon", "import telethon, time; time.sleep(30)"),
        ("+ exec 95.py (بدونِ main)", (
            "s=open(%r,encoding='utf-8').read();"
            "ns={'__name__':'p','__file__':%r,'__builtins__':__builtins__};"
            "exec(compile(s,%r,'exec'),ns);import time;time.sleep(30)"
            % (str(SELFBOT), str(SELFBOT), str(SELFBOT)))),
        ("+ manager_82 (ماژول)", "import manager_82, time; time.sleep(30)"),
    ]
    for label, code in cases:
        rss, pss, _n = run_measured([py, "-c", code], str(REPO), env, settle=6.0)
        rows.append((label, rss, pss))
    return rows


def measure_process(py, env, n):
    """دام: n پروسه‌ی کاملِ 95.py در پوشه‌های جدا."""
    root = Path(tempfile.mkdtemp(prefix="jafj_mem_proc_"))
    procs = []
    try:
        for i in range(n):
            d = root / f"acc{i}"
            d.mkdir()
            procs.append(subprocess.Popen([py, str(SELFBOT)], cwd=str(d),
                                          env=env, stdout=subprocess.DEVNULL,
                                          stderr=subprocess.DEVNULL))
        time.sleep(9)
        rss = pss = 0.0
        nproc = 0
        for p in procs:
            for pid in tree(p.pid):
                r, sm = mem_of(pid)
                rss += r
                pss += sm
                nproc += 1
        return rss, pss, n, nproc
    finally:
        for p in procs:
            try:
                p.kill()
            except Exception:
                pass
        import shutil
        shutil.rmtree(root, ignore_errors=True)


def measure_daemon(py, env, n, mode):
    """fork یا shard: یک دیمن + n اکانت، با همان مسیرِ کدِ مدیر."""
    script = FORKD if mode == "fork" else SHARDD
    root = Path(tempfile.mkdtemp(prefix=f"jafj_mem_{mode}_"))
    argv = [py, str(script), "--selfbot", str(SELFBOT)]
    if mode == "shard":
        argv += ["--max-accounts", str(n)]
    p = subprocess.Popen(argv, cwd=str(REPO), env=env,
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL, bufsize=0)
    try:
        # منتظرِ ready
        p.stdout.readline()
        for i in range(n):
            d = root / f"acc{i}"
            d.mkdir()
            msg = json.dumps({"cmd": "run", "cwd": str(d),
                              "log": str(d / "run.log"), "uid": str(900 + i)})
            p.stdin.write((msg + "\n").encode())
            p.stdin.flush()
            p.stdout.readline()
            time.sleep(0.4)
        time.sleep(9)
        rss, pss, nproc = tree_mem(p.pid)
        return rss, pss, n, nproc
    finally:
        try:
            p.stdin.write(b'{"cmd":"quit"}\n')
            p.stdin.flush()
        except Exception:
            pass
        for pid in tree(p.pid):
            try:
                os.kill(pid, 15)
            except Exception:
                pass
        import shutil
        shutil.rmtree(root, ignore_errors=True)


# ───────────────────────────────────────────── ظرفیت ──
def capacity(base_mb, marginal_mb, budget_mb, reserve_mb=96.0):
    usable = float(budget_mb) - float(reserve_mb) - float(base_mb)
    if usable <= 0 or marginal_mb <= 0:
        return 0
    return int(usable // marginal_mb)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--accounts", type=int, default=4)
    ap.add_argument("--mode", default="all",
                    choices=["all", "process", "fork", "shard"])
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--budget", default="256,512,1024")
    args = ap.parse_args()

    py = args.python
    env = dict(os.environ)
    env.setdefault("JAFJ_NO_AUTO_LOGIN", "1")
    tmp = Path(tempfile.mkdtemp(prefix="jafj_mem_data_"))
    env["DATA_DIR"] = str(tmp)
    env.setdefault("PORT", "8899")

    report = {"baseline": [], "modes": {}, "capacity": {}}
    if not args.json:
        print(f"repo={REPO}  python={py}  accounts={args.accounts}")
        print("\n── ثابت‌ها (RSS / PSS، جمعِ درخت) ──")
    for label, rss, pss in measure_baseline(py, env):
        report["baseline"].append({"label": label, "rss": rss, "pss": pss})
        if not args.json:
            print(f"  {label:34s} RSS={rss:6.1f}  PSS={pss:6.1f} MB")
    base_proc = report["baseline"][0]["pss"] if report["baseline"] else 0.0

    modes = ["process", "fork", "shard"] if args.mode == "all" else [args.mode]
    for mode in modes:
        try:
            if mode == "process":
                rss, pss, n, nproc = measure_process(py, env, args.accounts)
            else:
                rss, pss, n, nproc = measure_daemon(py, env, args.accounts, mode)
        except Exception as e:
            if not args.json:
                print(f"\n── {mode}: اندازه‌گیری نشد ({type(e).__name__}: {e})")
            continue
        one_rss, one_pss, _ = (0, 0, 0)
        try:
            if mode == "process":
                one_rss, one_pss, _, _ = measure_process(py, env, 1)
            else:
                one_rss, one_pss, _, _ = measure_daemon(py, env, 1, mode)
        except Exception:
            pass
        marginal = ((pss - one_pss) / (n - 1)) if n > 1 and one_pss else pss / n
        report["modes"][mode] = {"rss": rss, "pss": pss, "n": n,
                                 "nproc": nproc, "one_pss": one_pss,
                                 "marginal": marginal}
        if not args.json:
            print(f"\n── {mode}: {n} اکانت در {nproc} پروسه → "
                  f"RSS={rss:.1f}  PSS={pss:.1f} MB")
            if one_pss:
                print(f"   ۱ اکانت={one_pss:.1f}MB · هر اکانتِ اضافه="
                      f"{marginal:.1f}MB")

    if not args.json:
        print("\n── ظرفیت (با همین اعداد، ۹۶ مگابایت برای مدیر/سیستم کنار) ──")
    for b in [int(x) for x in str(args.budget).split(",") if x.strip()]:
        row = {}
        for mode, d in report["modes"].items():
            row[mode] = capacity(d["one_pss"], d["marginal"], b)
        report["capacity"][b] = row
        if not args.json:
            cells = "  ".join(f"{m}={v:>4d}" for m, v in row.items())
            print(f"  {b:>5d} MB → {cells}")
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
