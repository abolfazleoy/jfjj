#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ═══════════════════════════════════════════════════════════════════════════
#  JAFJ — main.py  (bootstrap برای میزبان‌های «اپ پایتونی»: Wispbyte،
#                   Hostless python build، هر جایی که فقط یک دستور
#                   شروع مثل `python main.py` می‌گیرد)
#
#  این فایل فقط «راه‌انداز» است، نه ربات:
#    ۱) کد را از گیت‌هاب می‌گیرد/به‌روز می‌کند      → ./code
#    ۲) محیط پایتون و وابستگی‌ها را می‌سازد          → ./venv
#    ۳) داده‌ها را در یک پوشه‌ی جدا نگه می‌دارد       → ./data
#    ۴) entrypointِ خودِ ریپو (railway-start.sh) را اجرا می‌کند که
#       supervisor است و manager_82.py را بالا می‌آورد.
#
#  ⚠️ نکته‌ی مهم (همان چیزی که «سلف اجرا نمی‌شود» را توضیح می‌دهد):
#     95.py یک رباتِ مستقلِ سراسری نیست. سلفِ هر مشتری است که
#     خودِ manager_82.py بعد از لاگینِ آن اکانت، با cwd پوشه‌ی همان
#     اکانت اجرا می‌کند:
#         data/clients/<uid>/  →  jafj_creds.json + jafj.session
#                               →  python 95.py
#     اگر 95.py را از این‌جا (کنار manager، بدون creds و session) اجرا
#     کنی، فوراً با «ترمینال تعاملی نیست / PHONE را بگذار» می‌میرد —
#     دقیقاً همان چیزی که دیدی. پس این فایل عمداً 95.py را اجرا نمی‌کند.
#     (اگر واقعاً می‌خواهی فقط یک سلفِ تنها اجرا شود، JAFJ_ONLY=self
#      را با JAFJ_SELF_DIR بده — پایین توضیح داده شده.)
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


# ───────────────────────────────────────────────────────────── helpers ──
def log(msg):
    print(f"JAFJ-BOOT: {msg}", flush=True)


def die(msg, code=1):
    print(f"JAFJ-BOOT: ❌ {msg}", flush=True)
    sys.exit(code)


def repo():
    """repo از محیط، در لحظه‌ی صدا زدن خوانده می‌شود (نه فقط در import)."""
    return (os.environ.get("JAFJ_REPO") or DEFAULT_REPO).strip()


def branch():
    return (os.environ.get("JAFJ_BRANCH") or DEFAULT_BRANCH).strip() or DEFAULT_BRANCH


def token():
    return (os.environ.get("JAFJ_GIT_TOKEN") or "").strip()      # ریپوی خصوصی


def data_dir():
    return Path(os.environ.get("DATA_DIR") or DEFAULT_DATA).expanduser().resolve()


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
    log("$ " + " ".join(str(c) for c in cmd))
    out = subprocess.DEVNULL if quiet else None
    return subprocess.run(
        [str(c) for c in cmd], cwd=str(cwd) if cwd else None, env=env,
        stdout=out, stderr=out,
    )


# ─────────────────────────────────────────────────── 1) selfbot mode check ──
def only_mode():
    return (os.environ.get("JAFJ_ONLY") or "").strip().lower()


# ─────────────────────────────────────────────────────── 2) code from git ──
def sync_code():
    CODE_DIR.parent.mkdir(parents=True, exist_ok=True)
    url = repo_url()

    if not (CODE_DIR / ".git").exists():
        if CODE_DIR.exists():
            shutil.rmtree(CODE_DIR, ignore_errors=True)
        log(f"cloning {shown(url)} (branch {branch()}) → {CODE_DIR}")
        args = ["git", "clone", "--depth", "1", "--branch", branch(), url, str(CODE_DIR)]
        if run(args).returncode != 0:
            # شاید برنچ وجود ندارد → برنچ پیش‌فرض را بگیر
            log(f"branch «{branch()}» clone نشد — با برنچ پیش‌فرض امتحان می‌کنم")
            if run(["git", "clone", "--depth", "1", url, str(CODE_DIR)]).returncode != 0:
                die("git clone نشد. JAFJ_REPO / JAFJ_BRANCH / JAFJ_GIT_TOKEN را چک کن.")
    else:
        log("code موجود است — به‌روزرسانی…")
        ok = run(["git", "-C", str(CODE_DIR), "fetch", "--depth", "1",
                  "origin", branch()]).returncode == 0
        if ok:
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


# ───────────────────────────────────────────────── 3) venv + dependencies ──
def req_hash():
    f = CODE_DIR / "requirements.txt"
    return hashlib.sha256(f.read_bytes()).hexdigest() if f.is_file() else ""


def stamp_file():
    return VENV_DIR / ".reqhash"


