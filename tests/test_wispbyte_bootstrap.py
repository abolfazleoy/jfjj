#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""main.py — راه‌اندازِ میزبان‌های «اپ پایتونی» (Wispbyte و مشابهش).

گزارشِ کاربر: «main.py فایلِ manager_82 را اجرا می‌کند ولی فایلِ سلف را نه.»

ریشه‌ی ماجرا این است که این دو فایل هم‌رده و هم‌شأن نیستند:

  * `manager_82.py` رباتِ مدیریت است — تنها پروسه‌ای که باید از بوت بالا
    بیاید (یک نمونه، با `bot.lock`، با وب‌سرورِ سلامت روی `$PORT`).
  * `95.py` سلف‌باتِ **هر مشتری** است. لاگینش با کدِ تلگرام داخل خودِ
    رباتِ مدیریت انجام می‌شود («🚀 راه‌اندازی سلف روی اکانتم») و بعد مدیر
    آن را با `cwd=data/clients/<uid>/` و `stdin=DEVNULL` بالا می‌آورد —
    چون `jafj_creds.json` و `jafj.session` را همین پوشه دارد.

پس اجرای `95.py` از کنارِ `manager_82.py` (بدون creds/session، با
ترمینالِ غیرتعاملی) همیشه فوراً می‌مرد. این تست سه چیز را قفل می‌کند:

  ۱) `main.py` در حالتِ عادی هیچ‌وقت ۹۵.py را خودش اجرا نمی‌کند؛ فقط
     entrypointِ خودِ ریپو (`railway-start.sh`) را exec می‌کند.
  ۲) مسیرها درست به محیط تزریق می‌شوند: کد از `code/` (غیرقابل‌تغییر)،
     داده در `DATA_DIR` (جدا)، `JAFJ_SELFBOT_REF` به `code/95.py`.
  ۳) حالتِ اختیاریِ «فقط یک سلف» (`JAFJ_ONLY=self`) بدون creds/session با
     پیامِ روشن می‌ایستد، نه با کرشِ مبهم.
"""
import importlib.util
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
FAILS = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + (f"   {extra}" if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def load():
    spec = importlib.util.spec_from_file_location("jafj_main", str(REPO / "main.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    here = os.getcwd()
    saved = {k: os.environ.get(k) for k in
             ("JAFJ_REPO", "JAFJ_BRANCH", "JAFJ_GIT_TOKEN", "DATA_DIR",
              "JAFJ_ONLY", "JAFJ_SELF_UID", "JAFJ_DRY_RUN", "PORT")}
    tmp = Path(tempfile.mkdtemp(prefix="jafj_main_test_"))
    try:
        M = load()

        # ── ۱) آدرسِ ریپو و پوشاندنِ توکن ─────────────────────────────────
        os.environ.pop("JAFJ_GIT_TOKEN", None)
        os.environ["JAFJ_REPO"] = "abolfazleoy/jfjj"
        check("repo_url: owner/name → https://github.com/owner/name.git",
              M.repo_url() == "https://github.com/abolfazleoy/jfjj.git", M.repo_url())
        os.environ["JAFJ_GIT_TOKEN"] = "ghp_SECRET123"
        check("repo_url: توکن در URL (برای ریپوی خصوصی)",
              "ghp_SECRET123@github.com" in M.repo_url(), M.repo_url())
        check("shown: توکن هرگز لاگ نمی‌شود", "ghp_SECRET123" not in M.shown(M.repo_url()))
        os.environ["JAFJ_REPO"] = "/local/path/repo"
        check("repo_url: مسیر/URL آماده دست‌نخورده می‌ماند",
              M.repo_url() == "/local/path/repo", M.repo_url())
        os.environ.pop("JAFJ_GIT_TOKEN", None)

        # ── ۲) حالتِ عادی: فقط entrypointِ ریپو، بدونِ ۹۵.py ───────────────
        os.environ["JAFJ_REPO"] = "abolfazleoy/jfjj"
        os.environ["DATA_DIR"] = str(tmp / "data")
        os.environ["JAFJ_DRY_RUN"] = "1"
        os.environ["PORT"] = "9099"
        os.environ.pop("JAFJ_ONLY", None)
        os.environ.pop("JAFJ_BOOT", None)
        check("mode: پیش‌فرض یعنی manager", M.mode() == "manager", M.mode())

        env = M.check_layout(M.build_env(sys.executable))
        check("env: کد از code/ (JAFJ_IMAGE_DIR)", env["JAFJ_IMAGE_DIR"] == str(M.CODE_DIR))
        check("env: داده جدا از کد (DATA_DIR != JAFJ_IMAGE_DIR)",
              env["DATA_DIR"] != env["JAFJ_IMAGE_DIR"], env["DATA_DIR"])
        check("env: مرجع سلف در پوشه‌ی کد است",
              env["JAFJ_SELFBOT_REF"] == str(M.CODE_DIR / "95.py"), env["JAFJ_SELFBOT_REF"])
        check("env: PORT به ارث می‌رسد", env["PORT"] == "9099", env["PORT"])
        check("env: خروجی بی‌بافر (لاگِ میزبان)", env.get("PYTHONUNBUFFERED") == "1")

        rc = M.start_manager(Path(sys.executable), env)      # DRY-RUN → exec نمی‌کند
        check("start_manager در DRY-RUN کد ۰ برمی‌گرداند و کسی را اجرا نمی‌کند", rc == 0, rc)

        src = (REPO / "main.py").read_text(encoding="utf-8")
        import re
        body = re.search(r"def start_manager\(.*?\n(?=def |\Z)", src, re.S)
        body = body.group(0) if body else ""
        check("start_manager اصلاً پروسه‌ی سلف را بالا نمی‌آورد",
              "Popen" not in body and "SELF_NAME]" not in body)
        check("start_manager فقط entrypointِ ریپو را exec می‌کند",
              "execve" in body and "railway-start.sh" in src)
        supbody = re.search(r"def supervise_selfbot\(.*?\n(?=def |\Z)", src, re.S)
        supbody = supbody.group(0) if supbody else ""
        check("سلف فقط در حالتِ self/both اجرا می‌شود (supervise_selfbot)",
              "Popen" in supbody and "SELF_NAME" in supbody)
        check("start_manager هیچ رشته‌ای برای سلف ندارد", "SELF_NAME" not in body)

        # ── ۳) «فقط یک سلف» بدونِ creds/session: پیامِ روشن، نه کرش ────────
        os.environ["JAFJ_ONLY"] = "self"
        os.environ["JAFJ_SELF_UID"] = "12345"
        check("mode=self درست خوانده می‌شود", M.mode() == "self")
        code = None
        try:
            M.start_self_only(Path(sys.executable), dict(env))
        except SystemExit as e:
            code = e.code
        check("سلف‌تنها بدونِ jafj_creds.json با کد خطا و پیام می‌ایستد",
              code not in (None, 0), code)
        os.environ.pop("JAFJ_ONLY", None)
        os.environ.pop("JAFJ_SELF_UID", None)

        # ── ۴) دروغِ امنیتی نباشد: DATA_DIR نوشتنی چک می‌شود ───────────────
        bad = tmp / "readonly"
        bad.mkdir()
        os.environ["DATA_DIR"] = str(bad / "sub")
        env2 = M.check_layout(M.build_env(sys.executable))
        check("check_layout پوشه‌ی داده را می‌سازد",
              Path(env2["DATA_DIR"]).is_dir(), env2["DATA_DIR"])
    finally:
        os.chdir(here)
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    print()
    if FAILS:
        print("FAILED:", ", ".join(FAILS))
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
