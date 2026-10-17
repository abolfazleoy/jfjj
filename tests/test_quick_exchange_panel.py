#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""تبادل سریع + بستن پنل + قاعدهٔ «اول کانال، بعد گروه».

این تست رفتارِ واقعیِ ۹۵.py را با تلگرامِ قلابی اجرا می‌کند (نه فقط
جست‌وجوی رشته در سورس). سه فاز دارد:

  A) پنل و بستن پنل
     - پنل ته‌اش توضیحِ «تبادل سریع» و راهِ «بستن پنل» را دارد؛
     - `بستن پنل` پیامِ پنلِ ربات را پاک می‌کند و *همان* پیامِ شروعِ
       ران را دوباره می‌فرستد؛
     - پیامِ شروعِ تازه دوباره پردازش نمی‌شود (ضدحلقه)؛
     - بستن وسطِ wizard تبادل سریع هم کار می‌کند و wizard را کنسل می‌کند.

  B) تبادل سریع و قاعدهٔ «اول کانال»
     - ورودیِ بی‌معنی (کلمهٔ «کانال»، «پنل»، جملهٔ فارسی) هرگز به‌عنوان
       کانال/گروه ذخیره نمی‌شود؛
     - اگر کاربر اول گروه را بدهد، ذخیره می‌شود ولی تبادل شروع نمی‌شود
       تا کانال ثبت شود (همان باگِ گزارش‌شده)؛
     - کانال = گروه رد می‌شود؛
     - `تبادل روشن` بدون کانال روشن نمی‌شود.

  C) حلقه‌های واقعی (دو پروسهٔ جدا)
     - بدون کانال: با وجود تبادلِ روشن، گروهِ ثبت‌شده و رکوردِ تأییدشده،
       هیچ اسکن/جوینی انجام نمی‌شود؛
     - با کانال: همان شرایط باید اسکن و جوین را انجام دهد (کنترلِ مثبت).

