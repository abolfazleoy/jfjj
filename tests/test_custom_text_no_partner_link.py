#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""رگرسیون باگ مشتری: «بعد از تنظیم متن‌های سفارشی جفج، علاوه بر لینک من،
لینک طرف تبادل هم inside پیام می‌آمد.»

سناریو: اول «تبادل سریع» (پیش‌فرض‌ها) کار می‌کرده، بعد مشتری متن‌های
سفارشی خودش را ثبت کرده. در نسخه‌های قدیمی، مسیر «نیومدی» لینک طرف را
اتوماتیک زیر متن می‌چسباند و توکن `{channel}` هم لینک طرف را رندر
می‌کرد؛ نتیجه پیامی بود با دو لینک (لینک خودی + لینک یارو).

این تست روی کد واقعی 95.py تضمین می‌کند:
  ۱) توکن `{channel}` با هر فاصله/حرف‌بندی‌ای خالی می‌شود.
  ۲) لینک خام طرف (هر املایی: @name / t.me / لینک خصوصی +HASH) حتی
     اگر داخل متن ذخیره‌شده مانده باشد حذف می‌شود.
  ۳) لینک کانال خودم (`{mychannel}` و لینک خام خودم) دست‌نخورده می‌ماند.
  ۴) این قانون در هر سه مسیر ارسال برقرار است:
     reply_joined (پیشقدم/ورودی) و send_not_joined_reminder.
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
ROOT = os.path.join(tempfile.gettempdir(), "jafj_custom_text_run")
APP = os.path.join(ROOT, "app")
DATA = os.path.join(ROOT, "data")

