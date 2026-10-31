#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""پشتیبانیِ GitHub Codespaces — «کد اسپیس می‌تواند ربات را آنلاین کند؟»

این تست قفل می‌کند که codespaces مثل بقیهٔ هاست‌ها رفتار کند:

  ۱) `.devcontainer/devcontainer.json` یک تنظیمِ معتبر است: پورت ۸۰۸۰ فوروارد
     می‌شود، `PORT` روی ۸۰۸۰ است، وابستگی‌ها نصب می‌شوند و ربات در هر بوتِ
     کانتینر بالا می‌آید (postStartCommand).

  ۲) `codespaces-start.sh` مثل بقیهٔ هاست‌ها از همان ناظرِ مشترک
     (`railway-start.sh`) استفاده می‌کند — یک نقطه‌ی حقیقت — و داده را در
     پوشه‌ای می‌گذارد که بین Stop/Start زنده می‌ماند.

  ۳) در عمل: با یک مدیرِ قلابی (stub) واقعاً بالا می‌آید، وب‌سرورِ سلامت روی
     `$PORT` جواب ۲۰۰ می‌دهد، pidfile نوشته می‌شود، نمونهٔ دوم ساخته نمی‌شود
     و با خاموش‌کردنِ کنترل‌شده، پروسه می‌رود.

چرا این تست لازم است: codespaces فرقِ ظریفی با بقیهٔ هاست‌ها دارد (کد از
خودِ گیت‌چک‌اوت اجرا می‌شود و دیسک با Stop/Start پاک نمی‌شود). اگر یکی از
این‌ها خراب شود، ربات در codespaces «بی‌صدا» بالا نمی‌آید و کسی نمی‌فهمد چرا.
"""
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ROOT = Path(tempfile.gettempdir()) / "jafj_codespaces_run"
FAILS = []

STUB_MANAGER = '''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""مدیرِ قلابی: مثل مدیرِ واقعی یک وب‌سرورِ سلامت روی $PORT باز می‌کند."""
import http.server
import os
import socketserver
import sys

port = int(os.environ.get("PORT") or "8080")


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"JAFJ OK\\n"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


print("STUB MANAGER RUNNING", flush=True)
sys.stdout.flush()
with Server(("0.0.0.0", port), Handler) as httpd:
    httpd.serve_forever()
