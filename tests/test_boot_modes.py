#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""main.py — چک‌لیستِ بوت و حالت‌های اجرا.

گزارشِ کاربر: «کدِ main.py کامل نیست؛ قبلاً مشکلی نداشت.» یعنی هم باید خودِ
مدیر بالا بیاید و هم سلف، و اگر چیزی جا افتاده بود **همان اول** معلوم شود،
نه بعد از ده دقیقه حدس‌زدن.

این تست قفل می‌کند:

  ۱) `mode()` سه حالت را درست می‌خواند: manager (پیش‌فرض) / both / self.
  ۲) `self_folder()` از `JAFJ_SELF_UID` و `JAFJ_SELF_DIR` پوشه‌ی اکانت را
     می‌سازد و بدون هیچ‌کدام None می‌دهد (خطا در لاگ، نه کرشِ مبهم).
  ۳) `self_ready()` بدونِ creds/session جواب منفی می‌دهد.
  ۴) `self_running()` پروسه‌ی زنده‌ی همان پوشه را می‌شناسد و PID مرده را نه
     (این همان چیزی است که از «دو سلف روی یک سشن» جلوگیری می‌کند).
  ۵) `boot_report()` چک‌لیست را چاپ و در `data/boot.log` ذخیره می‌کند.
  ۶) `python main.py --check` بدونِ اجرای ربات، چک‌لیست را می‌دهد و کد ۰.
  ۷) حالتِ `both` هم مدیر و هم سلف را بالا می‌آورد (هر دو در یک لاگ).
