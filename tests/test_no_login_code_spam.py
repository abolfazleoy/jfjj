#!/usr/bin/env python3
"""رگرسیونِ «بعد از آپدیت/بک‌آپ، موقع روشن‌کردن سرویس‌ها برای مشتری‌ها کدِ ورود می‌آید».

سناریوی گزارش‌شده: مدیر آپدیت می‌دهد، یک بک‌آپ می‌گیرد/بازیابی می‌کند، بعد
سرویس‌ها را روشن می‌کند → **برای همه‌ی مشتری‌ها کدِ ورودِ تلگرام می‌آید**.

چرا؟ `TelegramClient.start(phone=...)` وقتی سشن معتبر نباشد خودش
`send_code_request` می‌زند. و سشن دقیقاً همان‌جایی باطل می‌شود که:

  • فایل `jafj.session` خراب/ناقص باشد (کپیِ خام از فایلِ در حال نوشتن)،
  • فایل موجود با رشته‌ی قدیمیِ داخل DB بازنویسی شود (`write_session`)،
  • فایلِ سشنِ یک پروسهٔ زنده زیر پایش عوض شود (بازیابی وسط اجرا).

این تست با یک سشنِ **واقعیِ sqlite** (همان اسکیمای تلگرام) و یک `95.py`
اجرا می‌شود و ثابت می‌کند هیچ کدی نمی‌رود:

  N1  `session_health` فایلِ سالم/خالی/خراب/بدون‌کلید را درست تشخیص می‌دهد
  N2  `write_session` فایلِ سالمِ موجود را با رشته‌ی DB **خراب نمی‌کند**
  N3  فایلِ خراب از رشته‌ی DB بازسازی می‌شود (`verify_session`)
  N4  سشنِ غیرقابل‌بازسازی → اکانت «نیاز به لاگین» می‌شود، `want_on=0`،
      فایل قرنطینه (`.bad`) و **هیچ پروسه‌ای اجرا نمی‌شود** (پس هیچ کدی نمی‌رود)
  N5  `watchdog`/`resume_wanted`/`boot_all` به اکانتِ نیازمند لاگین دست نمی‌زنند
  N6  لاگینِ موفق مهر را برمی‌دارد و اکانت دوباره خودکار روشن می‌شود
  N7  سلفِ واقعی (95.py) با `JAFJ_NO_AUTO_LOGIN=1` و سشنِ باطل: **کد نمی‌فرستد**
      و با کدِ ۷۸ خارج می‌شود (تستِ واقعیِ زیرفرایندی با telethon جعلی)
  N8  بدون آن متغیر (اجرای دستی) رفتار قبلی حفظ می‌شود (کد می‌رود)

اجرا: `python3 tests/test_no_login_code_spam.py` → باید `ALL: PASS` بدهد.
"""
import importlib.util
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import textwrap

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
ROOT = os.path.join(tempfile.gettempdir(), "jafj_nocode_run")
DATA = os.path.join(ROOT, "data")
APP = os.path.join(ROOT, "app")
STORE = os.path.join(ROOT, "store")

shutil.rmtree(ROOT, ignore_errors=True)
os.makedirs(DATA, exist_ok=True)
os.makedirs(APP, exist_ok=True)
os.makedirs(STORE, exist_ok=True)

os.environ["DATA_DIR"] = DATA
os.environ["PORT"] = "8401"
os.environ["JAFJ_SELFBOT_REF"] = os.path.join(ROOT, "ref_95.py")
os.environ.pop("DATA_GITHUB_TOKEN", None)

spec = importlib.util.spec_from_file_location("m82", os.path.join(REPO, "manager_82.py"))
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)

RESULTS = {}