DRIVER = r"""
import asyncio, importlib.util, os, sys, time
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


def fresh():
    for f in ("jafj_settings.json", "jafj.db", "jafj_limits.json"):
        if os.path.exists(f):
            os.remove(f)
    e = m.Engine()
    e.st.prof("standard")["channel"] = "@mychan"
    return e


# ═══════ C1 — strip_peer_links: مستقل، همه املاها ═══════
peer = "@partner_chan"
spells_gone = [
    "@partner_chan",
    "https://t.me/partner_chan",
    "http://telegram.me/partner_chan/",
    "t.me/partner_chan",
    "پیشتاز @partner_chan بیا",
]
for s in spells_gone:
    out = m.strip_peer_links(s, peer)
    check("partner_chan" not in out, "C1: حذف لینک طرف %r -> %r" % (s, out))
# لینک خودم نباید دست بخورد
check(m.strip_peer_links("بیا @mychan را جوین شو", peer) == "بیا @mychan را جوین شو",
      "C1: لینک کانال خودم دست‌نخورده می‌ماند")
# لینک خصوصی طرف (هر سه شکل نوشتاری)
priv = "https://t.me/+AbCdEf1234567890"
for s in ("https://t.me/+AbCdEf1234567890",
          "t.me/joinchat/AbCdEf1234567890",
          "+AbCdEf1234567890"):
    out = m.strip_peer_links("متن " + s + " پایان", priv)
    check("AbCdEf1234567890" not in out, "C1: حذف invite خصوصی %r -> %r" % (s, out))
# ورودی خام/نبود طرف: کرش نکند و دست نزند
check(m.strip_peer_links("هر متن", "") == "هر متن", "C1: peer خاموش = بدون تغییر")
check(m.strip_peer_links("", peer) == "", "C1: متن خالی = رشته خالی")
print("DONE C1 strip_peer_links")


# ═══════ C2 — ex_render: همه کلیدها، توکن و لینک خام طرف ═══════
eng = fresh()
x = eng.ex_cfg()
# مرحله ۱: پیش‌فرض‌های تبادل سریع اعمال شده‌اند
for k, v in m.QUICK_EXCHANGE_DEFAULTS.items():
    x[k] = v
# مرحله ۲: مشتری متن‌های سفارشی خودش را ثبت می‌کند
x.update({
    "msg_come": "بیا {channel} جوین شو؛ کانال من {mychannel}",
    "msg_ok": "اوکی { channel } شد",
    "msg_no": "نیومدی {CHANNEL}، بیا @mychan",
    "msg_claim_no": "ادعا کردی https://t.me/partner_chan",
    "msg_wait": "صبر {channel} کن",
    "msg_nolink": "لینکت را بفرست t.me/partner_chan",
})
for key in ("msg_come", "msg_ok", "msg_no", "msg_claim_no",
            "msg_wait", "msg_nolink"):
    out = eng.ex_render(key, "Ali", "@partner_chan")
    check("partner_chan" not in out and "{channel" not in out.lower()
          and "{ channel" not in out.lower(),
          "C2: %s بدون لینک/توکن طرف -> %r" % (key, out))
# لینک خودم در msg_come باید رندر شده باشد
check("@mychan" in eng.ex_render("msg_come", "Ali", "@partner_chan"),
      "C2: {mychannel} با لینک خودم پر می‌شود")
# متن دارای هر دو لینک: طرف می‌رود، خودم می‌مانم
x["msg_come"] = "دو لینک: @mychan و @partner_chan"
out = eng.ex_render("msg_come", "Ali", "@partner_chan")
check("@mychan" in out and "partner_chan" not in out,
      "C2: لینک خودم می‌ماند و لینک طرف می‌رود -> %r" % out)
# متن کاملاً امنِ بدون لینک، دست‌نخورده
x["msg_come"] = "سلام، خوش اومدی"
check(eng.ex_render("msg_come", "Ali", "@partner_chan") == "سلام، خوش اومدی",
      "C2: متن ساده دست نمی‌خورد")
print("DONE C2 ex_render")


# ═══════ C3 — reply_joined واقعی (پیشقدم + ورودی) ═══════
a = src.find("    async def reply_joined(rec):")
b = src.find("    def joins_left_today():", a)
assert a > 0 and b > a
reply_ded = "\n".join(ln[4:] if ln.startswith("    ") else ln
                      for ln in src[a:b].splitlines())

SENT = []
class FakeClient:
    async def send_message(self, chat, body, reply_to=None, link_preview=True):
        SENT.append(body)
        return True
class CD:
    async def action(self, kind, rec_id, fn):
        return await fn()

ns = {"eng": eng, "asyncio": asyncio, "ex_cd": CD(), "DRY_RUN": False,
      "client": FakeClient(),
      "come_delay_seconds": lambda: 0,
      "response_delay_seconds": lambda: 0}
exec(reply_ded, ns)
reply_joined = ns["reply_joined"]

x["msg_come"] = "بیا {channel} جوین شو"
x["msg_ok"] = "اوکی {channel}"
eng.st.save()
for direction in ("out", "in"):
    rec, _ = eng.db.ex_add(8100 + (1 if direction == "out" else 2),
                           "partner_user", "@partner_chan")
    eng.db.ex_set(rec["id"], status="joined", direction=direction,
                  peer_id=rec["peer_id"], src_chat=-100, src_msg=10, replied=0)
    SENT.clear()
    asyncio.run(reply_joined(eng.db.ex_get(rec["id"])))
    body = SENT[-1] if SENT else ""
    check("partner_chan" not in body,
          "C3: reply_joined[%s] لینک طرف ندارد -> %r" % (direction, body))
    if direction == "out":
        check("@mychan" in body,
              "C3: پیام پیشقدم لینک خودم را دارد -> %r" % body)
print("DONE C3 reply_joined")


# ═══════ C4 — send_not_joined_reminder واقعی ═══════
a2 = src.find("    async def send_not_joined_reminder(rec):")
b2 = src.find("    # ---------- پیدا کردن کانال طرف ----------", a2)
assert a2 > 0 and b2 > a2
rem_ded = "\n".join(ln[4:] if ln.startswith("    ") else ln
                    for ln in src[a2:b2].splitlines())
SENT2 = []
class FakeClient2:
    async def send_message(self, chat, body, reply_to=None, link_preview=True):
        SENT2.append(body)
        return True
class CD2:
    def wait_for(self, rec_id):
        return 0
    def last_kind(self, rec_id):
        return ""
    async def action(self, kind, rec_id, fn):
        return await fn()
ns2 = {"eng": eng, "time": time, "asyncio": asyncio, "ex_cd": CD2(),
       "DRY_RUN": False, "client": FakeClient2()}
exec(rem_ded, ns2)
send_rem = ns2["send_not_joined_reminder"]

x["reply"] = True
x["msg_no"] = "نیومدی جان {channel}، بیا @mychan"
rec, _ = eng.db.ex_add(8200, "liar", "@partner_chan")
eng.db.ex_set(rec["id"], peer_id=8200, src_chat=11, src_msg=22,
              direction="in", claim_joined=0, reminders_total=0)
asyncio.run(send_rem(eng.db.ex_get(rec["id"])))
body = SENT2[-1] if SENT2 else ""
check("partner_chan" not in body, "C4: یادآور لینک طرف ندارد -> %r" % body)
check("@mychan" in body, "C4: لینک خودم در یادآور می‌ماند -> %r" % body)
print("DONE C4 reminder")


# ═══════ C5 — سناریوی دقیق مشتری + لبه‌های خطر ═══════

# C5-1: چرخه‌ی واقعی «تبادل سریع اول، متن سفارشی بعد» روی Engine واقعی.
# اول پیش‌فرض‌های ویزارد اعمال می‌شوند، بعد مشتری متن‌های خصمانه می‌سازد.
eng2 = fresh()
x2 = eng2.ex_cfg()
# همان منطق _ensure_quick_exchange_defaults: جای خالی را با پیش‌فرض ویزارد پر کن
for k, v in m.QUICK_EXCHANGE_DEFAULTS.items():
    if not str(x2.get(k) or "").strip():
        x2[k] = v
defaults_ok = all(x2.get(k) == v for k, v in m.QUICK_EXCHANGE_DEFAULTS.items())
check(defaults_ok, "C5: ویزارد تبادل سریع متن‌های پیش‌فرضِ بدون لینک طرف را می‌نشاند")
# خود پیش‌فرض‌ها هم نباید هیچ نشانی از لینک طرف داشته باشند
defaults_clean = all("{channel}" not in v and "t.me" not in v
                     and "joinchat" not in v for v in m.QUICK_EXCHANGE_DEFAULTS.values())
check(defaults_clean, "C5: هیچ‌کدام از متن‌های پیش‌فرض ویزارد لینک/توکن طرف ندارند")
hostile = {
    "msg_come": "بیا {channel} و @partner_chan و https://t.me/partner_chan",
    "msg_ok": "اوکی { Channel } شد t.me/partner_chan",
    "msg_no": ("نیومدی {CHANNEL}، لینک خصوصیش هم هست "
               "https://t.me/+Xy9Zx8Wv7654321 و joinchat/Xy9Zx8Wv7654321 بازم"),
    "msg_claim_no": "joinchat/Xy9Zx8Wv7654321 و +Xy9Zx8Wv7654321",
    "msg_wait": "صبر کن @partner_chan جان",
    "msg_nolink": "لینکت را بفرست",
}
x2.update(hostile)
priv_peer = "https://t.me/+Xy9Zx8Wv7654321"
# strip بر اساس یک مرجع کار می‌کند: رکورد دعوت خصوصی فقط املای همان hash
# را می‌تواند پاک کند (یوزرنیم دیگری در دسترس نیست) و برعکس.
for key, peer, banned in (
        ("msg_come", "@partner_chan", ("partner_chan",)),
        ("msg_ok", "@partner_chan", ("partner_chan",)),
        ("msg_no", priv_peer, ("Xy9Zx8Wv7654321",)),
        ("msg_claim_no", priv_peer, ("Xy9Zx8Wv7654321",)),
        ("msg_wait", "@partner_chan", ("partner_chan",))):
    out = eng2.ex_render(key, "Ali", peer)
    bad = (any(b in out for b in banned)
           or ("{channel" in out.lower().replace(" ", "")))
    check(not bad, "C5: چرخه‌ی ویزارد→متن سفارشی، %s تمیز است -> %r" % (key, out))
print("DONE C5 lifecycle")

# C5-2: امنیت زیررشته‌ای — توکن مستقلِ طرف برود ولی لینک خودم (که ممکن
# است پیشوندش مشابه باشد) دست‌نخورده بماند. یوزرنیم‌ها طول معتبر تلگرام دارند.
import re as _re
cases_sub = [
    ("@partner_chan", "@partner_chan_official", "لینک خودمِ بلندتر با پیشوند مشابه"),
    ("@abadgram", "@my_abadgram", "لینک خودم که رشته‌ی طرف را در دل دارد"),
    ("@abadgram", "@abadgram_shop", "یوزرنیم طرف در برابر خودمِ بلندتر"),
]
for peer, own, label in cases_sub:
    eng3 = fresh()
    eng3.st.prof("standard")["channel"] = own
    eng3.ex_cfg()["msg_come"] = f"بیا {own} را جوین شو، نه {peer}"
    out = eng3.ex_render("msg_come", "S", peer)
    standalone = _re.search(_re.escape(peer) + r"\b", out)
    check(own in out and not standalone,
          "C5 زیررشته: %s -> %r" % (label, out))
print("DONE C5 substring")

# C5-3: تکرار چندباره‌ی لینک طرف، همه باید بروند.
out = m.strip_peer_links("@partner_chan متن @partner_chan باز @partner_chan",
                         "@partner_chan")
check("partner_chan" not in out, "C5: هر سه تکرار لینک طرف حذف می‌شوند -> %r" % out)
# لینک با اسلش انتهایی و www
for s in ("https://www.t.me/partner_chan/",
          "https://telegram.me/partner_chan/",
          "t.me/partner_chan/"):
    out = m.strip_peer_links("متن " + s + " پایان", "@partner_chan")
    check("partner_chan" not in out, "C5: املای %r حذف شد -> %r" % (s, out))
print("DONE C5 repeats/spellings")

# C5-4: peer غیرقابل‌اعتماد (آیدی عددی/نامعتبر) → حذف ناامن انجام نشود و کرش نکند.
out = m.strip_peer_links("هر متن @partner_chan", "123456789")
check(out == "هر متن @partner_chan", "C5: آیدی عددی هرگز مبنای حذف متن نمی‌شود")
check(m.strip_peer_links("متنی", None) == "متنی", "C5: peer=None کرش نمی‌کند")
print("DONE C5 unsafe peer")

# C5-5: قفل سورسی — هر دو مسیر msg_wait حالا لینک طرف را پاس می‌دهند و
# fallback خطای ex_render هم مستقل strip می‌کند.
hits = [i for i in range(len(src)) if src.startswith('await say("msg_wait"', i)]
check(len(hits) >= 2 and all("say(\"msg_wait\", " in src[i:i + 120] for i in hits),
      "C5: هر دو فراخوانی msg_wait لینک شناخته‌شده‌ی طرف را برای strip پاس می‌دهند")
fb = src[src.index("def ex_render("):src.index("def ex_list_text")]
check("strip_peer_links(t, channel)" in fb,
      "C5: مسیر استثنای ex_render هم strip لینک طرف را تکرار می‌کند (نه متن خام)")
# هیچ مسیر گروهی‌ای نباید بدون ex_render متن بفرستد: سه send_message گروهی
# شناخته‌شده باید body متغیر رندرشده باشد، نه رشته‌ی خام حاوی لینک.
for marker in ('await client.send_message(chat, body, reply_to=mid',
               'return await event.reply(t)'):
    check(marker in src, "C5: مسیر ارسال گروهی از متن رندرشده استفاده می‌کند: " + marker)
print("DONE C5 source locks")

if FAILS:
    print("FAILED:", len(FAILS))
    for f in FAILS:
        print("  -", f)
    sys.exit(1)
print("DONE PASS")
"""


