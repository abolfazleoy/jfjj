#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""«بخش‌های آموزش پرید» — رگرسیونِ از‌دست‌رفتنِ tut_sections.

سناریوی واقعیِ مدیر: چند بخشِ آموزش با ویدیو ثبت می‌کند؛ بعد یک
دیپلوی/ری‌استارت، نسخه‌ی <b>قدیمیِ</b> manager_config.json از راه می‌رسد
(pullِ سینکِ گیت‌هاب قبل از بوت، بازیابی از پشتیبانِ کهنه، یا یک نمونه‌ی
زامبی با کانفیگِ تهی که ذخیره می‌کند) و همه‌ی بخش‌ها یک‌جا می‌پرند — فقط
«آموزش فعال‌سازی» می‌ماند.

این تست دو لایه را قفل می‌کند:

  لایه‌ی ۱ — tools/gh_data_sync.py (pull دیگر کور جایگزین نمی‌کند):
    1) بسته‌ی کهنه + کانفیگِ محلیِ قدیمی‌تر → ادغام: بخش‌های پُرتر می‌مانند.
    2) کانفیگِ محلیِ تازه‌تر از بسته → دست نمی‌خورد (حذفِ عمدیِ مدیر له
       نمی‌شود).
    3) بعد از pullِ ادغامی، push همان نسخه‌ی پُرتر را ذخیره می‌کند.
    4) پوشه‌ی config_history داخل بسته می‌رود و بعد از wipe برمی‌گردد.

  لایه‌ی ۲ — manager_82.py (تورِ نجات + بازیابی با یک دکمه):
    5) قبل از هر تغییرِ بخش‌ها یک نسخه‌ی زمان‌دار در config_history می‌نشیند.
    6) اگر بخش‌ها بپرند، cfg_lost_sections() نسخه‌ی پُرتر و بخش‌های
       گم‌شده را پیدا می‌کند و هشدارِ بوت به مدیر می‌گوید.
    7) «🕘 بازیابی بخش‌ها» (a:secs_h) فهرستِ نسخه‌ها را نشان می‌دهد و
       a:secs_h_rs:<file> فقط بخش‌های گم‌شده را برمی‌گرداند (بخش‌های
       تازه‌ی مدیر له نمی‌شوند).
    8) بعد از بازیابی، محتوای هر بخش (ویدیوها) سر جایش است و «➕ افزودن
       به محتوا» مثل قبل ویدیوی بعدی را پشت قبلی‌ها می‌گذارد.
