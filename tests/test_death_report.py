#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""«داشت کار می‌کرد، یهو سرور آفلاین شد» — چرا؟

وقتی کانتینر با OOM یا Stopِ پنل کشته می‌شود، هیچ کدی اجرا نمی‌شود؛ نه
crash.log، نه `.jafj_last_exit` — بوتِ بعدی هم بی‌خبر است و کاربر فقط
«آفلاین شد» می‌بیند. حالا هر دقیقه یک ضربان (زمان + حافظه‌ی آزاد + تعدادِ
سلف‌ها) روی دیسک نوشته می‌شود و بوتِ بعد با مقایسه‌ی آن با ثبتِ خروج
می‌گوید پروسه «تمیز» مرده یا ناگهانی.
"""
import importlib.util
import inspect
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


def main():
    root = Path(tempfile.mkdtemp(prefix="jafj_hb_"))
    here = os.getcwd()
    saved_data = os.environ.get("DATA_DIR")
    saved_port = os.environ.get("PORT")
    os.environ["DATA_DIR"] = str(root / "data")
    os.environ["PORT"] = "8499"
    os.environ.pop("JAFJ_ONLY", None)
    data = Path(os.environ["DATA_DIR"])
    data.mkdir(parents=True, exist_ok=True)
    try:
        sys.path.insert(0, str(REPO))
        import manager_82 as M

        hb_path = data / M.HEARTBEAT_NAME
        ex_path = data / M.LAST_EXIT_NAME

        # ── ۱) بدونِ ضربان → چیزی برای گفتن نیست ─────────────────────
        check("بدونِ ضربان: گزارش خالی است", M.last_death_report(data) == "")

        # ── ۲) ضربان بدونِ ثبتِ خروج = مرگِ ناگهانی (OOM/Stop) ────────
        M.write_heartbeat(data, {"free": 51, "clients": 6})
        hb = json.loads(hb_path.read_text(encoding="utf-8"))
        check("ضربان: فایل نوشته شد", hb_path.is_file())
        check("ضربان: زمان دارد", abs(float(hb.get("ts")) - time.time()) < 10, hb)
        check("ضربان: حافظه و تعدادِ سلف ثبت شد",
              hb.get("free") == 51 and hb.get("clients") == 6, hb)
        txt = M.last_death_report(data)
        check("مرگِ ناگهانی: «بدونِ خروجِ تمیز» می‌گوید",
              "بدونِ خروجِ تمیز" in txt, txt)
        check("مرگِ ناگهانی: حافظه‌ی آزاد را می‌گوید", "51MB" in txt, txt)
        check("مرگِ ناگهانی: تعدادِ سلف را می‌گوید", "6 سلف" in txt, txt)
        check("مرگِ ناگهانی: OOM/Stop را حدس می‌زند", "OOM" in txt, txt)

        # ── ۳) خروجِ ثبت‌شده با کدِ OOM/SIGTERM ───────────────────────
        ex_path.write_text(json.dumps({"code": 137, "uptime": 1200,
                                       "ts": time.time() + 1}), encoding="utf-8")
        txt = M.last_death_report(data)
        check("کدِ ۱۳۷: کد را در پیام می‌آورد", "137" in txt, txt)
        check("کدِ ۱۳۷: «SIGKILL/OOM» می‌گوید",
              "SIGKILL" in txt or "OOM" in txt, txt)

        # ── ۴) خروجِ تمیز و نزدیک → پیامِ اضافه نده ───────────────────
        ex_path.write_text(json.dumps({"code": 0, "ts": time.time() + 1}),
                           encoding="utf-8")
        check("خروجِ تمیز: سکوت (پیامِ الکی نمی‌دهد)",
              M.last_death_report(data) == "", M.last_death_report(data))

        # ── ۵) خاموشیِ طولانی → می‌گوید چه‌قدر خاموش بود ──────────────
        old_ts = time.time() - 2 * 3600
        hb_path.write_text(json.dumps({"ts": old_ts, "free": 300, "clients": 2}),
                           encoding="utf-8")
        ex_path.write_text(json.dumps({"code": 0, "ts": old_ts + 1}),
                           encoding="utf-8")
        txt = M.last_death_report(data)
        check("خاموشیِ طولانی: مدت را می‌گوید", "دقیقه خاموش بود" in txt, txt)

        # ── ۶) وصل‌شدن به حلقه و بوت ──────────────────────────────────
        src = (REPO / "manager_82.py").read_text(encoding="utf-8")
        check("مدیر: heartbeat_loop ثبت شده",
              "async def heartbeat_loop" in src and
              "self.heartbeat_loop()" in src)
        check("مدیر: گزارشِ مرگ در بوت چاپ می‌شود",
              "last_death_report(BASE_DIR)" in src)
        check("مدیر: ضربان در بوت زده می‌شود",
              'write_heartbeat(BASE_DIR, {"stage": "boot"})' in src)
        check("مدیر: هشدارِ حافظه‌ی کم هست", "حافظه‌ی آزاد کم است" in src)

        # ── ۷) حلقه‌ی ضربان: یک coroutine واقعی در کلاسِ مدیر ─────────
        owner = None
        for obj in vars(M).values():
            if inspect.isclass(obj) and hasattr(obj, "heartbeat_loop"):
                owner = obj
                break
        check("مدیر: heartbeat_loop داخلِ یک کلاس است", owner is not None)
        check("مدیر: heartbeat_loop یک coroutine است",
              owner is not None and inspect.iscoroutinefunction(
                  owner.heartbeat_loop))
        if owner is not None:
            fn_src = inspect.getsource(owner.heartbeat_loop)
            check("حلقه: ضربان را می‌نویسد", "write_heartbeat" in fn_src)
            check("حلقه: هشدارِ حافظه‌ی کم را می‌دهد", "حافظه‌ی آزاد کم" in fn_src)
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
