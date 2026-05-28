#!/usr/bin/env python3
"""
飞书 Bot 长连接客户端 — 用飞书 SDK 主动建立 WebSocket，不需要公网入口。

适用场景：
  - bot 部署在内网，没有公网 URL 接收 webhook 事件
  - 服务器能访问公网（出方向），由 SDK 主动连接飞书的 WS 服务

业务逻辑全部复用 feishu_bot_webhook.py 里的函数，本文件只替换"接收层"。

用法：
  python3 feishu_bot_longpoll.py serve

依赖：lark-oapi（PyPI）
  uv pip install --python 3.11 lark-oapi
  # 国内镜像：
  uv pip install --python 3.11 lark-oapi -i https://pypi.tuna.tsinghua.edu.cn/simple

飞书后台必做：
  1. 应用 → 事件与回调 → 「长连接」模式（如果飞书后台有该开关）
  2. 订阅事件：task.v2.task_created_v1, task.v2.task_updated_v1
  3. 不需要再填事件订阅 URL 和卡片回调 URL
"""

import sys
import os
import json
import time
import threading
import pathlib

# 把脚本目录加进 sys.path，确保能 import 同目录的 feishu_bot_webhook
SCRIPT_DIR = pathlib.Path(__file__).parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

# 配置读取：用 feishu_api 的路径（~/.claude/pipelit/config.json），跟 save_config / save_user 对齐
# 业务过滤：复用 feishu_bot_webhook 的事件判断逻辑
from feishu_api import read_config, USER_CONFIG_DIR
from feishu_bot_webhook import is_assigned_to_me


def get_bot_cfg() -> dict:
    cfg = read_config()
    return cfg.get("bot", {}) if cfg else {}


LOG_DIR = USER_CONFIG_DIR / "webhook_logs"


def log(msg: str) -> None:
    """长连接专属日志，带 [longpoll] tag 跟 webhook 区分。"""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts   = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [longpoll] {msg}\n"
    with open(LOG_DIR / "webhook.log", "a", encoding="utf-8") as f:
        f.write(line)
    sys.stdout.write(line)
    sys.stdout.flush()


# ── SDK 加载（懒加载，缺依赖时给清晰提示）─────────────────────────────────────

try:
    import lark_oapi as lark
    from lark_oapi.event.callback.model.p2_card_action_trigger import (
        P2CardActionTriggerResponse,
    )
except ImportError as e:
    print(f"缺少依赖 lark-oapi（{e}）。请先安装：", file=sys.stderr)
    print("  uv pip install --python 3.11 lark-oapi", file=sys.stderr)
    print("国内镜像：", file=sys.stderr)
    print("  uv pip install --python 3.11 lark-oapi -i https://pypi.tuna.tsinghua.edu.cn/simple", file=sys.stderr)
    sys.exit(1)


# ── 业务处理（复用 webhook._process_event 的过滤逻辑）─────────────────────────

def _process_task_event(event_type: str, body: dict) -> None:
    """
    判断事件是否需要触发，然后调用 analyzer.pipeline。
    逻辑等同 feishu_bot_webhook._process_event。
    """
    try:
        event   = body.get("event", {})
        task_id = (
            event.get("task", {}).get("guid")
            or event.get("task_id")
        )
        if not task_id:
            log(f"[event] no task_id, skip ({event_type})")
            return

        log(f"[event] type={event_type} task={task_id}")

        cfg            = get_bot_cfg()
        trigger_events = cfg.get("trigger_events", ["task_assigned", "task_created"])
        my_user_id     = cfg.get("user_id") or (read_config() or {}).get("user_id", "")

        if "task_created" in event_type:
            if "task_created" not in trigger_events:
                log("[event] task_created not in trigger_events, skip")
                return

        elif "task_updated" in event_type:
            if "task_assigned" not in trigger_events:
                log("[event] task_assigned not in trigger_events, skip")
                return
            if not is_assigned_to_me(body, my_user_id):
                log("[event] not assigned to me, skip")
                return

        import feishu_bot_analyzer as analyzer
        analyzer.pipeline(task_id)

    except Exception as e:
        log(f"[event] process error: {e}")


def _to_dict(data) -> dict:
    """SDK 强类型对象 → dict，方便复用现有基于 dict 的解析逻辑。"""
    return json.loads(lark.JSON.marshal(data))


# ── SDK 回调 ────────────────────────────────────────────────────────────────