"""
import base64
import hashlib
import http.server
import importlib.util
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
ROOT = Path(tempfile.gettempdir()) / "jafj_sections_recovery_run"

FAILS = []


def check(cond, label):
    print(("PASS  " if cond else "FAIL  ") + label)
    if not cond:
        FAILS.append(label)
    return bool(cond)


def load_sync():
    spec = importlib.util.spec_from_file_location(
        "mgh", str(REPO / "tools" / "gh_data_sync.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── Fake GitHub Contents API ──────────────────────────────────────────────────
class FakeGH(http.server.BaseHTTPRequestHandler):
    store = {}
    put_attempts = 0

    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        raw = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _path(self):
        p = self.path.split("?", 1)[0]
        marker = "/contents/"
        i = p.find(marker)
        return p[i + len(marker):] if i >= 0 else ""

    def do_GET(self):
        path = self._path()
        if path in FakeGH.store:
            sha, content = FakeGH.store[path]
            self._send(200, {"content": base64.b64encode(content).decode("ascii"),
                             "encoding": "base64", "sha": sha, "path": path})
        else:
            self._send(404, {"message": "Not Found"})

    def do_PUT(self):
        FakeGH.put_attempts += 1
        path = self._path()
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        content = base64.b64decode(body.get("content", ""))
        cur = FakeGH.store.get(path)
        if cur is not None and body.get("sha") != cur[0]:
            self._send(409, {"message": "does not match"})
            return
        if cur is None and body.get("sha"):
            self._send(409, {"message": "does not match (missing)"})
            return
        sha = hashlib.sha1(content).hexdigest()
        FakeGH.store[path] = (sha, content)
        self._send(201 if cur is None else 200, {"content": {"sha": sha}})


class FakeServer:
    def __init__(self):
        FakeGH.store = {}
        FakeGH.put_attempts = 0
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeGH)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


BUNDLE_PATH = "data/customer_data.zip"


def env_for(data, port, **extra):
    env = dict(os.environ,
               DATA_DIR=str(data),
               DATA_GITHUB_TOKEN="test-token",
               DATA_GITHUB_REPO="djskkskw/jfjj-data",
               DATA_GITHUB_PATH=BUNDLE_PATH,
               DATA_GITHUB_BRANCH="main",
               DATA_GITHUB_API="http://127.0.0.1:%d" % port)
    env.pop("RAILWAY_ENVIRONMENT", None)
    env.update(extra)
    return env


def run_cli(data, port, cmd):
    return subprocess.run(
        [sys.executable, str(REPO / "tools" / "gh_data_sync.py"), cmd],
        env=env_for(data, port), capture_output=True, text=True, timeout=120)


RICH = {
    "bot_token": "t",
    "tut_chat": 100,
    "tut_ids": [11, 12],
    # بقیه‌ی «قابلیت‌ها»ی دستیِ مدیر — همان‌هایی که کاربر می‌گوید پریده:
    "cmd_items": [
        {"title": "🚀 راه‌اندازی سلف", "cmd": "اول 95.py را بفرست…", "note": "مرحله ۱"},
        {"title": "🤝 تبادل", "cmd": "کانال را به @me بده…", "note": ""},
    ],
    "rules_text": "قوانینِ کاملِ ربات که مدیر دستی نوشته است.",
    "welcome": "سلام! به ربات خوش آمدی — متنِ خوش‌آمدِ دستی.",
    "card_number": "6037-9911-2233-4455",
    "card_name": "به نامِ علی",
    "tut_sections": [
        {"id": 1, "name": "آموزش بعد از فعال‌سازی", "emoji": "🚀", "chat": 100,
         "ids": [601, 701], "when": "after_run", "delay": 0, "on": True,
         "once": True, "header": False, "in_hub": True, "note": "",
         "btn_label": "⚙️ سرویس من", "btn_cmd": "m:svc", "text": "",
         "preset": "after_run"},
        {"id": 2, "name": "آموزش خرید اشتراک", "emoji": "💎", "chat": 100,
         "ids": [801], "when": "after_sub", "delay": 0, "on": True,
         "once": True, "header": False, "in_hub": True, "note": "",
         "btn_label": "💎 اشتراک ماهانه", "btn_cmd": "m:plans", "text": "",
         "preset": "sub"},
        {"id": 3, "name": "آموزش کیف پول", "emoji": "💳", "chat": 100,
         "ids": [901, 902], "when": "after_wallet", "delay": 0, "on": True,
         "once": True, "header": False, "in_hub": True, "note": "",
         "btn_label": "💳 شارژ کیف پول", "btn_cmd": "w:topup", "text": "",
         "preset": "wallet"},
    ],
}
STALE = {"bot_token": "t", "tut_chat": 100, "tut_ids": [11], "tut_sections": [],
         # نسخه‌ی کهنه/زامبی: دستورات آماده فقط یک مورد، متن‌ها خالی
         "cmd_items": [{"title": "🚀 راه‌اندازی سلف", "cmd": "قدیمی", "note": ""}],
         "rules_text": "", "welcome": "", "card_number": "", "card_name": ""}


def write_cfg(data, obj, mtime=None):
    p = Path(data) / "manager_config.json"
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    if mtime:
        os.utime(str(p), (mtime, mtime))
    return p


def minimal_data(root):
    root.mkdir(parents=True, exist_ok=True)
    (root / ".jafj_deploy_id").write_text("abc123", encoding="utf-8")
    con = sqlite3.connect(str(root / "manager.db"))
    con.execute("CREATE TABLE customers(x INTEGER)")
    con.commit()
    con.close()
    return root


# ═════════════════════ لایه‌ی ۱: سینکِ گیت‌هاب ═════════════════════
def scenario_sync():
    print("--- لایه‌ی ۱: pullِ بسته‌ی کهنه بخش‌ها را نمی‌برد ---")
    srv = FakeServer()
    try:
        # الف) بسته‌ی گیت‌هاب = نسخه‌ی کهنه (بدون بخش) — مثلِ وقتی که آخرین
        #    pushِ موفق مالِ چند روز پیش است.
        rich = minimal_data(ROOT / "s_rich")
        write_cfg(rich, RICH)
        check(run_cli(rich, srv.port, "push").returncode == 0,
              "pushِ کانفیگِ پُر انجام شد")
        stale = minimal_data(ROOT / "s_stale")
        write_cfg(stale, STALE)
        check(run_cli(stale, srv.port, "push").returncode == 0,
              "pushِ نمونه‌ی زامبی با کانفیگِ تهی (بسته حالا کهنه است)")

        # ب) دیپلویِ بعدی روی همان داده‌ی اصلی: pull باید بخش‌ها را نگه دارد
        data = ROOT / "s_rich"
        old = time.time() - 7200          # کانفیگِ محلی قدیمی‌تر از بسته
        write_cfg(data, RICH, mtime=old)
        r = run_cli(data, srv.port, "pull")
        check(r.returncode == 0, "pull اجرا شد")
        cfg = json.loads((data / "manager_config.json").read_text(encoding="utf-8"))
        check(len(cfg.get("tut_sections") or []) == 3,
              "بسته‌ی کهنه بخش‌ها را نبرد (۳ بخش سر جایشان)")
        check([s["name"] for s in cfg["tut_sections"]] ==
              [s["name"] for s in RICH["tut_sections"]],
              "نامِ بخش‌ها (بعد از فعال‌سازی / اشتراک / کیف پول) دست‌نخورده")
        check([s["ids"] for s in cfg["tut_sections"]] ==
              [s["ids"] for s in RICH["tut_sections"]],
              "ویدیوهای ثبت‌شده‌ی هر بخش (ids) سر جایشان")
        check(cfg.get("tut_ids") == [11, 12],
              "محتوای آموزشِ اصلی هم پُرتر ماند")
        check(len(cfg.get("cmd_items") or []) == 2,
              "«📋 دستورات آماده»ی مدیر با بسته‌ی کهنه یکی‌درمیان نشد")
        check(cfg.get("rules_text") == RICH["rules_text"],
              "متنِ قوانینِ پُرتر ماند")
        check(cfg.get("welcome") == RICH["welcome"],
              "متنِ خوش‌آمدِ پُرتر ماند")
        check(cfg.get("card_number") == RICH["card_number"]
              and cfg.get("card_name") == RICH["card_name"],
              "شماره‌کارت و نامِ صاحبِ کارت (تنظیماتِ دستی) نپرید")

        # پ) کانفیگِ محلیِ تازه‌تر از بسته → دست نمی‌خورد (حذفِ عمدی له نشود)
        data2 = minimal_data(ROOT / "s_newer")
        pruned = json.loads(json.dumps(RICH, ensure_ascii=False))
        pruned["tut_sections"] = pruned["tut_sections"][:1]   # مدیر دو تا را برداشت
        write_cfg(data2, pruned, mtime=time.time() + 5)
        r = run_cli(data2, srv.port, "pull")
        cfg2 = json.loads((data2 / "manager_config.json").read_text(encoding="utf-8"))
        check(r.returncode == 0 and len(cfg2["tut_sections"]) == 1,
              "کانفیگِ محلیِ تازه‌تر دست نخورد (حذفِ عمدیِ مدیر برنگشت)")
        check("تازه‌تر" in (r.stdout + r.stderr),
              "pull در لاگ می‌گوید چرا دست نزده")
        check(cfg2.get("cmd_items") == pruned.get("cmd_items")
              or len(cfg2.get("cmd_items") or []) == 2,
              "در حالتِ «محلی تازه‌تر» هم دستورات آماده دست نخورد")

        # ت) بعد از pullِ ادغامی، push همان نسخه‌ی پُرتر را ذخیره می‌کند
        check(run_cli(data, srv.port, "push").returncode == 0,
              "push بعد از ادغام موفق")
        check(run_cli(data, srv.port, "pull").returncode == 0, "pullِ دوباره")
        cfg3 = json.loads((data / "manager_config.json").read_text(encoding="utf-8"))
        check(len(cfg3["tut_sections"]) == 3,
              "دورِ کامل pull→push→pull بخش‌ها را نگه می‌دارد")

        # ث) پوشه‌ی تاریخچه‌ی کانفیگ داخل بسته می‌رود و بعد از wipe برمی‌گردد
        hist = data / "config_history"
        hist.mkdir(exist_ok=True)
        (hist / "config_1700000000.json").write_text(
            json.dumps(RICH, ensure_ascii=False), encoding="utf-8")
        check(run_cli(data, srv.port, "push").returncode == 0,
              "push با پوشه‌ی config_history")
        wipe = minimal_data(ROOT / "s_wiped")       # دیسکِ پاک‌شده
        r = run_cli(wipe, srv.port, "pull")
        check(r.returncode == 0 and (wipe / "config_history" /
                                     "config_1700000000.json").is_file(),
              "تاریخچه‌ی کانفیگ بعد از wipe دیسک از گیت‌هاب برمی‌گردد")
        back = json.loads((wipe / "config_history" /
                           "config_1700000000.json").read_text(encoding="utf-8"))
        check(len(back.get("tut_sections") or []) == 3,
              "نسخه‌ی بازیابی‌شده‌ی تاریخچه بخش‌ها را دارد")
    finally:
        srv.close()


# ═════════════════════ لایه‌ی ۲: خودِ ربات ═════════════════════
FAKE_TELETHON = textwrap.dedent('''
    class TelegramClient:
        def __init__(self, *a, **k):
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

    ADMIN, USER = 100, 200
    results = []

    def check(cond, name):
        results.append((name, bool(cond)))

    def btn_datas(kb):
        out = []
        for row in (kb or []):
            for b in row:
                try:
                    d = b[1][1]
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
            st = self.msgs.get(chat, {})
            return [st.get(i) for i in (ids or [])]
        async def send_message(self, uid, message=None, **kw):
            if hasattr(message, "id") and hasattr(message, "media"):
                self.msg_sends.append((uid, message, kw))
                return None
            self.text_sends.append((uid, message, kw))
            return None
        async def send_file(self, *a, **k):
            return None
        async def forward_messages(self, *a, **k):
            return None

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
        check("def cfg_snapshot(" in src, "config snapshot helper exists")
        check("def cfg_lost_sections(" in src, "lost-sections detector exists")
        check("def cfg_restore_sections(" in src, "section restore helper exists")
        check('k == "secs_h"' in src and 'k.startswith("secs_h_rs:")' in src,
              "recovery panel + routes exist")
        check("cfg_snapshot(\\"sections\\")" in src,
              "every section change snapshots the config first")
        check('"config_history"' in open("tools/gh_data_sync.py",
                                        encoding="utf-8").read(),
              "sync tool ships config_history in the bundle")

        real_time = time.time
        fake_now = [real_time()]
        time.time = lambda: fake_now[0]

        m = M.Manager()
        bot = FakeBot()
        m.bot = bot
        m.cfg["admin_ids"] = [ADMIN]

        async def cb(data, uid=ADMIN):
            fake_now[0] += 5
            ev = FakeCbEv(uid, data)
            await m.on_callback(ev)
            return ev

        # ---------- 1) سه بخش با ویدیو ثبت می‌شود ----------
        ids = []
        for name, em, when in (("آموزش بعد از فعال‌سازی", "🚀", "after_run"),
                               ("آموزش خرید اشتراک", "💎", "after_sub"),
                               ("آموزش کیف پول", "💳", "after_wallet")):
            fake_now[0] += 60            # snapshot هر ۳۰ ثانیه یک‌بار می‌نشیند
            s = m.tut_new(name)
            m.tut_update(s["id"], emoji=em, when=when, chat=ADMIN,
                         ids=[600 + s["id"]])
            ids.append(s["id"])
        secs = m.tut_sections()
        check(len(secs) == 3, "سه بخش ساخته شد")
        hist = M.cfg_history_list()
        check(len(hist) >= 2, "تاریخچه‌ی کانفیگ ساخته شد (قبل از هر تغییر)")
        newest = hist[0][1]
        check(len(newest.get("tut_sections") or []) >= 2,
              "تازه‌ترین نسخه‌ی تاریخچه بخش‌ها را دارد")
        check(M.cfg_lost_sections() is None,
              "تا وقتی بخش‌ها هستند، «گم‌شده» گزارش نمی‌شود")

        # ---------- 2) فاجعه: کانفیگِ قدیمی برمی‌گردد ----------
        check(any(len(M._cfg_secs(d)) == 3 for _n, d, _m in M.cfg_history_list()),
              "نسخه‌ی کاملِ هر سه بخش در تاریخچه نشست")
        fake_now[0] += 60
        m.tut_remove(ids[1])             # نسخه‌ی قدیمی فقط یک بخش دارد
        m.tut_remove(ids[2])
        stale = dict(m.cfg.d)
        stale["tut_sections"] = [s for s in stale["tut_sections"]
                                 if s["id"] == ids[0]]
        with open(M.CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(stale, f, ensure_ascii=False)
        m.cfg = M.Config()
        check(len(m.tut_sections()) == 1,
              "بعد از برگشتِ نسخه‌ی قدیمی فقط یک بخش مانده (همان فاجعه)")

        lost = M.cfg_lost_sections()
        check(lost is not None, "گم‌شدنِ بخش‌ها تشخیص داده شد")
        if lost:
            fname, snap, lost_ids = lost
            check(set(lost_ids) == {ids[1], ids[2]},
                  "دقیقاً همان دو بخشِ گم‌شده پیدا شدند")
            check(len(snap.get("tut_sections") or []) == 3,
                  "نسخه‌ی پُرترِ تاریخچه شناسایی شد")

            notices = m._startup_notices()
            check(any("بخشِ آموزش" in n and "بازیابی" in n for n in notices),
                  "هشدارِ بوت به مدیر می‌گوید بخش‌ها پریده و راهِ برگشت کجاست")

        # ---------- 3) پنلِ بازیابی ----------
        ev = await cb("a:secs")
        check("a:secs_h" in btn_datas(ev.edits[-1][1]),
              "صفحه‌ی بخش‌ها دکمه‌ی «🕘 بازیابی بخش‌ها» دارد")
        ev = await cb("a:secs_h")
        txt, kb = ev.edits[-1]
        datas = btn_datas(kb)
        check("گم‌شده" in txt, "پنلِ بازیابی، بخش‌های گم‌شده را فهرست می‌کند")
        check("آموزش خرید اشتراک" in txt and "آموزش کیف پول" in txt,
              "اسمِ هر دو بخشِ گم‌شده در پنل دیده می‌شود")
        check("a:secs_h_all" in datas,
              "دکمه‌ی «🧩 برگرداندنِ همه‌ی بخش‌های گم‌شده» هست")
        check(any(d.startswith("a:secs_h_rs:") for d in datas),
              "بازیابی از یک نسخه‌ی خاص هم ممکن است")
        check(all(len(d.encode()) <= 64 for d in datas)
              and all(len(t) <= 64 for t in btn_texts(kb)),
              "داده و متنِ دکمه‌ها زیر سقفِ تلگرام")

        # یک بخشِ تازه هم ساخته می‌شود تا معلوم شود له نمی‌شود
        fresh = m.tut_new("بخشِ تازه‌ی بعد از فاجعه")
        ev = await cb("a:secs_h_all")
        secs = m.tut_sections()
        names = [s["name"] for s in secs]
        check(len(secs) == 4,
              "دو بخشِ گم‌شده برگشتند + بخشِ تازه‌ی مدیر له نشد (۴ تا)")
        check("آموزش خرید اشتراک" in names and "آموزش کیف پول" in names,
              "بخش‌های اشتراک و کیف پول برگشتند")
        check("بخشِ تازه‌ی بعد از فاجعه" in names,
              "بخشِ تازه‌ی مدیر سر جایش ماند")
        sub = next((s for s in secs if s["name"] == "آموزش خرید اشتراک"), None)
        check(sub is not None and sub["ids"] and sub["chat"] == ADMIN
              and all(isinstance(i, int) for i in sub["ids"]),
              "ویدیوی ثبت‌شده‌ی همان بخش هم با خودش برگشت")
        check(sub is not None and sub["when"] == "after_sub"
              and sub["emoji"] == "💎" and sub.get("note", "") is not None,
              "زمانِ ارسال و ایموجیِ بخش دست‌نخورده برگشت")
        check(M.cfg_lost_sections() is None,
              "بعد از بازیابی، دیگر «گم‌شده» گزارش نمی‌شود")
        check(any("برگشت" in (t or "") for t, _ in ev.edits),
              "نتیجه‌ی بازیابی در پنل اعلام می‌شود")

        # ---------- 4) افزودنِ ویدیوی دوم بعد از بازیابی ----------
        fake_now[0] += 5
        await cb(f"a:sec_add:{sub['id']}")
        check((m.fsm.get(ADMIN) or {}).get("mode") == "append",
              "افزودن به محتوای بخشِ بازیابی‌شده کار می‌کند")
        m.fsm[ADMIN]["tut_pending"].append(777)
        await cb(f"a:sec_done:{sub['id']}")
        check(m.tut_find(sub["id"])["ids"] == [600 + ids[1], 777],
              "ویدیوی دوم پشتِ ویدیوی برگشتی نشست (آیدیِ اصلیِ پیام حفظ شد)")

        # ---- 4b) محتوای یک بخشِ «موجود» می‌پرد (کیف پول/امتیاز/اشتراک) ----
        # سناریوی واقعیِ کاربر: بخش سرِ جایش است ولی ویدیو/متنش خالی شده، پس
        # «گم‌شده» نیست و فقط ترمیمِ محتوا نجاتش می‌دهد.
        wallet = next(s for s in m.tut_sections() if s["name"] == "آموزش کیف پول")
        orig_ids = list(wallet["ids"])
        m.tut_update(wallet["id"], ids=[], text="", note="", chat=0)
        poor = M.cfg_poor_sections()
        check(any(sid == wallet["id"] for sid, _n, _m, _h in poor),
              "خالی‌شدنِ محتوای بخشِ موجود تشخیص داده شد")
        ev = await cb("a:secs_h")
        txt, kb = ev.edits[-1]
        check("محتوایش خالی شده" in txt and "آموزش کیف پول" in txt,
              "پنل می‌گوید کدام بخش هست ولی محتوایش خالی شده")
        check("a:secs_h_c" in btn_datas(kb),
              "دکمه‌ی «📚 برگرداندنِ محتوا» هست")
        check(any(len(d.encode()) <= 64 for d in btn_datas(kb)),
              "داده‌ی دکمه‌ها زیر سقفِ تلگرام")
        ev = await cb("a:secs_h_c")
        w2 = m.tut_find(wallet["id"])
        check(orig_ids and w2["ids"] == orig_ids,
              "دقیقاً همان ویدیوهای ثبت‌شده برگشتند")
        check(w2["chat"] == ADMIN, "چتِ منبعِ محتوا هم برگشت")
        check(all(sid != wallet["id"] for sid, _n, _m, _h in M.cfg_poor_sections()),
              "بعد از ترمیم، دیگر «خالی» گزارش نمی‌شود")
        check(any("برگشت" in (t2 or "") for t2, _k in ev.edits),
              "نتیجه‌ی ترمیم در پنل اعلام می‌شود")

        # آنچه مدیر الان دارد له نمی‌شود: متنِ تازه‌تر می‌ماند
        m.tut_update(wallet["id"], text="متنِ تازه‌ی خودم")
        M.cfg_snapshot("test-fresh-text")
        m.tut_update(wallet["id"], text="")
        n_fixed, _detail = M.cfg_restore_section_content(wallet["id"])
        check(n_fixed == 1, "ترمیمِ تک‌بخش کار می‌کند")
        m.cfg = M.Config()
        check(m.tut_find(wallet["id"])["text"] == "متنِ تازه‌ی خودم",
              "پُرترین نسخه‌ی تاریخیِ متن برگشت، نه نسخه‌ی کهنه")

        # پیامِ تکراری اضافه نمی‌شود
        n_before = len(m.tut_find(wallet["id"])["ids"])
        M.cfg_restore_section_content(None)
        m.cfg = M.Config()
        check(len(m.tut_find(wallet["id"])["ids"]) == n_before,
              "دوباره‌کاری نکرد: پیامِ تکراری اضافه نشد")

        # هشدارِ بوت + ترمیمِ یک‌دکمه بعد از آن
        m.tut_update(wallet["id"], ids=[])
        check(any("محتوای" in n2 and "خالی شده" in n2 for n2 in m._startup_notices()),
              "هشدارِ بوت هم برای محتوای خالی‌شده می‌آید")
        ev = await cb("a:secs_h_c:" + str(wallet["id"]))
        check(m.tut_find(wallet["id"])["ids"] == orig_ids,
              "با دکمه‌ی تک‌بخش هم ویدیوها برگشتند")

        # ---------- 5) بازیابیِ کلِ تنظیمات ----------
        fake_now[0] += 90
        m.tut_remove(sub["id"])
        m.tut_remove(fresh["id"])
        ev = await cb("a:secs_h")
        rf = [d for d in btn_datas(ev.edits[-1][1]) if d.startswith("a:secs_h_rf:")]
        check(bool(rf), "دکمه‌ی «📥 کل تنظیمات» برای هر نسخه هست")
        ev = await cb(rf[0])
        check(len(m.tut_sections()) >= 3,
              "بازیابیِ کامل، نسخه‌ی پُرتر را نشاند")
        check(m.sup.cfg is m.cfg, "Supervisor هم کانفیگِ تازه را گرفت")

        # نسخه‌ی نامعتبر → خطای تمیز، بدونِ دست‌خوردنِ داده
        before = len(m.tut_sections())
        ev = await cb("a:secs_h_rs:config_0000000000.json")
        check("پیدا نشد" in ev.edits[-1][0] and len(m.tut_sections()) == before,
              "نسخه‌ی ناموجود خطای تمیز می‌دهد و چیزی را دست نمی‌زند")

        # ---------- 6) سقفِ تاریخچه ----------
        check(len(M.cfg_history_list()) <= 500, "تاریخچه از سقفِ سخت بیشتر نمی‌شود")
        # چرخشِ سن‌محور: تازه‌ها کامل می‌مانند، قدیمی‌ترها نمایی نازک می‌شوند.
        hist_dir = M.CFG_HISTORY_DIR
        real_time, saved_files = time.time, sorted(os.listdir(hist_dir))
        try:
            base = time.time()
            for i in range(160):
                fn = os.path.join(hist_dir, "config_%d.json" % (1_000_000 + i))
                with open(fn, "w", encoding="utf-8") as f:
                    f.write(json.dumps({"tut_sections": [], "n": i}))
                mt = base - (40 * 86400) + i          # همه ۴۰ روز پیش
                os.utime(fn, (mt, mt))
            M._cfg_history_rotate()
            left = set(os.listdir(hist_dir))
            old_left = [n for n in left if n.startswith("config_1000")]
            check(0 < len(old_left) < 120,
                  "نسخه‌های کهنه نازک می‌شوند ولی صفر نمی‌شوند")
            check(set(saved_files) <= left,
                  "نسخه‌های تازه‌ی همین نشست در چرخش حذف نمی‌شوند")
            check(len(left) <= 500, "سقفِ سختِ تاریخچه رعایت می‌شود")
            for n in list(left - set(saved_files)):
                os.remove(os.path.join(hist_dir, n))
        finally:
            time.time = real_time

        time.time = real_time

    asyncio.run(main())
    print(f"BUILD {M.BUILD_VERSION}")
    for name, ok in results:
        print(f"CHECK {'PASS' if ok else 'FAIL'} - {name}")
    bad = [n for n, ok in results if not ok]
    print("RECOVERY_RESULT", "PASS" if not bad else "FAIL")
''')


def reset_app():
    app = ROOT / "app"
    data = ROOT / "data"
    shutil.rmtree(app, ignore_errors=True)
    shutil.rmtree(data, ignore_errors=True)
    app.mkdir(parents=True, exist_ok=True)
    data.mkdir(parents=True, exist_ok=True)
    for f in ("manager_82.py", "95.py"):
        shutil.copy2(str(REPO / f), str(app / f))
    shutil.copytree(str(REPO / "tools"), str(app / "tools"))
    tel = app / "telethon"
    tel.mkdir(exist_ok=True)
    (tel / "__init__.py").write_text(FAKE_TELETHON, encoding="utf-8")
    (tel / "sessions.py").write_text(FAKE_SESSIONS, encoding="utf-8")
    (tel / "errors.py").write_text(FAKE_ERRORS, encoding="utf-8")
    return app, data


def run_inner(app, data, port):
    env = dict(os.environ, DATA_DIR=str(data), PORT=str(port), JAFJ_PORT=str(port))
    for k in ("RAILWAY_ENVIRONMENT", "RAILWAY_SERVICE_ID", "RAILWAY_PROJECT_ID",
              "JAFJ_HOSTED", "JAFJ_LOGIN_RETRY", "BACKUP_CHAT", "BACKUP_EVERY",
              "BOT_TOKEN", "API_ID", "API_HASH", "ADMIN_IDS"):
        env.pop(k, None)
    p = subprocess.run([sys.executable, "-c", INNER], cwd=str(app), env=env,
                       capture_output=True, text=True, timeout=300)
    return p.stdout + p.stderr


if __name__ == "__main__":
    shutil.rmtree(ROOT, ignore_errors=True)
    ROOT.mkdir(parents=True, exist_ok=True)
    scenario_sync()
    print("--- لایه‌ی ۲: تورِ نجاتِ ربات + بازیابی با یک دکمه ---")
    app, data = reset_app()
    out = run_inner(app, data, 8194)
    checks = [ln for ln in out.splitlines() if ln.startswith("CHECK")]
    print("\n".join(checks) or out[-4000:])
    if "RECOVERY_RESULT" not in out:
        print("---- raw ----")
        print(out[-5000:])
    print("\n".join(ln for ln in out.splitlines()
                    if ln.startswith(("BUILD", "RECOVERY_RESULT"))))
    if "RECOVERY_RESULT PASS" not in out:
        print(out[-6000:])
    good = ("RECOVERY_RESULT PASS" in out
            and not any(c.endswith("FAIL") or " FAIL " in c for c in checks)
            and not FAILS)
    print("sections-recovery:", "PASS" if good else "FAIL")
    sys.exit(0 if good else 1)
