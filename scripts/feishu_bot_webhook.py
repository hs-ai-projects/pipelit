#!/usr/bin/env python3
"""
飞书 Webhook HTTP 服务器 — 纯粹的 HTTP 层，不含业务逻辑。

职责：
  - 监听飞书事件订阅回调（POST /feishu/event）
  - 监听卡片按钮回调（POST /feishu/card-action）
  - 验证签名，立即响应 200，异步交给 analyzer 处理
  - 提供健康检查（GET /health）

业务逻辑全部在 feishu_bot_analyzer.py，本文件不需要改动。

用法：
  python3 feishu_bot_webhook.py serve [--port PORT]   启动服务器
  python3 feishu_bot_webhook.py setup                  配置向导
  python3 feishu_bot_webhook.py test <task_id>         手动触发测试
"""

import sys
import os
import json
import time
import hashlib
import hmac
import threading
import pathlib
from http.server import HTTPServer, BaseHTTPRequestHandler

# ── 路径 ───────────────────────────────────────────────────────────────────────

PLUGIN_ROOT = pathlib.Path(
    os.environ.get("CLAUDE_PLUGIN_ROOT", pathlib.Path(__file__).parent.parent)
)
CACHE_DIR   = PLUGIN_ROOT / ".cache"
CONFIG_FILE = CACHE_DIR / "config.json"
LOG_DIR     = CACHE_DIR / "webhook_logs"


# ── 日志 ───────────────────────────────────────────────────────────────────────