اجرا:  python3 tests/test_quick_exchange_panel.py
"""
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.join(tempfile.gettempdir(), "jafj_qe_panel_run")

FAKE = textwrap.dedent('''
    import asyncio, importlib.util, os, sys, time, types

    REPO = os.environ["REPO"]
    os.chdir(os.environ["DATA"])

    sent = []            # پیام‌های ارسالی ربات به «me»
    deleted = []         # آرگومان‌های delete_messages
    scan_calls = []      # گروه‌هایی که iter_messages رویشان صدا زده شد
    requests = []        # درخواست‌های تلگرام (Join/Import/…)
    CLIENTS = []
    FAILS = []
    CHECKS = [0]

    def check(cond, name):
        CHECKS[0] += 1
        print(("OK " if cond else "FAIL ") + name)
        if not cond:
            FAILS.append(name)

    class FakeMsg:
        def __init__(self, mid, text=""):
            self.id = mid
            self.raw_text = text

    class FakeClient:
        def __init__(self, *a, **k):
            self.handlers = []
            self._id = 10000
            self._done = asyncio.Event()
            CLIENTS.append(self)
        def on(self, builder):
            def deco(fn):
                self.handlers.append((builder, fn))
                return fn
            return deco
        async def start(self, phone=None, **k):
            return self
        async def get_me(self):
            return types.SimpleNamespace(first_name="Test", username="tester", id=555)
        async def send_message(self, peer, text=None, **k):
            self._id += 1
            msg = FakeMsg(self._id, text or "")
            if str(peer) in ("me", "555"):
                sent.append(msg)
            return msg
        async def delete_messages(self, peer, ids):
            deleted.append(list(ids))
            return len(list(ids))
        async def run_until_disconnected(self):
            await self._done.wait()
        async def get_entity(self, x):
            return types.SimpleNamespace(id=9001, access_hash=1234, title="Chan")
        async def iter_messages(self, group, limit=None, **k):
            scan_calls.append(str(group))
            if False:
                yield None
        def __call__(self, req):
            requests.append(req)
            async def _done():
                return types.SimpleNamespace(
                    chats=[types.SimpleNamespace(id=9001, access_hash=1234,
                                                 title="Chan")])
            return _done()
        def __getattr__(self, name):
            async def _stub(*a, **k):
                return None
            return _stub

    class NewMsgBuilder:
        def __init__(self, *a, **k):
            self.args, self.kwargs = a, k

    tl = types.ModuleType("telethon")
    tl.TelegramClient = FakeClient
    tl.events = types.SimpleNamespace(NewMessage=NewMsgBuilder)
    tl.errors = types.SimpleNamespace(**{
        n: type(n, (Exception,), {}) for n in (
            "FloodWaitError", "SlowModeWaitError", "ChatWriteForbiddenError",
            "ChannelPrivateError", "UsernameNotOccupiedError", "RPCError",
            "UserNotParticipantError", "UserAlreadyParticipantError",
            "InviteHashExpiredError", "InviteHashInvalidError",
            "ChannelsTooMuchError", "InviteRequestSentError")})
    tlchan = types.ModuleType("telethon.tl.functions.channels")
    tlmsg = types.ModuleType("telethon.tl.functions.messages")
    def _req_class(name):
        class _R:
            def __init__(self, *a, **k):
                self.args, self.kwargs = a, k
        _R.__name__ = name
        return _R
    for n in ("JoinChannelRequest", "LeaveChannelRequest", "GetParticipantRequest"):
        setattr(tlchan, n, _req_class(n))
    tlmsg.ImportChatInviteRequest = _req_class("ImportChatInviteRequest")
    tlf = types.ModuleType("telethon.tl.functions")
    tlf.channels, tlf.messages = tlchan, tlmsg
    tltl = types.ModuleType("telethon.tl")
    tltl.functions = tlf
    tl.tl = tltl
    for name, mod in (("telethon", tl), ("telethon.events", tl.events),
                      ("telethon.errors", tl.errors), ("telethon.tl", tltl),
                      ("telethon.tl.functions", tlf),
                      ("telethon.tl.functions.channels", tlchan),
                      ("telethon.tl.functions.messages", tlmsg)):
        sys.modules[name] = mod

    spec = importlib.util.spec_from_file_location(
        "selfbot95", os.path.join(REPO, "95.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.DRY_RUN = False

    eng = mod.Engine()
    creds = {"api_id": 1, "api_hash": "h", "phone": "+989120000000"}
    CLIENT = [None]

    class Ev:
        def __init__(self, text, mid):
            self.raw_text = text
            self.out = True
            self.sender_id = 555
            self.message = types.SimpleNamespace(id=mid)
            self.chat_id = 555
            self.id = mid
        async def get_reply_message(self):
            return None
        async def get_chat(self):
            return types.SimpleNamespace(id=555)
        async def reply(self, t):
            return await CLIENT[0].send_message("me", t)

    def reset(channel=False, vip=False, enabled=False, groups=(), scan=False):
        eng.st.prof("standard")["channel"] = "@mychannel" if channel else ""
        eng.st.prof("vip")["channel"] = "@vipchannel" if vip else ""
        x = eng.ex_cfg()
        x["groups"] = list(groups)
        x["enabled"] = bool(enabled)
        x["op_gap_min_sec"] = 0
        x["op_gap_max_sec"] = 0
        x["initiate"] = True
        x["scan_every_sec"] = 1
        x["response_min_sec"] = 0
        x["response_max_sec"] = 0
        x["come_min_sec"] = 0
        x["come_max_sec"] = 0
        eng.st["risk"]["_auto_off"] = False
        eng.st.save()
        eng.db._x("DELETE FROM exchange")
        if scan:
            scan_calls.clear()
            requests.clear()

    async def cmd(text, mid=[20000]):
        mid[0] += 1
        before = len(sent)
        await CLIENT[0].handlers_me(Ev(text, mid[0]))
        return sent[before:]

    async def main():
        task = asyncio.create_task(mod.connect_and_run(eng, creds))
        client = None
        for _ in range(600):
            if CLIENTS:
                client = CLIENTS[-1]
                if len(client.handlers) >= 1:
                    break
            await asyncio.sleep(0.02)
        CLIENT[0] = client
        me = None
        for b, fn in client.handlers:
            if b.kwargs.get("chats") == "me":
                me = fn
        if me is None:
            print("FAIL no saved-messages handler")
            return 1
        client.handlers_me = me
        print("HANDLERS %d" % len(client.handlers))

        # ═════════════ A) پنل و بستن پنل ═════════════
        reset()
        out = await cmd("پنل")
        p = out[-1].raw_text if out else ""
        check("💎 جفج 3.0" in p, "panel opens with dashboard header")
        check("منوی اصلی" in p, "panel has main menu")
        check("تبادل سریع" in p, "panel tail mentions quick exchange")
        check("فقط ۲ قدم" in p, "panel explains quick exchange in 2 steps")
        check("مثلاً @mychannel" in p, "panel shows a concrete channel example")
        check("کانالِ خودت" in p, "panel says the first input is your channel")
        check("گروه تبادل" in p, "panel says the second input is the group")
        check("بستن پنل" in p, "panel tail shows close-panel command")
        check("پنل پاک می‌شه" in p, "panel explains what close does")
        check("بستن" in p and "پیامِ شروع" in p,
              "close description mentions startup message")

        panel_id = out[-1].id
        before_del = len(deleted)
        before_n = len(sent)
        out = await cmd("بستن پنل")
        check(len(deleted) == before_del + 1, "close deletes bot panel message")
        check(panel_id in deleted[-1], "close deletes the exact panel id")
        check(len(sent) == before_n + 1, "close sends exactly one new message")
        start = sent[-1].raw_text
        boot = sent[0].raw_text
        check("آنلاین شد" in start, "close sends the startup text")
        check(start == boot, "close re-sends the exact boot message")
        check("تبادل سریع" in start, "startup text advertises quick exchange")
        check("داشبورد" in start,
              "startup text tells how to reopen the panel")
        # پیامِ شروعِ تازه دوباره پردازش نشود
        n0 = len(sent)
        await me(Ev("", sent[-1].id))
        check(len(sent) == n0, "startup message is not re-processed (no loop)")

        # بستن وقتی پنلی باز نیست: فقط پیام شروع
        before_del = len(deleted)
        before_n = len(sent)
        out = await cmd("بستن پنل")
        check(len(deleted) == before_del, "close with no panel deletes nothing")
        check(len(sent) == before_n + 1, "close with no panel still sends startup")

        before_del = len(deleted)
        await cmd(".closepanel")
        check(len(deleted) == before_del + 1 or len(deleted) == before_del,
              "dot command closes panel gracefully")
        before_del = len(deleted)
        await cmd("بستن")
        check(len(deleted) == before_del, "bare بستن is accepted (nothing to delete)")

        await cmd("پنل")
        await cmd("پنل")
        before_del = len(deleted)
        await cmd("بستن پنل")
        check(len(deleted) == before_del + 1, "close after two panels deletes once")
        check(len(deleted[-1]) >= 2, "close deletes all tracked panel messages")

        # ═════════════ B) ویزارد تبادل سریع ═════════════
        reset()
        out = await cmd("تبادل سریع")
        w = out[-1].raw_text if out else ""
        check("فقط ۲ قدم" in w, "wizard explains the 2-step flow")
        check("کانالِ خودت" in w, "wizard asks for the channel first")
        check("انصراف" in w and "لغو" in w, "wizard shows the cancel command")

        out = await cmd("گروه @mygroup")
        g = out[-1].raw_text if out else ""
        check("گروه ذخیره شد" in g, "group without channel is stored but parked")
        check("کانال" in g, "group-first still asks for the channel")
        check(not eng.ex_cfg()["enabled"], "group-first does NOT enable exchange")
        check(not eng.st.prof("standard")["channel"], "group-first leaves channel empty")

        out = await cmd("کانال @mychannel")
        done = out[-1].raw_text if out else ""
        check("تبادل آماده‌ست" in done, "channel then finishes the wizard")
        check(eng.st.prof("standard")["channel"] == "@mychannel",
              "channel is persisted after wizard")
        check(eng.ex_cfg()["groups"] == ["@mygroup"], "group is persisted after wizard")
        check(eng.ex_cfg()["enabled"] is True, "wizard turns exchange on")
        check(eng.ex_cfg().get("msg_ok") == "جوین شدم ✅",
              "quick exchange fills default reply texts")
        check(eng.ex_cfg().get("msg_no", "").startswith("چک کردم"),
              "quick exchange uses the new msg_no default")
        check(eng.st["risk"]["_auto_off"] is False,
              "quick exchange clears the auto-off guard")

        out = await cmd("تبادل سریع")
        r = out[-1].raw_text if out else ""
        check("از قبل آماده" in r, "wizard detects an already-ready setup")
        check("روشن" in r, "ready message says it is already on")

        eng.ex_cfg()["enabled"] = False
        eng.st.save()
        out = await cmd("تبادل سریع")
        r2 = out[-1].raw_text if out else ""
        check("فقط روشنش کن" in r2, "ready-but-off tells the user to turn it on")
        check("تبادل روشن" in r2, "ready-but-off shows the exact command")

        # ═════════════ C) اعتبارسنجی ورودی ═════════════
        reset()
        await cmd("تبادل سریع")
        out = await cmd("کانال")
        check("کانالِ خودت" in out[-1].raw_text,
              "bare channel word is a prompt, not a value")
        out = await cmd("پنل")
        check("معتبر نیست" in out[-1].raw_text,
              "panel word is rejected as a channel")
        out = await cmd("تبادل")
        check("معتبر نیست" in out[-1].raw_text,
              "exchange word is rejected as a channel")
        out = await cmd("سلام دنیا")
        check("معتبر نیست" in out[-1].raw_text,
              "a Persian sentence is rejected as a channel")
        out = await cmd("@abcd")
        check("گروه تبادل" in out[-1].raw_text,
              "valid channel moves the wizard to the group step")
        out = await cmd("@abcd")
        check("یکی باشند" in out[-1].raw_text,
              "channel == group is rejected")
        check(not eng.ex_cfg()["enabled"], "same channel/group never enables exchange")
        out = await cmd("https://t.me/mygroup")
        check("تبادل آماده‌ست" in out[-1].raw_text,
              "t.me link is accepted as the group")
        check(eng.ex_cfg()["groups"] == ["@mygroup"],
              "t.me group link is normalized to @username")
        check(eng.st.prof("standard")["channel"] == "@abcd",
              "the earlier channel is preserved")

        reset()
        await cmd("تبادل سریع")
        out = await cmd("لغو")
        check("لغو شد" in out[-1].raw_text, "cancel aborts the wizard")
        check(not eng.ex_cfg()["enabled"], "cancel leaves exchange off")
        n0 = len(sent)
        await cmd("@aftercancel")
        check(len(sent) == n0, "after cancel a bare username is ignored")
        check(not eng.st.prof("standard")["channel"],
              "after cancel no channel is stored")

        # کانال تکراری برای گروه، و لینک‌های نرمال‌شده
        reset()
        await cmd("تبادل سریع")
        out = await cmd("کانال https://t.me/c1chan")
        check("گروه تبادل" in out[-1].raw_text,
              "full channel link is accepted")
        out = await cmd("گروه t.me/g1chan")
        check("تبادل آماده‌ست" in out[-1].raw_text,
              "short group link is accepted")
        check(eng.st.prof("standard")["channel"] == "@c1chan",
              "channel URL normalized to @name")
        check(eng.ex_cfg()["groups"] == ["@g1chan"],
              "group URL normalized to @name")

        # ═════════════ D) قاعدهٔ «اول کانال» در دستورها ═════════════
        reset()
        out = await cmd("تبادل روشن")
        r = out[-1].raw_text if out else ""
        check("نشد" in r and "روشن" in r,
              "exchange refuses to turn on without a channel")
        check("اول کانال" in r, "refusal explains channel-first rule")
        check("کانال @" in r, "refusal shows the channel command")
        check("گروهِ تبادل" in r, "refusal explains the group is not followed")
        check(not eng.ex_cfg()["enabled"], "exchange stays off without a channel")

        out = await cmd("تبادل")
        check("کانالِ من تنظیم نشده" in out[-1].raw_text,
              "exchange page warns about the missing channel")

        out = await cmd("کانال @mychannel")
        check("@mychannel" in out[-1].raw_text, "channel command confirms the value")
        out = await cmd("تبادل روشن")
        check("روشن" in out[-1].raw_text and "نشد" not in out[-1].raw_text,
              "exchange turns on after the channel is set")
        check(eng.ex_cfg()["enabled"], "enabled flag is set")
        out = await cmd("تبادل")
        check("کانالِ من تنظیم نشده" not in out[-1].raw_text,
              "exchange page no longer warns")

        reset()
        eng.st.prof("vip")["channel"] = "@vipchannel"
        eng.st.save()
        check(eng.ex_channel_ready() is True, "VIP-only channel counts as ready")
        out = await cmd("تبادل روشن")
        check(eng.ex_cfg()["enabled"], "exchange can use a VIP-only channel")
        reset()
        check(eng.ex_channel_ready() is False, "no channel -> not ready")
        eng.st.prof("standard")["channel"] = "کانال"
        eng.st.save()
        check(eng.ex_channel_ready() is False,
              "junk stored channel (the word کانال) is not ready")
        eng.st.prof("standard")["channel"] = "https://t.me/+AbCdEfGh"
        check(eng.ex_channel_ready() is True,
              "invite link counts as a valid channel")
        eng.st.prof("standard")["channel"] = "@xchan"
        check(eng.ex_channel_ready() is True, "standard channel -> ready")

        out = await cmd("تبادل خاموش")
        check("خاموش" in out[-1].raw_text, "exchange off command works")
        check(not eng.ex_cfg()["enabled"], "exchange really turns off")

        # ═════════════ E) نرمال‌سازی و مقایسهٔ آیدی ═════════════
        n = mod.normalize_peer_ref
        check(n("@MyChan") == "@MyChan", "normalize keeps @username")
        check(n("MyChan") == "@MyChan", "normalize adds @ to a bare username")
        check(n("https://t.me/MyChan") == "@MyChan", "normalize full URL")
        check(n("t.me/MyChan/") == "@MyChan", "normalize short URL with slash")
        check(n("telegram.me/MyChan") == "@MyChan", "normalize telegram.me URL")
        check(n("https://t.me/s/MyChan") == "@MyChan", "normalize preview URL")
        check(n("https://t.me/+AbCdEfGh") == "https://t.me/+AbCdEfGh",
              "normalize invite link")
        check(n("https://t.me/joinchat/AbCdEfGh") == "https://t.me/+AbCdEfGh",
              "normalize old joinchat link")
        check(n("+AbCdEfGh") == "https://t.me/+AbCdEfGh",
              "normalize bare invite hash")
        check(n("-1001234567890") == "-1001234567890", "normalize numeric id")
        check(n("کانال") is None, "Persian command word is not a ref")
        check(n("panel") is None, "panel word is not a ref")
        check(n("a b") is None, "spaced value is not a ref")
        check(n("") is None, "empty value is not a ref")
        check(n("https://t.me/c/123/456") is None, "private message link is not a ref")
        sp = mod.same_peer_ref
        check(sp("@a", "t.me/a") is True, "same ref: @a vs t.me/a")
        check(sp("@a", "@A") is True, "same ref is case-insensitive")
        check(sp("@a", "@b") is False, "different refs are different")
        check(sp("https://t.me/+XyZ123", "+XyZ123") is True,
              "same invite ref with/without t.me")

        # ═════════════ F) بستن پنل وسط wizard ═════════════
        reset()
        await cmd("تبادل سریع")
        n0 = len(sent)
        before_del = len(deleted)
        await cmd("بستن پنل")
        check(len(sent) == n0 + 1, "close mid-wizard sends only startup text")
        check("آنلاین شد" in sent[-1].raw_text, "close mid-wizard sends startup text")
        check(len(deleted) == before_del, "close mid-wizard has no panel to delete")
        n1 = len(sent)
        await cmd("@shouldnotstore")
        check(len(sent) == n1, "wizard is really cancelled after close")
        check(not eng.st.prof("standard")["channel"],
              "nothing is stored after close mid-wizard")
        check(not eng.ex_cfg()["enabled"], "exchange stays off after close mid-wizard")

        print("CHECKS %d" % CHECKS[0])
        print("FAILED %d" % len(FAILS))
        client._done.set()
        try:
            await asyncio.wait_for(task, timeout=20)
        except Exception:
            pass
        return 0 if not FAILS else 1

    if __name__ == "__main__":
        sys.exit(asyncio.run(main()))
''')

LOOPS = textwrap.dedent('''
    import asyncio, importlib.util, os, sys, time, types

    REPO = os.environ["REPO"]
    MODE = os.environ["MODE"]
    os.chdir(os.environ["DATA"])

    scan_calls = []
    requests = []
    CLIENTS = []

    class FakeClient:
        def __init__(self, *a, **k):
            self.handlers = []
            self._done = asyncio.Event()
            self._id = 10000
            CLIENTS.append(self)
        def on(self, builder):
            def deco(fn):
                self.handlers.append((builder, fn))
                return fn
            return deco
        async def start(self, phone=None, **k):
            return self
        async def get_me(self):
            return types.SimpleNamespace(first_name="Test", username="tester", id=555)
        async def send_message(self, peer, text=None, **k):
            self._id += 1
            class M:
                id = self._id
                raw_text = text or ""
            return M()
        async def delete_messages(self, peer, ids):
            return None
        async def run_until_disconnected(self):
            await self._done.wait()
        async def get_entity(self, x):
            return types.SimpleNamespace(id=9001, access_hash=1234, title="Chan")
        async def iter_messages(self, group, limit=None, **k):
            scan_calls.append(str(group))
            if False:
                yield None
        def __call__(self, req):
            requests.append(type(req).__name__)
            async def _done():
                return types.SimpleNamespace(
                    chats=[types.SimpleNamespace(id=9001, access_hash=1234,
                                                 title="Chan")])
            return _done()
        def __getattr__(self, name):
            async def _stub(*a, **k):
                return None
            return _stub

    class NewMsgBuilder:
        def __init__(self, *a, **k):
            self.args, self.kwargs = a, k

    tl = types.ModuleType("telethon")
    tl.TelegramClient = FakeClient
    tl.events = types.SimpleNamespace(NewMessage=NewMsgBuilder)
    tl.errors = types.SimpleNamespace(**{
        n: type(n, (Exception,), {}) for n in (
            "FloodWaitError", "SlowModeWaitError", "ChatWriteForbiddenError",
            "ChannelPrivateError", "UsernameNotOccupiedError", "RPCError",
            "UserNotParticipantError", "UserAlreadyParticipantError",
            "InviteHashExpiredError", "InviteHashInvalidError",
            "ChannelsTooMuchError", "InviteRequestSentError")})
    tlchan = types.ModuleType("telethon.tl.functions.channels")
    tlmsg = types.ModuleType("telethon.tl.functions.messages")
    def _req_class(name):
        class _R:
            def __init__(self, *a, **k):
                self.args, self.kwargs = a, k
        _R.__name__ = name
        return _R
    for n in ("JoinChannelRequest", "LeaveChannelRequest", "GetParticipantRequest"):
        setattr(tlchan, n, _req_class(n))
    tlmsg.ImportChatInviteRequest = _req_class("ImportChatInviteRequest")
    tlf = types.ModuleType("telethon.tl.functions")
    tlf.channels, tlf.messages = tlchan, tlmsg
    tltl = types.ModuleType("telethon.tl")
    tltl.functions = tlf
    tl.tl = tltl
    for name, mod in (("telethon", tl), ("telethon.events", tl.events),
                      ("telethon.errors", tl.errors), ("telethon.tl", tltl),
                      ("telethon.tl.functions", tlf),
                      ("telethon.tl.functions.channels", tlchan),
                      ("telethon.tl.functions.messages", tlmsg)):
        sys.modules[name] = mod

    spec = importlib.util.spec_from_file_location(
        "selfbot95", os.path.join(REPO, "95.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.DRY_RUN = False
    eng = mod.Engine()

    eng.st.prof("standard")["channel"] = ("" if MODE == "neg" else "@mychannel")
    eng.st.prof("vip")["channel"] = ""
    x = eng.ex_cfg()
    x["enabled"] = True
    x["groups"] = ["@g1", "@g2"]
    x["initiate"] = True
    x["scan_every_sec"] = 1
    x["op_gap_min_sec"] = 0
    x["op_gap_max_sec"] = 0
    x["min_join_gap_sec"] = 1
    x["max_join_gap_sec"] = 1
    x["scan_max_age_sec"] = 3600
    x["report_mode"] = "off"
    x["max_reminders"] = 0
    x["auto_join"] = True
    eng.st.save()
    eng.join_thr.apply({"min_gap_sec": 1, "max_gap_sec": 1, "max_per_hour": 0})
    rec, _new = eng.db.ex_add(777, "@peer", "@peerchannel")
    eng.db.ex_set(rec["id"], status="approved", direction="in",
                  peer_id=777, peer_name="@peer", created_at=int(time.time()),
                  note="test")

    async def main():
        creds = {"api_id": 1, "api_hash": "h", "phone": "+989120000000"}
        task = asyncio.create_task(mod.connect_and_run(eng, creds))
        client = None
        for _ in range(500):
            if CLIENTS:
                client = CLIENTS[-1]
                if client.handlers:
                    break
            await asyncio.sleep(0.02)
        await asyncio.sleep(2.2)
        print("MODE", MODE)
        print("SCANS", len(scan_calls))
        print("REQUESTS", len(requests), ",".join(requests))
        print("ENABLED", eng.ex_cfg()["enabled"])
        print("CHANNEL", eng.st.prof("standard")["channel"])
        client._done.set()
        try:
            await asyncio.wait_for(task, timeout=15)
        except Exception:
            pass

    asyncio.run(main())
''')


def reset_dir():
    shutil.rmtree(ROOT, ignore_errors=True)
    os.makedirs(ROOT)


def run_driver(code, mode):
    env = dict(os.environ, REPO=REPO, DATA=ROOT, MODE=mode)
    return subprocess.run([sys.executable, "-c", code], env=env,
                          text=True, capture_output=True, timeout=180)


def main():
    reset_dir()
    fails = []

    print("--- phase A/B: panel, close, quick exchange, validation ---")
    r = run_driver(FAKE, "main")
    out = r.stdout + r.stderr
    keep = [l for l in r.stdout.splitlines()
            if l.startswith(("OK ", "FAIL ", "CHECKS ", "FAILED ", "HANDLERS "))]
    print("\n".join(keep) if keep else out[-3000:])
    if r.returncode != 0:
        fails.append("interactive driver failed")
        if not keep:
            print(out[-4000:])
    checks = 0
    failed = 0
    for line in r.stdout.splitlines():
        if line.startswith("CHECKS "):
            checks = int(line.split()[1])
        elif line.startswith("FAILED "):
            failed = int(line.split()[1])
    print("   %d checks, %d failed" % (checks, failed))
    if checks < 60:
        fails.append("expected at least 60 checks, got %d" % checks)
    if failed:
        fails.append("%d interactive checks failed" % failed)

    print("--- phase C1: loops must do nothing without a channel ---")
    reset_dir()
    r1 = run_driver(LOOPS, "neg")
    o1 = r1.stdout + r1.stderr
    print(o1.strip()[-1200:])
    neg_ok = (r1.returncode == 0
              and "SCANS 0" in o1
              and "REQUESTS 0" in o1)
    print("%s  no-channel gate (scans=0, telegram calls=0)"
          % ("✅ PASS" if neg_ok else "❌ FAIL"))
    if not neg_ok:
        fails.append("no-channel gate failed")

    print("--- phase C2: with a channel, scans and joins must run ---")
    reset_dir()
    r2 = run_driver(LOOPS, "pos")
    o2 = r2.stdout + r2.stderr
    print(o2.strip()[-1200:])
    pos_ok = (r2.returncode == 0 and "SCANS 0" not in o2
              and "REQUESTS 0" not in o2
              and "JoinChannelRequest" in o2)
    print("%s  channel-present control (scans>0, join attempted)"
          % ("✅ PASS" if pos_ok else "❌ FAIL"))
    if not pos_ok:
        fails.append("positive control failed")

    print()
    if fails:
        print("❌ FAILED: " + " | ".join(fails))
        return 1
    print("✅ PASS  quick-exchange + close-panel + channel-first")
    return 0


if __name__ == "__main__":
    sys.exit(main())
