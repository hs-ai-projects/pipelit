#!/usr/bin/env python3
"""
Feishu Task API helper — stdlib only, zero external dependencies.

Requires: Python 3.10+

Usage:
  python3 feishu_api.py check_config
  python3 feishu_api.py save_config <app_id> <app_secret>
  python3 feishu_api.py check_project_config
  python3 feishu_api.py save_project_config <frontend_path|null> <backend_path|null>
  python3 feishu_api.py get_task <task_id>
  python3 feishu_api.py list_tasks [--completed] [--page_size N]
  python3 feishu_api.py get_subtasks <task_id>
  python3 feishu_api.py complete_task <task_id>
  python3 feishu_api.py add_comment <task_id> <comment>

Output: JSON to stdout. Errors to stderr (JSON format), exit code 1.
"""

import sys
import os
import json
import time
import re
import stat
import urllib.request
import urllib.error
import pathlib

FEISHU_BASE = "https://open.feishu.cn"
PLUGIN_ROOT = pathlib.Path(
    os.environ.get("CLAUDE_PLUGIN_ROOT", pathlib.Path(__file__).parent.parent)
)
USER_CONFIG_DIR = pathlib.Path.home() / ".claude" / "plugins" / "cache" / "pipelit"
CONFIG_FILE = USER_CONFIG_DIR / "config.json"
TOKEN_CACHE_FILE = USER_CONFIG_DIR / ".token_cache.json"

UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I
)

HTTP_TIMEOUT = 15  # seconds


# ── Helpers ───────────────────────────────────────────────────────────────────

def format_ms_timestamp(ts, fmt="%Y-%m-%d %H:%M") -> str | None:
    """统一处理飞书毫秒/秒时间戳，兼容两种格式。"""
    if not ts:
        return None
    value = int(ts)
    if value > 10_000_000_000:  # 毫秒
        value = value // 1000
    return time.strftime(fmt, time.localtime(value))


def _secure_write(path: pathlib.Path, content: str) -> None:
    """写入文件并设置 0o600 权限（Windows 下忽略权限设置）。"""
    path.write_text(content)
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0o600
    except (AttributeError, NotImplementedError, OSError):
        pass  # Windows 不支持，忽略


# ── HTTP ──────────────────────────────────────────────────────────────────────

def http(method: str, path: str, token: str = None, body: dict = None) -> dict:
    url = FEISHU_BASE + path
    data = json.dumps(body).encode() if body else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return json.loads(raw)
        except Exception:
            return {"code": e.code, "msg": raw.decode(errors="replace")}
    except urllib.error.URLError as e:
        raise RuntimeError(f"网络请求失败：{e.reason}") from e


# ── Config ────────────────────────────────────────────────────────────────────

def read_config() -> dict | None:
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text())
    return None


def save_config(app_id: str, app_secret: str) -> dict:
    USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    cfg = read_config() or {}
    cfg["app_id"] = app_id
    cfg["app_secret"] = app_secret
    _secure_write(CONFIG_FILE, json.dumps(cfg, indent=2))
    TOKEN_CACHE_FILE.unlink(missing_ok=True)
    return {"success": True, "message": f"凭据已保存到 {CONFIG_FILE}"}


def check_config() -> dict:
    cfg = read_config()
    if not cfg or not cfg.get("app_id") or not cfg.get("app_secret"):
        return {
            "configured": False,
            "message": (
                "飞书凭据未配置。请按以下步骤操作：\n\n"
                "1. 前往 https://open.feishu.cn/ → 开发者后台 → 创建自建应用\n"
                "2. 申请权限：task:task:read / task:task:writeonly / task:comment:write / task:attachment:read\n"
                "3. 发布应用版本（需企业管理员审批）\n"
                "4. 获取 App ID 和 App Secret\n\n"
                "获取后运行：python3 feishu_api.py save_config <app_id> <app_secret>"
            ),
        }
    return {"configured": True, "app_id": cfg["app_id"]}


def check_project_config() -> dict:
    cfg = read_config() or {}
    frontend = cfg.get("frontend_path")
    backend = cfg.get("backend_path")
    return {
        "configured": bool(frontend or backend),
        "frontend_path": frontend,
        "backend_path": backend,
    }


def save_project_config(frontend_path: str = None, backend_path: str = None) -> dict:
    USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    cfg = read_config() or {}
    if frontend_path:
        cfg["frontend_path"] = frontend_path.rstrip("/\\")
    if backend_path:
        cfg["backend_path"] = backend_path.rstrip("/\\")
    _secure_write(CONFIG_FILE, json.dumps(cfg, indent=2, ensure_ascii=False))
    return {
        "success": True,
        "frontend_path": cfg.get("frontend_path"),
        "backend_path": cfg.get("backend_path"),
    }


# ── Token ─────────────────────────────────────────────────────────────────────

def get_token() -> str:
    if TOKEN_CACHE_FILE.exists():
        cache = json.loads(TOKEN_CACHE_FILE.read_text())
        if time.time() < cache.get("expires_at", 0):
            return cache["token"]

    cfg = read_config()
    if not cfg:
        raise RuntimeError("凭据未配置，请先运行 check_config")

    result = http("POST", "/open-apis/auth/v3/tenant_access_token/internal", body={
        "app_id": cfg["app_id"],
        "app_secret": cfg["app_secret"],
    })
    if result.get("code") != 0:
        raise RuntimeError(f"获取 token 失败（code={result.get('code')}）：{result.get('msg')}")

    token = result["tenant_access_token"]
    expires_at = time.time() + result.get("expire", 7200) - 60

    USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    _secure_write(TOKEN_CACHE_FILE, json.dumps({"token": token, "expires_at": expires_at}))
    return token


