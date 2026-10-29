#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""پشتیبانیِ blitz.cloud (میزبانِ جدید به‌جای Render).

چیزهایی که روی blitz.cloud واقعاً داده را می‌بَرد و اینجا تضمین می‌شود:

  ۱) فایل‌سیستمِ کانتینر با هر ری‌استارت دور ریخته می‌شود و blitz.cloud فقط
     پوشه‌هایی را نگه می‌دارد که ایمیج با `VOLUME` اعلام کرده است — پس
     `Dockerfile` باید `/data` را VOLUME کند و `DATA_DIR=/data` بدهد، وگرنه
     `manager.db` / `shop.db` / سشن‌های `clients/<uid>/` هر ری‌استارت می‌پرند.
  ۲) پورت از `$PORT` می‌آید (پیش‌فرض ۸۰۸۰) و هلث‌سرویس باید همان را بگیرد.
  ۳) پلنِ رایگان بعد از ۳۰ دقیقه بی‌بازدید می‌خوابد → پشتیبانِ پیش‌فرض کوتاه،
     و میزبان به‌عنوان «hosted» شناخته می‌شود (حلقه‌ی ورود به‌جای exit).
  ۴) entrypoint: `blitz-start.sh` فقط پیش‌فرض‌های بلایتز را می‌دهد و بقیه‌ی
     جریان (کدِ تازه + ناظرِ کرش) از railway-start.sh می‌آید.
"""
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
ROOT = Path(tempfile.gettempdir()) / "jafj_blitz_host_run"

FAILS = []


def check(cond, label):
    print(("PASS  " if cond else "FAIL  ") + label)
    if not cond:
        FAILS.append(label)
    return bool(cond)


# ── ۱) Dockerfile ────────────────────────────────────────────────────────────
def check_dockerfile():
    print("--- 1: Dockerfile پوشه‌ی داده را VOLUME می‌کند ---")
    p = REPO / "Dockerfile"
    if not check(p.exists(), "Dockerfile در ریشه هست"):
        return
    t = p.read_text(encoding="utf-8")
    check(re.search(r'VOLUME\s*\[\s*"/data"\s*\]', t),
          "VOLUME /data اعلام شده (تنها راهِ ماندنِ داده روی blitz.cloud)")
    # DATA_DIR نباید در ایمیج هاردکد شود: entrypoint تصمیم می‌گیرد (تا نصبِ
    # قدیمیِ Railway/Render با Volume خودش نشکند). فقط کامنت‌ها می‌توانند
    # از آن حرف بزنند.
    instructions = "\n".join(ln for ln in t.splitlines()
                             if not ln.lstrip().startswith("#"))
    check("DATA_DIR=" not in instructions,
          "DATA_DIR در دستورهای ایمیج هاردکد نشده (تصمیمش با entrypoint است)")
    check(re.search(r"EXPOSE\s+8080", t), "EXPOSE 8080 اعلام شده")
    check(re.search(r"PORT=8080", t), "پیش‌فرضِ PORT=8080 هست")
    check("JAFJ_HOSTED=1" in t, "JAFJ_HOSTED=1 پیش‌فرض است (میزبان شناخته شود)")
    check(re.search(r"COPY[^\n]*blitz-start\.sh", t), "blitz-start.sh داخل ایمیج می‌رود")
    check(re.search(r"chmod[^\n]*blitz-start\.sh", t), "blitz-start.sh اجرایی می‌شود")
    check("COPY tools/ /opt/jafj/tools/" in t, "ابزارِ سینکِ گیت‌هاب داخل ایمیج هست")
    check(re.search(r'CMD\s*\[\s*"sh",\s*"/opt/jafj/blitz-start\.sh"\s*\]', t),
          "CMD به entrypointِ بلایتز اشاره می‌کند")


# ── ۲) entrypoint ───────────────────────────────────────────────────────────
def check_entrypoint():
    print("--- 2: blitz-start.sh ---")
    p = REPO / "blitz-start.sh"
    if not check(p.exists(), "blitz-start.sh در ریشه هست"):
        return
    sh = subprocess.run(["sh", "-n", str(p)], capture_output=True, text=True)
    check(sh.returncode == 0, "سینتکس sh سالم است (%s)" % sh.stderr.strip()[:80])
    t = p.read_text(encoding="utf-8")
    check('export JAFJ_APP_DIR="${JAFJ_APP_DIR:-/data}"' in t,
          "پوشه‌ی ماندگار /data پیش‌فرض است")
    check('export DATA_DIR="${DATA_DIR:-/data}"' in t,
          "DATA_DIR پیش‌فرض /data است (entrypoint، نه ایمیج)")
    check(re.search(r"JAFJ_APP_SLEEPS=1", t),
          "برای پلنِ خواب‌دار، پشتیبانِ کوتاه پیش‌فرض می‌شود")
    check('exec sh "$IMAGE_DIR/railway-start.sh"' in t,
          "جریانِ مشترکِ بوت/ناظر از railway-start.sh می‌آید")
    check("manager_82.py" not in t.replace("railway-start.sh", ""),
          "خودش کدِ مدیر را اجرا نمی‌کند (یک نقطه‌ی حقیقت)")

    rs = (REPO / "railway-start.sh").read_text(encoding="utf-8")
    check("blitz-start.sh" not in rs.replace("render-start.sh", ""),
          "railway-start.sh به بلایتز وابسته نمی‌شود (میزبان‌خنثی می‌ماند)")


# ── ۳) رفتارِ manager با envهای بلایتز ─────────────────────────────────────
INNER = r"""
import os, sys, time, urllib.request
sys.path.insert(0, os.environ["JAFJ_CODE_DIR"])
import manager_82 as M
print("HOSTED", M.is_hosted(), flush=True)
print("HOST_LABEL", M.HOST_LABEL, flush=True)
print("LOGIN_RETRY", M.login_retry_forever(), flush=True)
print("BACKUP", M.backup_interval(), flush=True)
port = int(os.environ.get("PORT", "0"))
body = ""
for _ in range(40):
    try:
        body = urllib.request.urlopen("http://127.0.0.1:%d/healthz" % port,
                                      timeout=1).read().decode()
        break
    except Exception:
        time.sleep(0.25)
