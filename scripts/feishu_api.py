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
  python3 feishu_api.py get_task_full <task_id>    # 一次拿到：任务+子任务+附件图片+项目配置
  python3 feishu_api.py list_tasks [--completed] [--page_size N] [--status fixing]
  python3 feishu_api.py get_subtasks <task_id>
  python3 feishu_api.py complete_task <task_id>
  python3 feishu_api.py add_comment <task_id> <comment>
  python3 feishu_api.py get_release_config
  python3 feishu_api.py save_release_config '<json_string>'

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

# ── 路径常量 ──────────────────────────────────────────────────────────────────
# 用户数据：跨项目/跨工作目录共享，固定在用户主目录
USER_CONFIG_DIR = pathlib.Path.home() / ".claude" / "pipelit"
CONFIG_FILE = USER_CONFIG_DIR / "config.json"
TOKEN_CACHE_FILE = USER_CONFIG_DIR / ".token_cache.json"
USER_TOKEN_CACHE = USER_CONFIG_DIR / ".user_token_cache.json"

# 静态资源：跟着脚本走，相对 __file__ 引用
TEMPLATE_DIR = pathlib.Path(__file__).parent / "templates"


def _migrate_legacy_cache() -> None:
    """一次性迁移：从旧的 <plugin_root>/.cache/ 迁移到 ~/.claude/pipelit/。
    幂等：新位置已有 config.json 则跳过。
    """
    if CONFIG_FILE.exists():
        return

    candidates = []
    env_root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if env_root:
        candidates.append(pathlib.Path(env_root) / ".cache")
    candidates.append(pathlib.Path(__file__).parent.parent / ".cache")

    for legacy_dir in candidates:
        legacy_config = legacy_dir / "config.json"
        if not legacy_config.exists():
            continue
        USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        for fname in ("config.json", ".token_cache.json", ".user_token_cache.json"):
            src = legacy_dir / fname
            dst = USER_CONFIG_DIR / fname
            if src.exists() and not dst.exists():
                dst.write_bytes(src.read_bytes())
        # 迁移 images 子目录（若存在）
        legacy_images = legacy_dir / "images"
        new_images = USER_CONFIG_DIR / "images"
        if legacy_images.is_dir() and not new_images.exists():
            new_images.mkdir(parents=True, exist_ok=True)
            for img in legacy_images.iterdir():
                if img.is_file():
                    (new_images / img.name).write_bytes(img.read_bytes())
        return


_migrate_legacy_cache()

UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I
)

HTTP_TIMEOUT = 15  # seconds

# ── 飞书自定义字段：状态 ────────────────────────────────────────
# 通过观察任务原始数据写死，避免依赖 task:custom_field:read 权限
STATUS_FIELD_GUID = "aedeac33-4950-4c69-889c-f1258cad9c8e"
STATUS_OPTIONS = {
    "fixing": "44f5860c-a587-4ed8-b7e1-12d445bd39df",  # 修复中
}


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


def http_download(url: str, token: str) -> bytes:
    """通过完整 URL 下载二进制内容（用于附件下载）。"""
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"下载失败 HTTP {e.code}: {e.read().decode(errors='replace')}")
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


AUTH_REDIRECT_URI = "http://127.0.0.1:9876/callback"


def _get_app_token() -> str:
    """获取 app_access_token（用于 OAuth 码换 token）。"""
    cfg = read_config()
    result = http("POST", "/open-apis/auth/v3/app_access_token/internal", body={
        "app_id": cfg["app_id"],
        "app_secret": cfg["app_secret"],
    })
    if result.get("code") != 0:
        raise RuntimeError(f"获取 app_token 失败：{result.get('msg')}")
    return result["app_access_token"]


def _save_user_token(data: dict) -> None:
    USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    _secure_write(USER_TOKEN_CACHE, json.dumps({
        "access_token": data["access_token"],
        "refresh_token": data.get("refresh_token", ""),
        "expires_at": time.time() + data.get("expires_in", 7200) - 60,
    }))