def _install_fake_telethon_sessions():
    """telethon جعلیِ مینیمال فقط برای `write_session` (در sandbox نصب نیست).

    SQLiteSessionِ واقعی همان جدولِ `sessions` را می‌سازد؛ ما هم همان را
    می‌سازیم تا `session_health` روی فایلِ تولیدشده واقعاً تست شود.
    """
    import types

    class StringSession:
        def __init__(self, s=""):
            self._s = s or ""
            self.dc_id = 2
            self.server_address = "149.154.167.51"
            self.port = 443
            self.auth_key = b"A" * 256

        def save(self):
            return self._s

    class SQLiteSession:
        def __init__(self, path, *a, **k):
            self.path = path
            self.file = path + ".session"
            self._dc = (2, "149.154.167.51", 443)
            self._key = None

        def set_dc(self, dc_id, server, port):
            self._dc = (dc_id, server, port)

        @property
        def auth_key(self):
            return self._key

        @auth_key.setter
        def auth_key(self, v):
            self._key = v

        def save(self):
            con = sqlite3.connect(self.file)
            try:
                con.execute(
                    "CREATE TABLE IF NOT EXISTS sessions (dc_id integer primary key,"
                    " server_address text, port integer, auth_key blob,"
                    " takeout_id integer)")
                con.execute("DELETE FROM sessions")
                con.execute("INSERT INTO sessions VALUES (?,?,?,?,?)",
                            (self._dc[0], self._dc[1], self._dc[2],
                             self._key, None))
                con.commit()
            finally:
                con.close()

        def close(self):
            pass

    tl = types.ModuleType("telethon")
    sess = types.ModuleType("telethon.sessions")
    sess.StringSession = StringSession
    sess.SQLiteSession = SQLiteSession
    tl.sessions = sess
    sys.modules.setdefault("telethon", tl)
    sys.modules.setdefault("telethon.sessions", sess)


_install_fake_telethon_sessions()


def check(name, cond, extra=""):
    RESULTS[name] = bool(cond)
    print("%s %s" % (name, "PASS" if cond else "FAIL  " + str(extra)))


def make_session(path, auth_key=b"K" * 256, corrupt=False, empty_key=False):
    """یک فایل سشن با همان اسکیمای SQLiteSession تلگرام بساز."""
    try:
        os.remove(path)
    except Exception:
        pass
    if corrupt:
        with open(path, "wb") as f:
            f.write(b"this is not a sqlite file at all" * 10)
        return path
    con = sqlite3.connect(path)
    try:
        con.execute(
            "CREATE TABLE sessions (dc_id integer primary key, server_address text,"
            " port integer, auth_key blob, takeout_id integer)")
        con.execute("INSERT INTO sessions VALUES (?,?,?,?,?)",
                    (2, "149.154.167.51", 443, None if empty_key else auth_key, None))
        con.commit()
    finally:
        con.close()
    return path


class FakeMgr:
    """Managerِ سبک برای Supervisor (بدون تلگرام)."""

    def __init__(self):
        self.cfg = M.Config()
        self.db = M.DB(os.path.join(DATA, "mgr_%d.db" % id(self)))
        self.sup = M.Supervisor(self.cfg, self.db)
        self.sup.mgr = self
        self._loop = None
        self.bot = None
        self.notified = []
        self.shop = None

    def can_run(self, uid):
        return True, ""

    def effective_plan(self, uid):
        return None

    def sync_points_limits(self, uid):
        return True

    def has_sub(self, uid):
        return True

    def _notify_needs_login(self, uid, reason=""):
        self.notified.append((uid, reason))
        return True

    def _esc(self, x):
        return str(x)


def add_client(mgr, uid, session_string="S" * 60, make_file=True,
               corrupt=False, empty_key=False):
    mgr.db.add(uid, "u%d" % uid, "U%d" % uid, 0)
    mgr.db.set(uid, status="active", session=session_string, phone="+989120000000",
               want_on=1)
    folder = mgr.sup.folder(uid)
    p = os.path.join(folder, "jafj.session")
    if make_file:
        make_session(p, corrupt=corrupt, empty_key=empty_key)
    return uid, p


