#!/usr/bin/env python3
"""شفافیتِ «پیام گروه» — گزارش باید علتِ سکوتِ گروه را صریح بگوید.

گزارش مشتری: «ربات تو پیوی گزارش میده، پیش‌قدم میشه، ولی تو گروهِ تبادل
هیچ پیامی نمی‌فرسته.» بررسیِ کد نشان داد `reply_joined` در چند حالت
بی‌صدا `False` برمی‌گشت:

  • متنِ تبادل (`msg_come`/`msg_ok`) ثبت نشده — شایع‌ترین؛ مخصوصاً بعد
    از مهاجرتِ متن‌های پیش‌فرضِ قدیمی که خالی می‌شوند.
  • «جواب» (`تبادل جواب`) خاموش شده.
  • `src_chat`/`src_msg` در رکورد نیست (لینک از گروه نیامده).
  • ارسال واقعاً شکست خورده (فلود/اسلومود/… ) — فقط در رویدادها.
  • برای این تبادل قبلاً پیام رفته بود (`replied=1`).

در همهٔ این حالت‌ها گزارشِ لحظه‌ایِ پیوی فقط خطِ «💬 متن تبادل ارسال شد»
را نداشت — هیچ سرنخی به کاربر نمی‌رسید. الان:

  ۱. `reply_joined` دلیلِ هر رد را در `eng.reply_note` ثبت می‌کند.
  ۲. `ex_live_join_text` وقتی پیام نرفته، خطِ «💬 پیام گروه: …» با علت
     دقیق + دستورِ اصلاح می‌گذارد.
  ۳. مسیرِ «تبادل ارسال» (`_reply_now`) هم دلیل را می‌گوید.

همهٔ سنجه‌ها روی **کدِ واقعی** اجرا می‌شوند: تابع `reply_joined` از خود
`95.py` استخراج و با Engine/DB واقعی اجرا می‌شود.

    python3 tests/test_group_reply_transparency.py  →  ALL: PASS
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
ROOT = os.path.join(tempfile.gettempdir(), "jafj_reply_transparency")
APP = os.path.join(ROOT, "app")
DATA = os.path.join(ROOT, "data")


DRIVER = r"""
import asyncio, importlib.util, os, random, sys, time
from types import SimpleNamespace
sys.path.insert(0, os.getcwd())