def get_user_token() -> str:
    """获取 user_access_token，优先用缓存，过期则刷新。"""
    if USER_TOKEN_CACHE.exists():
        cache = json.loads(USER_TOKEN_CACHE.read_text())
        if time.time() < cache.get("expires_at", 0):
            return cache["access_token"]
        # 尝试 refresh
        if cache.get("refresh_token"):
            app_token = _get_app_token()
            result = http("POST", "/open-apis/authen/v1/oidc/refresh_access_token",
                          token=app_token,
                          body={"grant_type": "refresh_token",
                                "refresh_token": cache["refresh_token"]})
            if result.get("code") == 0:
                _save_user_token(result["data"])
                return result["data"]["access_token"]
    raise RuntimeError(
        "用户未授权或 token 已过期。请运行：python3 feishu_api.py auth"
    )


def auth() -> dict:
    """交互式 OAuth 授权：打开浏览器 → 用户授权 → 回调拿 code → 换 token。"""
    import webbrowser
    from http.server import HTTPServer, BaseHTTPRequestHandler
    import urllib.parse

    cfg = read_config()
    if not cfg:
        raise RuntimeError("请先配置 app_id/app_secret")

    state = os.urandom(8).hex()
    scope = "task:task:read task:task:write task:comment:write task:attachment:read"
    auth_url = (
        f"{FEISHU_BASE}/open-apis/authen/v1/authorize"
        f"?app_id={cfg['app_id']}"
        f"&redirect_uri={urllib.parse.quote(AUTH_REDIRECT_URI)}"
        f"&scope={urllib.parse.quote(scope)}"
        f"&state={state}"
    )

    code_holder = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if "code" in params:
                code_holder["code"] = params["code"][0]
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write("<h2>授权成功！可以关闭此页面。</h2>".encode())
            else:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"missing code")

        def log_message(self, *a):
            pass

    server = HTTPServer(("127.0.0.1", 9876), Handler)
    server.timeout = 120

    print("正在打开浏览器，请在飞书页面点击授权...", file=sys.stderr)
    webbrowser.open(auth_url)
    server.handle_request()
    server.server_close()

    if "code" not in code_holder:
        raise RuntimeError("超时未收到授权码，请重试")

    app_token = _get_app_token()
    result = http("POST", "/open-apis/authen/v1/oidc/access_token",
                  token=app_token,
                  body={"grant_type": "authorization_code",
                        "code": code_holder["code"]})
    if result.get("code") != 0:
        raise RuntimeError(f"换取 token 失败（code={result.get('code')}）：{result.get('msg')}")

    _save_user_token(result["data"])
    return {"success": True, "message": "用户授权成功，token 已缓存"}


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


def fetch_task_images(tid: str, token: str) -> list:
    """拉取任务附件（图片），下载到本地，返回本地路径列表。"""
    result = http(
        "GET",
        f"/open-apis/task/v2/attachments?resource_type=task&resource_id={tid}&page_size=50",
        token=token,
    )
    if result.get("code") != 0:
        return []
    img_dir = USER_CONFIG_DIR / "images"
    img_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    for att in result.get("data", {}).get("items", []):
        name = att.get("name", "image.png")
        ext = pathlib.Path(name).suffix or ".png"
        att_id = att.get("guid", att.get("id", name))
        out_path = img_dir / f"{tid[:8]}_{att_id}{ext}"
        if not out_path.exists():
            url = att.get("url", "")
            if not url:
                saved.append({"error": "无下载链接", "name": name})
                continue
            try:
                out_path.write_bytes(http_download(url, token))
            except Exception as e:
                saved.append({"error": str(e), "name": name})
                continue
        saved.append({"path": str(out_path), "name": name})
    return saved


# ── API ───────────────────────────────────────────────────────────────────────

def lookup_user(email: str = None, mobile: str = None) -> dict:
    """通过邮箱或手机号查找飞书 user_id。"""
    token = get_token()
    body = {}
    if email:
        body["emails"] = [email]
    if mobile:
        body["mobiles"] = [mobile]
    if not body:
        raise RuntimeError("请提供邮箱(email)或手机号(mobile)")
    result = http(
        "POST",
        "/open-apis/contact/v3/users/batch_get_id?user_id_type=user_id",
        token=token,
        body=body,
    )
    if result.get("code") != 0:
        raise RuntimeError(f"查找用户失败（code={result.get('code')}）：{result.get('msg')}")
    user_list = result.get("data", {}).get("user_list", [])
    if not user_list or not user_list[0].get("user_id"):
        raise RuntimeError("未找到用户，请检查邮箱或手机号是否正确")
    return {"user_id": user_list[0]["user_id"]}


