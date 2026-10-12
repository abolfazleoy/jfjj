#!/usr/bin/env python3
"""تست بک‌آپ هوشمند (فقط با ثبت اطلاعات جدید + دکمه‌ی «📦 بک‌آپ» در پنل مدیر)
و سیستم قوانین در ابتدای ربات («📜 قوانین ربات» + ویرایش متن قوانین و متن‌های ربات).
"""
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap

ROOT = os.path.join(tempfile.gettempdir(), "jafj_rules_backup_test")
APP = os.path.join(ROOT, "app")
DATA = os.path.join(ROOT, "data")
SRC_REPO = os.environ.get("REPO", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FAKE_TELETHON = textwrap.dedent('''
    class TelegramClient:
        def __init__(self, session, api_id, api_hash, **kw):
            pass
        async def connect(self):
            return
        async def is_user_authorized(self):
            return True
        async def start(self, bot_token=None):
            return self
        async def disconnect(self):
            return
        async def get_me(self):
            class U:
                username = "fakebot"
                id = 1
            return U()
        def on(self, *a, **k):
            def deco(fn):
                return fn
            return deco
        async def run_until_disconnected(self):
            return
        async def send_message(self, *a, **k):
            class R:
                id = 1
            return R()
        async def get_entity(self, x):
            class E:
                username = None
            return E()
        async def send_file(self, *a, **k):
            class R:
                id = 10
                document = True
            return R()
        async def edit_message(self, *a, **k):
            class R:
                id = 10
                document = True
            return R()
        async def forward_messages(self, *a, **k):
            return None
        async def get_messages(self, *a, **k):
            return []
        def iter_messages(self, *a, **k):
            async def _gen():
                return
                yield
            return _gen()
        async def download_media(self, *a, **k):
            return None

    class Button:
        @staticmethod
        def inline(*a, **k):
            return ("inline", a, k)
        @staticmethod
        def url(*a, **k):
            return ("url", a, k)
        @staticmethod
        def request_phone(*a, **k):
            return ("phone", a, k)
        @staticmethod
        def text(*a, **k):
            return ("text", a, k)
        @staticmethod
        def clear(*a, **k):
            return None

    class events:
        class NewMessage:
            def __init__(self, *a, **k):
                pass
        class CallbackQuery:
            def __init__(self, *a, **k):
                pass

    class _Err(Exception):
        pass
    FloodWaitError = _Err
    PhoneNumberBannedError = _Err
    PhoneNumberInvalidError = _Err
    SessionPasswordNeededError = _Err
    PhoneCodeInvalidError = _Err
    PhoneCodeExpiredError = _Err
    UserNotParticipantError = _Err
''')

FAKE_SESSIONS = textwrap.dedent('''
    class StringSession:
        def __init__(self, s=""):
            self._s = s or ""
            self.dc_id = 1
            self.server_address = "127.0.0.1"
            self.port = 443
            self.auth_key = b"fake-auth-key-1234567890"
        def save(self):
            return self._s

    class SQLiteSession:
        def __init__(self, *a, **k):
            pass
        def set_dc(self, *a, **k):
            pass
        def save(self):
            pass
        def close(self):
            pass
''')

FAKE_ERRORS = textwrap.dedent('''
    class FloodWaitError(Exception):
        def __init__(self, seconds=0, *a, **k):
            super().__init__(f"FloodWait {seconds}")
            self.seconds = int(seconds or 0)
    class PhoneNumberBannedError(Exception):
        pass
    class PhoneNumberInvalidError(Exception):
        pass
    class SessionPasswordNeededError(Exception):
        pass
    class PhoneCodeInvalidError(Exception):
        pass
    class PhoneCodeExpiredError(Exception):
        pass
    class UserNotParticipantError(Exception):
        pass
''')

INNER = textwrap.dedent('''
    import os, sys, json, asyncio, time, datetime, shutil
    sys.path.insert(0, os.getcwd())
    import manager_82 as M

    ADMIN = 100
    USER1 = 201
    USER2 = 202
    results = []

    def check(cond, name):
        results.append((name, bool(cond)))

    def btn_datas(kb):
        out = []
        for row in (kb or []):
            for b in row:
                try:
                    d = b[1][1] if isinstance(b, tuple) else None
                except Exception:
                    d = None
                if isinstance(d, (bytes, bytearray)):
                    out.append(d.decode("utf-8", "ignore"))
        return out

    class FakeSentMsg:
        def __init__(self, mid, caption="", fpath=""):
            self.id = mid
            self.caption = caption
            self.text = ""
            self.document = True
            self.media = True
            self._fpath = fpath
            self.sender_id = 1

    class FakeBot:
        def __init__(self):
            self.text_sends = []
            self.files = []
            self.stored_msgs = {}
            self.iter_raises = False
            self.handlers = []
            self._next_id = 50
        def on(self, *a, **k):
            def deco(fn):
                self.handlers.append(fn)
                return fn
            return deco
        async def get_me(self):
            class U:
                username = "fakebot"
                id = 1
            return U()
        async def get_entity(self, x):
            class E:
                id = int(x) if str(x).lstrip("-").isdigit() else 100
                username = None
                public = False
            return E()
        async def send_message(self, uid, message=None, **kw):
            self.text_sends.append((uid, message, kw))
            class R:
                id = 1
            return R()
        async def send_file(self, uid, file=None, caption=None, **kw):
            self._next_id += 1
            cp = os.path.join(os.environ["DATA_DIR"], f"sent_{self._next_id}.zip")
            if isinstance(file, str) and os.path.isfile(file):
                shutil.copy2(file, cp)
            m = FakeSentMsg(self._next_id, caption or "", cp)
            self.files.append((uid, cp, caption, kw))
            self.stored_msgs[m.id] = m
            return m
        async def edit_message(self, target, mid, caption, file=None, **kw):
            cp = os.path.join(os.environ["DATA_DIR"], f"edit_{mid}.zip")
            if isinstance(file, str) and os.path.isfile(file):
                shutil.copy2(file, cp)
            m = FakeSentMsg(mid, caption or "", cp)
            self.stored_msgs[mid] = m
            self.files.append((target, cp, caption, kw))
            return m
        async def get_messages(self, chat, ids=None):
            if isinstance(ids, list):
                return [self.stored_msgs.get(int(i)) for i in ids]
            return self.stored_msgs.get(int(ids))
        def iter_messages(self, target, limit=50):
            if self.iter_raises:
                raise RuntimeError("BotMethodInvalidError: GetHistoryRequest")
            items = list(self.stored_msgs.values())[::-1][:limit]
            async def _gen():
                for x in items:
                    yield x
            return _gen()
        async def download_media(self, msg, file=None):
            fp = getattr(msg, "_fpath", None)
            if fp and file and os.path.isfile(fp):
                shutil.copy2(fp, file)
                return file
            return fp

    class FakeCbEv:
        def __init__(self, uid, data):
            self.sender_id = uid
            self.chat_id = uid
            self.data = data.encode()
            self.message_id = 777
            self.answers = []
            self.edits = []
        async def answer(self, t=""):
            self.answers.append(t)
        async def edit(self, text, parse_mode=None, buttons=None,
                       link_preview=False, **kw):
            self.edits.append((text, buttons))
            return True

    class FakeMsgEv:
        def __init__(self, uid, mid, raw_text="", document=None, fpath=None):
            self.sender_id = uid
            self.chat_id = uid
            self.id = mid
            self.raw_text = raw_text
            self.photo = None
            self.document = document
            self.grouped_id = None
            self.video = self.gif = self.voice = None
            self.audio = self.sticker = self.contact = None
            self.media = document
            self.is_private = True
            self._fpath = fpath
            self.file = type("F", (), {"name": "jafj_backup.zip"})() if document else None
            self.message = type("M", (), {
                "date": datetime.datetime.now(),
                "contact": None, "media": document,
                "document": document, "file": self.file,
                "_fpath": fpath, "message": raw_text})()
        async def get_sender(self):
            class S:
                username = "user"
                first_name = "کاربر"
            return S()

    async def main():
        src = open("manager_82.py", encoding="utf-8").read()
        real_time = time.time
        fake_now = [real_time()]
        time.time = lambda: fake_now[0]

        m = M.Manager()
        bot = FakeBot()
        m.bot = bot
        m.cfg["admin_ids"] = [ADMIN]

        # Extract real NewMessage handler
        block_start = src.index("@self.bot.on(events.NewMessage(incoming=True))")
        block_end = src.index("@self.bot.on(events.CallbackQuery)")
        raw_lines = src[block_start:block_end].split("\\n")
        handler_block = "\\n".join(
            raw_lines[0] if i == 0 else
            (raw_lines[i][8:] if raw_lines[i].startswith(" " * 8) else raw_lines[i])
            for i in range(len(raw_lines)))
        ns = dict(vars(M))
        ns["self"] = m
        ns["events"] = type("E", (), {"NewMessage": type("NM", (), {"__init__": lambda s, *a, **k: None})})
        exec(compile(handler_block, "<newmessage-handler>", "exec"), ns)
        handler = bot.handlers[-1]

        async def cb(uid, data):
            fake_now[0] += 5
            ev = FakeCbEv(uid, data)
            await m.on_callback(ev)
            return ev

        # ═══ 1. قوانین در ابتدای ربات (/start) ═══
        check("a:rules" in btn_datas(M.admin_menu()), "admin_menu has 📜 قوانین ربات button")
        check("m:rules" in btn_datas(M.main_menu()), "main_menu has 📜 قوانین ربات button")
        check(m.rules_on() is True, "rules_on is True by default")

        # کاربر جدید /start می‌زند -> اول قوانین می‌آید، نه منوی اصلی
        fake_now[0] += 5
        bot.text_sends.clear()
        await m.user_cmd(USER1, USER1, "start", "", {"username": "u1", "name": "امیر"})
        check(len(bot.text_sends) == 1, "new user /start sends 1 message")
        first_txt, first_kw = bot.text_sends[-1][1], bot.text_sends[-1][2]
        check("قوانین و مقررات" in first_txt, "/start shows rules first")
        check("rules:accept" in btn_datas(first_kw.get("buttons")),
              "rules screen has rules:accept button")
        check(m.rules_required(USER1) is True, "USER1 must accept rules before using bot")

        # تا وقتی قوانین را تایید نکرده، زدن دکمه‌های دیگر باز قوانین را نشان می‌دهد
        ev_premature = await cb(USER1, "s:setup")
        check("قوانین و مقررات" in ev_premature.edits[-1][0]
              and "rules:accept" in btn_datas(ev_premature.edits[-1][1]),
              "clicking s:setup before accepting rules shows rules gate")

        # کاربر روی دکمه پذیرش قوانین می‌زند -> منوی اصلی باز می‌شود
        ev_acc = await cb(USER1, "rules:accept")
        check(m.rules_required(USER1) is False and m.rules_accepted(USER1) is True,
              "clicking rules:accept marks rules_accepted=1")
        check("امیر" in ev_acc.edits[-1][0] and "s:setup" in btn_datas(ev_acc.edits[-1][1]),
              "after accepting rules, main menu opens immediately")

        # حالا اگر دوباره /start بزند، مستقیم منوی اصلی می‌آید
        fake_now[0] += 5
        bot.text_sends.clear()
        await m.user_cmd(USER1, USER1, "start", "", {"username": "u1", "name": "امیر"})
        check("قوانین و مقررات" not in bot.text_sends[-1][1]
              and "s:setup" in btn_datas(bot.text_sends[-1][2].get("buttons")),
              "second /start after accepting goes straight to main menu")

        # ═══ 2. تغییر متن قوانین و دکمه تایید در پنل مدیر ═══
        ev_r = await cb(ADMIN, "a:rules")
        r_datas = btn_datas(ev_r.edits[-1][1])
        check("a:rules:edit" in r_datas and "a:rules:tog" in r_datas
              and "a:rules:btn" in r_datas and "a:rules:reset" in r_datas,
              "admin rules screen has edit, toggle, button-text, and reset controls")

        ev_re = await cb(ADMIN, "a:rules:edit")
        check((m.fsm.get(ADMIN) or {}).get("step") == "rules_set",
              "a:rules:edit starts rules_set step")
        fake_now[0] += 5
        await handler(FakeMsgEv(ADMIN, 801, "قانون جدید ۱: رعایت ادب\\nقانون جدید ۲: عدم اسپم"))
        check("قانون جدید ۱" in m.cfg["rules_text"], "new rules_text saved in cfg")
        check(m.rules_required(USER1) is True,
              "changing rules text resets rules_accepted so users see the updated rules")

        # تغییر متن دکمه تایید قوانین
        await cb(ADMIN, "a:rules:btn")
        fake_now[0] += 5
        await handler(FakeMsgEv(ADMIN, 802, "✅ با قوانین موافقم"))
        check(m.rules_btn_label() == "✅ با قوانین موافقم", "custom rules accept button saved")

        # کاربر قوانین جدید را می‌بیند و تایید می‌کند
        ev_u1 = await cb(USER1, "m:home")
        check("قانون جدید ۱" in ev_u1.edits[-1][0], "user sees updated rules text")
        await cb(USER1, "rules:accept")
        check(m.rules_accepted(USER1) is True, "user accepted updated rules")

        # ═══ 3. بک‌آپ فقط در صورت ثبت اطلاعات جدید + دکمه «📦 بک‌آپ» در پنل مدیر ═══
        # شبیه‌سازی ربات واقعی تلگرام که در آن iter_messages خطای BotMethodInvalid می‌دهد
        bot.iter_raises = True
        bot.files.clear()
        ok1, msg1 = await m.backup_once(force=True)
        check(ok1 is True and len(bot.files) >= 1, "initial backup sent")
        files_after_first = len(bot.files)

        # شبیه‌سازی تغییراتِ لحظه‌ایِ بدون تغییر اطلاعات جدید:
        # 1) wal_checkpoint روی دیتابیس‌ها
        m.db.c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        m.shop.c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        # 2) فایل‌های لحظه‌ای سلف (jafj_status.json، jafj.session، jafj.db)
        f_u1 = m.sup.folder(USER1)
        with open(os.path.join(f_u1, "jafj_status.json"), "w", encoding="utf-8") as f:
            json.dump({"ts": int(time.time()) + 999, "uptime": 123}, f)
        with open(os.path.join(f_u1, "jafj.session"), "wb") as f:
            f.write(b"sqlite-session-ping-" + os.urandom(16))
        with open(os.path.join(f_u1, "jafj.db"), "wb") as f:
            f.write(b"client-db-timer-tick-" + os.urandom(16))

        ok2, msg2 = await m.backup_once(force=False)
        check(ok2 is False and "بدون تغییر" in msg2 and len(bot.files) == files_after_first,
              "no false backup when only status/session/wal_checkpoint changed")

        # حالا اطلاعات جدید ثبت می‌شود (مشتری جدید) -> بک‌آپ خودکار باید بگیرد!
        m.db.add(USER2, "u2", "کاربر جدید", 0)
        ok3, msg3 = await m.backup_once(force=False)
        check(ok3 is True and len(bot.files) > files_after_first,
              "auto backup triggers immediately when new client data is registered")

        # دکمه «📦 بک‌آپ» در پنل مدیر فایل zip را مستقیماً به مدیر می‌دهد
        before_dl = len(bot.files)
        ev_bk = await cb(ADMIN, "a:backup")
        check(len(bot.files) > before_dl,
              "pressing a:backup in admin panel sends zip file to admin")
        bk_datas = btn_datas(ev_bk.edits[-1][1])
        check("a:backup:dl" in bk_datas and "a:backup:auto" in bk_datas
              and "a:restore" in bk_datas,
              "backup screen offers download, auto-backup toggle, and restore")

        # خاموش کردن بک‌آپ خودکار از پنل مدیر
        await cb(ADMIN, "a:backup:auto")
        check(m.cfg["auto_backup_on"] is False, "a:backup:auto toggles auto_backup_on off")
        m.db.log(ADMIN, "another_change", "test")
        ok4, msg4 = await m.backup_once(force=False)
        check(ok4 is False, "when auto_backup_on is False, background backup_once does not send")
        await cb(ADMIN, "a:backup:auto")
        check(m.cfg["auto_backup_on"] is True, "a:backup:auto toggles auto_backup_on back on")

        # ارسال فایل بک‌آپ توسط مدیر به خود ربات -> ذخیره + دکمه بازیابی
        latest_zip = os.path.join(M.BASE_DIR, "jafj_backup_latest.zip")
        fake_now[0] += 5
        bot.text_sends.clear()
        took = await m.accept_admin_backup_file(
            FakeMsgEv(ADMIN, 850, "", document=True, fpath=latest_zip))
        check(took is True and len(bot.text_sends) == 1,
              "bot accepts backup zip sent by admin")
        check("a:restore" in btn_datas(bot.text_sends[-1][2].get("buttons")),
              "backup file acceptance message includes one-click ♻️ بازیابی button")

    asyncio.run(main())
    for name, ok in results:
        print(f"CHECK {'PASS' if ok else 'FAIL'} - {name}")
    bad = [name for name, ok in results if not ok]
    print("RULES_BACKUP_RESULT", "PASS" if not bad else "FAIL")
''')


def reset():
    shutil.rmtree(ROOT, ignore_errors=True)
    os.makedirs(APP, exist_ok=True)
    os.makedirs(DATA, exist_ok=True)
    for f in ("manager_82.py", "95.py"):
        shutil.copy2(os.path.join(SRC_REPO, f), APP)
    tel = os.path.join(APP, "telethon")
    os.makedirs(tel, exist_ok=True)
    with open(os.path.join(tel, "__init__.py"), "w", encoding="utf-8") as f:
        f.write(FAKE_TELETHON)
    with open(os.path.join(tel, "sessions.py"), "w", encoding="utf-8") as f:
        f.write(FAKE_SESSIONS)
    with open(os.path.join(tel, "errors.py"), "w", encoding="utf-8") as f:
        f.write(FAKE_ERRORS)


def main():
    reset()
    env = dict(os.environ)
    env["DATA_DIR"] = DATA
    env["PORT"] = "8195"
    for k in ("BACKUP_CHAT", "BACKUP_EVERY", "BOT_TOKEN", "API_ID", "API_HASH", "ADMIN_IDS"):
        env.pop(k, None)
    p = subprocess.run([sys.executable, "-c", INNER], cwd=APP, env=env,
                       capture_output=True, text=True, timeout=120)
    out = p.stdout + p.stderr
    print("\n".join(ln for ln in out.splitlines() if ln.startswith(("CHECK", "RULES_BACKUP_RESULT"))) or out[-3000:])
    good = "RULES_BACKUP_RESULT PASS" in out
    if not good:
        print(out[-4000:])
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())