spec = importlib.util.spec_from_file_location("m95", "95.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
src = open("95.py", encoding="utf-8").read()

FAILS = []


def check(cond, label):
    print(("OK   " if cond else "FAIL "), label)
    if not cond:
        FAILS.append(label)


async def anoop(x=0):
    return None


def fresh_engine(chan="@mychan"):
    for f in ("jafj_settings.json", "jafj.db", "jafj_limits.json"):
        if os.path.exists(f):
            os.remove(f)
    eng = m.Engine()
    assert hasattr(eng, "reply_note"), "Engine.reply_note ساخته نشده"
    eng.st.prof("standard")["channel"] = chan
    x = eng.ex_cfg()
    x["reply"] = True
    eng.st.save()
    return eng, x


def slice_block(start_marker, end_marker, ind=4):
    a = src.find(start_marker)
    assert a > 0, "start marker missing"
    b = src.find(end_marker, a)
    assert b > a, "end marker missing"
    lines = src[a:b].splitlines()
    while lines and (lines[0].lstrip().startswith("#") or not lines[0].strip()):
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(ln[ind:] if ln.startswith(" " * ind) else ln
                     for ln in lines)


reply_ded = slice_block("async def reply_joined(rec):", "def joins_left_today():")
flush_ded = slice_block("async def flush_reply_retries():", "def joins_left_today():")


class Client:
    # ارسالِ سالم؛ برای تستِ خطا، send_error ست می‌شود.
    send_error = None

    async def send_message(self, chat, body, **kw):
        if Client.send_error:
            raise Client.send_error
        SENT.append((chat, body, kw))
        return SimpleNamespace(id=999)


class Cd:
    async def action(self, kind, rec_id, fn, *a, **kw):
        return await fn()


def build_reply(eng):
    ns = {"m": m, "eng": eng, "client": Client(), "ex_cd": Cd(),
          "asyncio": asyncio, "time": time, "random": random,
          "DRY_RUN": False,
          "come_delay_seconds": lambda: 0,
          "response_delay_seconds": lambda: 0}
    exec("async def _r(rec):\n"
         + "\n".join("    " + l for l in reply_ded.splitlines())
         + "\n    return await reply_joined(rec)\n", ns)
    return ns["_r"]


def build_flush(eng, reply_fn):
    # تابعِ flush_reply_retries واقعی را با موتورِ واقعی می‌سازد.
    class Cd2:
        blocked_until = 0.0
    NOTES = []

    async def note(text):
        NOTES.append(text)

    ns = {"m": m, "eng": eng, "ex_cd": Cd2(), "note": note,
          "reply_joined": reply_fn, "asyncio": asyncio, "time": time,
          "random": random, "fa": m.fa}
    exec("async def _f():\n"
         + "\n".join("    " + l for l in flush_ded.splitlines())
         + "\n    return await flush_reply_retries()\n", ns)
    return ns["_f"], ns["ex_cd"], NOTES


def mk_rec(eng, peer, link, **kw):
    rec, _ = eng.db.ex_add(peer, "n%d" % peer, link)
    kw.setdefault("status", "joined")
    kw.setdefault("direction", "out")
    kw.setdefault("last_check", 0)
    kw.setdefault("next_check", 0)
    eng.db.ex_set(rec["id"], **kw)
    return eng.db.ex_get(rec["id"])


SENT = []


async def send_come(eng, **setup):
    x = eng.ex_cfg()
    for k, v in setup.items():
        x[k] = v
    eng.st.save()
    rec = mk_rec(eng, 7001, "@peerchan", direction="out", replied=0,
                 src_chat=555, src_msg=777)
    SENT.clear()
    ok = await build_reply(eng)(rec)
    rec = eng.db.ex_get(rec["id"])
    return ok, rec, (SENT[-1][1] if SENT else "")


async def main():
    # ═══ T1 — متنِ ثبت‌نشده: شایع‌ترین علتِ سکوتِ گروه ═══
    eng, x = fresh_engine()
    ok, rec, body = await send_come(eng, msg_come="", msg_first="", msg_ok="")
    check(not ok and not body and not SENT,
          "T1: بدونِ متن، پیام گروه نمی‌رود (رفتار ثابت)")
    check(eng.reply_note.get(rec["id"], ("", ""))[0] == "no_text",
          "T1: دلیلِ «متن ثبت نشده» ثبت شد (بود %r)"
          % (eng.reply_note.get(rec["id"]),))
    txt = eng.ex_live_join_text(rec, "", False)
    check("متنِ تبادل ثبت نشده" in txt and "تبادل سریع" in txt,
          "T1: گزارش، علت + دستورِ اصلاح را می‌گوید")

    # ═══ T2 — «جواب» خاموش ═══
    eng, x = fresh_engine()
    ok, rec, body = await send_come(eng, reply=False, msg_come="جوینم بیا")
    check(not ok and not SENT,
          "T2: با «جواب» خاموش، پیام نمی‌رود (رفتار ثابت)")
    check(eng.reply_note.get(rec["id"], ("", ""))[0] == "reply_off",
          "T2: دلیلِ «reply_off» ثبت شد")
    txt = eng.ex_live_join_text(rec, "", False)
    check("جواب‌دادن خاموش است" in txt and "تبادل جواب" in txt,
          "T2: گزارش، خاموش‌بودنِ «جواب» + دستور را می‌گوید")

    # ═══ T3 — خطای واقعی ارسال (فلود/اسلومود/…) ═══
    eng, x = fresh_engine()
    Client.send_error = RuntimeError("SlowModeWait: 120s")
    ok, rec, body = await send_come(eng, msg_come="جوینم بیا")
    Client.send_error = None
    check(not ok and not SENT,
          "T3: خطای ارسال → پیام نمی‌رود (رفتار ثابت)")
    rsn = eng.reply_note.get(rec["id"], ("", ""))[0]
    check(rsn.startswith("err:"),
          "T3: دلیلِ خطا ثبت شد (بود %r)" % (rsn,))
    txt = eng.ex_live_join_text(rec, "", False)
    check("خطای ارسال" in txt and "RuntimeError" in txt,
          "T3: گزارش، نوع خطا را می‌گوید")

    # ═══ T4 — ارسال موفق: مثل قبل، بدون دلیلِ اضافه ═══
    eng, x = fresh_engine()
    ok, rec, body = await send_come(eng, msg_come="جوینم بیا")
    check(ok and body == "جوینم بیا\n@mychan" and len(SENT) == 1,
          "T4: ارسال سالم مثل قبل کار می‌کند (بود %r)" % body)
    check(rec["id"] not in eng.reply_note,
          "T4: بعد از ارسال موفق، دلیلی ثبت نمی‌ماند")
    txt = eng.ex_live_join_text(rec, "", True)
    check("💬 متن تبادل ارسال شد" in txt and "پیام گروه:" not in txt,
          "T4: متنِ موفقِ گزارش دست‌نخورده است")

    # ═══ T5 — قبلاً پیام رفته بود (replied=1) ═══
    eng, x = fresh_engine()
    rec = mk_rec(eng, 7002, "@peerchan2", direction="out", replied=1,
                 src_chat=555, src_msg=778)
    ok = await build_reply(eng)(rec)
    check(not ok, "T5: تبادلِ replied=1 دوباره پیام نمی‌فرستد (رفتار ثابت)")
    check(eng.reply_note.get(rec["id"], ("", ""))[0] == "already",
          "T5: دلیلِ «قبلاً رفته» ثبت شد")
    check("قبلاً پیام رفته بود" in eng.ex_live_join_text(rec, "", False),
          "T5: گزارش، «قبلاً پیام رفته» را می‌گوید")

    # ═══ T6 — src گم‌شده (لینک از گروه نیامده) ═══
    eng, x = fresh_engine()
    x["msg_come"] = "جوینم بیا"
    eng.st.save()
    rec = mk_rec(eng, 7003, "@peerchan3", direction="out", replied=0,
                 src_chat=0, src_msg=0)
    SENT.clear()
    ok = await build_reply(eng)(rec)
    check(not ok and not SENT, "T6: بدونِ مختصاتِ گروه، پیام نمی‌رود (ثابت)")
    check(eng.reply_note.get(rec["id"], ("", ""))[0] == "no_src",
          "T6: دلیلِ «no_src» ثبت شد")
    check("پیدا نشد" in eng.ex_live_join_text(rec, "", False),
          "T6: گزارش، گم‌شدنِ پیامِ گروه را می‌گوید")

    # ═══ T7 — حدسِ از روی تنظیمات وقتی دلیلِ ثبت‌شده‌ای نیست ═══
    eng, x = fresh_engine()
    rec = mk_rec(eng, 7004, "@peerchan4", direction="out", replied=0,
                 src_chat=1, src_msg=1)
    check(eng._reply_reason(rec) == "no_text",
          "T7: بدونِ متن، حدسِ پیش‌فرضِ دلیل «متن ثبت نشده» است")
    x["reply"] = False
    eng.st.save()
    check(eng._reply_reason(rec) == "reply_off",
          "T7: با «جوابِ» خاموش، حدسِ دلیل «reply_off» است")

    # ═══ T8 — مسیرِ «تبادل ارسال» هم دلیل را می‌گوید (سورس) ═══
    check("eng._reply_reason_text(rec)" in src,
          "T8: پیامِ «تبادل ارسال» دلیل را با _reply_reason_text می‌گوید")
    eng8, _ = fresh_engine()
    check(eng8._reply_reason_text({"id": 0}) ==
          "متنِ تبادل ثبت نشده — در پیوی بزن: `تبادل سریع` یا `تبادل پیام متنِ دلخواه`",
          "T8: جملهٔ دلیلِ «متن ثبت نشده» دستورِ اصلاح دارد")

    # ═══ T9–T13 — تلاشِ دوبارهٔ خودکار بعد از فلود/اسلومود ═══
    class SlowModeWaitError(Exception):
        def __init__(self, seconds):
            super().__init__("SlowModeWait %d" % seconds)
            self.seconds = int(seconds)

    # T9 — فلود → زمان‌بندی؛ بعد از رفعِ محدودیت → خودکار ارسال
    eng, x = fresh_engine()
    x["msg_come"] = "جوینم بیا"
    eng.st.save()
    flush, cd9, NOTES9 = build_flush(eng, build_reply(eng))
    rec = mk_rec(eng, 7005, "@peerchan5", direction="out", replied=0,
                 src_chat=555, src_msg=779)
    SENT.clear()
    Client.send_error = SlowModeWaitError(120)
    ok = await build_reply(eng)(rec)
    Client.send_error = None
    check(not ok and not SENT,
          "T9: ارسال در پنجرهٔ اسلومود شکست می‌خورد (رفتار ثابت)")
    info = eng.reply_retry.get(rec["id"])
    check(bool(info) and int(info[1]) == 1,
          "T9: تلاشِ دوباره زمان‌بندی شد (بود %r)" % (info,))
    info[0] = time.time() - 1          # محدودیت تمام شده
    await flush()
    body9 = SENT[-1][1] if SENT else ""
    check(body9 == "جوینم بیا\n@mychan",
          "T9: بعد از رفعِ محدودیت، پیام خودکار رفت (بود %r)" % body9)
    check(rec["id"] not in eng.reply_retry,
          "T9: بعد از ارسال موفق از صفِ تلاش حذف شد")
    check(any("بعد از رفعِ محدودیت" in n for n in NOTES9),
          "T9: پیوی هم خبر داد که دیر، اما رفت")

    # T10 — سقفِ ۳ تلاش → انصراف با راهنمای دستی، بدونِ لوپِ بی‌پایان
    eng, x = fresh_engine()
    x["msg_come"] = "جوینم بیا"
    eng.st.save()
    flush10, cd10, NOTES10 = build_flush(eng, build_reply(eng))
    rec = mk_rec(eng, 7006, "@peerchan6", direction="out", replied=0,
                 src_chat=556, src_msg=780)
    eng.reply_retry[rec["id"]] = [time.time() - 1, 3]
    SENT.clear()
    await flush10()
    check(rec["id"] not in eng.reply_retry and not SENT,
          "T10: بعد از سقفِ تلاش‌ها، رکورد رها می‌شود")
    check(any("تبادل ارسال" in n for n in NOTES10),
          "T10: پیوی راهِ دستی («تبادل ارسال») را می‌گوید")

    # T11 — صفِ کلی هنوز بسته (فلود) → عقب می‌افتد، نمی‌سوزد
    eng, x = fresh_engine()
    x["msg_come"] = "جوینم بیا"
    eng.st.save()
    flush11, cd11, NOTES11 = build_flush(eng, build_reply(eng))
    rec = mk_rec(eng, 7007, "@peerchan7", direction="out", replied=0,
                 src_chat=557, src_msg=781)
    eng.reply_retry[rec["id"]] = [time.time() - 1, 1]
    SENT.clear()
    cd11.blocked_until = time.time() + 120
    await flush11()
    info = eng.reply_retry.get(rec["id"])
    check(info and info[0] > time.time() and not SENT,
          "T11: با صفِ بسته، تلاش عقب می‌افتد ولی از دست نمی‌رود")

    # T12 — خطای غیرِ فلود → یک تیکِ دیگر با شمارندهٔ بالاتر
    eng, x = fresh_engine()
    x["msg_come"] = "جوینم بیا"
    eng.st.save()
    flush12, cd12, NOTES12 = build_flush(eng, build_reply(eng))
    rec = mk_rec(eng, 7008, "@peerchan8", direction="out", replied=0,
                 src_chat=558, src_msg=782)
    eng.reply_retry[rec["id"]] = [time.time() - 1, 1]
    Client.send_error = RuntimeError("not found")
    await flush12()
    Client.send_error = None
    info = eng.reply_retry.get(rec["id"])
    check(info and int(info[1]) == 2 and info[0] > time.time(),
          "T12: خطای غیرِ فلود هم شمارنده را بالا می‌برد (بود %r)" % (info,))

    # T13 — ارسالِ سالم، هر ردپایی از تلاشِ دوباره را پاک می‌کند
    eng, x = fresh_engine()
    x["msg_come"] = "جوینم بیا"
    eng.st.save()
    rec = mk_rec(eng, 7009, "@peerchan9", direction="out", replied=0,
                 src_chat=559, src_msg=783)
    eng.reply_retry[rec["id"]] = [time.time() - 1, 2]
    SENT.clear()
    ok = await build_reply(eng)(rec)
    check(ok and rec["id"] not in eng.reply_retry,
          "T13: ارسالِ سالم، صفِ تلاش را هم پاک می‌کند")

    print("DONE FAIL" if FAILS else "DONE PASS")
    if FAILS:
        for f in FAILS:
            print("  -", f)
        sys.exit(1)
    print("ALL: PASS")


asyncio.run(main())
"""


def main():
    shutil.rmtree(ROOT, ignore_errors=True)
    os.makedirs(APP, exist_ok=True)
    os.makedirs(DATA, exist_ok=True)
    shutil.copy(os.path.join(REPO, "95.py"), os.path.join(APP, "95.py"))
    env = os.environ.copy()
    env["DATA_DIR"] = DATA
    for k in ("PORT", "RENDER", "RAILWAY_ENVIRONMENT"):
        env.pop(k, None)
    p = subprocess.run([sys.executable, "-c", DRIVER], cwd=APP, env=env,
                       capture_output=True, text=True, timeout=300)
    print(p.stdout[-9000:])
    if p.stderr.strip():
        print("STDERR:", p.stderr[-3000:])
    return p.returncode


if __name__ == "__main__":
    sys.exit(main())