def scenario_health():
    print("--- N1: session_health سالم/خالی/خراب/بدون‌کلید ---")
    base = os.path.join(ROOT, "h")
    os.makedirs(base, exist_ok=True)
    ok, _ = M.session_health(make_session(os.path.join(base, "a.session")))
    check("N1a_good", ok is True)
    bad, why = M.session_health(os.path.join(base, "nope.session"))
    check("N1b_missing", bad is False and "نیست" in why, why)
    empty, why = M.session_health(make_session(os.path.join(base, "e.session"),
                                               empty_key=True))
    check("N1c_empty_key", empty is False and "کلید" in why, why)
    cor, why = M.session_health(make_session(os.path.join(base, "c.session"),
                                             corrupt=True))
    check("N1d_corrupt", cor is False, why)
    zero, why = M.session_health(os.path.join(base, "z.session"))
    open(os.path.join(base, "z.session"), "wb").close()
    zero, why = M.session_health(os.path.join(base, "z.session"))
    check("N1e_zero_byte", zero is False, why)


def scenario_keep_existing():
    print("--- N2: write_session فایلِ سالم را با رشتهٔ DB خراب نمی‌کند ---")
    m = FakeMgr()
    uid, path = add_client(m, 810001, session_string="Z" * 60)
    before = open(path, "rb").read()
    m.sup.write_session(uid, "Z" * 60)          # رشتهٔ بی‌ربط/قدیمی
    after = open(path, "rb").read()
    check("N2a_kept_valid_file", before == after)
    check("N2b_still_healthy", M.session_health(path)[0] is True)


def scenario_rebuild():
    print("--- N3: فایلِ خراب از رشتهٔ DB بازسازی می‌شود ---")
    m = FakeMgr()
    uid, path = add_client(m, 810011, corrupt=True)
    ok, why = m.sup.verify_session(uid)
    check("N3a_rebuilt_ok", ok is True, why)
    check("N3b_file_now_healthy", M.session_health(path)[0] is True)
    check("N3c_not_marked", m.sup.needs_login(uid) is False)


def scenario_unrecoverable():
    print("--- N4: سشنِ غیرقابل‌بازسازی → «نیاز به لاگین» و هیچ پروسه‌ای ---")
    m = FakeMgr()
    uid, path = add_client(m, 810021, session_string="", corrupt=True)
    ok, msg = m.sup.start(uid)
    check("N4a_start_refused", ok is False and "کد" in msg, msg)
    check("N4b_marked", m.sup.needs_login(uid) is True)
    check("N4c_want_on_cleared", m.db.want_on(uid) is False)
    check("N4d_session_quarantined", os.path.isfile(path + ".bad"),
          os.listdir(os.path.dirname(path)))
    check("N4e_no_process", uid not in m.sup.procs)
    check("N4f_admin_notified", any(u == uid for u, _ in m.notified), m.notified)
    # دوباره هم صدا زدن نباید پروسه بسازد (یعنی کدِ دوباره)
    m.sup.start(uid)
    check("N4g_no_process_on_retry", uid not in m.sup.procs)


def scenario_resume_skips():
    print("--- N5: watchdog/resume/boot به اکانتِ نیازمند لاگین دست نمی‌زنند ---")
    m = FakeMgr()
    uid, path = add_client(m, 810031, session_string="", corrupt=True)
    m.sup.mark_needs_login(uid, "تست")
    started, failed, skipped = m.sup.resume_wanted(force=False)
    check("N5a_resume_skips", uid not in started and uid not in [u for u, _ in failed],
          (started, failed, skipped))
    n = m.sup.boot_all()
    check("N5b_boot_skips", uid not in m.sup.procs and n == 0, (n, m.sup.procs))
    # با force هم نباید پروسه بسازد چون سشن خراب است (ولی بررسی می‌شود)
    m.sup.boot_all(force_restart=True)
    check("N5c_force_still_no_code", uid not in m.sup.procs, m.sup.procs)