def save_user(email: str = None, mobile: str = None) -> dict:
    """查找并保存当前用户的 user_id 到配置。"""
    user = lookup_user(email=email, mobile=mobile)
    USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    cfg = read_config() or {}
    cfg["user_id"] = user["user_id"]
    _secure_write(CONFIG_FILE, json.dumps(cfg, indent=2, ensure_ascii=False))
    return {"success": True, "user_id": user["user_id"], "message": "用户已保存"}


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


def list_tasks(completed: bool = False, page_size: int = 20, status: str | None = None) -> dict:
    token = get_user_token()  # 用 user_access_token 才能拉到"我的任务"
    params = f"page_size={min(page_size, 100)}&completed={str(completed).lower()}&user_id_type=user_id"
    result = http("GET", f"/open-apis/task/v2/tasks?{params}", token=token)
    if result.get("code") != 0:
        raise RuntimeError(f"列出任务失败（code={result.get('code')}）：{result.get('msg')}")

    items = result["data"].get("items", [])

    # 按自定义字段"状态"过滤（每个任务多一次详情请求）
    if status:
        target_value = STATUS_OPTIONS.get(status)
        if not target_value:
            raise RuntimeError(f"未知状态：{status}，可选值：{list(STATUS_OPTIONS.keys())}")
        filtered = []
        for t in items:
            detail = http("GET", f"/open-apis/task/v2/tasks/{t['guid']}?user_id_type=user_id", token=token)
            cf = detail.get("data", {}).get("task", {}).get("custom_fields", [])
            field = next((c for c in cf if c.get("guid") == STATUS_FIELD_GUID), None)
            if field and field.get("single_select_value") == target_value:
                filtered.append(t)
        items = filtered

    return {
        "tasks": [
            {
                "id": t["guid"],
                "summary": t["summary"],
                "status": t.get("status", "todo"),
                "due": format_ms_timestamp(t.get("due", {}).get("timestamp"), "%Y-%m-%d"),
            }
            for t in items
        ],
        "has_more": result["data"].get("has_more", False) if not status else False,
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


def get_task_full(task_id: str) -> dict:
    """一次调用拿到任务全部上下文：任务详情 + 子任务 + 附件图片 + 项目配置。"""
    tid = parse_task_id(task_id)
    token = get_token()

    # 任务详情
    task_result = http("GET", f"/open-apis/task/v2/tasks/{tid}?user_id_type=user_id", token=token)
    if task_result.get("code") != 0:
        raise RuntimeError(f"获取任务失败（code={task_result.get('code')}）：{task_result.get('msg')}")
    t = task_result["data"]["task"]

    # 评论
    comments = get_task_comments(tid, token)

    # 子任务
    subtask_result = http(
        "GET",
        f"/open-apis/task/v2/tasks/{tid}/subtasks?user_id_type=user_id&page_size=50",
        token=token,
    )
    subtasks = []
    if subtask_result.get("code") == 0:
        for st in subtask_result.get("data", {}).get("items", []):
            subtasks.append({
                "id": st["guid"],
                "summary": st["summary"],
                "status": st.get("status", "todo"),
                "link": f"https://applink.feishu.cn/client/todo/detail?guid={st['guid']}",
            })

    # 附件图片（自动下载）
    images = fetch_task_images(tid, token)
    downloaded_images = [i for i in images if "path" in i]

    # 项目配置
    cfg = read_config() or {}
    project_config = {
        "configured": bool(cfg.get("frontend_path") or cfg.get("backend_path")),
        "frontend_path": cfg.get("frontend_path"),
        "backend_path": cfg.get("backend_path"),
    }

    return {
        "task": {
            "id": t["guid"],
            "summary": t["summary"],
            "description": t.get("description", ""),
            "status": t.get("status", "todo"),
            "due": format_ms_timestamp(t.get("due", {}).get("timestamp"), "%Y-%m-%d %H:%M"),
            "members": [{"id": m["id"], "role": m.get("role")} for m in t.get("members", [])],
            "comments": comments,
        },
        "subtasks": subtasks,
        "has_subtasks": len(subtasks) > 0,
        "images": images,
        "has_images": len(downloaded_images) > 0,
        "project_config": project_config,
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


def upload_image(image_path: str) -> str:
    """上传本地图片到飞书，返回 image_key。需要 im:image 权限。"""
    token = get_token()
    path = pathlib.Path(image_path)
    if not path.exists():
        raise RuntimeError(f"图片文件不存在：{image_path}")

    # 构造 multipart/form-data
    boundary = "----FeishuUploadBoundary"
    mime_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".gif": "image/gif", ".webp": "image/webp"}
    content_type = mime_map.get(path.suffix.lower(), "image/png")

    body_parts = []
    body_parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"image_type\"\r\n\r\nmessage".encode())
    body_parts.append(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{path.name}\"\r\nContent-Type: {content_type}\r\n\r\n".encode()
        + path.read_bytes()
    )
    body_parts.append(f"--{boundary}--\r\n".encode())
    data = b"\r\n".join(body_parts)

    req = urllib.request.Request(
        FEISHU_BASE + "/open-apis/im/v1/images",
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        result = json.loads(e.read())

    if result.get("code") != 0:
        raise RuntimeError(f"图片上传失败（code={result.get('code')}）：{result.get('msg')}")
    return result["data"]["image_key"]


def send_image(chat_id: str, image_path: str) -> dict:
    """上传本地图片并发送到飞书群。"""
    image_key = upload_image(image_path)
    token = get_token()
    result = http(
        "POST",
        "/open-apis/im/v1/messages?receive_id_type=chat_id",
        token=token,
        body={
            "receive_id": chat_id,
            "msg_type": "image",
            "content": json.dumps({"image_key": image_key}, ensure_ascii=False),
        },
    )
    if result.get("code") != 0:
        raise RuntimeError(f"发送图片失败（code={result.get('code')}）：{result.get('msg')}")
    return {"success": True, "message_id": result["data"]["message_id"], "image_key": image_key}


def send_card(receive_id: str, card: dict, receive_id_type: str = "chat_id") -> dict:
    """向飞书群或用户发送卡片消息。
    receive_id_type: chat_id（群）/ user_id / open_id / union_id
    """
    token = get_token()
    result = http(
        "POST",
        f"/open-apis/im/v1/messages?receive_id_type={receive_id_type}",
        token=token,
        body={
            "receive_id": receive_id,
            "msg_type": "interactive",
            "content": json.dumps(card, ensure_ascii=False),
        },
    )
    if result.get("code") != 0:
        raise RuntimeError(f"发送卡片失败（code={result.get('code')}）：{result.get('msg')}")
    msg_id = result.get("data", {}).get("message_id", "")
    return {"success": True, "message_id": msg_id, "receive_id": receive_id}


def build_release_card(params_json: str) -> dict:
    """从版本信息构建飞书发版卡片。

    params_json: JSON 字符串，字段：version, date, content, doc_url(可选)
    返回可直接传给 send_card 的卡片 dict。
    """
    params = json.loads(params_json)
    version = params["version"]
    date = params["date"]
    content = params["content"]
    doc_url = params.get("doc_url", "")

    template_file = TEMPLATE_DIR / "release_card_template.json"
    if not template_file.exists():
        raise RuntimeError(f"卡片模板不存在：{template_file}")
    template = json.loads(template_file.read_text(encoding="utf-8"))

    # 替换 header title
    header_content = template["header"]["title"]["content"]
    header_content = header_content.replace("{{version}}", version).replace("{{date}}", date)
    template["header"]["title"]["content"] = header_content

    # 替换 body content（兼容 column_set 和普通 div 两种结构）
    el = template["body"]["elements"][0]
    if el["tag"] == "column_set":
        text_el = el["columns"][0]["elements"][0]["text"]
    else:
        text_el = el["text"]

    body_text = text_el["content"].replace("{{content}}", content)
    if doc_url:
        body_text = body_text.replace("{{doc_url}}", doc_url)
    else:
        body_text = body_text.replace("\n\n[查看完整文档 →]({{doc_url}})", "")
    text_el["content"] = body_text

    return template


def send_message(chat_id: str, text: str) -> dict:
    """向飞书群或用户发送文本消息。chat_id 以 oc_ 开头为群，以 ou_ 开头为用户。"""
    token = get_token()
    result = http(
        "POST",
        "/open-apis/im/v1/messages?receive_id_type=chat_id",
        token=token,
        body={
            "receive_id": chat_id,
            "msg_type": "text",
            "content": json.dumps({"text": text}, ensure_ascii=False),
        },
    )
    if result.get("code") != 0:
        raise RuntimeError(f"发送消息失败（code={result.get('code')}）：{result.get('msg')}")
    msg_id = result.get("data", {}).get("message_id", "")
    return {"success": True, "message_id": msg_id, "chat_id": chat_id}


# ── Release Config ───────────────────────────────────────────────────────────

def get_release_config() -> dict:
    cfg = read_config() or {}
    release = cfg.get("release")
    if not release:
        return {"configured": False}
    return {"configured": True, "release": release}


def save_release_config(release_json: str) -> dict:
    release = json.loads(release_json)
    USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    cfg = read_config() or {}
    cfg["release"] = release
    _secure_write(CONFIG_FILE, json.dumps(cfg, indent=2, ensure_ascii=False))
    return {"success": True, "message": f"release 配置已保存到 {CONFIG_FILE}"}


# ── Bot / Webhook Config ──────────────────────────────────────────────────────

def get_bot_config() -> dict:
    cfg = read_config() or {}
    bot = cfg.get("bot")
    if not bot:
        return {"configured": False}
    return {"configured": True, "bot": bot}


def save_bot_config(bot_json: str) -> dict:
    bot = json.loads(bot_json)
    USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    cfg = read_config() or {}
    cfg["bot"] = bot
    _secure_write(CONFIG_FILE, json.dumps(cfg, indent=2, ensure_ascii=False))
    return {"success": True, "message": f"bot 配置已保存到 {CONFIG_FILE}"}


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
        elif cmd == "auth":
            out = auth()
        elif cmd == "save_user":
            email = args[args.index("--email") + 1] if "--email" in args else None
            mobile = args[args.index("--mobile") + 1] if "--mobile" in args else None
            out = save_user(email=email, mobile=mobile)
        elif cmd == "get_task":
            out = get_task(args[1])
        elif cmd == "list_tasks":
            completed = "--completed" in args
            page_size = int(args[args.index("--page_size") + 1]) if "--page_size" in args else 20
            status = args[args.index("--status") + 1] if "--status" in args else None
            out = list_tasks(completed, page_size, status)
        elif cmd == "get_task_full":
            out = get_task_full(args[1])
        elif cmd == "get_subtasks":
            out = get_subtasks(args[1])
        elif cmd == "complete_task":
            out = complete_task(args[1])
        elif cmd == "add_comment":
            out = add_comment(args[1], " ".join(args[2:]))
        elif cmd == "send_message":
            out = send_message(args[1], " ".join(args[2:]))
        elif cmd == "send_card":
            id_type = args[3] if len(args) > 3 else "chat_id"
            out = send_card(args[1], json.loads(args[2]), id_type)
        elif cmd == "upload_image":
            out = {"image_key": upload_image(args[1])}
        elif cmd == "send_image":
            out = send_image(args[1], args[2])
        elif cmd == "download_task_images":
            tid = parse_task_id(args[1])
            token = get_token()
            images = fetch_task_images(tid, token)
            out = {"images": images, "count": len(images)}
        elif cmd == "build_release_card":
            out = build_release_card(args[1])
        elif cmd == "get_release_config":
            out = get_release_config()
        elif cmd == "save_release_config":
            out = save_release_config(args[1])
        elif cmd == "get_bot_config":
            out = get_bot_config()
        elif cmd == "save_bot_config":
            out = save_bot_config(args[1])
        else:
            raise RuntimeError(f"未知命令：{cmd}")

        print(json.dumps(out, ensure_ascii=False, indent=2))
    except Exception as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
