#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ═══════════════════════════════════════════════════════════════════════════
#  JAFJ — main.py  (راه‌انداز برای میزبان‌های «اپ پایتونی»: Wispbyte،
#                   Hostless python build، هر جایی که فقط یک دستور شروع
#                   مثل `python main.py` می‌گیرد)
#
#  کاری که می‌کند:
#    ۰) «چک‌لیست بوت» را چاپ می‌کند (git، پایتون، telethon، دسترسیِ نوشتن،
#       فایل‌های ریپو، پورت، نمونه‌ی دوم) → هر چیزی کم باشد همان‌جا معلوم است
#    ۱) کد را از گیت‌هاب می‌گیرد/به‌روز می‌کند      → ./code
#    ۲) محیط پایتون و وابستگی‌ها را می‌سازد          → ./venv
#    ۳) داده‌ها را در یک پوشه‌ی جدا نگه می‌دارد       → ./data
#    ۴) اجرا با یکی از سه حالت (JAFJ_ONLY):
#
#         JAFJ_ONLY=manager  (پیش‌فرض)
#             entrypointِ خودِ ریپو (railway-start.sh) را اجرا می‌کند:
#             supervisor + manager_82.py. سلفِ هر اکانت را خودِ مدیر، بعد از
#             لاگین، در data/clients/<uid>/ بالا می‌آورد.
#
#         JAFJ_ONLY=both      + JAFJ_SELF_UID=<uid>
#             مدیر بالا می‌آید، و علاوه بر آن سلفِ همان یک اکانت هم مستقیماً
#             اجرا می‌شود و خروجی‌اش در همین لاگِ سایت می‌آید. اگر مدیر از
#             قبل خودش آن سلف را روشن کرده باشد، دوباره اجرا نمی‌شود
#             (دو سلف روی یک سشن = سشن خراب).
#
#         JAFJ_ONLY=self       + JAFJ_SELF_UID=<uid>  (یا JAFJ_SELF_DIR)
#             فقط سلف؛ مدیر اجرا نمی‌شود. برای تستِ اینکه 95.py سالم است.
#
#  بررسیِ سریع بدونِ اجرای ربات:   python main.py --check
#  (یا JAFJ_CHECK_ONLY=1) — چک‌لیست را چاپ می‌کند و خارج می‌شود.
# ═══════════════════════════════════════════════════════════════════════════

import hashlib
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.chdir(HERE)

DEFAULT_REPO = "abolfazleoy/jfjj"
DEFAULT_BRANCH = "main"

CODE_DIR = HERE / "code"
DEFAULT_DATA = HERE / "data"
VENV_DIR = HERE / "venv"

MANAGER_NAME = "manager_82.py"
SELF_NAME = "95.py"
ENTRY_NAME = "railway-start.sh"      # entrypointِ مشترکِ ریپو (supervisor)

CHECK_LINES = []                     # برای نوشتن در data/boot.log


# ───────────────────────────────────────────────────────────── helpers ──
def log(msg):
    line = f"JAFJ-BOOT: {msg}"
    CHECK_LINES.append(line)
    print(line, flush=True)


def die(msg, code=1):
    line = f"JAFJ-BOOT: ❌ {msg}"
    CHECK_LINES.append(line)
    print(line, flush=True)
    flush_boot_log(None)
    sys.exit(code)


def check(label, ok, detail=""):
    """یک سطر از چک‌لیستِ بوت + ثبت برای data/boot.log."""
    line = f"JAFJ-CHECK: {'✅' if ok else '❌'} {label}" + (
        f" — {detail}" if detail else "")
    CHECK_LINES.append(line)
    print(line, flush=True)
    return ok


def flush_boot_log(data_dir):
    """چک‌لیست در data/boot.log هم بماند (برای فرستادن به پشتیبانی)."""
    try:
        d = Path(data_dir or data_dir_path())
        d.mkdir(parents=True, exist_ok=True)
        with open(d / "boot.log", "w", encoding="utf-8") as f:
            f.write("\n".join(CHECK_LINES) + "\n")
    except Exception:
        pass