def on_task_updated(data) -> None:
    """task.v2.task_updated_v1 回调（应用维度，只追踪 bot 自己创建的任务）。"""
    body = _to_dict(data)
    threading.Thread(
        target=_process_task_event,
        args=("task_updated", body),
        daemon=True,
    ).start()


def on_task_user_access_updated(data) -> None:
    """task.task.update_user_access_v2 回调（用户维度，覆盖客户端创建的任务）。

    这才是"指派给我的任务"场景需要的事件。SDK 1.6.x 没有内置 handler，
    走 register_p1_customized_event 自定义订阅接收。
    """
    body = _to_dict(data)
    threading.Thread(
        target=_process_task_event,
        args=("task_updated", body),   # 复用 task_updated 分支的过滤逻辑
        daemon=True,
    ).start()


def on_task_created(data) -> None:
    """task.task.created_v1 回调（自定义订阅兜底）。"""
    body = _to_dict(data)
    threading.Thread(
        target=_process_task_event,
        args=("task_created", body),
        daemon=True,
    ).start()


def on_card_action(data) -> "P2CardActionTriggerResponse":
    """卡片按钮点击回调。立即返回 toast，重活异步交给 analyzer。"""
    try:
        body        = _to_dict(data)
        action_val  = body.get("action", {}).get("value", {})
        action_type = action_val.get("action", "")
        task_id     = action_val.get("task_id", "")

        log(f"[card-action] action={action_type} task={task_id}")

        if action_type == "confirm_dev" and task_id:
            import feishu_bot_analyzer as analyzer
            threading.Thread(
                target=analyzer.execute_from_pending,
                args=(task_id,),
                daemon=True,
            ).start()
        else:
            log("[card-action] unknown action or missing task_id, skip")

    except Exception as e:
        log(f"[card-action] error: {e}")

    # 必须返回响应对象，否则飞书前端按钮卡住
    return P2CardActionTriggerResponse({
        "toast": {"type": "info", "content": "已收到，处理中"}
    })


# ── 启动 ────────────────────────────────────────────────────────────────────

def cmd_serve() -> None:
    cfg        = read_config() or {}
    app_id     = cfg.get("app_id", "")
    app_secret = cfg.get("app_secret", "")
    bot_cfg    = cfg.get("bot", {})

    if not app_id or not app_secret:
        log("[error] app_id 或 app_secret 未配置。先跑：")
        log("  python3 ~/pipelit/scripts/feishu_api.py save_config <App_ID> <App_Secret>")
        sys.exit(1)

    # 启动前检查
    warnings = []
    if not bot_cfg.get("notify_chat_id"):
        warnings.append("notify_chat_id 未配置，卡片通知无法发送")
    if not bot_cfg.get("project_path"):
        warnings.append("project_path 未配置，自动执行将失败")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        warnings.append("ANTHROPIC_API_KEY 未设置，claude --print 将报错")
    for w in warnings:
        log(f"[warn] {w}")

    # 注册事件分发器（长连接模式两个参数都传空字符串）
    # 用户维度事件（task.task.update_user_access_v2）SDK 1.6.x 没内置 handler，
    # 走 register_p1_customized_event 自定义订阅。
    handler = (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_task_task_updated_v1(on_task_updated)
        .register_p1_customized_event("task.task.update_user_access_v2", on_task_user_access_updated)
        .register_p1_customized_event("task.task.created_v1", on_task_created)
        .register_p2_card_action_trigger(on_card_action)
        .build()
    )

    info = {
        "status":         "starting",
        "mode":           "longpoll",
        "trigger_mode":   bot_cfg.get("trigger_mode", "spawn"),
        "trigger_events": bot_cfg.get("trigger_events", []),
        "warnings":       warnings,
    }
    log(f"[start] {json.dumps(info, ensure_ascii=False)}")
    print(json.dumps(info, ensure_ascii=False, indent=2))

    client = lark.ws.Client(
        app_id,
        app_secret,
        event_handler=handler,
        log_level=lark.LogLevel.INFO,
    )

    try:
        # 阻塞调用，SDK 内置自动重连与心跳
        client.start()
    except KeyboardInterrupt:
        log("[stop] keyboard interrupt")


# ── CLI ─────────────────────────────────────────────────────────────────────

def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] != "serve":
        print("Usage: feishu_bot_longpoll.py serve")
        sys.exit(1)
    cmd_serve()


if __name__ == "__main__":
    main()
