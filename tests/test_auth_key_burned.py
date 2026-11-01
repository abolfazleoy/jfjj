#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""«سشن سوخته» — همان چیزی که در پیامِ واقعیِ کاربر بود و «شبکه» گزارش شد.

متنِ واقعیِ لاگ:

    AuthKeyDuplicatedError: The authorization key (session file) was used
    under two different IP addresses simultaneously, and can no longer be
    used. ...

سه ایراد که این تست قفل می‌کند:

  ۱) الگوهای قدیمی فقط `AUTH_KEY_DUPLICATED` (با آندرلاین) را می‌شناختند و
     متنِ CamelCase تلگرام را نمی‌خواندند؛ پس `classify_selfbot_log` می‌رفت
     سرِ «شبکه» و پیامِ «به تلگرام وصل نمی‌شود» می‌داد — در حالی که کلید
     برای همیشه مرده بود.
  ۲) `95.py` روی همین خطا `retry` می‌زد؛ یعنی تا ابد با یک کلیدِ مرده وصل
     می‌شد و شکست می‌خورد. از بیرون: «۹۵.py اجرا نمی‌شود».
  ۳) مدیر سشنِ سوخته را قرنطینه نمی‌کرد؛ پس هر بوت/بازیابی دوباره از همان
     رشته‌ی مرده سشن می‌ساخت و حلقه تکرار می‌شد.