def data_dir_path():
    return Path(os.environ.get("DATA_DIR") or DEFAULT_DATA).expanduser().resolve()


def repo():
    """repo از محیط، در لحظه‌ی صدا زدن خوانده می‌شود (نه فقط در import)."""
    return (os.environ.get("JAFJ_REPO") or DEFAULT_REPO).strip()


def branch():
    return (os.environ.get("JAFJ_BRANCH") or DEFAULT_BRANCH).strip() or DEFAULT_BRANCH


def token():
    return (os.environ.get("JAFJ_GIT_TOKEN") or "").strip()      # ریپوی خصوصی


def repo_url():
    """آدرس کلون. اگر JAFJ_REPO خودش URL یا مسیر باشد، همان استفاده می‌شود."""
    r, t = repo(), token()
    if "://" in r or r.startswith(("/", "./", "git@")):
        return r
    if t:
        return f"https://{t}@github.com/{r}.git"
    return f"https://github.com/{r}.git"


def shown(url):
    """آدرس را برای لاگ امن می‌کند (توکن چاپ نشود)."""
    t = token()
    return "https://github.com/***@…" if t and t in url else url


def run(cmd, cwd=None, env=None, quiet=False):
    """اجرای دستور؛ اگر خودِ برنامه نصب نباشد پیامِ روشن می‌دهد (نه Traceback)."""
    log("$ " + " ".join(str(c) for c in cmd))
    out = subprocess.DEVNULL if quiet else None
    try:
        return subprocess.run(
            [str(c) for c in cmd], cwd=str(cwd) if cwd else None, env=env,
            stdout=out, stderr=out,
        )
    except FileNotFoundError:
        die(f"دستور «{cmd[0]}» روی این میزبان نصب نیست. "
            f"اگر {cmd[0]} از لازمه‌های ایمیج است، ایمیج/بیلدِ میزبان را عوض کن.")
        return None


# ─────────────────────────────────────────────────── 0) چک‌لیستِ بوت ──
def mode():
    """manager (پیش‌فرض) | both | self  — هم JAFJ_ONLY و هم JAFJ_BOOT."""
    m = (os.environ.get("JAFJ_ONLY") or os.environ.get("JAFJ_BOOT") or "").strip().lower()
    if m in ("1", "true", "yes", "all", "both", "هر دو", "هردو"):
        return "both"
    if m in ("self", "selfbot", "سلف"):
        return "self"
    return "manager"


def self_uid():
    return (os.environ.get("JAFJ_SELF_UID") or "").strip()


def self_folder(data_dir):
    """پوشه‌ی اکانتی که سلفش را جدا اجرا می‌کنیم."""
    d = (os.environ.get("JAFJ_SELF_DIR") or "").strip()
    if d:
        return Path(d).expanduser().resolve()
    if self_uid():
        return Path(data_dir) / "clients" / self_uid()
    return None


