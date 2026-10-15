#!/usr/bin/env python3
"""فیلتر خروجی: پیام ناخواسته‌ی «برای استفاده از ربات باید کانال ... جوین شوی»
(t.me/A_TOOLSx2) هرگز نباید از ربات ارسال شود؛ پیام‌های عادی باید سالم بمانند.

تست بدون نیاز به telethon: بخشِ فیلتر از manager_82.py استخراج و اجرا می‌شود.
"""
import asyncio
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = open(os.path.join(ROOT, "manager_82.py"), encoding="utf-8").read()

start = SRC.index("BLOCKED_OUTGOING_PATTERNS = (")
end = SRC.index("def local_now():")
ns = {"re": re}
exec(SRC[start:end], ns)
is_blocked_outgoing = ns["is_blocked_outgoing"]
install_outgoing_filter = ns["install_outgoing_filter"]


class FakeClient:
    def __init__(self):
        self.sent = []
        self.edited = []

    async def send_message(self, entity, message=None, *a, **kw):
        self.sent.append((entity, message))
        return type("M", (), {"id": 42})()

    async def edit_message(self, entity, message=None, *a, **kw):
        self.edited.append((entity, message))
        return type("M", (), {"id": 42})()


SPAM = (
    "🚀 To use this bot, you must join our channel: https://t.me/A_TOOLSx2\n\n"
)
FA_OK = "🔒 <b>عضویت اجباری</b>\nبرای استفاده از ربات باید عضو شوی."

assert is_blocked_outgoing(SPAM)
assert is_blocked_outgoing("join https://t.me/a_toolsx2 now")
assert is_blocked_outgoing("to use this bot you must join the channel")
assert not is_blocked_outgoing(FA_OK)
assert not is_blocked_outgoing("")
assert not is_blocked_outgoing(None)


async def main():
    c = FakeClient()
    install_outgoing_filter(c)
    # ارسال مسدودشده نباید به کلاینت اصلی برسد
    r = await c.send_message(1, SPAM, parse_mode="html")
    assert c.sent == [], c.sent
    assert r.id == 0
    # ویرایش مسدودشده هم نباید برسد
    await c.edit_message(1, SPAM)
    assert c.edited == [], c.edited
    # پیام عادی باید بی‌تغییر برود
    r2 = await c.send_message(1, FA_OK)
    assert c.sent == [(1, FA_OK)]
    assert r2.id == 42
    await c.edit_message(1, text=FA_OK)
    assert c.edited == [(1, None)], c.edited  # ویرایش عادی با kwarg «text» رد شد
    # نصب دوباره نباید دو لایه بسازد
    install_outgoing_filter(c)
    await c.send_message(2, FA_OK)
    assert c.sent[-1] == (2, FA_OK)
    assert len(c.sent) == 2


asyncio.run(main())
print("OK: outgoing block tests passed")