"""
import importlib.util
import os
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
FAILS = []

REAL_TAIL = (
    "⚠️ اتصال برای بررسیِ سشن: AuthKeyDuplicatedError: The authorization key "
    "(session file) was used under two different IP addresses simultaneously, "
    "and can no longer be used. Use the same session exclusively, or use "
    "different sessions (caused by InvokeWithLayerRequest("
    "InitConnectionRequest(GetConfigRequest)))"
)


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name
          + (f"   [{extra}]" if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def load95():
    spec = importlib.util.spec_from_file_location("sb95_burn", str(REPO / "95.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    root = Path(tempfile.mkdtemp(prefix="jafj_burn_"))
    here = os.getcwd()
    saved_data = os.environ.get("DATA_DIR")
    os.environ["DATA_DIR"] = str(root / "data")
    os.environ["PORT"] = "8366"
    os.environ["JAFJ_NO_IP_PROBE"] = "1"
    os.environ.pop("JAFJ_ONLY", None)
    try:
        sys.path.insert(0, str(REPO))
        import manager_82 as M

        # ── ۱) دسته‌بندی: متنِ واقعیِ تلگرام باید «keydup» شود، نه «network» ──
        kind, hint = M.classify_selfbot_log(REAL_TAIL, None)
        check("classify: متنِ واقعی AuthKeyDuplicated → keydup", kind == "keydup",
              kind)
        check("classify: توضیحش «دو IP» و «لاگین» را می‌گوید",
              ("دو IP" in hint) and ("لاگین" in hint), hint)
        for tail, rc in [("AUTH_KEY_DUPLICATED", None),
                         ("AuthKeyUnregisteredError: The key is not registered", None),
                         ("SessionRevokedError: the session was revoked", None),
                         ("", 77)]:
            k, _h = M.classify_selfbot_log(tail, rc)
            check(f"classify → keydup برای «{(tail or '')[:30]}» rc={rc}",
                  k == "keydup", k)

        # چیزهایی که نباید قاطی شوند
        k, _h = M.classify_selfbot_log("", 76)
        check("classify: کد ۷۶ همچنان «dup» است (سشن سالم)", k == "dup", k)
        k, _h = M.classify_selfbot_log(
            "⛔ نسخه‌ی دیگری از همین اکانت همین حالا در حال اجراست", None)
        check("classify: پیامِ نسخه‌ی تکراری همچنان «dup» است", k == "dup", k)
        k, _h = M.classify_selfbot_log(
            "🔄 اتصال قطع شد — 10 ثانیه دیگر دوباره وصل می‌شوم…", None)
        check("classify: قطعِ ساده‌ی اتصال همچنان «network» است", k == "network", k)
        k, _h = M.classify_selfbot_log("", 79)
        check("classify: کد ۷۹ → network (شبکه‌ی میزبان بسته است)", k == "network", k)

        # ── ۲) متنِ پیامِ مشتری ──
        body = M.selfbot_failure_notice("acc", 8843731884, "keydup",
                                        "کلید باطل شد", REAL_TAIL)
        check("پیام: «سوزانده»/AuthKeyDuplicated را می‌گوید",
              ("AuthKeyDuplicated" in body) or ("سوزانده" in body), body[-300:])
        check("پیام: «دو IP» را می‌گوید", "دو IP" in body, body[-300:])
        check("پیام: راهِ حل = لاگینِ دوباره", "دوباره لاگین" in body,
              body[-300:])
        check("پیام: نمی‌گوید «سشن سالم است»", "سالم است" not in body,
              body[-300:])
        check("پیام: HTML امن است", "&lt;" not in body.split("🔎")[0])

        # ── ۳) ۹۵.py: تشخیص + کدهای خروج ──
        SB = load95()
        check("95.py: AuthKeyDuplicatedError شناسایی می‌شود",
              SB.is_burned_key_error("AuthKeyDuplicatedError", "x") is True)
        check("95.py: متنِ «two different IP addresses» شناسایی می‌شود",
              SB.is_burned_key_error("RPCError", REAL_TAIL) is True)
        check("95.py: خطای شبکه اشتباهاً «سوخته» شمرده نمی‌شود",
              SB.is_burned_key_error("ConnectionError",
                                     "Connection to Telegram failed 3 times") is False)
        check("95.py: کدِ خروجِ ۷۷ برای کلیدِ سوخته",
              SB.EXIT_KEY_BURNED == 77)
        check("95.py: کدهای ۷۶/۷۸/۷۹ سرِ جایشان هستند",
              (SB.EXIT_DUP, SB.EXIT_NEEDS_RELOGIN, SB.EXIT_NET_DEAD) == (76, 78, 79))
        src = (REPO / "95.py").read_text(encoding="utf-8")
        check("95.py: connect_and_run روی کلیدِ سوخته «key_burned» می‌دهد",
              'return "key_burned"' in src)
        check("95.py: run_bot با EXIT_KEY_BURNED خارج می‌شود (retry نمی‌کند)",
              "return EXIT_KEY_BURNED" in src)
        check("95.py: بعد از اتصالِ موفق «lost» برمی‌گردد نه «retry»",
              'return "lost"' in src)
        check("95.py: شمارنده‌ی شکستِ پشتِ‌سرهم دارد",
              "max_fails" in src and "EXIT_NET_DEAD" in src)
        check("95.py: IPِ خروجی در لاگ ثبت می‌شود",
              "log_egress_ip()" in src and "jafj_ip.txt" in src)
        check("95.py: با JAFJ_NO_IP_PROBE کاوش نمی‌کند",
              SB.egress_ip() is None)

        # ── ۴) مدیر: کد ۷۷ → سشن قرنطینه، لاگین لازم، امتیاز کسر نشود ──
        sup = M.Supervisor(M.Config(), M.DB())
        uid = 8843731884
        folder = Path(sup.folder(uid))
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "jafj.session").write_bytes(b"dead-key")
        (folder / "jafj_creds.json").write_text("{}", encoding="utf-8")
        sup.db.x("INSERT OR IGNORE INTO clients(uid, status, created_at, session)"
                 " VALUES(?,?,?,?)",
                 (uid, "active", int(time.time()), "s" * 40), None)
        sup.db.set(uid, want_on=1, need_login=0)

        burned_self = root / "burned_95.py"
        burned_self.write_text(
            "import sys\n"
            "print('⚠️ اتصال برای بررسیِ سشن: AuthKeyDuplicatedError: The "
            "authorization key (session file) was used under two different IP "
            "addresses simultaneously')\n"
            "sys.exit(77)\n", encoding="utf-8")
        old_self = M.SELFBOT
        M.SELFBOT = str(burned_self)
        sup._session_ok_or_mark = lambda u: (True, "")
        sup.sync_selfbot = lambda u: (True, "")
        ok, msg = sup.start(uid)
        M.SELFBOT = old_self

        check("start با کد ۷۷ → False", ok is False)
        check("start با کد ۷۷ → نوعِ session (امتیاز کسر نمی‌شود)",
              sup.last_failure.get(uid) == "session", sup.last_failure.get(uid))
        check("start با کد ۷۷ → پیام «باطل»/AuthKeyDuplicated دارد",
              ("باطل" in msg) and ("لاگین" in msg), msg[:300])
        check("start با کد ۷۷ → سشن قرنطینه شد (jafj.session → .bad)",
              (folder / "jafj.session.bad").exists()
              and not (folder / "jafj.session").exists())
        row = sup.db.get(uid) or {}
        check("start با کد ۷۷ → need_login=1", bool(row.get("need_login")),
              row.get("need_login"))
        check("start با کد ۷۷ → want_on=0 (watchdog دوباره اجرا نکند)",
              not bool(row.get("want_on")), row.get("want_on"))
        check("start با کد ۷۷ → رشته‌ی سشنِ مرده از DB پاک شد",
              not (row.get("session") or ""), (row.get("session") or "")[:20])
        wanted = [r["uid"] for r in sup.db.wanted()]
        check("start با کد ۷۷ → اکانت دیگر در لیستِ «باید روشن باشد» نیست",
              uid not in wanted, wanted)

        # verify_session هم دوباره از رشته‌ی مرده سشن نمی‌سازد
        ok_v, why_v = sup.verify_session(uid)
        check("verify_session بعد از سوختن → آماده نیست", ok_v is False, why_v)
        check("verify_session فایلِ سشن نمی‌سازد (بازسازی از رشته‌ی مرده ممنوع)",
              not (folder / "jafj.session").exists())
    finally:
        os.chdir(here)
        if saved_data is None:
            os.environ.pop("DATA_DIR", None)
        else:
            os.environ["DATA_DIR"] = saved_data
        os.environ.pop("JAFJ_NO_IP_PROBE", None)
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
