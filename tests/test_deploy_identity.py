#!/usr/bin/env python3
"""«دیپلوی شد یا نه؟» — شناسه‌ی نسخه‌ی در حالِ اجرا.

سؤالِ همیشگی بعد از مرج: کد روی گیت‌هاب نشسته، ولی روی هاست چی؟ این تست سه
لایه را قفل می‌کند:

  1) اثرانگشتِ کد (CODE_ID): با هر تغییرِ manager_82.py/95.py عوض می‌شود، پس
     اگر دیپلوی بی‌اثر بماند (ایمیجِ قدیمی، یا دیسکی که روی مسیرِ کد مانت
     شده) همان عددِ قبلی می‌ماند و فوراً دیده می‌شود. متغیرِ JAFJ_CODE_ID که
     اسکریپتِ بوت می‌سازد اولویت دارد تا لاگ و /version و تلگرام یکی بگویند.
  2) مسیرِ HTTP: «/version» بیلد/کامیت/اثرانگشت/مسیرِ فایل/زمانِ بوت را
     می‌دهد و «/» و «/healthz» همان «JAFJ OK» می‌مانند (هلث‌چکِ Render و
     تستِ test_render_host به آن بایت‌ها وابسته‌اند).
  3) تلگرام: پنلِ «🧬 نسخه‌ی کد» (a:ver) همان عدد را به مدیر نشان می‌دهد،
     اگر کد از ایمیج اجرا نشود هشدار می‌دهد، وضعیتِ بازیابیِ بخش‌ها را هم
     خلاصه می‌کند و دکمه‌ی «🕘 بازیابی بخش‌ها» دارد.

روشِ اجرا مثلِ بقیه‌ی تست‌ها: سورسِ واقعیِ manager_82 با telethonِ قلابی در یک
پوشه‌ی موقت اجرا می‌شود.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.join(tempfile.gettempdir(), "jafj_deploy_identity_run")
APP = os.path.join(ROOT, "app")
DATA = os.path.join(ROOT, "data")
PORT = 8237

FAILS = []


def check(cond, label, extra=""):
    print(("PASS  " if cond else "FAIL  ") + label
          + (("  → " + str(extra)) if not cond and extra else ""), flush=True)
    if not cond:
        FAILS.append(label)
    return bool(cond)


def _fake_telethon_sources():
    """FAKE_TELETHON/FAKE_SESSIONS/FAKE_ERRORS را از تستِ موجود برمی‌دارد.

    آن ماژول موقعِ import سناریوهایش را اجرا می‌کند، پس به‌جای import، درختِ
    syntax را می‌خوانیم و فقط مقدارِ همین سه ثابت را برمی‌داریم.
    """
    import ast
    path = os.path.join(REPO, "tests", "test_sections_recovery.py")
    tree = ast.parse(open(path, encoding="utf-8").read())
    got = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            tgt = node.targets[0]
            if not (isinstance(tgt, ast.Name)
                    and tgt.id in ("FAKE_TELETHON", "FAKE_SESSIONS",
                                   "FAKE_ERRORS")):
                continue
            val = node.value
            if (isinstance(val, ast.Call) and val.args
                    and isinstance(val.args[0], ast.Constant)):
                val = val.args[0]            # textwrap.dedent('...')
            if isinstance(val, ast.Constant) and isinstance(val.value, str):
                import textwrap as _tw
                got[tgt.id] = _tw.dedent(val.value)
    missing = {"FAKE_TELETHON", "FAKE_SESSIONS", "FAKE_ERRORS"} - set(got)
    if missing:
        raise SystemExit("fake telethon constants not found: %r" % missing)
    return got["FAKE_TELETHON"], got["FAKE_SESSIONS"], got["FAKE_ERRORS"]


def reset_app():
    shutil.rmtree(ROOT, ignore_errors=True)
    os.makedirs(APP)
    os.makedirs(DATA)
    for name in ("manager_82.py", "95.py"):
        shutil.copy2(os.path.join(REPO, name), os.path.join(APP, name))
    tel = os.path.join(APP, "telethon")
    os.makedirs(tel)
    fa, fs, fe = _fake_telethon_sources()
    for name, body in (("__init__.py", fa), ("sessions.py", fs),
                       ("errors.py", fe)):
        with open(os.path.join(tel, name), "w", encoding="utf-8") as f:
            f.write(body)


INNER = textwrap.dedent('''
    import os, sys, json, time, urllib.request
    sys.path.insert(0, os.getcwd())
    import manager_82 as M

    out = {}
    out["code_id"] = M.CODE_ID
    out["commit"] = M.GIT_COMMIT
    out["build"] = M.BUILD_VERSION
    out["manager"] = M.MANAGER_PATH
    out["image_dir"] = M.image_dir()
    out["stale"] = bool(M.CODE_IS_STALE)
    out["fp_same"] = M.code_fingerprint(M.image_dir()) == M.code_fingerprint()

    # اثرانگشت با تغییرِ کد عوض می‌شود؟
    import shutil
    tmp = "/tmp/jafj_fp_other"
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    shutil.copy2(os.path.join(M.image_dir(), "manager_82.py"), tmp)
    shutil.copy2(os.path.join(M.image_dir(), "95.py"), tmp)
    out["fp_before"] = M.code_fingerprint(tmp)
    with open(os.path.join(tmp, "95.py"), "a", encoding="utf-8") as f:
        f.write("\\n# changed\\n")
    out["fp_after"] = M.code_fingerprint(tmp)
    shutil.rmtree(tmp, ignore_errors=True)

    # /version روی سرویسِ واقعیِ بوت‌شده
    port = int(os.environ.get("PORT", "0"))
    body, root, hz = "", "", b""
    for _ in range(40):
        try:
            root = urllib.request.urlopen("http://127.0.0.1:%d/" % port,
                                          timeout=1).read().decode()
            break
        except Exception:
            time.sleep(0.25)
    try:
        body = urllib.request.urlopen("http://127.0.0.1:%d/version" % port,
                                      timeout=2).read().decode()
    except Exception as e:
        body = "ERR:%s" % e
    try:
        hz = urllib.request.urlopen("http://127.0.0.1:%d/healthz" % port,
                                    timeout=2).read()
    except Exception as e:
        hz = ("ERR:%s" % e).encode()
    out["version_body"] = body
    out["root_body"] = root
    out["healthz_body"] = hz.decode("utf-8", "replace")

    # پنلِ تلگرام
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

    import asyncio
    ADMIN = 100
    m = M.Manager()
    m.cfg["admin_ids"] = [ADMIN]

    async def main():
        ev = FakeCbEv(ADMIN, "a:ver")
        await m.on_callback(ev)
        txt, kb = ev.edits[-1]
        datas = []
        for row in (kb or []):
            for b in row:
                try:
                    d = b[1][1]           # Button(text=..., data=...)
                except Exception:
                    d = None
                if isinstance(d, (bytes, bytearray)):
                    d = d.decode("utf-8", "ignore")
                if d:
                    datas.append(d)
        out["panel_text"] = txt
        out["panel_datas"] = datas
        out["panel_btn_bytes"] = max([len(str(d).encode()) for d in datas] or [0])
        ev2 = FakeCbEv(ADMIN, "a:home")
        await m.on_callback(ev2)
        out["home_edits"] = len(ev2.edits)
        out["home_answers"] = [str(a)[:80] for a in ev2.answers]
        out["home_text"] = ev2.edits[-1][0] if ev2.edits else ""
        out["notices"] = list(m._startup_notices())
        # بخشِ گم‌شده در پنلِ نسخه دیده می‌شود؟
        rows = list(m.tut_sections())
        rows.append({"id": 9, "name": "بخشِ گم‌شده‌ی آزمایش", "emoji": "🧪",
                     "chat": ADMIN, "ids": [4242], "when": "manual",
                     "delay": 0, "on": True, "once": True, "header": False,
                     "in_hub": True, "note": "", "btn_label": "", "btn_cmd": "",
                     "text": "", "preset": ""})
        M.cfg_snapshot("test-before-loss")
        m.cfg["tut_sections"] = [s for s in rows if s["id"] != 9]
        await asyncio.sleep(2.1)          # ضدتکرارِ ۲ ثانیه‌ایِ callback
        ev3 = FakeCbEv(ADMIN, "a:ver")
        await m.on_callback(ev3)
        out["panel_after_loss"] = ev3.edits[-1][0] if ev3.edits else ""

    asyncio.run(main())
    print("IDENT_JSON " + json.dumps(out, ensure_ascii=False))
''')


def run_inner():
    env = dict(os.environ)
    env.update({
        "DATA_DIR": DATA,
        "JAFJ_APP_DIR": DATA,
        "JAFJ_IMAGE_DIR": APP,
        "PORT": str(PORT),
        "JAFJ_PORT": str(PORT),
        "BOT_TOKEN": "",
        "PYTHONPATH": APP,
    })
    env.pop("JAFJ_COMMIT", None)
    env.pop("JAFJ_CODE_ID", None)
    p = subprocess.run([sys.executable, "-c", INNER], cwd=APP, env=env,
                       capture_output=True, text=True, timeout=300)
    m = re.search(r"^IDENT_JSON (.+)$", p.stdout, re.M)
    if not m:
        print(p.stdout[-3000:])
        print(p.stderr[-3000:])
        check(False, "اسکریپتِ داخلی خروجی داد")
        return {}
    return json.loads(m.group(1))


def run_inner_with_env(extra):
    env = dict(os.environ)
    env.update({
        "DATA_DIR": DATA, "JAFJ_APP_DIR": DATA, "JAFJ_IMAGE_DIR": APP,
        "PORT": str(PORT + 1), "JAFJ_PORT": str(PORT + 1), "BOT_TOKEN": "",
        "PYTHONPATH": APP,
    })
    env.update(extra)
    p = subprocess.run([sys.executable, "-c", INNER], cwd=APP, env=env,
                       capture_output=True, text=True, timeout=300)
    m = re.search(r"^IDENT_JSON (.+)$", p.stdout, re.M)
    return json.loads(m.group(1)) if m else {}


def check_scripts():
    sh = open(os.path.join(REPO, "railway-start.sh"), encoding="utf-8").read()
    check("JAFJ_CODE_ID" in sh and "export JAFJ_CODE_ID" in sh,
          "اسکریپتِ بوت اثرانگشتِ کد را می‌سازد و صادر می‌کند")
    check("sha256sum" in sh and "shasum" in sh,
          "اثرانگشت هم با sha256sum هم با shasum ساخته می‌شود")
    check(re.search(r'log "build=.*code=\$JAFJ_CODE_ID', sh),
          "لاگِ بوت بیلد و کامیت و اثرانگشت را با هم می‌نویسد")
    src = open(os.path.join(REPO, "manager_82.py"), encoding="utf-8").read()
    check("def code_fingerprint" in src and "CODE_ID" in src,
          "مدیر اثرانگشتِ کد را دارد")
    check('"/version"' in src, "مسیرِ /version در هلث‌سرویس هست")
    check("async def version_status" in src and '"a:ver"' in src.replace('if k == "ver":', '"a:ver"'),
          "پنلِ «🧬 نسخه‌ی کد» و مسیرش در تلگرام هست")


def main():
    print("--- deploy identity: CODE_ID + /version + پنلِ تلگرام ---")
    check_scripts()
    reset_app()
    out = run_inner()
    if not out:
        return
    cid = out.get("code_id") or ""
    check(bool(re.fullmatch(r"[0-9a-f]{8}", cid)),
          "CODE_ID یک هشِ ۸ رقمی است (%r)" % cid)
    check(out.get("fp_same") is True, "اثرانگشت پایدار است (دو بار یکی)")
    check(out.get("fp_before") != out.get("fp_after"),
          "با تغییرِ کد، اثرانگشت عوض می‌شود")
    check(out.get("stale") is False,
          "کد از پوشه‌ی ایمیج اجرا می‌شود ⇒ «قدیمی» هشدار نمی‌گیرد")

    vb = out.get("version_body") or ""
    check(vb.startswith("build: v"), "/version با build شروع می‌شود")
    for key in ("commit:", "code:", "manager:", "started:"):
        check(key in vb, "/version خطِ %s دارد" % key)
    check(cid in vb, "/version همان اثرانگشتِ پنل را می‌گوید")
    check(out.get("root_body") == "JAFJ OK\n",
          "«/» همان JAFJ OK ماند (هلث‌چک دست نخورد)")
    check(out.get("healthz_body") == "JAFJ OK\n",
          "«/healthz» همان JAFJ OK ماند")

    txt = out.get("panel_text") or ""
    check("🧬" in txt and cid in txt, "پنلِ تلگرام اثرانگشتِ کد را نشان می‌دهد")
    check("Manual Deploy" in txt,
          "پنل می‌گوید اگر نسخه قدیمی است چه کار کند")
    check("/version" in txt, "پنل آدرسِ /version را هم می‌دهد")
    check("a:secs_h" in (out.get("panel_datas") or []),
          "از پنلِ نسخه می‌شود به «🕘 بازیابی بخش‌ها» رفت")
    check(int(out.get("panel_btn_bytes") or 0) <= 64,
          "داده‌ی دکمه‌ها زیر سقفِ ۶۴ بایتِ تلگرام")
    check(cid in (out.get("home_text") or ""),
          "خانه‌ی پنلِ مدیر هم نسخه‌ی در حالِ اجرا را نشان می‌دهد")
    check(any("نسخه‌ی در حالِ اجرا" in n and cid in n
              for n in (out.get("notices") or [])),
          "هشدارِ بوت نسخه‌ی در حالِ اجرا (با اثرانگشت) را می‌گوید")
    after = out.get("panel_after_loss") or ""
    check("گم‌شده" in after,
          "پنلِ نسخه خلاصه‌ی بازیابی را هم نشان می‌دهد (بخشِ گم‌شده)")

    # اولویتِ متغیرهای میزبان: JAFJ_CODE_ID و JAFJ_COMMIT
    out2 = run_inner_with_env({"JAFJ_CODE_ID": "abc12345",
                               "JAFJ_COMMIT": "9327f0c12345"})
    check((out2.get("code_id") or "") == "abc12345",
          "JAFJ_CODE_ID اولویت دارد (لاگ و /version یکی می‌شوند)")
    check((out2.get("commit") or "").startswith("9327f0c"),
          "JAFJ_COMMIT به عنوانِ کامیت نشان داده می‌شود")
    check("9327f0c" in (out2.get("version_body") or ""),
          "/version همان کامیتِ میزبان را می‌گوید")

    shutil.rmtree(ROOT, ignore_errors=True)


if __name__ == "__main__":
    main()
    bad = len(FAILS)
    print("FAILED %d" % bad)
    for f in FAILS:
        print("  - " + f)
    print("ALL:", "FAIL" if bad else "PASS")
    sys.exit(1 if bad else 0)