def reset():
    shutil.rmtree(ROOT, ignore_errors=True)
    os.makedirs(APP, exist_ok=True)
    os.makedirs(DATA, exist_ok=True)
    for f in ("95.py", "manager_82.py"):
        shutil.copy2(os.path.join(REPO, f), APP)


def run():
    env = dict(os.environ)
    env["DATA_DIR"] = DATA
    env["PORT"] = "8279"
    env["JAFJ_PORT"] = "8279"
    for k in ("RAILWAY_ENVIRONMENT", "RAILWAY_SERVICE_ID", "RAILWAY_PROJECT_ID",
              "RENDER", "RENDER_SERVICE_NAME", "JAFJ_HOSTED", "JAFJ_LOGIN_RETRY",
              "BOT_TOKEN", "API_ID", "API_HASH", "BACKUP_CHAT", "BACKUP_EVERY"):
        env.pop(k, None)
    p = subprocess.run([sys.executable, "-c", DRIVER], cwd=APP, env=env,
                       capture_output=True, text=True, timeout=300)
    return p.stdout, p.stderr, p.returncode


def main():
    print("--- custom exchange texts must never leak the partner link ---")
    reset()
    out, err, rc = run()
    if err.strip():
        print("--- driver stderr (tail) ---")
        print(err[-3000:])
    for line in out.splitlines():
        if line.startswith(("OK", "FAIL", "DONE", "FAILED", "  -")):
            print(line)
    if "DONE PASS" in out and "FAIL" not in out:
        print("ALL: PASS")
        return True
    print("ALL: FAIL")
    return False


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