def log(msg: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts   = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [webhook] {msg}\n"
    with open(LOG_DIR / "webhook.log", "a", encoding="utf-8") as f:
        f.write(line)
    sys.stdout.write(line)
    sys.stdout.flush()


# ── 配置 ───────────────────────────────────────────────────────────────────────

def read_config() -> dict:
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    return {}


def get_bot_cfg() -> dict:
    return read_config().get("bot", {})


# ── 事件解析 ───────────────────────────────────────────────────────────────────

def parse_task_event(body: dict) -> tuple[str, str] | tuple[None, None]:
    """
    从飞书事件 body 中提取 (event_type, task_id)。
    兼容飞书事件订阅 v2.0 格式。
    返回 (None, None) 表示不是需要处理的事件。
    """
    header     = body.get("header", {})
    event_type = header.get("event_type", "")
    event      = body.get("event", {})

    task_id = None

    if "task_created" in event_type:
        task   = event.get("task", {})
        task_id = task.get("guid") or event.get("task_id")

    elif "task_updated" in event_type:
        task_id = event.get("task_id") or event.get("task", {}).get("guid")
        # 只处理成员变更（指派）事件
        update_fields = event.get("update_fields", [])
        if "members" not in update_fields:
            return None, None

    if not task_id:
        return None, None

    return event_type, task_id


def is_assigned_to_me(body: dict, my_user_id: str) -> bool:
    """
    判断任务是否新指派给我（task_updated 的成员变更事件专用）。
    task_created 时不调用此函数（直接触发）。
    """
    if not my_user_id:
        return True   # 未配置 user_id 则不过滤，所有任务都触发

    event   = body.get("event", {})
    old_ids = {m.get("id") or m.get("user_id", "")
               for m in event.get("old_value", {}).get("members", [])}
    new_ids = {m.get("id") or m.get("user_id", "")
               for m in event.get("new_value", {}).get("members", [])}
    return my_user_id in (new_ids - old_ids)   # 新增成员中包含我


# ── HTTP Handler ───────────────────────────────────────────────────────────────

class WebhookHandler(BaseHTTPRequestHandler):

    # ── GET /health ────────────────────────────────────────────────────────────
    def do_GET(self) -> None:
        if self.path == "/health":
            cfg = get_bot_cfg()
            self._json(200, {
                "status":        "ok",
                "ts":            int(time.time()),
                "trigger_mode":  cfg.get("trigger_mode", "notify"),
                "plugin_root":   str(PLUGIN_ROOT),
            })
        else:
            self._json(404, {"error": "not found"})

    # ── POST ───────────────────────────────────────────────────────────────────
    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        raw    = self.rfile.read(length)

        if self.path == "/feishu/event":
            self._handle_event(raw)
        elif self.path == "/feishu/card-action":
            self._handle_card_action(raw)
        else:
            self._json(404, {"error": "not found"})

    # ── /feishu/event ──────────────────────────────────────────────────────────
    def _handle_event(self, raw: bytes) -> None:
        try:
            body = json.loads(raw)
        except Exception:
            self._json(400, {"error": "invalid json"})
            return

        # 飞书 URL 验证（3-handshake）
        if body.get("type") == "url_verification":
            log("[handshake] url_verification OK")
            self._json(200, {"challenge": body.get("challenge", "")})
            return

        # 签名验证（配置了 encrypt_key 才校验）
        if not self._verify_signature(raw):
            log("[auth] signature mismatch, rejected")
            self._json(401, {"error": "invalid signature"})
            return

        # 立即响应 200，飞书要求 3s 内响应
        self._json(200, {"msg": "ok"})

        # 异步处理，不阻塞 HTTP 线程
        threading.Thread(
            target=self._process_event, args=(body,), daemon=True
        ).start()

    def _process_event(self, body: dict) -> None:
        """解析事件，判断是否需要触发，然后调用 analyzer.pipeline。"""
        try:
            event_type, task_id = parse_task_event(body)
            if not task_id:
                log(f"[event] skip (not a task event or no task_id)")
                return

            log(f"[event] type={event_type} task={task_id}")

            cfg           = get_bot_cfg()
            trigger_events = cfg.get("trigger_events", ["task_assigned", "task_created"])
            my_user_id    = cfg.get("user_id") or read_config().get("user_id", "")

            # task_created：检查 trigger_events 配置
            if "task_created" in event_type:
                if "task_created" not in trigger_events:
                    log("[event] task_created not in trigger_events, skip")
                    return

            # task_updated（成员变更）：确认是指派给我
            elif "task_updated" in event_type:
                if "task_assigned" not in trigger_events:
                    log("[event] task_assigned not in trigger_events, skip")
                    return
                if not is_assigned_to_me(body, my_user_id):
                    log("[event] not assigned to me, skip")
                    return

            # 调用 analyzer 完整流程
            import feishu_bot_analyzer as analyzer
            analyzer.pipeline(task_id)

        except Exception as e:
            log(f"[event] process error: {e}")

    # ── /feishu/card-action ────────────────────────────────────────────────────
    def _handle_card_action(self, raw: bytes) -> None:
        """
        处理卡片按钮点击。
        飞书要求 5s 内响应，所以立即返回 200，异步执行。
        """
        try:
            body = json.loads(raw)
        except Exception:
            self._json(400, {"error": "invalid json"})
            return

        self._json(200, {"msg": "ok"})

        action_val  = body.get("action", {}).get("value", {})
        action_type = action_val.get("action", "")
        task_id     = action_val.get("task_id", "")

        log(f"[card-action] action={action_type} task={task_id}")

        if action_type == "confirm_dev" and task_id:
            threading.Thread(
                target=self._run_execute_from_pending,
                args=(task_id,), daemon=True
            ).start()
        else:
            log(f"[card-action] unknown action or missing task_id, skip")

    def _run_execute_from_pending(self, task_id: str) -> None:
        try:
            import feishu_bot_analyzer as analyzer
            analyzer.execute_from_pending(task_id)
        except Exception as e:
            log(f"[card-action] execute error: {e}")

    # ── 签名验证 ───────────────────────────────────────────────────────────────
    def _verify_signature(self, raw: bytes) -> bool:
        """
        验证飞书请求签名（可选，未配置 encrypt_key 则跳过）。
        算法：SHA256(timestamp + nonce + encrypt_key + body)
        """
        cfg         = get_bot_cfg()
        encrypt_key = cfg.get("encrypt_key", "")
        if not encrypt_key:
            return True   # 开发/测试环境可不配置

        ts    = self.headers.get("X-Lark-Request-Timestamp", "")
        nonce = self.headers.get("X-Lark-Request-Nonce", "")
        sig   = self.headers.get("X-Lark-Signature", "")

        content  = ts + nonce + encrypt_key + raw.decode("utf-8")
        expected = hashlib.sha256(content.encode("utf-8")).hexdigest()
        return hmac.compare_digest(sig, expected)

    # ── 响应工具 ───────────────────────────────────────────────────────────────
    def _json(self, code: int, data: dict) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:
        pass   # 关闭默认 access log，统一用 log()


# ── 启动 & 配置向导 ────────────────────────────────────────────────────────────

def cmd_serve(port: int = None) -> None:
    cfg  = get_bot_cfg()
    port = port or cfg.get("port", 8765)

    # 启动前检查必要配置
    warnings = []
    if not cfg.get("notify_chat_id"):
        warnings.append("notify_chat_id 未配置，卡片通知无法发送")
    if not cfg.get("project_path"):
        warnings.append("project_path 未配置，自动执行将失败")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        warnings.append("ANTHROPIC_API_KEY 未设置，claude --print 将报错")
    for w in warnings:
        log(f"[warn] {w}")

    server = HTTPServer(("0.0.0.0", port), WebhookHandler)
    info   = {
        "status":        "running",
        "port":          port,
        "trigger_mode":  cfg.get("trigger_mode", "notify"),
        "trigger_events": cfg.get("trigger_events", []),
        "routes": {
            "event":       f"POST http://0.0.0.0:{port}/feishu/event",
            "card_action": f"POST http://0.0.0.0:{port}/feishu/card-action",
            "health":      f"GET  http://0.0.0.0:{port}/health",
        },
        "warnings": warnings,
    }
    log(f"[start] {json.dumps(info, ensure_ascii=False)}")
    print(json.dumps(info, ensure_ascii=False, indent=2))

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log("[stop] keyboard interrupt")


def cmd_setup() -> None:
    """交互式配置向导，写入 .cache/config.json 的 bot 字段。"""
    print("=== 飞书 Bot Webhook 配置向导 ===\n")

    port          = input("监听端口 [8765]: ").strip() or "8765"
    encrypt_key   = input("Encrypt Key（飞书后台获取，可留空跳过签名验证）: ").strip()
    notify_chat   = input("通知群 chat_id（oc_xxx）: ").strip()
    user_id       = input("你的飞书 user_id（ou_xxx，运行 feishu_api.py save_user 获取）: ").strip()
    project_path  = input("项目根目录（claude 在此运行）: ").strip()
    gitlab_token  = input("GitLab Personal Access Token（glpat-xxx）: ").strip()
    trigger_mode  = input("触发模式 notify/spawn [spawn]: ").strip() or "spawn"

    cfg = {}
    if CONFIG_FILE.exists():
        cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))

    cfg["bot"] = {
        "port":           int(port),
        "encrypt_key":    encrypt_key,
        "notify_chat_id": notify_chat,
        "user_id":        user_id,
        "project_path":   project_path,
        "gitlab_token":   gitlab_token,
        "trigger_mode":   trigger_mode,
        "trigger_events": ["task_assigned", "task_created"],
    }

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(
        json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\n✅ 已保存到 {CONFIG_FILE}")
    print(f"\n下一步：")
    print(f"  1. export ANTHROPIC_API_KEY=sk-ant-xxx")
    print(f"  2. python3 feishu_bot_webhook.py serve")
    print(f"  3. 飞书后台填写事件订阅 URL：http://your-server:{port}/feishu/event")
    print(f"  4. 订阅事件：task.v2.task_created_v1 / task.v2.task_updated_v1")


def cmd_test(task_id: str) -> None:
    """手动触发 pipeline，绕过 HTTP 层直接测试。"""
    log(f"[test] trigger pipeline task_id={task_id}")
    import feishu_bot_analyzer as analyzer
    analyzer.pipeline(task_id)
    print(f"[test] done. 查看日志：{LOG_DIR / 'webhook.log'}")


# ── 入口 ───────────────────────────────────────────────────────────────────────

def main() -> None:
    args = sys.argv[1:]

    if not args or args[0] == "serve":
        port = None
        if len(args) > 1:
            try:
                port = int(args[-1])
            except ValueError:
                pass
        cmd_serve(port)

    elif args[0] == "setup":
        cmd_setup()

    elif args[0] == "test" and len(args) > 1:
        cmd_test(args[1])

    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