print("HEALTH", repr(body), flush=True)
"""


def run_manager(extra_env, port):
    code_dir = ROOT / "code"
    data = ROOT / "data"
    code_dir.mkdir(parents=True, exist_ok=True)
    data.mkdir(parents=True, exist_ok=True)
    for f in ("manager_82.py", "95.py"):
        shutil.copy2(REPO / f, code_dir / f)
    env = dict(os.environ)
    for k in ("RAILWAY_ENVIRONMENT", "RAILWAY_SERVICE_ID", "RAILWAY_PROJECT_ID",
              "RENDER", "RENDER_SERVICE_NAME", "RENDER_SERVICE_ID",
              "BLITZ", "BLITZ_APP_NAME", "BLITZ_APP_ID",
              "FLY_APP_NAME", "HEROKU_APP_NAME", "KOYEB_APP_NAME",
              "JAFJ_HOSTED", "JAFJ_LOGIN_RETRY", "JAFJ_APP_SLEEPS",
              "JAFJ_HOST_LABEL", "BACKUP_EVERY", "BOT_TOKEN", "API_ID",
              "API_HASH"):
        env.pop(k, None)
    env.update({"JAFJ_CODE_DIR": str(code_dir), "DATA_DIR": str(data),
                "PORT": str(port), "JAFJ_SELFBOT_REF": str(code_dir / "95.py")})
    env.update(extra_env)
    p = subprocess.run([sys.executable, "-c", INNER], cwd=str(data), env=env,
                       capture_output=True, text=True, timeout=120)
    return p.stdout + p.stderr


def parse(out):
    got = {}
    for line in out.splitlines():
        parts = line.split(" ", 1)
        if parts[0] in ("HOSTED", "HOST_LABEL", "LOGIN_RETRY", "BACKUP", "HEALTH"):
            got[parts[0]] = parts[1].strip() if len(parts) > 1 else ""
    return got


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def check_manager():
    print("--- 3: manager با envهای blitz.cloud ---")
    ROOT.mkdir(parents=True, exist_ok=True)
    port = free_port()
    out = run_manager({"BLITZ_APP_NAME": "jafjbot", "PORT": str(port)}, port)
    got = parse(out)
    for k in ("HOSTED", "HOST_LABEL", "LOGIN_RETRY", "BACKUP", "HEALTH"):
        print("  %s=%r" % (k, got.get(k)))
    check(got.get("HOSTED") == "True", "BLITZ_APP_NAME → میزبان شناخته می‌شود")
    check(got.get("HOST_LABEL") == "jafjbot", "برچسبِ میزبان نامِ اپ است")
    check(got.get("LOGIN_RETRY") == "True",
          "حلقه‌ی ورود به‌جای exit (کانتینر نمی‌میرد)")
    check(got.get("BACKUP") == "900", "بدون JAFJ_APP_SLEEPS پشتیبان ۹۰۰s می‌ماند")
    check(got.get("HEALTH") == "'JAFJ OK\\n'",
          "هلث‌سرویس روی 0.0.0.0:$PORT جواب می‌دهد")

    print("--- 4: پلنِ خواب‌دار و برچسبِ دستی ---")
    port2 = free_port()
    out = run_manager({"BLITZ_APP_NAME": "jafjbot", "JAFJ_APP_SLEEPS": "1",
                       "JAFJ_HOST_LABEL": "blitz-eu", "PORT": str(port2)}, port2)
    got = parse(out)
    check(got.get("BACKUP") == "120",
          "با JAFJ_APP_SLEEPS=1 پشتیبان پیش‌فرض ۱۲۰s می‌شود")
    check(got.get("HOST_LABEL") == "blitz-eu", "JAFJ_HOST_LABEL برچسب را override می‌کند")

    out = run_manager({"BLITZ_APP_NAME": "jafjbot", "JAFJ_APP_SLEEPS": "0",
                       "BACKUP_EVERY": "600", "PORT": str(free_port())}, 0)
    check("BACKUP 600" in out, "BACKUP_EVERY صریح همیشه اولویت دارد")

    out = run_manager({"BLITZ_APP_NAME": "jafjbot", "JAFJ_APP_SLEEPS": "0",
                       "PORT": str(free_port())}, 0)
    check("BACKUP 900" in out, "JAFJ_APP_SLEEPS=0 پشتیبانِ کوتاه را خاموش می‌کند")


# ── ۵) مستندات ─────────────────────────────────────────────────────────────
def check_docs():
    print("--- 5: README ---")
    t = (REPO / "README.md").read_text(encoding="utf-8")
    check("blitz.cloud" in t, "بخشِ blitz.cloud در README هست")
    for need, label in (
            ("DATA_GITHUB_TOKEN", "توکنِ گیت‌هاب به‌عنوان نسخه‌ی بیرونی"),
            ("/data", "پوشه‌ی ماندگار /data"),
            ("30", "خوابِ ۳۰ دقیقه‌ایِ پلن رایگان"),
            ("JAFJ_APP_SLEEPS", "کلیدِ تنظیمِ پشتیبانِ کوتاه"),
            ("healthz", "مانیتورِ بیدارنگه‌دار"),
    ):
        check(need in t, "README به %s اشاره می‌کند" % label)


def main():
    print("--- blitz.cloud: ماندگاریِ داده + هلث‌سرویس + entrypoint ---")
    ROOT.mkdir(parents=True, exist_ok=True)
    check_dockerfile()
    check_entrypoint()
    check_manager()
    check_docs()
    shutil.rmtree(ROOT, ignore_errors=True)
    if FAILS:
        print("FAILED:", len(FAILS))
        for f in FAILS:
            print("  -", f)
        print("ALL: FAIL")
        return False
    print("ALL: PASS")
    return True


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
