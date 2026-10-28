#!/usr/bin/env python3
"""رگرسیونِ «بک‌آپ می‌دم، بعد از دیپلوی اطلاعات برمی‌گرده ولی پیامِ پشتیبان گم می‌شه».

سناریوی گزارش‌شده (لاگ واقعی مدیر):

    ✅ بازیابی از فایلی که فرستادی: 157 مشتری · 8 سرویس در حال روشن شدن
    ⚠️ بازیابیِ اطلاعات ناموفق بود — پشتیبانی پیدا نشد (نه در تلگرام نه روی دیسک)
    ⚠️ دیتابیس خالی است و نتوانستم پشتیبانِ قبلی را در تلگرام پیدا کنم

و بعد از آن هر `.backup` رد می‌شود، چون گاردِ «دیتابیس خالی» جلویش را می‌گیرد →
حلقهٔ بسته: نه بازیابی ممکن است، نه پشتیبانِ تازه ساخته می‌شود.

علتِ ریشه‌ای: **رباتِ تلگرام `messages.getHistory` ندارد.** تا وقتی اشاره‌گرِ
تک‌پیام (`chat` + `msg_id`) روی دیسک بود، `getMessages` کار می‌کرد؛ دیسک که پاک
شد، آدرس هم رفت و هیچ راهی برای «گشتن» نماند.

این تست با یک telethon جعلیِ **ربات‌گونه** اجرا می‌شود: `iter_messages` و
`get_dialogs` عمداً خطا می‌دهند (دقیقاً مثل رباتِ واقعی) و فقط `get_messages`
با آیدیِ مشخص کار می‌کند. پس هر چیزی که اینجا سبز شود، روی رباتِ واقعی هم
بدون «شانس» کار می‌کند.

پوشش:
  P1  `parse_restore_ref` — آیدی، لینکِ t.me/c، لینکِ یوزرنیم، ریپلای، خالی
  P2  `command_text(".restore 12345")` آرگومان را نگه می‌دارد (قبلاً دور می‌ریخت)
  P3  بعد از پشتیبان‌گیری، آدرسِ پیام در `.jafj_backup_meta` **و** در
      `manager_config.json` ذخیره می‌شود
  P4  دیسکِ کامل پاک + بدون اشاره‌گر → بازیابی شکست می‌خورد (اثباتِ باگ)
  P5  همان حالت، ولی با ارجاعِ مدیر (`.restore <id>`) → بازیابی موفق
  P6  اشاره‌گر از meta (دیسکِ ماندگار) → بازیابی **بدون** گشتن در تاریخچه
  P7  فقط اشاره‌گرِ داخل `manager_config.json` (meta پاک) → باز هم بازیابی
  P8  گاردِ دیتابیسِ خالی، مسیرِ ریپلای/آیدی را در پیامش می‌گوید
  P9  بعد از بازیابی، تک‌پیامِ پشتیبان دوباره ساخته/به‌روز می‌شود (re-anchor)

اجرا: `python3 tests/test_backup_pointer_recovery.py` → باید `ALL: PASS` بدهد.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap

ROOT = os.path.join(tempfile.gettempdir(), "jafj_backup_pointer_run")
APP = os.path.join(ROOT, "app")
DATA = os.path.join(ROOT, "data")
STORE = os.path.join(ROOT, "store")
SRC = os.environ.get("REPO", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── telethon جعلی: رباتِ واقعی (بدون تاریخچه) ────────────────────────────────
FAKE_INIT = textwrap.dedent('''
import os, shutil

BOT_ID = 111
CHATS = {}            # _key(target) -> [FakeMsg, ...] (تازه‌ترین اول)
_next_id = [1000]


def _key(target):
    try:
        return str(int(target))
    except Exception:
        return str(target).strip().lower().lstrip("@")


class FakeDoc:
    def __init__(self, name="backup.zip"):
        self.name = name
        self.mime_type = "application/zip"


class FakeMsg:
    def __init__(self, mid, chat, caption="", text="", sender_id=BOT_ID,
                 fpath=None, media=None):
        self.id = mid
        self.chat_id = chat
        self.caption = caption or ""
        self.text = text or ""
        self.sender_id = sender_id
        self._fpath = fpath
        self.document = media
        self.media = media
        self.edits = 0

    @property
    def file(self):
        return self.document


class U:
    username = "fakebot"
    id = BOT_ID


class BotMethodInvalidError(Exception):
    pass


class TelegramClient:
    def __init__(self, session, api_id, api_hash, **kw):
        pass

    async def get_me(self):
        return U()

    async def get_entity(self, x):
        class E:
            username = None
        return E()

    # ── همان محدودیتِ رباتِ واقعی ──
    async def get_dialogs(self, limit=None):
        raise BotMethodInvalidError("getDialogs is not available for bots")

    def iter_dialogs(self, limit=None):
        async def _gen():
            raise BotMethodInvalidError("getDialogs is not available for bots")
            yield
        return _gen()

    def iter_messages(self, target, limit=50, **kw):
        async def _gen():
            raise BotMethodInvalidError("getHistory is not available for bots")
            yield
        return _gen()

    # ── این یکی برای ربات مجاز است ──
    async def get_messages(self, target, ids=None, **kw):
        if ids is None:
            raise BotMethodInvalidError("getHistory is not available for bots")
        out = []
        msgs = {m.id: m for m in CHATS.get(_key(target), [])}
        for i in (ids if isinstance(ids, (list, tuple)) else [ids]):
            out.append(msgs.get(int(i)))
        return out

    async def send_message(self, *a, **k):
        class R:
            id = 1
        return R()

    async def send_file(self, target, fpath, caption=None, **kw):
        _next_id[0] += 1
        mid = _next_id[0]
        os.makedirs(os.environ["FAKE_BACKUP_DIR"], exist_ok=True)
        dst = os.path.join(os.environ["FAKE_BACKUP_DIR"], "msg_%d.zip" % mid)
        shutil.copy2(str(fpath), dst)
        msg = FakeMsg(mid, _key(target), caption=caption, fpath=dst, media=FakeDoc())
        CHATS.setdefault(_key(target), []).insert(0, msg)
        return msg

    async def edit_message(self, target, message=None, text=None, *a, file=None, **kw):
        for m in CHATS.get(_key(target), []):
            if m.id == message:
                m.caption = text or ""
                m.edits += 1
                if file:
                    dst = os.path.join(os.environ["FAKE_BACKUP_DIR"], "msg_%d.zip" % m.id)
                    shutil.copy2(str(file), dst)
                    m._fpath = dst
                    m.document = FakeDoc()
                    m.media = m.document
                return m
        raise RuntimeError("message not found")

    async def delete_messages(self, target, ids, **kw):
        ids = set(int(i) for i in (ids or ()))
        k = _key(target)
        CHATS[k] = [m for m in CHATS.get(k, []) if m.id not in ids]

    async def download_media(self, msg, file=None, **kw):
        src = getattr(msg, "_fpath", None)
        if not src or not os.path.isfile(str(src)):
            raise RuntimeError("no file")
        if file:
            shutil.copy2(str(src), str(file))
            return str(file)
        return str(src)
''')

FAKE_SESS = textwrap.dedent('''
class StringSession:
    def __init__(self, s=""):
        self._s = s or ""
    def save(self):
        return self._s


class SQLiteSession:
    def __init__(self, *a, **k):
        pass
''')

FAKE_ERRORS = textwrap.dedent('''
class FloodWaitError(Exception):
    def __init__(self, seconds=0, *a, **k):
        self.seconds = seconds
''')

DRIVER = textwrap.dedent('''
import asyncio, json, os, shutil, sys, zipfile
sys.path.insert(0, os.getcwd())
import manager_82 as M
from telethon import TelegramClient, FakeMsg, FakeDoc, CHATS

results = {}


def check(name, cond, extra=""):
    results[name] = bool(cond)
    print("%s %s" % (name, "PASS" if cond else "FAIL  " + str(extra)))


def wipe(keep_config=False):
    """دیسکِ داده را کامل پاک کن (شبیه دیپلوی روی پلنِ بدون Disk)."""
    data = os.environ["DATA_DIR"]
    saved = None
    cfgp = os.path.join(data, "manager_config.json")
    if keep_config and os.path.isfile(cfgp):
        with open(cfgp, encoding="utf-8") as f:
            saved = f.read()
    for name in os.listdir(data):
        p = os.path.join(data, name)
        if os.path.isdir(p):
            shutil.rmtree(p, ignore_errors=True)
        else:
            try:
                os.remove(p)
            except Exception:
                pass
    if saved:
        with open(cfgp, "w", encoding="utf-8") as f:
            f.write(saved)


def drop_db():
    """دیتابیس‌ها را پاک کن ولی اشاره‌گر/تنظیمات بمانند (دیسکِ ماندگار).

    این همان حالتی است که کاربر دارد: داده از بین رفته ولی
    manager_config.json و .jafj_backup_meta (از سینکِ گیت‌هاب یا بک‌آپِ
    قبلی) سرِ جایشان هستند.
    """
    data = os.environ["DATA_DIR"]
    for name in ("manager.db", "shop.db", "manager.db-wal", "manager.db-shm",
                 "shop.db-wal", "shop.db-shm"):
        try:
            os.remove(os.path.join(data, name))
        except Exception:
            pass
    shutil.rmtree(os.path.join(data, "clients"), ignore_errors=True)


def new_mgr(admins=(111,)):
    m = M.Manager()
    m.bot = TelegramClient(None, 1, "h")
    m.cfg["admin_ids"] = list(admins)
    m.fsm = {}
    # بوت/ری‌استارتِ سرویس‌ها اینجا موضوعِ تست نیست (تستِ جدا دارد)
    calls = {"resume": 0, "reanchor": 0}
    m._resume_after_restore = lambda why="": calls.__setitem__("resume", calls["resume"] + 1) or 1
    m._reanchor_backup = lambda why="": calls.__setitem__("reanchor", calls["reanchor"] + 1) or True
    m._calls = calls
    return m


def count(m):
    try:
        r = m.db.x("SELECT COUNT(*) c FROM clients", (), "one")
        return r["c"] if r else 0
    except Exception:
        return -1


def seed(m, n=3):
    for i in range(n):
        uid = 900 + i
        m.db.add(uid, "u%d" % uid, "U%d" % uid, 0)
        m.db.set(uid, status="active", session="S" * 40, phone="+98912",
                 want_on=1)
        os.makedirs(m.sup.folder(uid), exist_ok=True)
        with open(os.path.join(m.sup.folder(uid), "jafj.session"), "wb") as f:
            f.write(b"x")


async def main():
    try:
        # ── P1: پارسِ ارجاع ──
        check("P1a_parse_id", M.parse_restore_ref("12345") == (None, 12345))
        check("P1b_parse_link_c",
              M.parse_restore_ref("https://t.me/c/123456789/45") == (-100123456789, 45),
              M.parse_restore_ref("https://t.me/c/123456789/45"))
        check("P1c_parse_link_user",
              M.parse_restore_ref("t.me/mybot/77") == ("mybot", 77),
              M.parse_restore_ref("t.me/mybot/77"))
        check("P1d_parse_reply", M.parse_restore_ref("", reply_id=555) == (None, 555))
        check("P1e_parse_empty", M.parse_restore_ref("") == (None, None))
        check("P1f_parse_garbage", M.parse_restore_ref("سلام") == (None, None))

        # ── P2: دستور با آرگومان ──
        check("P2a_cmd_restore_arg",
              M.command_text(".restore 12345") == "/restore 12345",
              M.command_text(".restore 12345"))
        check("P2b_cmd_restore_bare", M.command_text(".restore") == "/restore")
        check("P2c_cmd_sentence_untouched",
              M.command_text("بک آپ نمیگیره") == "بک آپ نمیگیره")

        # ── P3: پشتیبان‌گیری → ذخیرهٔ آدرس در meta و cfg ──
        os.environ["BACKUP_CHAT"] = "111"
        m = new_mgr()
        seed(m, 3)
        ok, msg = await m.backup_once(force=True)
        mid = m._backup_msg_id
        meta = {}
        mp = m._backup_meta_path()
        if os.path.isfile(mp):
            with open(mp, encoding="utf-8") as f:
                meta = json.load(f)
        with open(os.path.join(os.environ["DATA_DIR"], "manager_config.json"),
                  encoding="utf-8") as f:
            cfg_on_disk = json.load(f)
        check("P3a_backup_sent", ok and mid, msg)
        check("P3b_meta_has_chat_and_id",
              int(meta.get("msg_id") or 0) == int(mid or 0) and meta.get("chat") == "111",
              meta)
        check("P3c_cfg_has_pointer",
              int(cfg_on_disk.get("backup_msg_id") or 0) == int(mid or 0)
              and str(cfg_on_disk.get("backup_msg_chat") or "") == "111",
              {k: cfg_on_disk.get(k) for k in ("backup_msg_id", "backup_msg_chat")})
        backup_msg = CHATS["111"][0]

        # ── P4: دیسک پاک، بدون هیچ اشاره‌گری → همان خطای گزارش‌شده ──
        wipe()
        try:
            os.remove(M._admin_upload_path())
        except Exception:
            pass
        m2 = new_mgr()
        ok4, msg4 = await m2.restore_from_backup(force=False)
        check("P4_no_pointer_no_restore", (not ok4) and count(m2) == 0,
              "ok=%s msg=%s n=%s" % (ok4, msg4, count(m2)))

        # ── P5: همان حالت، ولی مدیر آیدیِ پیام را می‌دهد (`.restore 12345`) ──
        ok5, msg5 = await m2.restore_from_backup(force=True, ref_msg_id=backup_msg.id)
        check("P5_explicit_ref_restores", ok5 and count(m2) == 3,
              "ok=%s msg=%s n=%s" % (ok5, msg5, count(m2)))
        check("P5b_resume_called", m2._calls["resume"] >= 1, m2._calls)
        check("P5c_pointer_learned_after_ref",
              int(m2.cfg.get("backup_msg_id") or 0) == int(backup_msg.id),
              m2.cfg.get("backup_msg_id"))

        # ── P6: دیسک ماندگار (meta هست) → بدون گشتن در تاریخچه ──
        drop_db()
        m6 = new_mgr()
        ok6, msg6 = await m6.restore_from_backup(force=False)
        check("P6_pointer_from_meta_restores", ok6 and count(m6) == 3,
              "ok=%s msg=%s n=%s" % (ok6, msg6, count(m6)))

        # ── P7: فقط اشاره‌گرِ داخل manager_config.json ──
        try:
            os.remove(os.path.join(os.environ["DATA_DIR"], ".jafj_backup_meta"))
        except Exception:
            pass
        for cand in (".jafj_backup_fp", ".jafj_deploy_id", "jafj_backup_latest.zip"):
            try:
                os.remove(os.path.join(os.environ["DATA_DIR"], cand))
            except Exception:
                pass
        drop_db()
        m7 = new_mgr()
        ok7, msg7 = await m7.restore_from_backup(force=False)
        check("P7_pointer_from_cfg_restores", ok7 and count(m7) == 3,
              "ok=%s msg=%s n=%s" % (ok7, msg7, count(m7)))

        # ── P8: پیامِ گاردِ دیتابیسِ خالی راهِ ریپلای/آیدی را می‌گوید ──
        m8 = new_mgr()
        g = await m8._empty_db_backup_guard("111")
        check("P8_guard_message_has_recovery_hint",
              g and "ریپلای" in g and ".restore" in g, g)

        # ── P9: بعد از بازیابی، تک‌پیام دوباره ساخته/به‌روز می‌شود ──
        m9 = new_mgr()
        try:
            del m9._reanchor_backup          # متدِ واقعیِ کلاس را می‌خواهیم
        except Exception:
            pass
        seed(m9, 2)
        hits = {"n": 0}

        async def _spy(force=False):
            hits["n"] += 1
            return True, "spy"
        m9.backup_once = _spy
        started = m9._reanchor_backup("تست")
        await asyncio.sleep(4.0)
        check("P9a_reanchor_scheduled", started is True)
        check("P9b_reanchor_makes_backup", hits["n"] == 1, hits)

        # گارد: بدون مشتری هیچ پشتیبانی ساخته نمی‌شود (پشتیبانِ خالی نمی‌رود)
        m10 = new_mgr()
        try:
            del m10._reanchor_backup
        except Exception:
            pass
        for uid in (900, 901, 902):
            try:
                m10.db.x("DELETE FROM clients WHERE uid=?", (uid,))
            except Exception:
                pass
        m10.backup_once = _spy
        before = hits["n"]
        m10._reanchor_backup("خالی")
        await asyncio.sleep(4.0)
        check("P9c_reanchor_skips_empty_db", hits["n"] == before, hits)
    except Exception as e:
        import traceback
        traceback.print_exc()
        results["EXCEPTION"] = "%s: %s" % (type(e).__name__, e)

    good = all(v is True for v in results.values()) and "EXCEPTION" not in results
    print("ALL:", "PASS" if good else "FAIL")


asyncio.run(main())
''')


def main():
    shutil.rmtree(ROOT, ignore_errors=True)
    os.makedirs(APP, exist_ok=True)
    os.makedirs(DATA, exist_ok=True)
    os.makedirs(STORE, exist_ok=True)
    for name in ("manager_82.py", "95.py"):
        shutil.copy2(os.path.join(SRC, name), APP)
    tel = os.path.join(APP, "telethon")
    os.makedirs(tel, exist_ok=True)
    with open(os.path.join(tel, "__init__.py"), "w", encoding="utf-8") as f:
        f.write(FAKE_INIT)
    with open(os.path.join(tel, "sessions.py"), "w", encoding="utf-8") as f:
        f.write(FAKE_SESS)
    with open(os.path.join(tel, "errors.py"), "w", encoding="utf-8") as f:
        f.write(FAKE_ERRORS)

    env = dict(os.environ)
    env["DATA_DIR"] = DATA
    env["FAKE_BACKUP_DIR"] = STORE
    env["PORT"] = "8371"
    env["BACKUP_CHAT"] = "111"
    for k in ("BOT_TOKEN", "API_ID", "API_HASH", "ADMIN_IDS", "BACKUP_EVERY"):
        env.pop(k, None)
    p = subprocess.run([sys.executable, "-c", DRIVER], cwd=APP, env=env,
                       capture_output=True, text=True, timeout=180)
    out = p.stdout + p.stderr
    print(out.strip())
    ok = p.returncode == 0 and "ALL: PASS" in out
    shutil.rmtree(ROOT, ignore_errors=True)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