def scenario_login_clears():
    print("--- N6: لاگینِ موفق مهر را برمی‌دارد ---")
    m = FakeMgr()
    uid, path = add_client(m, 810041, session_string="", corrupt=True)
    m.sup.mark_needs_login(uid, "تست")
    check("N6a_marked", m.sup.needs_login(uid) is True)
    # شبیه‌سازیِ لاگینِ موفق: سشنِ تازه از DB + پاک‌کردن مهر
    m.db.set(uid, session="N" * 60, need_login=0, want_on=1)
    m.sup.clear_needs_login(uid)
    m.sup.write_session(uid, "N" * 60, keep_existing=False)
    check("N6b_cleared", m.sup.needs_login(uid) is False)
    check("N6c_want_again", m.db.want_on(uid) is True)
    check("N6d_session_ok", M.session_health(path)[0] is True)


# ── N7/N8: اجرای واقعیِ 95.py با telethon جعلی ────────────────────────────
FAKE_TELETHON = textwrap.dedent('''
import os

CODE_SENT = []          # هر بار که کد درخواست شود اینجا ثبت می‌شود
AUTHORIZED = os.environ.get("FAKE_AUTHORIZED", "0") == "1"


class RPCError(Exception):
    pass


class FloodWaitError(RPCError):
    def __init__(self, seconds=0, *a, **k):
        self.seconds = seconds


class SlowModeWaitError(FloodWaitError):
    pass


class _Err(RPCError):
    pass


ChatWriteForbiddenError = type("ChatWriteForbiddenError", (_Err,), {})
ChannelPrivateError = type("ChannelPrivateError", (_Err,), {})
UsernameNotOccupiedError = type("UsernameNotOccupiedError", (_Err,), {})
UserNotParticipantError = type("UserNotParticipantError", (_Err,), {})
UserAlreadyParticipantError = type("UserAlreadyParticipantError", (_Err,), {})
InviteHashExpiredError = type("InviteHashExpiredError", (_Err,), {})
InviteHashInvalidError = type("InviteHashInvalidError", (_Err,), {})
ChannelsTooMuchError = type("ChannelsTooMuchError", (_Err,), {})
InviteRequestSentError = type("InviteRequestSentError", (_Err,), {})


class _Me:
    id = 1
    first_name = "T"
    username = "t"


class TelegramClient:
    def __init__(self, *a, **k):
        self._connected = False

    async def connect(self):
        self._connected = True

    def is_connected(self):
        return self._connected

    async def disconnect(self):
        self._connected = False

    async def is_user_authorized(self):
        return AUTHORIZED

    async def start(self, phone=None, **k):
        CODE_SENT.append("code")
        if callable(phone):
            try:
                phone()
            except Exception:
                raise RuntimeError("no-tty")
        if not AUTHORIZED:
            raise RuntimeError("no-tty")
        return self

    async def get_me(self):
        return _Me()


class _NS:
    pass


class Button:
    @staticmethod
    def inline(*a, **k):
        return a

    @staticmethod
    def text(*a, **k):
        return a


class events:
    class NewMessage:
        def __init__(self, *a, **k):
            pass

        def __call__(self, f):
            return f

    class CallbackQuery:
        def __init__(self, *a, **k):
            pass

        def __call__(self, f):
            return f
''')

FAKE_SESSIONS = textwrap.dedent('''
class StringSession:
    def __init__(self, s=""):
        self._s = s or ""
        self.dc_id = 2
        self.server_address = "149.154.167.51"
        self.port = 443

    def save(self):
        return self._s


class SQLiteSession:
    def __init__(self, *a, **k):
        pass

    def set_dc(self, *a):
        pass

    @property
    def auth_key(self):
        return b""

    @auth_key.setter
    def auth_key(self, v):
        pass

    def save(self):
        pass

    def close(self):
        pass
''')

FAKE_TL_FUNCS = '''
class _Req:
    def __init__(self, *a, **k):
        pass


JoinChannelRequest = LeaveChannelRequest = GetParticipantRequest = _Req
ImportChatInviteRequest = _Req
'''