def boot_report(py, env):
    """هر چیزی که «چرا بالا نیامد» را می‌تواند بسازد، همان اول چک می‌شود."""
    log(f"host={env.get('JAFJ_HOST_LABEL', 'wispbyte')} "
        f"python={sys.version.split()[0]} dir={HERE} mode={mode()}")
    check("پایتون ۳.۸+", sys.version_info >= (3, 8),
          f"{sys.version.split()[0]}")
    check("git نصب است", bool(shutil.which("git")), shutil.which("git") or "پیدا نشد")
    check("پوشه‌ی اپ نوشتنی است", os.access(HERE, os.W_OK), str(HERE))
    d = Path(env["DATA_DIR"])
    try:
        d.mkdir(parents=True, exist_ok=True)
        probe = d / ".jafj_write_test"
        probe.write_text("ok")
        probe.unlink()
        check("پوشه‌ی داده نوشتنی است", True, str(d))
    except Exception as e:
        check("پوشه‌ی داده نوشتنی است", False, f"{d}: {e}")
    try:
        du = shutil.disk_usage(str(d if d.exists() else HERE))
        check("فضای خالی دیسک", du.free > 200 * 1024 * 1024,
              f"{du.free // (1024 * 1024)}MB آزاد")
    except Exception:
        pass
    check("کد ریپو موجود است",
          all((CODE_DIR / n).is_file() for n in (MANAGER_NAME, SELF_NAME)),
          str(CODE_DIR))
    check("entrypoint ریپو موجود است", (CODE_DIR / ENTRY_NAME).is_file(), ENTRY_NAME)
    try:
        ok_dep = subprocess.run([str(py), "-c", "import telethon"],
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL).returncode == 0
    except Exception:
        ok_dep = False
    check("telethon در مفسرِ اجرا نصب است", ok_dep, str(py))
    if os.environ.get("PORT"):
        check("PORT از میزبان رسیده", True, os.environ["PORT"])
    # نمونه‌ی دوم: دو مدیر روی یک پوشه‌ی داده = پیام‌های تکراری و سشن خراب
    lock = d / "bot.lock"
    if lock.is_file():
        try:
            pid = int(lock.read_text().strip() or 0)
            alive = bool(pid) and pid != os.getpid()
            if alive:
                try:
                    os.kill(pid, 0)
                except OSError:
                    alive = False
            if alive:
                check("نمونه‌ی دومی از مدیر در حال اجراست", False,
                      f"pid={pid} (همان توکن/همان سشن — اول آن را ببند)")
        except Exception:
            pass
    if mode() in ("self", "both"):
        f = self_folder(env["DATA_DIR"])
        if f is None:
            check("حالتِ سلف: پوشه‌ی اکانت", False,
                  "JAFJ_SELF_UID یا JAFJ_SELF_DIR را بده")
        else:
            has = (f / "jafj_creds.json").exists() and (f / "jafj.session").exists()
            check("حالتِ سلف: creds/session اکانت", has,
                  str(f) + ("" if has else " — اول از پنلِ مدیر لاگین کن"))
    flush_boot_log(env["DATA_DIR"])
    return env


# ─────────────────────────────────────────────────────── 1) code from git ──
def sync_code():
    CODE_DIR.parent.mkdir(parents=True, exist_ok=True)
    url = repo_url()

    if not (CODE_DIR / ".git").exists():
        if CODE_DIR.exists():
            shutil.rmtree(CODE_DIR, ignore_errors=True)
        log(f"cloning {shown(url)} (branch {branch()}) → {CODE_DIR}")
        args = ["git", "clone", "--depth", "1", "--branch", branch(), url, str(CODE_DIR)]
        r = run(args)
        if r is None or r.returncode != 0:
            # شاید برنچ وجود ندارد → برنچ پیش‌فرض را بگیر
            log(f"branch «{branch()}» clone نشد — با برنچ پیش‌فرض امتحان می‌کنم")
            r2 = run(["git", "clone", "--depth", "1", url, str(CODE_DIR)])
            if r2 is None or r2.returncode != 0:
                die("git clone نشد. JAFJ_REPO / JAFJ_BRANCH / JAFJ_GIT_TOKEN را چک کن "
                    "(یا میزبان دسترسی به گیت‌هاب ندارد).")
    else:
        log("code موجود است — به‌روزرسانی…")
        r = run(["git", "-C", str(CODE_DIR), "fetch", "--depth", "1",
                 "origin", branch()])
        if r is not None and r.returncode == 0:
            run(["git", "-C", str(CODE_DIR), "reset", "--hard", "FETCH_HEAD"])
            # فایل‌های جامانده‌ی نسخه‌های قبلی (مثل 78.py قدیمی) پاک شوند
            run(["git", "-C", str(CODE_DIR), "clean", "-fdq"])
        else:
            log("⚠️ git fetch نشد — با نسخه‌ی موجود ادامه می‌دهم")

    for need in (MANAGER_NAME, SELF_NAME):
        if not (CODE_DIR / need).is_file():
            die(f"{need} در ریپو نیست ({CODE_DIR}) — ریپو/برنچ را چک کن.")
    for sh in CODE_DIR.glob("*.sh"):
        try:
            os.chmod(sh, 0o755)
        except Exception:
            pass