"""
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
FAILS = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + (f"   [{extra}]" if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def load():
    spec = importlib.util.spec_from_file_location("jafj_main_modes", str(REPO / "main.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def build_fake_repo(root):
    """ریپوی قلابی: مدیر و سلفی که فقط چند ثانیه زنده می‌مانند."""
    repo = root / "fake_repo"
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "manager_82.py").write_text(
        "import os, sys, time\n"
        "print('FAKE-MANAGER start cwd=' + os.getcwd(), flush=True)\n"
        "print('  PY ' + sys.executable, flush=True)\n"
        "time.sleep(30)\n", encoding="utf-8")
    (repo / "95.py").write_text(
        "import os, time\n"
        "print('FAKE-SELF start cwd=' + os.getcwd(), flush=True)\n"
        "print('  creds=' + str(os.path.exists('jafj_creds.json')) +\n"
        "      ' session=' + str(os.path.exists('jafj.session')), flush=True)\n"
        "time.sleep(20)\n", encoding="utf-8")
    # مثلِریال railway-start.sh: مسیر کد را از JAFJ_IMAGE_DIR می‌گیرد
    # (چون مدیر با cwd پوشه‌ی داده اجرا می‌شود، نه پوشه‌ی کد)
    (repo / "railway-start.sh").write_text(
        "#!/bin/sh\nexec python3 \"$JAFJ_IMAGE_DIR/manager_82.py\"\n",
        encoding="utf-8")
    (repo / "requirements.txt").write_text("", encoding="utf-8")
    subprocess.run(["git", "init", "-q", "."], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.email=a@b", "-c", "user.name=c",
                    "commit", "-qm", "init"], cwd=repo, check=True)
    subprocess.run(["git", "branch", "-M", "main"], cwd=repo, check=True)
    return repo


def main():
    here = os.getcwd()
    saved = {k: os.environ.get(k) for k in
             ("JAFJ_ONLY", "JAFJ_BOOT", "JAFJ_SELF_UID", "JAFJ_SELF_DIR",
              "JAFJ_REPO", "JAFJ_BRANCH", "DATA_DIR", "PYTHONPATH",
              "JAFJ_SKIP_VENV", "PORT")}
    root = Path(tempfile.mkdtemp(prefix="jafj_modes_"))
    try:
        M = load()

        # ── ۱) حالت‌ها ────────────────────────────────────────────────────
        os.environ.pop("JAFJ_ONLY", None)
        os.environ.pop("JAFJ_BOOT", None)
        check("mode(): پیش‌فرض = manager", M.mode() == "manager", M.mode())
        for val in ("both", "1", "all", "true"):
            os.environ["JAFJ_ONLY"] = val
            check(f"mode(): «{val}» = both", M.mode() == "both", M.mode())
        os.environ["JAFJ_ONLY"] = "self"
        check("mode(): «self» = self", M.mode() == "self")
        os.environ["JAFJ_ONLY"] = "manager"
        check("mode(): «manager» = manager", M.mode() == "manager")
        os.environ.pop("JAFJ_ONLY", None)
        os.environ["JAFJ_BOOT"] = "both"
        check("mode(): JAFJ_BOOT هم خوانده می‌شود", M.mode() == "both")
        os.environ.pop("JAFJ_BOOT", None)

        # ── ۲) پوشه‌ی اکانت ────────────────────────────────────────────────
        data = root / "data"
        data.mkdir(parents=True, exist_ok=True)
        check("self_folder(): بدونِ uid/dir = None",
              M.self_folder(str(data)) is None)
        os.environ["JAFJ_SELF_UID"] = "777"
        check("self_folder(): از uid → data/clients/<uid>",
              str(M.self_folder(str(data))) == str(data / "clients" / "777"),
              M.self_folder(str(data)))
        os.environ["JAFJ_SELF_DIR"] = str(root / "custom")
        check("self_folder(): JAFJ_SELF_DIR اولویت دارد",
              str(M.self_folder(str(data))) == str((root / "custom").resolve()))
        os.environ.pop("JAFJ_SELF_DIR", None)

        folder = data / "clients" / "777"
        folder.mkdir(parents=True, exist_ok=True)
        check("self_ready(): بدونِ creds/session → نه", M.self_ready(folder) is False)
        (folder / "jafj_creds.json").write_text("{}", encoding="utf-8")
        check("self_ready(): فقط creds کافی نیست", M.self_ready(folder) is False)
        (folder / "jafj.session").write_bytes(b"x")
        check("self_ready(): با هر دو → بله", M.self_ready(folder) is True)

        # ── ۳) تشخیصِ «سلف از قبل روشن است» ───────────────────────────────
        check("self_running(): بدونِ pidfile → نه", M.self_running(folder) is False)
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(20)"],
                             stdin=subprocess.DEVNULL)
        (folder / ".jafj_self.pid").write_text(str(p.pid), encoding="utf-8")
        check("self_running(): PID زنده ولی cmdline بی‌ربط → نه",
              M.self_running(folder) is False)
        p.kill()
        p.wait()
        (folder / "95.py").write_text("import time\ntime.sleep(20)\n", encoding="utf-8")
        p2 = subprocess.Popen([sys.executable, "95.py"], cwd=str(folder),
                              stdin=subprocess.DEVNULL)
        time.sleep(0.6)
        (folder / ".jafj_self.pid").write_text(str(p2.pid), encoding="utf-8")
        check("self_running(): PID زنده‌ی 95.py → بله", M.self_running(folder) is True)
        p2.kill()
        p2.wait()
        check("self_running(): PID مرده → نه", M.self_running(folder) is False)

        # ── ۴) چک‌لیست + boot.log ─────────────────────────────────────────
        os.environ["DATA_DIR"] = str(data)
        os.environ["PORT"] = "9411"
        os.environ["JAFJ_ONLY"] = "both"      # چک‌های سلف هم اجرا شوند
        env = {"DATA_DIR": str(data), "JAFJ_HOST_LABEL": "wispbyte",
               "JAFJ_SELF_UID": "777", "PORT": "9411"}
        M.CODE_DIR = root / "code_stub"
        M.CODE_DIR.mkdir(parents=True, exist_ok=True)
        (M.CODE_DIR / "manager_82.py").write_text("", encoding="utf-8")
        (M.CODE_DIR / "95.py").write_text("", encoding="utf-8")
        (M.CODE_DIR / "railway-start.sh").write_text("", encoding="utf-8")
        M.boot_report(Path(sys.executable), env)
        boot_log = data / "boot.log"
        text = boot_log.read_text(encoding="utf-8") if boot_log.exists() else ""
        check("boot_report: فایلِ data/boot.log ساخته شد", boot_log.is_file())
        check("boot_report: git و پایتون و کد و داده چک شدند",
              all(k in text for k in ("git نصب است", "پایتون", "کد ریپو",
                                      "پوشه‌ی داده", "telethon")), text[:200])
        check("boot_report: وضعیتِ سلف با uid گزارش شد",
              "حالتِ سلف" in text, text[-300:])

        # ── ۵) e2e: --check و حالتِ both (با ریپوی قلابی) ─────────────────
        repo = build_fake_repo(root)
        stub = root / "stub"; stub.mkdir(exist_ok=True)
        (stub / "telethon.py").write_text("__version__='stub'\n", encoding="utf-8")
        app = root / "app"; app.mkdir(exist_ok=True)
        shutil.copy2(REPO / "main.py", app / "main.py")
        env_e2e = dict(os.environ)
        env_e2e.update({
            "JAFJ_REPO": str(repo), "JAFJ_BRANCH": "main",
            "JAFJ_SKIP_VENV": "1", "PYTHONPATH": str(stub),
            "DATA_DIR": str(app / "data"), "PORT": "9412",
        })
        env_e2e.pop("JAFJ_ONLY", None)

        r = subprocess.run([sys.executable, "main.py", "--check"], cwd=str(app),
                           env=env_e2e, capture_output=True, text=True, timeout=180)
        check("e2e --check: کد خروج ۰", r.returncode == 0, r.returncode)
        check("e2e --check: چک‌لیست را چاپ کرد", "JAFJ-CHECK" in r.stdout)
        check("e2e --check: اجرا نکرد", "حالتِ بررسی" in r.stdout
              and "FAKE-MANAGER" not in r.stdout)
        check("e2e --check: boot.log ساخته شد",
              (app / "data" / "boot.log").is_file())

        # حالتِ both: مدیر + سلفِ همان اکانت
        acc = app / "data" / "clients" / "888"
        acc.mkdir(parents=True, exist_ok=True)
        (acc / "jafj_creds.json").write_text("{}", encoding="utf-8")
        (acc / "jafj.session").write_bytes(b"x")
        env_e2e.update({"JAFJ_ONLY": "both", "JAFJ_SELF_UID": "888"})
        proc = subprocess.Popen([sys.executable, "main.py"], cwd=str(app),
                                env=env_e2e, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True)
        out = ""
        deadline = time.time() + 90
        try:
            while time.time() < deadline:
                line = proc.stdout.readline()
                if not line:
                    break
                out += line
                if "FAKE-SELF start" in out and "FAKE-MANAGER start" in out:
                    break
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except Exception:
                proc.kill()
        check("e2e both: مدیر بالا آمد", "FAKE-MANAGER start" in out, out[-400:])
        check("e2e both: سلف هم بالا آمد", "FAKE-SELF start" in out, out[-400:])
        check("e2e both: سلف در پوشه‌ی اکانت اجرا شد",
              f"cwd={acc}" in out or "creds=True session=True" in out, out[-400:])
        check("e2e both: هر دو در یک لاگ آمدند",
              out.count("JAFJ-BOOT:") > 3)
    finally:
        os.chdir(here)
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(root, ignore_errors=True)

    print()
    if FAILS:
        print("FAILED:", ", ".join(FAILS))
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
