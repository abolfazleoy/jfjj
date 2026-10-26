#!/usr/bin/env python3
"""Private invite links to our channel must not hide the exchange partner link."""
import ast
import asyncio
import re
import sys
import textwrap
import time
import types
from pathlib import Path
from types import SimpleNamespace

source_path = Path(__file__).resolve().parents[1] / "95.py"
source = source_path.read_text(encoding="utf-8")
tree = ast.parse(source)

# Load the real link parser and invite helpers without importing Telegram clients.
helper_nodes = []
for node in tree.body:
    if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id in ("_LINK_PATTERNS", "_SKIP")
            for target in node.targets):
        helper_nodes.append(node)
    elif isinstance(node, ast.FunctionDef) and node.name in (
            "extract_links", "is_invite", "invite_hash"):
        helper_nodes.append(node)
ns = {"re": re}
exec(compile(ast.fix_missing_locations(ast.Module(body=helper_nodes, type_ignores=[])),
             "<link-helpers>", "exec"), ns)

start = source.index("    async def find_their_channel(event, sender, chat_id, deep=True):")
end = source.index("    # ---------- دریافت درخواست تبادل ----------", start)
function_source = textwrap.dedent(source[start:end])


class CheckChatInviteRequest:
    def __init__(self, invite_hash):
        self.invite_hash = invite_hash


# The function's real lazy import resolves against this minimal Telethon module.
telethon = types.ModuleType("telethon")
tl = types.ModuleType("telethon.tl")
functions = types.ModuleType("telethon.tl.functions")
messages = types.ModuleType("telethon.tl.functions.messages")
messages.CheckChatInviteRequest = CheckChatInviteRequest
for name, module in (("telethon", telethon), ("telethon.tl", tl),
                     ("telethon.tl.functions", functions),
                     ("telethon.tl.functions.messages", messages)):
    sys.modules[name] = module


class FakeClient:
    def __init__(self):
        self.entities = {"@mychannel": SimpleNamespace(id=123, username="mychannel")}
        self.invites = {
            "OWNPRIVATE123456": 123,
            "PARTNERPRIVATE123456": 456,
        }
        self.checked = []

    async def get_entity(self, ref):
        if ref not in self.entities:
            raise ValueError("unknown entity")
        return self.entities[ref]

    async def __call__(self, request):
        self.checked.append(request.invite_hash)
        cid = self.invites.get(request.invite_hash)
        return SimpleNamespace(chat=SimpleNamespace(id=cid) if cid else None)


class FakeState:
    def prof(self, tier):
        return {"channel": "@mychannel"}


class FakeEngine:
    def __init__(self):
        self.st = FakeState()
        self.my_username = "myaccount"
        self.logs = []

    def log(self, *args):
        self.logs.append(args)


async def check_private_own_link_is_skipped():
    client = FakeClient()
    engine = FakeEngine()
    ns.update({"eng": engine, "client": client, "re": re, "time": time,
               "extract_links": ns["extract_links"], "is_invite": ns["is_invite"],
               "invite_hash": ns["invite_hash"]})
    exec(compile(function_source, "<find-their-channel>", "exec"), ns)

    event = SimpleNamespace(
        id=50,
        raw_text=("جوین شدم؛ لینک من https://t.me/+OWNPRIVATE123456 "
                  "لینک طرف https://t.me/+PARTNERPRIVATE123456"),
    )
    sender = SimpleNamespace(id=77)
    link, origin = await ns["find_their_channel"](event, sender, 100, deep=False)
    assert link == "https://t.me/+PARTNERPRIVATE123456", link
    assert origin == "از پیام خودش", origin
    assert client.checked == ["OWNPRIVATE123456", "PARTNERPRIVATE123456"]

    # Even if Telegram cannot reveal either invite's chat ID, preserve Jafj's
    # documented two-link order: own destination first, exchange partner second.
    client.invites = {"OWNPRIVATE123456": None, "PARTNERPRIVATE123456": None}
    client.checked.clear()
    engine._exchange_link_id_cache.clear()
    link, _ = await ns["find_their_channel"](event, sender, 100, deep=False)
    assert link == "https://t.me/+PARTNERPRIVATE123456", link


asyncio.run(check_private_own_link_is_skipped())
print("peer link selection: PASS")