# ───────────────────────────────────────────────── 2) venv + dependencies ──
def req_hash():
    f = CODE_DIR / "requirements.txt"
    return hashlib.sha256(f.read_bytes()).hexdigest() if f.is_file() else ""


def stamp_file():
    return VENV_DIR / ".reqhash"


def deps_ok(py):
    try:
        r = subprocess.run([str(py), "-c", "import telethon"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return r.returncode == 0
    except Exception:
        return False


def install_deps(py):
    if not (CODE_DIR / "requirements.txt").is_file():
        log("requirements.txt نیست — از telethon استفاده می‌کنم")
        run([str(py), "-m", "pip", "install", "--disable-pip-version-check",
             "-q", "telethon>=1.34.0"], quiet=False)
        return True
    run([str(py), "-m", "pip", "install", "--disable-pip-version-check",
         "--upgrade", "pip"], quiet=True)
    r = run([str(py), "-m", "pip", "install", "--disable-pip-version-check",
             "-r", str(CODE_DIR / "requirements.txt")])
    return r is not None and r.returncode == 0


def ensure_python():
    if os.environ.get("JAFJ_SKIP_VENV", "").strip() in ("1", "true", "yes"):
        py = Path(sys.executable)
        log(f"venv رد شد (JAFJ_SKIP_VENV=1) — python={py}")
        if not deps_ok(py):
            install_deps(py)
        return py

    py = VENV_DIR / "bin" / "python"
    if not py.exists():
        log("ساخت محیط مجازی…")
        r = run([sys.executable, "-m", "venv", str(VENV_DIR)])
        if r is None or r.returncode != 0:
            log("⚠️ venv ساخته نشد — با پایتون سیستم ادامه می‌دهم")
            py = Path(sys.executable)
            if not deps_ok(py):
                install_deps(py)
            return py
        if not install_deps(py):
            die("نصب وابستگی‌ها شکست خورد (pip install -r requirements.txt)")
        stamp_file().write_text(req_hash())
        return py

    want = req_hash()
    have = stamp_file().read_text().strip() if stamp_file().exists() else ""
    if want != have or not deps_ok(py):
        log("وابستگی‌ها تغییر کرده/ناقص است — نصب دوباره…")
        if not install_deps(py):
            log("⚠️ pip install شکست خورد — با نسخه‌ی فعلی ادامه می‌دهم")
        else:
            stamp_file().write_text(want)
    else:
        log("وابستگی‌ها به‌روز است.")
    return py


# ───────────────────────────────────────────────── 3) environment wiring ──
def build_env(py):
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["JAFJ_HOSTED"] = env.get("JAFJ_HOSTED", "1")
    env["JAFJ_HOST_LABEL"] = env.get("JAFJ_HOST_LABEL", "wispbyte")
    env["JAFJ_IMAGE_DIR"] = str(CODE_DIR)          # کد: غیرقابل‌تغییر
    d = data_dir_path()
    env["JAFJ_APP_DIR"] = str(d)                   # داده: پایدار (در حد امکان)
    env["DATA_DIR"] = str(d)
    env["JAFJ_SELFBOT_REF"] = str(CODE_DIR / SELF_NAME)
    env["JAFJ_SUPERVISE"] = env.get("JAFJ_SUPERVISE", "1")
    env["JAFJ_KEEP_ALIVE"] = env.get("JAFJ_KEEP_ALIVE", "1")
    env["PORT"] = env.get("PORT", "8080")
    env["PATH"] = str(Path(py).parent) + os.pathsep + env.get("PATH", "")
    # PATH مهم است: 95.py برای نصب خودکار telethon (اگر لازم شد) از همین
    # مفسر استفاده می‌کند و manager هم sys.executable را به ارث می‌برد.
    return env


def check_layout(env):
    d = Path(env["DATA_DIR"])
    try:
        d.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    if Path(env["DATA_DIR"]).resolve() == CODE_DIR.resolve():
        log("⚠️ داده و کد در یک پوشه‌اند — با هر دیپلوی داده پاک می‌شود."
            " DATA_DIR را به یک مسیر پایدار (مثلاً /data) بده.")
    return env


def dry_run(env):
    return env.get("JAFJ_DRY_RUN", "").strip() in ("1", "true", "yes")


# ───────────────────────────── 4a) حالت manager: supervisor + مدیر ────────
def manager_argv():
    """(argv, cwd, label) برای بالا آوردنِ مدیر."""
    entry = CODE_DIR / ENTRY_NAME
    if entry.is_file():
        return ["sh", str(entry)], str(data_dir_path()), "railway-start.sh (supervisor)"
    return [str(CODE_DIR / MANAGER_NAME)], str(CODE_DIR), "manager_82.py (بدون supervisor)"


def start_manager(py, env):
    argv, cwd, label = manager_argv()
    if dry_run(env):
        log(f"DRY-RUN: {argv}  cwd={cwd}  ({label})")
        return 0
    log(f"اجرای {label}…")
    os.chdir(cwd)
    if argv[0] == "sh":
        # supervisor خودش مدیر را با pythonِ PATH (یعنی venv) اجرا می‌کند
        os.execve("/bin/sh", argv, env)
    os.execve(str(py), [str(py), str(CODE_DIR / MANAGER_NAME)], env)


# ───────────────────────── 4b) حالت self: فقط سلفِ یک اکانت ───────────────
def health_server(port):
    """میزبان‌های اپ‌پایتونی منتظر شنونده روی PORT‌اند؛ سلف سرور ندارد."""
    try:
        from http.server import BaseHTTPRequestHandler, HTTPServer

        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                body = b'{"ok": true, "mode": "selfbot"}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        srv = HTTPServer(("0.0.0.0", int(port)), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        log(f"health server روی 0.0.0.0:{port}")
    except Exception as e:
        log(f"⚠️ health server بالا نیامد: {e}")


def self_ready(folder):
    return (folder / "jafj_creds.json").is_file() and (folder / "jafj.session").is_file()


def self_running(folder):
    """آیا همین حالا یک سلف روی این پوشه زنده است؟ (پروسه‌ی خودِ مدیر)"""
    try:
        pid = int((folder / ".jafj_self.pid").read_text().strip() or 0)
    except Exception:
        return False
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            cmd = f.read().replace(b"\x00", b" ").decode("utf-8", "ignore")
        return SELF_NAME in cmd
    except Exception:
        return False


def supervise_selfbot(py, env, folder, stop_event=None):
    """سلف را با ری‌استارتِ پله‌ای اجرا کن؛ خروجی‌اش در همین لاگ می‌آید."""
    if not self_ready(folder):
        log(f"⚠️ سلفِ {folder} آماده نیست: "
            f"jafj_creds.json={'✅' if (folder / 'jafj_creds.json').exists() else '❌'} "
            f"jafj.session={'✅' if (folder / 'jafj.session').exists() else '❌'}")
        return 1
    selfbot = Path(env["JAFJ_SELFBOT_REF"])
    dst = folder / SELF_NAME
    try:
        if (not dst.exists()) or dst.stat().st_size != selfbot.stat().st_size:
            shutil.copy2(selfbot, dst)
    except Exception:
        pass
    e = dict(env)
    e.setdefault("JAFJ_NO_AUTO_LOGIN", "1")
    backoff, child = 5, None
    while stop_event is None or not stop_event.is_set():
        child = subprocess.Popen([str(py), SELF_NAME], cwd=str(folder), env=e,
                                 stdin=subprocess.DEVNULL)
        log(f"selfbot pid={child.pid} cwd={folder}")
        started = time.time()
        rc = child.wait()
        if stop_event is not None and stop_event.is_set():
            return 0
        if rc == 0:
            log("سلف تمیز بسته شد.")
            return 0
        if rc == 78:
            log("❌ سشنِ این اکانت باطل است (کد ۷۸) — از پنلِ مدیر دوباره لاگین کن.")
            return 78
        up = time.time() - started
        backoff = 5 if up > 120 else min(backoff * 2, 120)
        log(f"selfbot با کد {rc} بست ({int(up)}s) — {backoff} ثانیه بعد دوباره")
        if stop_event is not None:
            stop_event.wait(backoff)
        else:
            time.sleep(backoff)
    return 0


def start_self_only(py, env):
    folder = self_folder(env["DATA_DIR"])
    if folder is None:
        die("JAFJ_ONLY=self دادي ولي JAFJ_SELF_UID يا JAFJ_SELF_DIR ندادي.")
    folder = Path(folder)
    log(f"اجرای سلفِ تنها — cwd={folder}")
    if not self_ready(folder):
        die(f"پوشه‌ی این اکانت آماده نیست ({folder}): "
            f"jafj_creds.json={'✅' if (folder / 'jafj_creds.json').exists() else '❌'} "
            f"jafj.session={'✅' if (folder / 'jafj.session').exists() else '❌'} — "
            "اول در حالتِ عادی (manager) از «🚀 راه‌اندازی سلف روی اکانتم» لاگین کن.")
    if dry_run(env):
        log(f"DRY-RUN: python {SELF_NAME} (cwd={folder})")
        return 0
    health_server(env["PORT"])
    return supervise_selfbot(py, env, folder)


# ─────────────────── 4c) حالت both: مدیر + سلفِ همین یک اکانت ─────────────
def db_row(data_dir, uid):
    """یک ردیف از clients (فقط‌خواندنی) — برای گزارشِ وضعیت در لاگ."""
    try:
        import sqlite3
        db = Path(data_dir) / "manager.db"
        if not db.is_file() or not uid:
            return {}
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5)
        con.row_factory = sqlite3.Row
        try:
            r = con.execute("SELECT status, want_on, need_login, started_at"
                            " FROM clients WHERE uid=?", (int(uid),)).fetchone()
            return dict(r) if r else {}
        finally:
            con.close()
    except Exception:
        return {}


def db_set_want_on(data_dir, uid, value):
    """«نیتِ روشن‌بودن» اکانت را از دیتابیسِ مدیر عوض کن (برای takeover)."""
    try:
        import sqlite3
        db = Path(data_dir) / "manager.db"
        if not db.is_file() or not uid:
            return False
        con = sqlite3.connect(str(db), timeout=10)
        try:
            con.execute("UPDATE clients SET want_on=? WHERE uid=?",
                        (1 if value else 0, int(uid)))
            con.commit()
        finally:
            con.close()
        return True
    except Exception as e:
        log(f"⚠️ عوض‌کردنِ want_on ممکن نشد: {type(e).__name__}: {e}")
        return False


def last_log_lines(folder, n=8):
    try:
        txt = (Path(folder) / "run.log").read_text(encoding="utf-8", errors="ignore")
        lines = [ln for ln in txt.splitlines() if ln.strip()]
        return lines[-n:]
    except Exception:
        return []


def self_diagnostic(env, folder):
    """یک بلوکِ روشن: چرا سلف بالا نیامده (بدونِ دست‌زدن به چیزی)."""
    row = db_row(env["DATA_DIR"], self_uid())
    log(f"—— وضعیتِ سلفِ {folder} ——")
    log(f"   creds={'✅' if (folder / 'jafj_creds.json').exists() else '❌'} "
        f"session={'✅' if (folder / 'jafj.session').exists() else '❌'} "
        f"pidfile={'✅' if (folder / '.jafj_self.pid').exists() else '—'} "
        f"alive={self_running(folder)}")
    if row:
        log(f"   دیتابیس: status={row.get('status')} want_on={row.get('want_on')} "
            f"need_login={row.get('need_login')}")
    for ln in last_log_lines(folder):
        log(f"   | {ln}")
    # سه نشانه‌ای که «چرا بالا نمی‌آید» را در یک نگاه جواب می‌دهند:
    bad = folder / "jafj.session.bad"
    if bad.exists():
        log("   ⛔ سشنِ قبلی قرنطینه شده (jafj.session.bad): تلگرام کلیدش را "
            "باطل کرده یا لاگین باطل شده — این فایل به کار نمی‌آید و باید "
            "یک‌بار از پنل دوباره لاگین شود.")
    lock = folder / "jafj.run.lock"
    if lock.exists():
        try:
            lp = (lock.read_text(encoding="utf-8") or "").strip() or "?"
        except Exception:
            lp = "?"
        log(f"   🔒 قفلِ اجرا موجود است (pid={lp}) — اگر پروسه‌ای با این PID "
            f"زنده نیست، فایل را پاک کن تا نسخه‌ی بعدی اجرا شود.")
    ipf = folder / "jafj_ip.txt"
    if ipf.exists():
        try:
            log(f"   🌐 آخرین IPِ خروجیِ سلف: "
                f"{(ipf.read_text(encoding='utf-8') or '').strip()}")
        except Exception:
            pass
    if not (folder / "jafj.session").exists():
        log("   👉 لاگین هنوز کامل نشده: از پنلِ مدیر «🚀 راه‌اندازی سلف روی اکانتم».")
    elif row.get("need_login"):
        log("   👉 مدیر این اکانت را «نیاز به لاگین» علامت زده — دوباره لاگین کن.")
    else:
        log("   👉 اگر خودت هیچ سلفی نمی‌بینی، یعنی مدیر اجرایش نکرده؛ "
            "با JAFJ_SELF_TAKEOVER=1 می‌توانی اجرا را به من بسپاری.")


def start_both(py, env):
    """مدیر + نظارت بر سلفِ همین اکانت.

    ⚠️ درسِ گران: نسخه‌ی اولِ این حالت خودش یک 95.py دوم اجرا می‌کرد و اگر
    مدیر هم همان لحظه اجرایش کرده بود، **دو پروسه روی یک سشن** می‌شدند؛
    تلگرام هر دو را قطع می‌کند و نتیجه‌اش همان «🔄 اتصال قطع شد» بی‌پایان
    بود. پس پیش‌فرض = فقط نظارت (هیچ پروسه‌ی دومی ساخته نمی‌شود) و اجرای
    دستی فقط با JAFJ_SELF_TAKEOVER=1 و بعد از «want_on=0»کردنِ اکانت.
    """
    folder = self_folder(env["DATA_DIR"])
    if folder is None:
        die("JAFJ_ONLY=both دادي ولي JAFJ_SELF_UID يا JAFJ_SELF_DIR ندادي.")
    folder = Path(folder)
    takeover = (os.environ.get("JAFJ_SELF_TAKEOVER") or "").strip() in (
        "1", "true", "yes", "on")
    argv, cwd, label = manager_argv()
    log(f"حالتِ both: {label} + نظارت بر سلفِ {folder}"
        + ("  (takeover روشن است)" if takeover else "  (فقط نظارت)"))
    if dry_run(env):
        log(f"DRY-RUN: {argv} (cwd={cwd}); نظارت بر {folder}"
            + ("; در صورت نیاز اجرای مستقیم" if takeover else ""))
        return 0

    try:
        mgr = subprocess.Popen(argv, cwd=cwd, env=env)
    except FileNotFoundError:
        die(f"اجرای {argv[0]} ممکن نشد (نصب نبود).")
        return 1
    log(f"manager/supervisor pid={mgr.pid}")

    warn_after = float(os.environ.get("JAFJ_SELF_WARN", "120") or 120)
    wait_ready = float(os.environ.get("JAFJ_SELF_WAIT", "900") or 900)
    t0 = time.time()
    ready_since = None
    seen_alive = False
    warned = False
    took = False
    stop = threading.Event()
    th = None
    while True:
        if mgr.poll() is not None:
            stop.set()
            log(f"مدیر با کد {mgr.returncode} بست — خروج")
            return mgr.returncode or 1
        alive = self_running(folder)
        now = time.time()
        if alive and not seen_alive:
            seen_alive = True
            warned = False
            try:
                pid = (folder / ".jafj_self.pid").read_text().strip()
            except Exception:
                pid = "?"
            log(f"✅ سلفِ این اکانت بالا آمد (pid={pid}) — مدیر خودش اجرا کرد.")
            th = None
            took = False
        elif seen_alive and not alive and not took:
            seen_alive = False
            log("⚠️ سلفِ این اکانت خاموش شد — دلیلش در خطوطِ زیر:")
            self_diagnostic(env, folder)
        if not alive and not took:
            if self_ready(folder):
                if ready_since is None:
                    ready_since = now
                    log(f"اکانت آماده است ولی سلف بالا نیست — منتظرِ مدیر… ({int(warn_after)}s)")
                waited = now - ready_since
                if takeover and waited >= warn_after and th is None:
                    log("takeover: اجرای سلف را خودم به دست می‌گیرم "
                        "(want_on=0 تا مدیر دوباره اجرا نکند)…")
                    db_set_want_on(env["DATA_DIR"], self_uid(), 0)
                    stop = threading.Event()
                    th = threading.Thread(target=supervise_selfbot,
                                          args=(py, env, folder, stop), daemon=True)
                    th.start()
                    took = True
                    seen_alive = True
                elif (not takeover) and waited >= warn_after and not warned:
                    warned = True
                    self_diagnostic(env, folder)
                    log("   👉 مدیر سلف را روشن نکرد. اگر می‌خواهی من اجرا کنم: "
                        "JAFJ_SELF_TAKEOVER=1")
                    ready_since = now          # گزارشِ بعدی، warn_after بعد
            elif now - t0 > wait_ready and not warned:
                warned = True
                self_diagnostic(env, folder)
                log(f"   👉 تا {int(wait_ready)}s اکانت آماده نشد "
                    f"({folder}) — اول از پنلِ مدیر لاگین کن؛ منتظر می‌مانم.")
                t0 = now
        time.sleep(3)


# ───────────────────────────────────────────────────────────────── main ──
def main():
    check_only = bool(os.environ.get("JAFJ_CHECK_ONLY")) or "--check" in sys.argv
    log(f"dir={HERE} python={sys.version.split()[0]}")
    sync_code()
    py = ensure_python()
    env = check_layout(build_env(py))
    boot_report(py, env)
    if check_only:
        log("حالتِ بررسی (--check): اجرا نمی‌کنم.")
        return 0
    m = mode()
    log(f"code={CODE_DIR} data={env['DATA_DIR']} python={py} "
        f"mode={m} port={env['PORT']}")
    if m == "self":
        return start_self_only(py, env)
    if m == "both":
        return start_both(py, env)
    return start_manager(py, env)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nJAFJ-BOOT: خاموش شد.", flush=True)
        sys.exit(0)
    except SystemExit:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        die(f"{type(e).__name__}: {e}")