# ── Helpers ───────────────────────────────────────────────────────────────────

def parse_task_id(raw: str) -> str:
    m = UUID_RE.search(raw)
    return m.group(0) if m else raw.strip()


def get_task_comments(tid: str, token: str) -> list:
    result = http(
        "GET",
        f"/open-apis/task/v2/comments?resource_type=task&resource_id={tid}&page_size=100",
        token=token,
    )
    if result.get("code") != 0:
        return []
    return [
        {
            "id": c["id"],
            "content": c.get("content", ""),
            "created_at": format_ms_timestamp(c.get("created_at")),
        }
        for c in result.get("data", {}).get("items", [])
    ]


# ── API ───────────────────────────────────────────────────────────────────────

def get_task(task_id: str) -> dict:
    tid = parse_task_id(task_id)
    token = get_token()
    result = http("GET", f"/open-apis/task/v2/tasks/{tid}?user_id_type=user_id", token=token)
    if result.get("code") != 0:
        raise RuntimeError(f"获取任务失败（code={result.get('code')}）：{result.get('msg')}")
    t = result["data"]["task"]
    return {
        "id": t["guid"],
        "summary": t["summary"],
        "description": t.get("description", ""),
        "status": t.get("status", "todo"),
        "due": format_ms_timestamp(t.get("due", {}).get("timestamp"), "%Y-%m-%d %H:%M"),
        "members": [{"id": m["id"], "role": m.get("role")} for m in t.get("members", [])],
        "comments": get_task_comments(tid, token),
    }


def list_tasks(completed: bool = False, page_size: int = 20) -> dict:
    token = get_token()
    params = f"page_size={min(page_size, 100)}&completed={str(completed).lower()}&user_id_type=user_id"
    result = http("GET", f"/open-apis/task/v2/tasks?{params}", token=token)
    if result.get("code") != 0:
        raise RuntimeError(f"列出任务失败（code={result.get('code')}）：{result.get('msg')}")
    return {
        "tasks": [
            {
                "id": t["guid"],
                "summary": t["summary"],
                "status": t.get("status", "todo"),
                "due": format_ms_timestamp(t.get("due", {}).get("timestamp"), "%Y-%m-%d"),
            }
            for t in result["data"].get("items", [])
        ],
        "has_more": result["data"].get("has_more", False),
    }


def get_subtasks(task_id: str) -> dict:
    tid = parse_task_id(task_id)
    token = get_token()
    result = http(
        "GET",
        f"/open-apis/task/v2/tasks/{tid}/subtasks?user_id_type=user_id&page_size=50",
        token=token,
    )
    if result.get("code") != 0:
        raise RuntimeError(f"获取子任务失败（code={result.get('code')}）：{result.get('msg')}")
    items = result.get("data", {}).get("items", [])
    return {
        "has_subtasks": len(items) > 0,
        "subtasks": [
            {
                "id": t["guid"],
                "summary": t["summary"],
                "status": t.get("status", "todo"),
                "link": f"https://applink.feishu.cn/client/todo/detail?guid={t['guid']}",
            }
            for t in items
        ],
    }


def complete_task(task_id: str) -> dict:
    tid = parse_task_id(task_id)
    token = get_token()
    result = http(
        "PATCH",
        f"/open-apis/task/v2/tasks/{tid}?user_id_type=user_id",
        token=token,
        body={"task": {"completed_at": str(int(time.time() * 1000))}, "update_fields": ["completed_at"]},
    )
    if result.get("code") != 0:
        raise RuntimeError(f"完成任务失败（code={result.get('code')}）：{result.get('msg')}")
    return {"success": True, "message": f"任务 {tid} 已标记为完成"}


def add_comment(task_id: str, comment: str) -> dict:
    tid = parse_task_id(task_id)
    token = get_token()
    result = http(
        "POST",
        "/open-apis/task/v2/comments",
        token=token,
        body={"resource_type": "task", "resource_id": tid, "content": comment},
    )
    if result.get("code") != 0:
        raise RuntimeError(f"添加评论失败（code={result.get('code')}）：{result.get('msg')}")
    return {"success": True, "comment_id": result["data"]["comment"]["id"]}


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(0)

    cmd = args[0]
    try:
        if cmd == "check_config":
            out = check_config()
        elif cmd == "save_config":
            out = save_config(args[1], args[2])
        elif cmd == "check_project_config":
            out = check_project_config()
        elif cmd == "save_project_config":
            frontend = args[1] if len(args) > 1 and args[1] != "null" else None
            backend = args[2] if len(args) > 2 and args[2] != "null" else None
            out = save_project_config(frontend, backend)
        elif cmd == "get_task":
            out = get_task(args[1])
        elif cmd == "list_tasks":
            completed = "--completed" in args
            page_size = int(args[args.index("--page_size") + 1]) if "--page_size" in args else 20
            out = list_tasks(completed, page_size)
        elif cmd == "get_subtasks":
            out = get_subtasks(args[1])
        elif cmd == "complete_task":
            out = complete_task(args[1])
        elif cmd == "add_comment":
            out = add_comment(args[1], " ".join(args[2:]))
        else:
            raise RuntimeError(f"未知命令：{cmd}")

        print(json.dumps(out, ensure_ascii=False, indent=2))
    except Exception as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
