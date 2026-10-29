#!/usr/bin/env python3
"""افزودن/حذفِ دانه‌دانه‌ی محتوای آموزش‌ها — بدون «ریست» و از‌دست‌رفتن قبلی‌ها.

قفل کردن این رفتار:

  1. «➕ افزودن به محتوا» (a:tut_add / a:sec_add:<id>) محتوای قبلی را سرِ جایش
     نگه می‌دارد و پیام‌های تازه را به <b>آخرِ</b> لیست اضافه می‌کند؛ یعنی فردا
     می‌شود ویدیوی دوم را پشت ویدیوی اول پیوند زد بدون پاک‌کردن چیزی.
  2. «📤 ثبت / تغییر محتوا (جایگزینی)» همان رفتار قدیمی است: کل لیست عوض
     می‌شود (و موقع باز شدن هشدار می‌دهد که چند پیام جایگزین می‌شود).
  3. «📦 مدیریت محتوا» فهرستِ دانه‌دانه می‌دهد (ویدیو/متن/ویس/عکس/فایل…) و
     هر آیتم جدا با «🗑 حذف n» پاک می‌شود؛ «🗑 پاک‌کردن همه» یک‌جا همه را
     برمی‌دارد. شماره‌ها با چیزی که واقعاً برای کاربر می‌رود یکی است، حتی
     اگر بعضی پیام‌های منبع در تلگرام پاک شده باشند.
  4. افزودن از چتِ دیگری که محتوای قبلی آن‌جا ثبت شده رد می‌شود (یک لیستِ
     پیام فقط یک چتِ منبع دارد) — بدون اینکه محتوای قبلی دست بخورد.
  5. این رفتار هم برای «🎬 آموزش فعال‌سازی» اصلی هست و هم برای هر «🧩 بخش
     آموزش» (متن، ویدیو، ویس، عکس… فرقی ندارد).

روش اجرا مثل بقیه‌ی تست‌ها: سورس واقعی manager_82 با telethon قلابی و
دیتابیس واقعی (فایلی) ران می‌شود؛ هندلر NewMessage و on_callback هم از
همان سورس استخراج و مستقیم صدا زده می‌شوند.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap

ROOT = os.path.join(tempfile.gettempdir(), "jafj_tut_append_run")
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
            return None
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
    import os, sys, json, asyncio, time, datetime
    sys.path.insert(0, os.getcwd())
    import manager_82 as M

    ADMIN = 100
    USER = 200
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

    def btn_texts(kb):
        out = []
        for row in (kb or []):
            for b in row:
                try:
                    out.append(b[1][0])
                except Exception:
                    pass
        return out

    def label_lens(kb):
        return [len(b[1][0]) for row in (kb or []) for b in row
                if isinstance(b, tuple)]

    def all_bytes(kb):
        """همه‌ی داده‌های دکمه به‌صورت bytes (برای تستِ سقف ۶۴ بایت تلگرام)."""
        out = []
        for row in (kb or []):
            for b in row:
                try:
                    d = b[1][1]
                except Exception:
                    d = None
                if isinstance(d, (bytes, bytearray)):
                    out.append(d)
        return out

    class FakeMsg:
        """پیامِ ذخیره‌شده در چتِ مرجع (برای _tut_load / _tut_items)."""
        def __init__(self, mid, raw_text="", media=None, grouped_id=None, **flags):
            self.id = mid
            self.raw_text = raw_text
            self.media = media
            self.grouped_id = grouped_id
            self.entities = []
            self.photo = flags.get("photo")
            self.video = flags.get("video")
            self.gif = flags.get("gif")
            self.voice = flags.get("voice")
            self.audio = flags.get("audio")
            self.sticker = flags.get("sticker")
            self.document = flags.get("document")
            self.contact = flags.get("contact")

    class FakeBot:
        def __init__(self):
            self.msg_sends = []
            self.text_sends = []
            self.files = []
            self.forwards = []
            self.msgs = {}
            self.handlers = []
        def on(self, *a, **k):
            def deco(fn):
                self.handlers.append(fn)
                return fn
            return deco
        async def get_messages(self, chat, ids=None):
            store = self.msgs.get(chat, {})
            return [store.get(i) for i in (ids or [])]
        async def send_message(self, uid, message=None, **kw):
            if hasattr(message, "id") and hasattr(message, "media"):
                self.msg_sends.append((uid, message, kw))
                return None
            self.text_sends.append((uid, message, kw))
            return None
        async def send_file(self, uid, file=None, caption=None, **kw):
            self.files.append((uid, file, caption, kw))
            return None
        async def forward_messages(self, uid, ids=None, from_peer=None, **kw):
            self.forwards.append((uid, ids, from_peer))
            return None

    class FakeMsgEv:
        def __init__(self, uid, mid, raw_text="", photo=None, document=None,
                     video=None, voice=None, grouped_id=None, chat_id=None):
            self.sender_id = uid
            self.chat_id = chat_id if chat_id is not None else uid
            self.id = mid
            self.raw_text = raw_text
            self.photo = photo
            self.document = document
            self.video = video
            self.voice = voice
            self.grouped_id = grouped_id
            self.gif = self.audio = self.sticker = self.contact = None
            self.media = photo or document or video or voice
            self.is_private = True
            self.message = type("M", (), {
                "date": datetime.datetime.now(),
                "contact": None, "media": None})()
        async def get_sender(self):
            class S:
                username = "admin"
                first_name = "ادمین"
            return S()

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

    async def main():
        src = open("manager_82.py", encoding="utf-8").read()

        # ---------- 0) سیم‌کشی سورس ----------
        check("def tut_capture_start(" in src, "append/replace capture helper exists")
        check('"mode": mode' in src, "capture remembers its mode (append/replace)")
        check('k == "tut_add"' in src, "a:tut_add route exists (main tutorial)")
        check('k.startswith("sec_add:")' in src, "a:sec_add:<id> route exists")
        check('k == "tut_items"' in src and 'k.startswith("sec_items:")' in src,
              "content-management pages exist for both scopes")
        check('k.startswith("tut_di:")' in src and 'k.startswith("sec_di:")' in src,
              "per-item delete routes exist")
        check('k == "tut_dall"' in src and 'k.startswith("sec_dall:")' in src,
              "delete-all routes exist")
        check("async def _tut_items(" in src, "indexed content loader exists")
        check("def tut_content_del(" in src and "def tut_content_clear(" in src,
              "delete helpers exist")
        check('"a:tut_add"' in src and '"a:sec_add:"' in src
              and '"a:sec_set:"' in src,
              "capture buttons survive fsm cleanup (mode switch does not wipe)")

        # ---------- Manager واقعی + ربات قلابی ----------
        real_time = time.time
        fake_now = [real_time()]
        time.time = lambda: fake_now[0]

        m = M.Manager()
        bot = FakeBot()
        m.bot = bot
        m.cfg["admin_ids"] = [ADMIN]

        block_start = src.index("@self.bot.on(events.NewMessage(incoming=True))")
        block_end = src.index("@self.bot.on(events.CallbackQuery)")
        raw_lines = src[block_start:block_end].split("\\n")
        handler_block = "\\n".join(
            raw_lines[0] if i == 0 else
            (raw_lines[i][8:] if raw_lines[i].startswith(" " * 8) else raw_lines[i])
            for i in range(len(raw_lines)))
        ns = dict(vars(M))
        ns["self"] = m
        ns["events"] = type('E', (), {'NewMessage': type('NM', (), {'__init__': lambda s, *a, **k: None})})
        exec(compile(handler_block, "<newmessage-handler>", "exec"), ns)
        handler = bot.handlers[-1]

        async def cb(data, uid=ADMIN):
            fake_now[0] += 5
            ev = FakeCbEv(uid, data)
            await m.on_callback(ev)
            return ev

        async def send(mid, text="", **flags):
            fake_now[0] += 5
            await handler(FakeMsgEv(ADMIN, mid, text, **flags))

        # ---------- 1) بخش: ثبت ویدیوی اول (حالتِ جایگزینی، مثل قبل) ----------
        sec = m.tut_new("آموزش بعد از فعال‌سازی")
        sid = sec["id"]
        await cb(f"a:sec_set:{sid}")
        check(m.fsm[ADMIN]["step"] == "sec_set"
              and (m.fsm[ADMIN].get("mode") or "replace") == "replace"
              and m.fsm[ADMIN]["tut_pending"] == [],
              "a:sec_set opens an empty (replace) capture")
        await send(601, "ویدیو اول", video=("doc", "v1"))
        await cb(f"a:sec_done:{sid}")
        check(m.tut_find(sid)["ids"] == [601], "first video saved")

        # ---------- 2) فردا: ویدیوی دوم پشتِ اولی (بدون ریست) ----------
        fake_now[0] += 86400                      # یک روز بعد
        ev = await cb(f"a:sec:{sid}")
        datas = btn_datas(ev.edits[-1][1])
        check(f"a:sec_add:{sid}" in datas,
              "section page offers ➕ افزودن به محتوا once content exists")
        check(f"a:sec_set:{sid}" in datas and f"a:sec_items:{sid}" in datas,
              "section page still offers replace + content management")
        check(any("جایگزینی" in t for t in btn_texts(ev.edits[-1][1])),
              "replace button says it replaces")
        check(all(len(d) <= 64 for d in all_bytes(ev.edits[-1][1])),
              "all callback data within Telegram's 64-byte limit")

        await cb(f"a:sec_add:{sid}")
        st = m.fsm.get(ADMIN) or {}
        check(st.get("step") == "sec_set" and st.get("mode") == "append"
              and st.get("tut_pending") == [601],
              "append mode pre-loads existing content (old video kept)")
        await send(701, "ویدیو دوم", video=("doc", "v2"))
        conf = [t for u, t, _ in bot.text_sends if u == ADMIN]
        check(any("مجموع: 2 پیام" in (t or "") for t in conf),
              "capture confirmation counts old + new")
        await cb(f"a:sec_done:{sid}")
        s = m.tut_find(sid)
        check(s["ids"] == [601, 701], "second video appended after the first")
        check(s["chat"] == ADMIN, "source chat kept")
        with open(M.CONFIG_FILE, encoding="utf-8") as f:
            saved = json.load(f)
        check(saved["tut_sections"][0]["ids"] == [601, 701],
              "appended content persisted (restart-safe)")

        # ترتیبِ ارسال برای کاربر: اول ویدیوی قدیمی، بعد تازه
        bot.msgs[ADMIN] = {
            601: FakeMsg(601, "ویدیو اول", media=("doc", "v1"), video=True),
            701: FakeMsg(701, "ویدیو دوم", media=("doc", "v2"), video=True),
            801: FakeMsg(801, "متن خوش‌آمد"),
            901: FakeMsg(901, "ویس مدیر", media=("doc", "voice"), voice=True),
        }
        fake_now[0] += 5
        bot.msg_sends = []
        await m.tut_send_section(USER, sid, force=True)
        order = [x[1].id for x in bot.msg_sends if x[0] == USER]
        check(order == [601, 701], "user gets old video first, new one after it")

        # ---------- 3) جایگزینی: همان رفتار قدیمی (هشدار هم می‌دهد) ----------
        ev = await cb(f"a:sec_set:{sid}")
        txt = ev.edits[-1][0]
        check("جایگزین" in txt and "افزودن به محتوا" in txt,
              "replace prompt warns that old content will be replaced")
        check(m.fsm[ADMIN].get("mode") == "replace"
              and m.fsm[ADMIN]["tut_pending"] == [],
              "replace capture starts empty")
        await send(500, "تنها پیام جدید")
        await cb(f"a:sec_done:{sid}")
        check(m.tut_find(sid)["ids"] == [500], "replace still overwrites everything")

        # سوییچ بین دو حالت وسطِ کار، حالت را خراب نمی‌کند
        await cb(f"a:sec_set:{sid}")
        await send(501, "یک پیام")
        await cb(f"a:sec_add:{sid}")
        check(m.fsm[ADMIN]["mode"] == "append"
              and m.fsm[ADMIN]["tut_pending"] == [500],
              "switching to append reloads saved content, drops unsent pending")

        # ---------- 4) مدیریت محتوا: فهرست + حذف دانه‌دانه ----------
        m.tut_update(sid, chat=ADMIN, ids=[601, 801, 701, 901])
        ev = await cb(f"a:sec_items:{sid}")
        txt, kb = ev.edits[-1]
        datas = btn_datas(kb)
        check("4 پیام" in txt, "items page counts registered messages")
        check("🎬 ویدیو" in txt and "📝 متن" in txt and "🎤 ویس" in txt,
              "items page shows the kind of each item (video/text/voice)")
        check(f"a:sec_di:{sid}:0" in datas and f"a:sec_di:{sid}:1" in datas
              and f"a:sec_di:{sid}:2" in datas and f"a:sec_di:{sid}:3" in datas,
              "every item has its own delete button")
        check(f"a:sec_dall:{sid}" in datas, "delete-all button present")
        check(all(len(d) <= 64 for d in all_bytes(kb)),
              "item delete callback data within 64 bytes")
        check(label_lens(kb) and max(label_lens(kb)) <= 64,
              "item button labels stay within Telegram's 64-char limit")

        # حذف «ویدیو اول» = آیتم شماره‌ی ۱
        await cb(f"a:sec_di:{sid}:0")
        check(m.tut_find(sid)["ids"] == [801, 701, 901],
              "deleting item 1 removes exactly that video, rest stay")
        # حذف ویس (آخرین آیتم)
        fake_now[0] += 5
        await cb(f"a:sec_di:{sid}:2")
        check(m.tut_find(sid)["ids"] == [801, 701],
              "voice item deleted by its own number")
        # حذف متن باقی‌مانده‌ی اول
        fake_now[0] += 5
        await cb(f"a:sec_di:{sid}:0")
        check(m.tut_find(sid)["ids"] == [701], "text item deleted, video kept")
        # آیتمِ نامعتبر → چیزی دست نمی‌خورد
        fake_now[0] += 5
        await cb(f"a:sec_di:{sid}:9")
        check(m.tut_find(sid)["ids"] == [701], "out-of-range index changes nothing")
        with open(M.CONFIG_FILE, encoding="utf-8") as f:
            saved = json.load(f)
        check(saved["tut_sections"][0]["ids"] == [701],
              "deletions persisted to config")

        # ---------- 5) شماره‌ها وقتی پیامِ منبع در تلگرام پاک شده ----------
        m.tut_update(sid, chat=ADMIN, ids=[601, 801, 701])
        del bot.msgs[ADMIN][801]                   # پیام وسطی پاک شده
        ev = await cb(f"a:sec_items:{sid}")
        txt, kb = ev.edits[-1]
        check("2 پیام" in txt, "deleted source message is not listed")
        check(btn_datas(kb).count(f"a:sec_di:{sid}:2") == 1
              and f"a:sec_di:{sid}:0" in btn_datas(kb),
              "listed items keep their real position in the ids list")
        fake_now[0] += 5
        await cb(f"a:sec_di:{sid}:2")
        check(m.tut_find(sid)["ids"] == [601, 801],
              "deleting the shown item removes the right message (index-safe)")

        # ---------- 6) پاک‌کردن همه‌ی محتوای بخش ----------
        ev = await cb(f"a:sec_dall:{sid}")
        s = m.tut_find(sid)
        check(s["ids"] == [] and s["chat"] == 0, "delete-all empties the section")
        check("پاک شد" in ev.edits[-1][0], "delete-all confirms in panel")
        ev = await cb(f"a:sec_items:{sid}")
        check("ثبت نشده" in ev.edits[-1][0], "empty items page explains itself")
        check(f"a:sec_dall:{sid}" not in btn_datas(ev.edits[-1][1]),
              "no delete-all button when there is nothing")

        # ---------- 7) افزودن به بخشِ خالی = همان ثبتِ معمولی ----------
        mode, had = m.tut_capture_start(ADMIN, "sec_set", sid=sid, append=True)
        check(mode == "replace" and had == 0,
              "append on empty section falls back to plain registration")

        # ---------- 8) افزودن از چتِ دیگر رد می‌شود (محتوا قاطی نمی‌شود) ----------
        m.tut_update(sid, chat=ADMIN, ids=[601])
        await cb(f"a:sec_add:{sid}")
        fake_now[0] += 5
        await handler(FakeMsgEv(ADMIN, 702, "از چت دیگر", chat_id=999))
        st = m.fsm.get(ADMIN) or {}
        check(st.get("tut_pending") == [601],
              "message from another chat is not mixed into the list")
        check(any("ثبت نشد" in (t or "") for u, t, _ in bot.text_sends if u == 999),
              "admin is told why it was rejected")
        m.fsm.pop(ADMIN, None)

        # ---------- 9) آموزش فعال‌سازی اصلی: همان قابلیت‌ها ----------
        m.cfg["tut_chat"] = ADMIN
        m.cfg["tut_ids"] = [601]
        m.cfg.save()
        ev = await cb("a:tut")
        datas = btn_datas(ev.edits[-1][1])
        check("a:tut_add" in datas and "a:tut_set" in datas
              and "a:tut_items" in datas,
              "main tutorial page: append + replace + manage content")

        await cb("a:tut_add")
        check(m.fsm[ADMIN]["step"] == "tut_set"
              and m.fsm[ADMIN]["mode"] == "append"
              and m.fsm[ADMIN]["tut_pending"] == [601],
              "main tutorial append pre-loads existing content")
        await send(701, "", video=("doc", "v2"))
        await send(801, "متنِ بعد از ویدیو")
        await cb("a:tut_done")
        check(m.cfg["tut_ids"] == [601, 701, 801] and m.cfg["tut_chat"] == ADMIN,
              "main tutorial keeps old content and appends new ones")
        with open(M.CONFIG_FILE, encoding="utf-8") as f:
            saved = json.load(f)
        check(saved["tut_ids"] == [601, 701, 801],
              "main tutorial append persisted")

        bot.msgs[ADMIN][801] = FakeMsg(801, "متن خوش‌آمد")   # پیامِ منبع برگشت
        ev = await cb("a:tut_items")
        datas = btn_datas(ev.edits[-1][1])
        check("a:tut_di:0" in datas and "a:tut_di:2" in datas
              and "a:tut_dall" in datas,
              "main tutorial items page has per-item + delete-all")
        check(max(label_lens(ev.edits[-1][1]) or [0]) <= 64,
              "main tutorial item labels within 64 chars")
        fake_now[0] += 5
        await cb("a:tut_di:1")
        check(m.cfg["tut_ids"] == [601, 801],
              "main tutorial: item 2 (the new video) deleted alone")
        fake_now[0] += 5
        await cb("a:tut_dall")
        check(m.cfg["tut_ids"] == [] and m.cfg["tut_chat"] == 0,
              "main tutorial: delete-all clears everything")

        ev = await cb("a:tut")
        datas = btn_datas(ev.edits[-1][1])
        check("a:tut_add" not in datas,
              "no append button while the tutorial is empty")
        check("a:tut_set" in datas and "a:tut_items" in datas,
              "empty tutorial page still offers registration + management")
        await cb("a:tut_add")
        check(m.fsm[ADMIN]["step"] == "tut_set"
              and m.fsm[ADMIN]["tut_pending"] == [],
              "append on an empty tutorial = plain registration")
        m.fsm.pop(ADMIN, None)
        await cb("a:tut_set")
        check(m.fsm[ADMIN]["tut_pending"] == [], "plain registration still works")
        m.fsm.pop(ADMIN, None)

        # ---------- 10) دکمه‌های دیگر = لغو (مثل قبل) ----------
        await cb(f"a:sec_add:{sid}")
        await send(601, "ویدیو اول")
        await cb("m:home")
        check(ADMIN not in m.fsm, "any other button still cancels the capture")
        check(m.tut_find(sid)["ids"] == [601],
              "cancelled capture saves nothing (content untouched)")

        # ---------- 11) تحویل به کاربر بعد از حذف/افزودن ----------
        m.tut_update(sid, chat=ADMIN, ids=[601, 701])
        fake_now[0] += 5
        bot.msg_sends = []
        await m.tut_send_section(USER, sid, force=True)
        check([x[1].id for x in bot.msg_sends if x[0] == USER] == [601, 701],
              "delivery follows the edited list")

        # ---------- 12) رگرسیونِ «همه‌چی پریده»: فهرستِ 🗂 توضیحات ----------
        # سناریوی واقعیِ مدیر: یک بخشِ «بعد از فعال‌سازی» می‌سازد و ویدیو
        # ثبت می‌کند؛ قبلاً به‌محضِ همین یک بخش، همه‌ی توضیحاتِ آماده‌ی
        # قابلیت‌ها از فهرستِ مشتری غیب می‌شد و فقط «🚀 راه‌اندازی سلف»
        # می‌ماند. حالا بخشِ خودش اول می‌آید و توضیحاتِ آماده سرِ جایشان
        # می‌مانند؛ تنها راهِ برداشتنشان سوئیچِ «📦 توضیحات پیش‌فرض» است.
        m.cfg["hub_defaults"] = True
        m.cfg["hub_on"] = True
        sec2 = m.tut_new("آموزش بعد از فعال‌سازی")
        m.tut_update(sec2["id"], emoji="🚀", when="after_run",
                     btn_cmd="s:setup",
                     btn_label="🚀 راه‌اندازی سلف روی اکانتم",
                     chat=ADMIN, ids=[601])
        datas, texts = [], []
        for pg in range(m.hub_pages()):
            _t, kb = m.hub_view(pg)
            datas += btn_datas(kb)
            texts += btn_texts(kb)
        check(f"hub:s:{sec2['id']}" in datas,
              "admin's own section is in the customer list")
        check(sum(1 for d in datas if d.startswith("hub:d:")) >= len(m.HUB_DEFAULTS),
              "built-in capability explanations are still listed next to it")
        check(any("آموزش بعد از فعال‌سازی" in t for t in texts),
              "the section itself is a tappable row in the list")
        check(any("سلف چیست" in t for t in texts)
              and any("تست رایگان" in t for t in texts)
              and any("کیف پول" in t for t in texts),
              "feature topics (سلف/تست رایگان/کیف پول) did not disappear")
        check("m:tut" in datas, "main tutorial entry still on the first page")

        # افزودنِ ویدیوی دوم به همان بخش، فهرست را خراب نمی‌کند
        await cb(f"a:sec_add:{sec2['id']}")
        await send(701, "ویدیو دوم", video=("doc", "v2"))
        await cb(f"a:sec_done:{sec2['id']}")
        check(m.tut_find(sec2["id"])["ids"] == [601, 701],
              "second video appended to the after-activation section")
        datas2 = []
        for pg in range(m.hub_pages()):
            datas2 += btn_datas(m.hub_view(pg)[1])
        check(f"hub:s:{sec2['id']}" in datas2
              and sum(1 for d in datas2 if d.startswith("hub:d:")) >= len(m.HUB_DEFAULTS),
              "list intact after appending content to a section")

        # تپِ همان بخش در فهرست: هر دو ویدیو + دکمه‌ی «🚀 راه‌اندازی سلف»
        fake_now[0] += 5
        bot.msg_sends, bot.text_sends = [], []
        ev = FakeCbEv(USER, f"hub:s:{sec2['id']}")
        await m.on_callback(ev)
        vids = [x[1].id for x in bot.msg_sends if x[0] == USER]
        foots = [btn_datas(x[2].get("buttons")) for x in bot.msg_sends
                 if x[0] == USER and x[2].get("buttons")]
        foots += [btn_datas(x[2].get("buttons")) for x in bot.text_sends
                  if x[0] == USER and x[2].get("buttons")]
        check(vids == [601, 701],
              "tapping the list item sends both videos in order")
        check(any("s:setup" in d for d in foots) and any("hub:list" in d for d in foots),
              "section carries its setup button + back to the list")

        # سوئیچِ خاموش‌کردنِ پیش‌فرض‌ها هنوز کار می‌کند (تنها راهِ حذف)
        await cb("a:hub_def")
        check(m.hub_defaults_on() is False and not m.hub_default_items(),
              "📦 توضیحات پیش‌فرض switch is the only way to drop them")
        datas3 = btn_datas(m.hub_view(0)[1])
        check(not [d for d in datas3 if d.startswith("hub:d:")],
              "defaults hidden while the switch is off")
        await cb("a:hub_def")
        check(m.hub_defaults_on() is True, "switch turns them back on")

        time.time = real_time

    asyncio.run(main())
    print(f"BUILD {M.BUILD_VERSION}")
    for name, ok in results:
        print(f"CHECK {'PASS' if ok else 'FAIL'} - {name}")
    bad = [name for name, ok in results if not ok]
    print("APPEND_RESULT", "PASS" if not bad else "FAIL")

''')


def reset():
    """Fresh APP with the current source + fake telethon."""
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


def run_inner(port):
    env = dict(os.environ)
    env["DATA_DIR"] = DATA
    env["PORT"] = str(port)
    env["JAFJ_PORT"] = str(port)
    for k in ("RAILWAY_ENVIRONMENT", "RAILWAY_SERVICE_ID", "RAILWAY_PROJECT_ID",
              "JAFJ_HOSTED", "JAFJ_LOGIN_RETRY", "BACKUP_CHAT", "BACKUP_EVERY",
              "BOT_TOKEN", "API_ID", "API_HASH", "ADMIN_IDS"):
        env.pop(k, None)
    p = subprocess.run([sys.executable, "-c", INNER], cwd=APP, env=env,
                       capture_output=True, text=True, timeout=180)
    return p.stdout + p.stderr


if __name__ == "__main__":
    print("--- افزودن/حذفِ دانه‌دانه‌ی محتوای آموزش‌ها (بدون ریست) ---")
    reset()
    out = run_inner(8193)
    checks = [ln for ln in out.splitlines() if ln.startswith("CHECK")]
    print("\n".join(checks) or out[-3000:])
    print("\n".join(ln for ln in out.splitlines()
                    if ln.startswith(("BUILD", "APPEND_RESULT"))))
    good = "APPEND_RESULT PASS" in out and not any(
        c.endswith("FAIL") or " FAIL " in c for c in checks)
    print("append:", "PASS" if good else "FAIL")
    if not good:
        print(out[-6000:])
    sys.exit(0 if good else 1)