def deps_ok(py):
    r = subprocess.run([str(py), "-c", "import telethon"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return r.returncode == 0


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
    return r.returncode == 0


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
        if run([sys.executable, "-m", "venv", str(VENV_DIR)]).returncode != 0:
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


# ───────────────────────────────────────────────── 4) environment wiring ──
def build_env(py):
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["JAFJ_HOSTED"] = env.get("JAFJ_HOSTED", "1")
    env["JAFJ_HOST_LABEL"] = env.get("JAFJ_HOST_LABEL", "wispbyte")
    env["JAFJ_IMAGE_DIR"] = str(CODE_DIR)          # کد: غیرقابل‌تغییر
    d = data_dir()
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
    d.mkdir(parents=True, exist_ok=True)
    probe = d / ".jafj_write_test"
    try:
        probe.write_text("ok")
        probe.unlink()
    except Exception as e:
        log(f"⚠️ DATA_DIR نوشتنی نیست ({d}: {e}) — /tmp استفاده می‌شود")
        env["DATA_DIR"] = env["JAFJ_APP_DIR"] = "/tmp/jafj-data"
        Path(env["DATA_DIR"]).mkdir(parents=True, exist_ok=True)
    if Path(env["DATA_DIR"]).resolve() == CODE_DIR.resolve():
        log("⚠️ داده و کد در یک پوشه‌اند — با هر دیپلوی داده پاک می‌شود."
            " DATA_DIR را به یک مسیر پایدار (مثلاً /data) بده.")
    return env


# ───────────────────────────── 5a) حالت عادی: manager + سلف‌هایش (پیشنهادی) ──
def start_manager(py, env):
    entry = CODE_DIR / ENTRY_NAME
    if env.get("JAFJ_DRY_RUN", "").strip() in ("1", "true", "yes"):
        log(f"DRY-RUN: exec sh {entry}   (python={py}, data={env['DATA_DIR']}, "
            f"code={env['JAFJ_IMAGE_DIR']}, port={env['PORT']})")
        return 0

    if entry.is_file():
        log("اجرای entrypoint ریپو (supervisor + manager_82.py)…")
        os.chdir(env["DATA_DIR"])
        os.execve("/bin/sh", ["sh", str(entry)], env)   # جایگزین همین پروسه
    # ریپوی قدیمی بدون entrypoint: مستقیم manager را اجرا کن
    log(f"⚠️ {ENTRY_NAME} نیست — manager_82.py را مستقیم اجرا می‌کنم"
        " (بدون supervisor)")
    os.chdir(str(CODE_DIR))
    os.execve(str(py), [str(py), str(CODE_DIR / MANAGER_NAME)], env)


# ───────────────── 5b) حالت اختیاری: فقط یک سلفِ تنها (بدون manager) ────────
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


def start_selfbot_only(py, env):
    folder = (os.environ.get("JAFJ_SELF_DIR") or "").strip()
    uid = (os.environ.get("JAFJ_SELF_UID") or "").strip()
    if not folder and uid:
        folder = str(Path(env["DATA_DIR"]) / "clients" / uid)
    if not folder:
        die("JAFJ_ONLY=self دادي ولي JAFJ_SELF_DIR يا JAFJ_SELF_UID ندادي.")
    folder = str(Path(folder).expanduser().resolve())

    for need in ("jafj_creds.json", "jafj.session"):
        if not Path(folder, need).exists():
            die(f"{need} در {folder} نیست — اول در حالت عادی (manager) آن اکانت را "
                f"از دکمه‌ی «🚀 راه‌اندازی سلف روی اکانتم» لاگین کن.")
    os.makedirs(folder, exist_ok=True)
    selfbot = Path(env["JAFJ_SELFBOT_REF"])
    if str(Path(folder, SELF_NAME).resolve()) != str(selfbot.resolve()):
        shutil.copy2(selfbot, Path(folder, SELF_NAME))     # نسخه‌ی همان ریپو

    health_server(env["PORT"])
    log(f"اجرای سلفِ تنها — cwd={folder}")
    if env.get("JAFJ_DRY_RUN", "").strip() in ("1", "true", "yes"):
        log(f"DRY-RUN: python {Path(folder, SELF_NAME)} (cwd={folder})")
        return 0

    e = dict(env)
    e.setdefault("JAFJ_NO_AUTO_LOGIN", "1")
    backoff, child = 5, None
    try:
        while True:
            child = subprocess.Popen([str(py), SELF_NAME], cwd=folder, env=e,
                                     stdin=subprocess.DEVNULL)
            log(f"selfbot pid={child.pid}")
            started = time.time()
            rc = child.wait()
            if rc == 0:
                log("سلف تمیز بسته شد.")
                return 0
            if rc == 78:
                die("سشن این اکانت باطل است — از پنل مدیر دوباره لاگین کن.", 78)
            up = time.time() - started
            backoff = 5 if up > 120 else min(backoff * 2, 120)
            log(f"سلف با کد {rc} بست ({int(up)}s) — {backoff} ثانیه بعد دوباره")
            time.sleep(backoff)
    except KeyboardInterrupt:
        if child and child.poll() is None:
            child.terminate()
        return 0


# ───────────────────────────────────────────────────────────────── main ──
def main():
    log(f"host={os.environ.get('JAFJ_HOST_LABEL', 'wispbyte')} "
        f"python={sys.version.split()[0]} dir={HERE}")
    sync_code()
    py = ensure_python()
    env = check_layout(build_env(py))
    log(f"code={CODE_DIR} data={env['DATA_DIR']} python={py} "
        f"mode={only_mode() or 'manager'} port={env['PORT']}")
    if only_mode() == "self":
        return start_selfbot_only(py, env)
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
