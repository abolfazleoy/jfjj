#!/usr/bin/env python3
"""Regression checks for configurable customer-facing pairing samples."""
import ast
from pathlib import Path

source = Path(__file__).resolve().parents[1] / "manager_82.py"
text = source.read_text(encoding="utf-8")
tree = ast.parse(text)

assert 'B("🎞 نمونه‌های جفج", "m:samples", "success")' in text
assert 'B("🎞 نمونه‌های جفج", "a:samples", "success")' in text
assert '"sample_chat": 0' in text and '"sample_ids": []' in text
assert 'if data == "m:samples":' in text and 'return await self.send_samples(uid)' in text
for action in ("samples", "sample_set", "sample_done", "sample_view", "sample_del"):
    assert f'if k == "{action}":' in text, f"missing admin action {action}"
assert '"sample_set", "trial_min"' in text
assert 'stp == "sample_set"' in text

manager = next(node for node in ast.walk(tree)
               if isinstance(node, ast.ClassDef) and node.name == "Manager")
methods = {node.name: node for node in manager.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
samples_src = ast.get_source_segment(text, methods["samples_src"])
send_samples = ast.get_source_segment(text, methods["send_samples"])
assert '"sample_chat"' in samples_src and '"sample_ids"' in samples_src
assert "self._tut_load(chat, ids)" in send_samples
assert "self._tut_copy(uid, msgs, chat)" in send_samples

print("samples feature: PASS")
