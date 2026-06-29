#!/usr/bin/env python3
"""
验证 task.task.update_user_access_v2 是 p1 还是 p2 schema。

服务器运行：
  ~/pipelit/.venv/bin/python scripts/check_event_schema.py
"""

import json

try:
    import lark_oapi as lark
except ImportError:
    print("缺 lark-oapi，先装：uv pip install lark-oapi")
    raise

try:
    from importlib.metadata import version
    print(f"lark-oapi version: {version('lark-oapi')}\n")
except Exception:
    print("lark-oapi version: unknown\n")

# ── 1. 检查方法是否存在 ────────────────────────────────────────────────────
builder = lark.EventDispatcherHandler.builder("", "")
has_p1 = hasattr(builder, "register_p1_customized_event")
has_p2 = hasattr(builder, "register_p2_customized_event")
print(f"register_p1_customized_event: {'✓' if has_p1 else '✗ 不存在'}")
print(f"register_p2_customized_event: {'✓' if has_p2 else '✗ 不存在'}\n")

# ── 2. 模拟 dispatch，看哪个 handler 能接到 ──────────────────────────────
EVENT_TYPE = "task.task.update_user_access_v2"
results = []


def make_handler(label):
    def h(data):
        results.append(label)
        print(f"  ✓ 命中: {label}")
    return h


b = lark.EventDispatcherHandler.builder("", "")
if has_p1:
    b = b.register_p1_customized_event(EVENT_TYPE, make_handler("p1"))
if has_p2:
    b = b.register_p2_customized_event(EVENT_TYPE, make_handler("p2"))
handler = b.build()

# 先查 RawRequest 签名
import inspect
print(f"RawRequest signature: {inspect.signature(lark.RawRequest.__init__)}\n")

# schema 1.0 格式
schema1_payload = json.dumps({
    "uuid": "test-uuid",
    "token": "",
    "ts": "1700000000",
    "type": "event_callback",
    "event": {
        "type": EVENT_TYPE,
        "task_guid": "test-task-guid",
        "event_types": ["task_assignees_update"],
    }
}).encode()

# schema 2.0 格式
schema2_payload = json.dumps({
    "schema": "2.0",
    "header": {
        "event_id": "test-id",
        "event_type": EVENT_TYPE,
        "create_time": "1700000000",
        "token": "",
        "app_id": "",
        "tenant_key": "",
    },
    "event": {
        "task_guid": "test-task-guid",
        "event_types": ["task_assignees_update"],
    }
}).encode()

print("── 模拟 schema 1.0 dispatch ──")
results.clear()
try:
    req = lark.RawRequest()
    req.body = schema1_payload
    req.headers = {}
    handler.do(req)
except Exception as e:
    print(f"  dispatch 异常: {e}")
if not results:
    print("  ✗ 无 handler 命中")

print("\n── 模拟 schema 2.0 dispatch ──")
results.clear()
try:
    handler.do(lark.RawRequest(schema2_payload, {}))
except Exception as e:
    print(f"  dispatch 异常: {e}")
if not results:
    print("  ✗ 无 handler 命中")

print("\n── 结论 ──")
print("命中 p1 → 事件是 1.0 schema，longpoll.py 第294行应改成 register_p1_customized_event")
print("命中 p2 → 事件是 2.0 schema，当前注册方式正确，问题在别处（订阅/权限）")
print("两个都没命中 → SDK 版本不支持此事件，需要升级或换方式接收")