'''


def check(cond, label):
    print(("PASS  " if cond else "FAIL  ") + label)
    if not cond:
        FAILS.append(label)
    return bool(cond)


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def http_get(url, timeout=3):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.status, r.read()


# ── ۱) فایل‌های devcontainer ────────────────────────────────────────────────
def check_devcontainer_files():
    print("--- 1: .devcontainer/ ---")
    dc = REPO / ".devcontainer" / "devcontainer.json"
    if not check(dc.exists(), ".devcontainer/devcontainer.json در ریپو هست"):
        return
    try:
        conf = json.loads(dc.read_text(encoding="utf-8"))
        check(True, "devcontainer.json JSON معتبر است")
    except Exception as e:
        check(False, "devcontainer.json JSON معتبر است (%s)" % e)
        return

    check("8080" in [str(p) for p in conf.get("forwardPorts", [])],
          "پورت ۸۰۸۰ فوروارد می‌شود (forwardPorts)")
    attrs = conf.get("portsAttributes", {})
    check(any("8080" in str(k) for k in attrs),
          "برای پورتِ سلامت label/portsAttributes تعریف شده")
    cenv = conf.get("containerEnv", {})
    check(str(cenv.get("PORT")) == "8080", "PORT=8080 در containerEnv است")
    check(str(cenv.get("JAFJ_HOSTED")) == "1",
          "JAFJ_HOSTED=1 (خروجِ تمیز هم کرش شمرده می‌شود، مثل بقیهٔ هاست‌ها)")
    post_create = conf.get("postCreateCommand", "")
    check("setup.sh" in str(post_create),
          "postCreateCommand وابستگی‌ها را نصب می‌کند")
    post_start = conf.get("postStartCommand", "")
    check("codespaces-start.sh" in str(post_start) and "--daemon" in str(post_start),
          "postStartCommand ربات را در هر بوتِ کانتینر بالا می‌آورد")

    setup = REPO / ".devcontainer" / "setup.sh"
    if check(setup.exists(), ".devcontainer/setup.sh هست"):
        sh = subprocess.run(["sh", "-n", str(setup)], capture_output=True, text=True)
        check(sh.returncode == 0, "سینتکس sh سالم است (%s)" % sh.stderr.strip()[:80])
        t = setup.read_text(encoding="utf-8")
        check("exit 0" in t or "exit 0" in t.replace("  ", " "),
              "setup.sh هرگز با خطا رد نمی‌شود (postStart نباید رد شود)")


# ── ۲) codespaces-start.sh ─────────────────────────────────────────────────
def check_script():
    print("--- 2: codespaces-start.sh ---")
    p = REPO / "codespaces-start.sh"
    if not check(p.exists(), "codespaces-start.sh در ریپو هست"):
        return
    sh = subprocess.run(["sh", "-n", str(p)], capture_output=True, text=True)
    check(sh.returncode == 0, "سینتکس sh سالم است (%s)" % sh.stderr.strip()[:80])
    t = p.read_text(encoding="utf-8")
    check("JAFJ_HOSTED" in t, "میزبان را hosted اعلام می‌کند (پروسه نباید بمیرد)")
    check('exec sh "$JAFJ_IMAGE_DIR/railway-start.sh"' in t,
          "جریانِ بوت/ناظر از railway-start.sh می‌آید (یک نقطه‌ی حقیقت)")
    check("JAFJ_SELFBOT_REF" in t, "مسیرِ سلف (95.py) صریح ست می‌شود")
    check("jafj-data" in t, "پوشهٔ داده بین Stop/Start زنده می‌ماند ($HOME/jafj-data)")
    check("PORT" in t and "8080" in t, "پورتِ پیش‌فرض ۸۰۸۰ (forwardPorts با آن یکی است)")
    check("--daemon" in t, "حالتِ پس‌زمینه برای postStartCommand دارد")
    code_only = "\n".join(l for l in t.splitlines() if not l.strip().startswith("#"))
    check("/opt/jafj" not in code_only,
          "به /opt/jafj (پوشهٔ ایمیجِ داکر) وابسته نیست — در codespaces کد، خودِ گیت‌چک‌اوت است")

    up = REPO / "codespaces-up.sh"
    if check(up.exists(), "codespaces-up.sh (ساخت/روشن‌کردنِ codespace) در ریپو هست"):
        sh = subprocess.run(["sh", "-n", str(up)], capture_output=True, text=True)
        check(sh.returncode == 0, "سینتکس sh سالم است (%s)" % sh.stderr.strip()[:80])
        u = up.read_text(encoding="utf-8")
        check("codespace create" in u, "codespace را می‌سازد")
        check("ports visibility" in u and "public" in u, "پورتِ سلامت را public می‌کند")
        check("app.github.dev" in u, "آدرسِ آنلاین را چاپ می‌کند")


# ── ۳) اجرای واقعی: مدیرِ قلابی بالا می‌آید ────────────────────────────────
def build_image_dir():
    img = ROOT / "img"
    shutil.rmtree(img, ignore_errors=True)
    img.mkdir(parents=True, exist_ok=True)
    (img / "manager_82.py").write_text(STUB_MANAGER, encoding="utf-8")
    (img / "95.py").write_text("# stub selfbot\n", encoding="utf-8")
    for name in ("railway-start.sh", "codespaces-start.sh"):
        shutil.copy2(REPO / name, img / name)
    (img / "tools").mkdir(exist_ok=True)
    return img


def stop_pid(pid):
    try:
        os.kill(pid, signal.SIGTERM)
    except Exception:
        return
    for _ in range(10):
        try:
            os.kill(pid, 0)
        except Exception:
            return
        time.sleep(0.3)
    try:
        os.kill(pid, signal.SIGKILL)
    except Exception:
        pass


def check_runtime():
    print("--- 3: اجرای واقعی در حالتِ --daemon ---")
    shutil.rmtree(ROOT, ignore_errors=True)
    ROOT.mkdir(parents=True, exist_ok=True)
    img = build_image_dir()
    data = ROOT / "data"
    data.mkdir(parents=True, exist_ok=True)
    port = free_port()

    env = dict(os.environ)
    env.update({
        "JAFJ_IMAGE_DIR": str(img),
        "DATA_DIR": str(data),
        "PORT": str(port),
        "HOME": str(ROOT / "home"),
        "JAFJ_PUBLIC_PORT": "0",     # برای تست، public نکن
    })
    for k in ("BOT_TOKEN", "DATA_GITHUB_TOKEN", "BACKUP_CHAT", "CODESPACE_NAME"):
        env.pop(k, None)

    proc = subprocess.run(["sh", str(img / "codespaces-start.sh"), "--daemon"],
                          capture_output=True, text=True, env=env, timeout=90)
    out = proc.stdout + proc.stderr
    check(proc.returncode == 0, "codespaces-start.sh --daemon با موفقیت برمی‌گردد")
    check("CODESPACES: code=" in out, "خلاصهٔ بوت (کد/داده/پورت) لاگ می‌شود")
    check(str(data) in out, "پوشهٔ داده همان DATA_DIR است")
    check(str(port) in out, "پورت در لاگ آمده")

    pidfile = data / "jafj.pid"
    logfile = data / "bot.log"
    ok_pid = check(pidfile.exists(), "pidfile نوشته شد")
    check(logfile.exists(), "لاگِ ربات ساخته شد")
    pid = None
    if ok_pid:
        try:
            pid = int(pidfile.read_text().strip())
        except Exception:
            pid = None
        check(bool(pid), "pidfile یک pid معتبر دارد")

    # وب‌سرورِ سلامت باید روی پورت جواب بدهد
    status, body = None, b""
    for _ in range(30):
        try:
            status, body = http_get("http://127.0.0.1:%d/healthz" % port, timeout=2)
            break
        except Exception:
            time.sleep(1)
    check(status == 200, "وب‌سرورِ سلامت روی $PORT جواب ۲۰۰ داد (%s)" % status)
    check(b"JAFJ OK" in body, "متنِ سلامت درست است")

    if logfile.exists():
        log = logfile.read_text(encoding="utf-8", errors="replace")
        check("SELFBOOT: code=" in log, "ناظرِ مشترک (railway-start.sh) اجرا شد")
        check("STUB MANAGER RUNNING" in log, "مدیر واقعاً اجرا شد")

    # نمونهٔ دوم نباید ساخته شود (دو نمونه با یک توکن = تلگرام دوتکه)
    if pid:
        again = subprocess.run(["sh", str(img / "codespaces-start.sh"), "--daemon"],
                               capture_output=True, text=True, env=env, timeout=60)
        out2 = again.stdout + again.stderr
        check("از قبل بالاست" in out2, "نمونهٔ دوم ساخته نمی‌شود (قفلِ pidfile)")
        pid2 = None
        try:
            pid2 = int(pidfile.read_text().strip())
        except Exception:
            pid2 = None
        check(pid2 == pid, "pidfile همان نمونهٔ قبلی را نگه داشت")

    if pid:
        stop_pid(pid)
        time.sleep(0.5)
        try:
            http_get("http://127.0.0.1:%d/healthz" % port, timeout=2)
            alive = True
        except Exception:
            alive = False
        check(not alive, "با خاموش‌کردنِ کنترل‌شده، سرویس هم می‌ایستد")


def main():
    shutil.rmtree(ROOT, ignore_errors=True)
    ROOT.mkdir(parents=True, exist_ok=True)
    check_devcontainer_files()
    check_script()
    check_runtime()
    print("ALL:", "PASS" if not FAILS else "FAIL")
    if FAILS:
        for f in FAILS:
            print("  - " + f)
    shutil.rmtree(ROOT, ignore_errors=True)
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