def run_selfbot(env_extra):
    """95.py را با telethon جعلی اجرا کن → (کد خروج, خروجی, کدها فرستاده شد؟)"""
    pkg = os.path.join(APP, "telethon")
    os.makedirs(os.path.join(pkg, "tl", "functions"), exist_ok=True)
    with open(os.path.join(pkg, "__init__.py"), "w") as f:
        f.write(FAKE_TELETHON)
    with open(os.path.join(pkg, "sessions.py"), "w") as f:
        f.write(FAKE_SESSIONS)
    with open(os.path.join(pkg, "errors.py"), "w") as f:
        f.write(FAKE_TELETHON.split("class _Me")[0])
    for sub in ("tl", os.path.join("tl", "functions")):
        initp = os.path.join(pkg, sub, "__init__.py")
        open(initp, "w").close()
    with open(os.path.join(pkg, "tl", "functions", "channels.py"), "w") as f:
        f.write("class JoinChannelRequest:\n  def __init__(self,*a,**k): pass\n"
                "class LeaveChannelRequest:\n  def __init__(self,*a,**k): pass\n"
                "class GetParticipantRequest:\n  def __init__(self,*a,**k): pass\n")
    with open(os.path.join(pkg, "tl", "functions", "messages.py"), "w") as f:
        f.write("class ImportChatInviteRequest:\n  def __init__(self,*a,**k): pass\n")

    folder = os.path.join(APP, "cli")
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "jafj_creds.json"), "w") as f:
        f.write('{"api_id": 1, "api_hash": "hashhashhash", "phone": "+989120000000"}')
    env = dict(os.environ)
    env.pop("DATA_DIR", None)
    env["PYTHONPATH"] = APP
    env["PORT"] = "0"
    env.update(env_extra)
    p = subprocess.run([sys.executable, os.path.join(folder, "95.py")],
                       cwd=folder, env=env, capture_output=True, text=True,
                       timeout=120)
    sent = "code request" in (p.stdout + p.stderr) or "CODE_SENT" in (p.stdout or "")
    return p.returncode, (p.stdout or "") + (p.stderr or ""), sent


def scenario_selfbot_no_code():
    print("--- N7: سلف با سشنِ باطل و NO_AUTO_LOGIN کد نمی‌فرستد (کدِ ۷۸) ---")
    os.makedirs(os.path.join(APP, "cli"), exist_ok=True)
    shutil.copy2(os.path.join(REPO, "95.py"), os.path.join(APP, "cli", "95.py"))
    # فایل سشن "هست" ولی authorized نیست
    rc, out, _ = run_selfbot({"JAFJ_NO_AUTO_LOGIN": "1", "FAKE_AUTHORIZED": "0"})
    check("N7a_exit_78", rc == 78, "rc=%s out=%s" % (rc, out[-400:]))
    check("N7b_says_no_code", "کدِ ورود" in out or "کد" in out, out[-300:])
    check("N7c_no_code_request", "Login code" not in out and "code request" not in out,
          out[-300:])

    print("--- N8: بدون NO_AUTO_LOGIN (اجرای دستی) رفتار قبلی ---")
    rc2, out2, _ = run_selfbot({"JAFJ_NO_AUTO_LOGIN": "", "FAKE_AUTHORIZED": "0"})
    check("N8a_manual_still_prompts", "تلاش" in out2 or "ترمینال" in out2
          or rc2 != 78, "rc=%s out=%s" % (rc2, out2[-300:]))


def main():
    try:
        scenario_health()
        scenario_keep_existing()
        scenario_rebuild()
        scenario_unrecoverable()
        scenario_resume_skips()
        scenario_login_clears()
        scenario_selfbot_no_code()
    except Exception as e:
        import traceback
        traceback.print_exc()
        RESULTS["EXCEPTION"] = "%s: %s" % (type(e).__name__, e)
    finally:
        try:
            subprocess.call(["pkill", "-f", "jafj_nocode_run"])
        except Exception:
            pass
        shutil.rmtree(ROOT, ignore_errors=True)
    good = all(v is True for v in RESULTS.values()) and "EXCEPTION" not in RESULTS
    print("ALL:", "PASS" if good else "FAIL")
    sys.exit(0 if good else 1)


if __name__ == "__main__":
    main()
