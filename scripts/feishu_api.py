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
  python3 feishu_api.py resolve_task_guid <task_id_or_short_prefix>
  python3 feishu_api.py print_auth_url             # 无浏览器环境：打印授权链接，手动复制
  python3 feishu_api.py exchange_code <code>        # 无浏览器环境：用授权码直接换 token
  python3 feishu_api.py pick_task_at_open_id <task_id> [--rule first_follower] [--exclude ou_x,ou_y]
  python3 feishu_api.py generate_release_mascot '<json_string>' | '@params.json'
  python3 feishu_api.py generate_release_image '<json_string>' | '@params.json'
  python3 feishu_api.py prepare_release_card_image '<json_string>' | '@params.json'
  python3 feishu_api.py send_release_card_with_mentions '<json_string>' | '@params.json'

Note: 长 JSON 参数可用 @path 语法从文件读取，避免 Windows shell 引号转义问题。
      支持的命令：build_release_card、generate_release_mascot、generate_release_image、
      prepare_release_card_image、send_release_card_with_mentions。

Output: JSON to stdout. Errors to stderr (JSON format), exit code 1.
"""

import sys
import os
import json
import time
import re
import stat
import base64
import random
import urllib.request
import urllib.error
import pathlib

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except AttributeError:
    pass

FEISHU_BASE = "https://open.feishu.cn"

# ── 路径常量 ──────────────────────────────────────────────────────────────────
# 用户数据：跨项目/跨工作目录共享，固定在用户主目录
USER_CONFIG_DIR = pathlib.Path.home() / ".claude" / "pipelit"
CONFIG_FILE = USER_CONFIG_DIR / "config.json"
TOKEN_CACHE_FILE = USER_CONFIG_DIR / ".token_cache.json"
USER_TOKEN_CACHE = USER_CONFIG_DIR / ".user_token_cache.json"

# 静态资源：跟着脚本走，相对 __file__ 引用
TEMPLATE_DIR = pathlib.Path(__file__).parent / "templates"
PLUGIN_ROOT = pathlib.Path(__file__).parent.parent

# Task 结果缓存（减少重复 API 调用）
TASK_CACHE_DIR = USER_CONFIG_DIR / "task-cache"
TASK_CACHE_TTL = 300  # 5 分钟（秒）
DEFAULT_RELEASE_REFERENCE_IMAGE = PLUGIN_ROOT / "feilun.png"


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

def _task_cache_path(tid: str) -> pathlib.Path:
    return TASK_CACHE_DIR / f"{tid}.json"


def _get_cached_task(tid: str) -> dict | None:
    """读取 task 缓存（TTL = TASK_CACHE_TTL 秒）。过期或不存在返回 None。"""
    path = _task_cache_path(tid)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if time.time() - data.get("_cached_at", 0) > TASK_CACHE_TTL:
            path.unlink(missing_ok=True)
            return None
        return data
    except Exception:
        return None


def _cache_task(tid: str, data: dict) -> None:
    """写入 task 缓存，附加 _cached_at 时间戳。"""
    try:
        TASK_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        payload = {**data, "_cached_at": time.time()}
        _task_cache_path(tid).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:
        pass  # 缓存写失败不影响主流程


def _invalidate_task_cache(tid: str) -> None:
    """任务状态变更后（complete / add_comment）主动删除缓存。"""
    _task_cache_path(tid).unlink(missing_ok=True)


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
    cfg = _read_project_config()
    cfg["app_id"] = app_id
    cfg["app_secret"] = app_secret
    _write_project_config(cfg)
    TOKEN_CACHE_FILE.unlink(missing_ok=True)
    project_file = _project_config_file()
    return {"success": True, "message": f"凭据已保存到 {project_file}"}


def check_config() -> dict:
    cfg = load_merged_config()
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
    cfg = load_merged_config()
    frontend = cfg.get("frontend_path")
    backend = cfg.get("backend_path")
    return {
        "configured": bool(frontend or backend),
        "frontend_path": frontend,
        "backend_path": backend,
    }


def _maybe_create_extends_pointer(cfg: dict) -> None:
    """若 cfg 同时含 frontend_path 和 backend_path，为非 cwd 的那个目录创建 extends 指针。

    规则：canonical 是 _resolve_canonical_config() 指向的文件（当前 cwd 的主配置）；
    另一个目录若已有实质配置（不只是 extends 字段）则不覆盖。
    """
    fp = cfg.get("frontend_path")
    bp = cfg.get("backend_path")
    if not fp or not bp:
        return

    canonical = _resolve_canonical_config()  # 当前 cwd 的 canonical 文件
    fp_path = pathlib.Path(fp)
    bp_path = pathlib.Path(bp)

    # 判断另一个目录（非当前 canonical 所在侧）
    canonical_is_under_fp = False
    try:
        canonical.relative_to(fp_path)
        canonical_is_under_fp = True
    except ValueError:
        pass

    other = bp_path if canonical_is_under_fp else fp_path
    ptr_file = other / ".pipelit" / "config.json"

    # 若另一个目录已有实质配置则不覆盖
    if ptr_file.exists():
        try:
            existing = json.loads(ptr_file.read_text(encoding="utf-8"))
            if any(k != "extends" for k in existing):
                return
        except (json.JSONDecodeError, OSError):
            pass

    ptr_file.parent.mkdir(parents=True, exist_ok=True)
    _secure_write(ptr_file, json.dumps({"extends": str(canonical)}, indent=2, ensure_ascii=False))


def save_project_config(frontend_path: str = None, backend_path: str = None) -> dict:
    cfg = _read_project_config()
    if frontend_path:
        cfg["frontend_path"] = frontend_path.rstrip("/\\")
    if backend_path:
        cfg["backend_path"] = backend_path.rstrip("/\\")
    _write_project_config(cfg)
    _maybe_create_extends_pointer(cfg)
    return {
        "success": True,
        "frontend_path": cfg.get("frontend_path"),
        "backend_path": cfg.get("backend_path"),
    }


# ── L2 Project Config Helpers ─────────────────────────────────────────────────

def _project_config_file(cwd: str | None = None) -> pathlib.Path:
    base = pathlib.Path(cwd) if cwd else pathlib.Path.cwd()
    return base / ".pipelit" / "config.json"


def _resolve_canonical_config(cwd: str | None = None) -> pathlib.Path:
    """返回 canonical 配置文件路径：若当前 cwd 的配置有 extends 字段，跟随一层。"""
    f = _project_config_file(cwd)
    if f.exists():
        try:
            raw = json.loads(f.read_text(encoding="utf-8"))
            target = raw.get("extends")
            if target:
                return pathlib.Path(target)
        except Exception:
            pass
    return f


def _read_project_config(cwd: str | None = None) -> dict:
    f = _resolve_canonical_config(cwd)
    if not f.exists():
        return {}
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        # 过滤掉 extends 字段，调用方不需要感知
        data.pop("extends", None)
        return data
    except Exception:
        return {}


def _write_project_config(data: dict, cwd: str | None = None) -> None:
    f = _resolve_canonical_config(cwd)
    f.parent.mkdir(parents=True, exist_ok=True)
    _secure_write(f, json.dumps(data, indent=2, ensure_ascii=False))


def load_merged_config(cwd: str | None = None) -> dict:
    """三层配置合并：L1 用户级 < L2 项目级 < L3 仓库级（浅合并，高层覆盖低层）。

    L1: ~/.claude/pipelit/config.json        凭据、全局默认值
    L2: <cwd>/.pipelit/config.json            项目路径、发版配置
    L3: <cwd>/.pipelit.json（可选）           仓库级 precheck、特殊规则
    """
    result: dict = {}

    # L1
    l1 = read_config()
    if l1:
        result.update(l1)

    base = pathlib.Path(cwd) if cwd else pathlib.Path.cwd()

    # L2
    l2_file = base / ".pipelit" / "config.json"
    if l2_file.exists():
        try:
            result.update(json.loads(l2_file.read_text(encoding="utf-8")))
        except Exception:
            pass

    # L3
    l3_file = base / ".pipelit.json"
    if l3_file.exists():
        try:
            result.update(json.loads(l3_file.read_text(encoding="utf-8")))
        except Exception:
            pass

    return result


# ── Token ─────────────────────────────────────────────────────────────────────

def get_token() -> str:
    cfg = load_merged_config()
    if not cfg.get("app_id") or not cfg.get("app_secret"):
        raise RuntimeError("凭据未配置，请先运行 check_config")

    if TOKEN_CACHE_FILE.exists():
        cache = json.loads(TOKEN_CACHE_FILE.read_text())
        if (time.time() < cache.get("expires_at", 0)
                and cache.get("app_id") == cfg["app_id"]):
            return cache["token"]

    result = http("POST", "/open-apis/auth/v3/tenant_access_token/internal", body={
        "app_id": cfg["app_id"],
        "app_secret": cfg["app_secret"],
    })
    if result.get("code") != 0:
        raise RuntimeError(f"获取 token 失败（code={result.get('code')}）：{result.get('msg')}")

    token = result["tenant_access_token"]
    expires_at = time.time() + result.get("expire", 7200) - 60

    USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    _secure_write(TOKEN_CACHE_FILE, json.dumps({
        "token": token,
        "expires_at": expires_at,
        "app_id": cfg["app_id"],
    }))
    return token


AUTH_REDIRECT_URI = "http://127.0.0.1:9876/callback"


def _get_app_token() -> str:
    """获取 app_access_token（用于 OAuth 码换 token）。"""
    cfg = load_merged_config()
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


def print_auth_url() -> dict:
    """无浏览器环境：打印授权链接，让用户在本地浏览器手动完成授权，再用 exchange_code 换 token。"""
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
    print(f"\n请在本地浏览器打开以下链接完成授权：\n\n{auth_url}\n", file=sys.stderr)
    print("授权后浏览器会跳到 127.0.0.1:9876（连接失败没关系），", file=sys.stderr)
    print("从地址栏复制 code=xxx 的值，然后运行：", file=sys.stderr)
    print("  python3 feishu_api.py exchange_code <code>\n", file=sys.stderr)
    return {"auth_url": auth_url}


def exchange_code(code: str) -> dict:
    """用授权码换取 user_access_token 并缓存（无浏览器环境专用）。"""
    app_token = _get_app_token()
    result = http("POST", "/open-apis/authen/v1/oidc/access_token",
                  token=app_token,
                  body={"grant_type": "authorization_code", "code": code})
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


_VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".flv", ".m4v"}
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"}


def fetch_task_images(tid: str, token: str) -> list:
    """拉取任务附件（图片 + 视频），下载到本地，返回附件列表。

    图片下载到 ~/.claude/pipelit/images/
    视频下载到 ~/.claude/pipelit/attachments/<tid[:8]>/
    每项格式：{"path": str, "name": str, "type": "image"|"video"}
    """
    result = http(
        "GET",
        f"/open-apis/task/v2/attachments?resource_type=task&resource_id={tid}&page_size=50",
        token=token,
    )
    if result.get("code") != 0:
        return []

    img_dir = USER_CONFIG_DIR / "images"
    vid_dir = USER_CONFIG_DIR / "attachments" / tid[:8]
    img_dir.mkdir(parents=True, exist_ok=True)

    saved = []
    for att in result.get("data", {}).get("items", []):
        name = att.get("name", "file")
        ext = pathlib.Path(name).suffix.lower()
        att_id = att.get("guid", att.get("id", name))

        is_video = ext in _VIDEO_EXTS
        is_image = ext in _IMAGE_EXTS or (not is_video and not ext)

        if is_video:
            vid_dir.mkdir(parents=True, exist_ok=True)
            out_path = vid_dir / f"{att_id}{ext}"
        else:
            out_path = img_dir / f"{tid[:8]}_{att_id}{ext or '.png'}"

        if not out_path.exists():
            url = att.get("url", "")
            if not url:
                saved.append({"error": "无下载链接", "name": name, "type": "video" if is_video else "image"})
                continue
            try:
                out_path.write_bytes(http_download(url, token))
            except Exception as e:
                saved.append({"error": str(e), "name": name, "type": "video" if is_video else "image"})
                continue

        saved.append({
            "path": str(out_path),
            "name": name,
            "type": "video" if is_video else "image",
        })
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


def get_task_full(task_id: str, no_cache: bool = False) -> dict:
    """一次调用拿到任务全部上下文：任务详情 + 子任务 + 附件图片 + 项目配置。

    结果缓存 TASK_CACHE_TTL 秒（默认 5 分钟），减少重复 API 调用。
    传 no_cache=True 强制刷新。
    """
    tid = parse_task_id(task_id)

    # 检查缓存
    if not no_cache:
        cached = _get_cached_task(tid)
        if cached:
            return {k: v for k, v in cached.items() if not k.startswith("_")}

    token = get_user_token()  # 个人任务需要 user_access_token

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

    # 附件：图片 + 视频（自动下载）
    attachments = fetch_task_images(tid, token)
    images = [a for a in attachments if a.get("type") == "image" and "path" in a]
    videos = [a for a in attachments if a.get("type") == "video" and "path" in a]
    video_errors = [a for a in attachments if a.get("type") == "video" and "error" in a]

    # 项目配置（三层合并）
    merged_cfg = load_merged_config()
    project_config = {
        "configured": bool(merged_cfg.get("frontend_path") or merged_cfg.get("backend_path")),
        "frontend_path": merged_cfg.get("frontend_path"),
        "backend_path": merged_cfg.get("backend_path"),
    }

    result = {
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
        "has_images": len(images) > 0,
        "videos": videos,
        "has_videos": len(videos) > 0,
        "project_config": project_config,
    }
    if videos:
        result["video_notice"] = (
            f"已下载 {len(videos)} 个视频附件，请人工查看：" +
            ", ".join(v["path"] for v in videos)
        )
    if video_errors:
        result["video_errors"] = video_errors
    _cache_task(tid, result)
    return result


def complete_task(task_id: str) -> dict:
    tid = parse_task_id(task_id)
    _invalidate_task_cache(tid)
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
    _invalidate_task_cache(tid)
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


def _load_json_param(arg: str) -> dict:
    """支持两种形式：直接 JSON 字符串 或 @path 表示从文件读取。

    @file 形式避免 Windows shell 对长 JSON 字符串的引号转义问题。
    """
    if arg.startswith("@"):
        return json.loads(pathlib.Path(arg[1:]).read_text(encoding="utf-8-sig"))
    return json.loads(arg)


RELEASE_IMAGE_THEMES = [
    "the mascot presenting a clean product launch dashboard",
    "the mascot celebrating a successful software deployment",
    "the mascot pointing at a luminous release timeline",
    "the mascot beside modular update cards and data rings",
    "the mascot introducing calm SaaS improvements",
    "the mascot with circular pipeline graphics",
]

RELEASE_MASCOT_ACTIONS = [
    "smiling and pointing upward with one hand",
    "holding a small glowing release package",
    "waving beside a dashboard with cheerful confidence",
    "giving a thumbs-up near a deployment timeline",
    "leaning forward with an excited discovery expression",
    "presenting floating update cards with an open palm",
]


def _truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


def _resolve_reference_image(params: dict) -> pathlib.Path | None:
    raw = params.get("reference_image_path") or os.environ.get("RELEASE_REFERENCE_IMAGE")
    use_default = params.get("use_reference_image", True)
    if not raw:
        cfg = load_merged_config()
        release = cfg.get("release") or {}
        raw = release.get("mascotImagePath")
    if raw:
        path = pathlib.Path(raw).expanduser()
        if not path.is_absolute():
            user_path = (USER_CONFIG_DIR / path).resolve()
            plugin_path = (PLUGIN_ROOT / path).resolve()
            path = user_path if user_path.exists() else plugin_path
        if not path.exists():
            raise RuntimeError(f"参考图片不存在：{path}")
        return path
    if _truthy(use_default) and DEFAULT_RELEASE_REFERENCE_IMAGE.exists():
        return DEFAULT_RELEASE_REFERENCE_IMAGE
    return None


def _release_brand_context(params: dict) -> str:
    cfg = load_merged_config()
    release = cfg.get("release") or {}
    return (
        params.get("brand_context")
        or release.get("mascotDescription")
        or release.get("projectName")
        or params.get("project_name")
        or "this software project"
    )


def _build_release_image_prompt(params: dict) -> str:
    prompt = (params.get("image_prompt") or "").strip()
    action = params.get("mascot_action") or random.choice(RELEASE_MASCOT_ACTIONS)
    brand_context = _release_brand_context(params)
    if prompt:
        return (
            "Use the provided reference image as the canonical project mascot style guide. "
            "Preserve the mascot's identity, face, outfit silhouette, color palette, and logo language. "
            f"Keep the same character, but use a fresh expression/action for this release: {action}. "
            f"Brand/system context: {brand_context}. "
            f"{prompt}"
        )

    version = params.get("version", "new release")
    date = params.get("date", "")
    content = re.sub(r"<[^>]+>", "", params.get("content", ""))
    content = re.sub(r"[*_`#>\[\]()]|https?://\S+", "", content)
    content = re.sub(r"\s+", " ", content).strip()[:700]
    theme = random.choice(RELEASE_IMAGE_THEMES)
    return (
        "Use the provided reference image as the canonical project mascot style guide. "
        "Preserve the mascot's identity, face, outfit silhouette, color palette, and logo language. "
        f"Keep the same character, but use a fresh expression/action for this release: {action}. "
        f"Brand/system context: {brand_context}. "
        f"Create a 1:1 hero image for a software release card. Theme: {theme}. "
        f"Release: {version} {date}. Highlights: {content or 'product improvements and fixes'}. "
        "Style: modern, polished, business-friendly, bright white background, high contrast, "
        "no readable text, no brand names, suitable as the right-side image in a Feishu/Lark announcement card."
    )


def _mime_type(path: pathlib.Path) -> str:
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }.get(path.suffix.lower(), "application/octet-stream")


def _post_multipart(url: str, api_key: str, fields: dict, files: list[tuple[str, pathlib.Path]]) -> dict:
    boundary = "----PipelitImageBoundary" + os.urandom(8).hex()
    parts: list[bytes] = []
    for name, value in fields.items():
        if value is None:
            continue
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}".encode("utf-8")
        )
    for name, path in files:
        parts.append(
            (
                f"--{boundary}\r\n"
                f"Content-Disposition: form-data; name=\"{name}\"; filename=\"{path.name}\"\r\n"
                f"Content-Type: {_mime_type(path)}\r\n\r\n"
            ).encode("utf-8")
            + path.read_bytes()
        )
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    data = b"\r\n".join(parts)
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.loads(resp.read())


def _openai_image_request(
    *,
    api_key: str,
    base_url: str,
    body: dict,
    reference_images: list[pathlib.Path] | None = None,
) -> dict:
    if reference_images:
        return _post_multipart(
            f"{base_url}/images/edits",
            api_key,
            body,
            [("image", path) for path in reference_images],
        )

    req = urllib.request.Request(
        f"{base_url}/images/generations",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.loads(resp.read())


def _write_openai_image(result: dict, out_path: pathlib.Path) -> None:
    data = result.get("data") or []
    if not data:
        raise RuntimeError(f"OpenAI 图片生成未返回 data：{result}")

    item = data[0]
    if item.get("b64_json"):
        out_path.write_bytes(base64.b64decode(item["b64_json"]))
    elif item.get("url"):
        with urllib.request.urlopen(item["url"], timeout=60) as resp:
            out_path.write_bytes(resp.read())
    else:
        raise RuntimeError(f"OpenAI 图片生成结果缺少 b64_json/url：{item}")


def _openai_image_defaults(params: dict) -> tuple[str, str, str, str]:
    model = params.get("image_model") or os.environ.get("OPENAI_IMAGE_MODEL") or "gpt-image-2"
    size = params.get("image_size") or os.environ.get("OPENAI_IMAGE_SIZE") or "1024x1024"
    quality = params.get("image_quality") or os.environ.get("OPENAI_IMAGE_QUALITY") or "low"
    base_url = (os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
    return model, size, quality, base_url


def _require_openai_api_key() -> str:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("未设置 OPENAI_API_KEY，无法生成图片")
    return api_key


def _save_release_mascot_config(path: pathlib.Path, params: dict) -> None:
    cfg = load_merged_config()
    release = cfg.get("release") or {}
    release["mascotImagePath"] = str(path)
    if params.get("mascot_description"):
        release["mascotDescription"] = params["mascot_description"]
    if params.get("company_icon_path"):
        release["companyIconPath"] = params["company_icon_path"]
    cfg["release"] = release
    USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    _secure_write(CONFIG_FILE, json.dumps(cfg, indent=2, ensure_ascii=False))


def _resolve_optional_image_path(raw: str | None) -> pathlib.Path | None:
    if not raw:
        return None
    path = pathlib.Path(raw).expanduser()
    if not path.is_absolute():
        path = (PLUGIN_ROOT / path).resolve()
    if not path.exists():
        raise RuntimeError(f"图片文件不存在：{path}")
    return path


def generate_release_mascot(params_json: str) -> dict:
    """初始化发版卡片 mascot。

    params_json 字段：project_name(可选)/company_icon_path(可选)/mascot_description(可选)/
    image_model/image_size/image_quality(可选)/save_to_config(可选，默认 true)。
    """
    params = _load_json_param(params_json)
    api_key = _require_openai_api_key()
    model, size, quality, base_url = _openai_image_defaults(params)
    project_name = params.get("project_name") or _release_brand_context(params)
    mascot_description = (params.get("mascot_description") or "").strip()
    company_icon = _resolve_optional_image_path(params.get("company_icon_path"))

    prompt = (
        f"Create a stable canonical 3D cartoon mascot reference image for {project_name}. "
        "The mascot should be friendly, memorable, brand-safe, and suitable for repeated software release cards. "
        "Make a clean square portrait on a bright white or lightly tinted background. "
        "Include a distinctive outfit, silhouette, color palette, and simple emblem language that can remain consistent. "
        "Do not include readable text, brand names, UI copy, watermarks, or busy scenery. "
        "The output should be a reusable reference image, not a one-off release poster. "
    )
    if mascot_description:
        prompt += f"User-provided mascot/system description: {mascot_description}. "
    if company_icon:
        prompt += (
            "Use the provided company icon only as brand inspiration for color, geometry, and emblem language. "
            "Do not simply paste the icon; integrate its visual language into the mascot design. "
        )

    body = {"model": model, "prompt": prompt, "size": size, "n": 1}
    if quality:
        body["quality"] = quality

    try:
        result = _openai_image_request(
            api_key=api_key,
            base_url=base_url,
            body=body,
            reference_images=[company_icon] if company_icon else None,
        )
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        try:
            detail = json.loads(raw)
            message = detail.get("error", {}).get("message") or detail.get("message") or raw
        except Exception:
            message = raw
        raise RuntimeError(f"OpenAI mascot 生成失败（HTTP {e.code}）：{message}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"OpenAI mascot 生成网络失败：{e.reason}") from e

    img_dir = USER_CONFIG_DIR / "release_images"
    img_dir.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^0-9A-Za-z._-]+", "-", str(project_name or "project")).strip("-") or "project"
    out_path = img_dir / f"{slug}-mascot.png"
    _write_openai_image(result, out_path)

    if _truthy(params.get("save_to_config", True)):
        _save_release_mascot_config(out_path, params)

    return {
        "success": True,
        "mascot_image_path": str(out_path),
        "company_icon_path": str(company_icon) if company_icon else None,
        "prompt": prompt,
        "model": model,
        "size": size,
        "quality": quality,
        "saved_to_config": _truthy(params.get("save_to_config", True)),
    }


def generate_release_image(params_json: str) -> dict:
    """调用 OpenAI Images API 生成发版卡片图片，保存到本地并返回 image_path。

    params_json 字段：version/date/content/image_prompt(可选)/image_model(可选)/
    image_size(可选)/image_quality(可选)/reference_image_path(可选)。
    默认优先使用 release.mascotImagePath，未配置时才回退项目根目录 feilun.png。
    需要环境变量 OPENAI_API_KEY。
    """
    params = _load_json_param(params_json)
    api_key = _require_openai_api_key()

    prompt = _build_release_image_prompt(params)
    model, size, quality, base_url = _openai_image_defaults(params)
    reference_image = _resolve_reference_image(params)

    body = {
        "model": model,
        "prompt": prompt,
        "size": size,
        "n": 1,
    }
    if quality:
        body["quality"] = quality

    try:
        result = _openai_image_request(
            api_key=api_key,
            base_url=base_url,
            body=body,
            reference_images=[reference_image] if reference_image else None,
        )
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        try:
            detail = json.loads(raw)
            message = detail.get("error", {}).get("message") or detail.get("message") or raw
        except Exception:
            message = raw
        raise RuntimeError(f"OpenAI 图片生成失败（HTTP {e.code}）：{message}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"OpenAI 图片生成网络失败：{e.reason}") from e

    img_dir = USER_CONFIG_DIR / "release_images"
    img_dir.mkdir(parents=True, exist_ok=True)
    version = re.sub(r"[^0-9A-Za-z._-]+", "-", str(params.get("version", "release"))).strip("-")
    out_path = img_dir / f"{version or 'release'}-{int(time.time())}.png"
    _write_openai_image(result, out_path)

    return {
        "success": True,
        "image_path": str(out_path),
        "prompt": prompt,
        "model": model,
        "size": size,
        "quality": quality,
        "reference_image_path": str(reference_image) if reference_image else None,
    }


def prepare_release_card_image(params_json: str) -> dict:
    """生成/上传发版卡片图，返回可直接写入卡片 img_key 的飞书 image_key。

    params_json 字段同 generate_release_image，另支持：
      image_path: 直接上传已有本地图片
      generate_image: 为 false 且未传 image_path 时跳过，返回 image_key=None
    """
    params = _load_json_param(params_json)
    image_path = params.get("image_path")
    generated_image = None
    should_generate = _truthy(params.get("generate_image", True)) or bool(params.get("image_prompt"))

    if not image_path and should_generate:
        generated_image = generate_release_image(json.dumps(params, ensure_ascii=False))
        image_path = generated_image["image_path"]

    if not image_path:
        return {
            "success": True,
            "image_key": None,
            "img_key": None,
            "image_path": None,
            "generated_image": None,
            "message": "未传 image_path 且 generate_image=false，跳过发版卡片图片",
        }

    image_key = upload_image(image_path)
    return {
        "success": True,
        "image_key": image_key,
        "img_key": image_key,
        "image_path": image_path,
        "generated_image": generated_image,
    }


def build_release_card(params_json: str) -> dict:
    """从版本信息构建飞书发版卡片。

    params_json: JSON 字符串或 @file，字段：version, date, content, doc_url(可选), img_key(可选)
    返回可直接传给 send_card 的卡片 dict。
    """
    params = _load_json_param(params_json)
    version = params["version"]
    date = params["date"]
    content = params["content"]
    doc_url = params.get("doc_url", "")
    img_key = params.get("img_key")

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

    # 替换 img_key；若模板是占位符但没有传图，则去掉图片列，避免继续使用写死图片。
    if el["tag"] == "column_set":
        for col in list(el["columns"]):
            for elem in list(col["elements"]):
                if elem.get("tag") == "img":
                    if img_key:
                        elem["img_key"] = img_key
                    elif "{{img_key}}" in elem.get("img_key", ""):
                        col["elements"].remove(elem)
            if not col["elements"]:
                el["columns"].remove(col)
        if len(el.get("columns", [])) == 1:
            el["columns"][0]["weight"] = 1

    return template


def pick_task_at_open_id(
    task_id: str,
    rule: str = "first_follower",
    exclude: list[str] | None = None,
) -> str | None:
    """按规则取飞书任务的 @ open_id。

    rule:
      - first_follower: 第一个 role=follower 且不在 exclude 的 open_id
      - first_assignee: 第一个 role=assignee 且不在 exclude 的 open_id
      - first_member:   不区分 role，按 members 顺序第一个不在 exclude 的 open_id
    task_id: 完整 UUID 或 ≥4 位短前缀（前缀时会自动调 list_tasks 匹配）
    exclude: 黑名单 open_id 列表
    返回单个 open_id，找不到则返回 None。
    """
    exclude_set = set(exclude or [])
    full_id = resolve_task_guid(task_id)
    token = get_token()
    result = http(
        "GET",
        f"/open-apis/task/v2/tasks/{full_id}?user_id_type=open_id",
        token=token,
    )
    if result.get("code") != 0:
        raise RuntimeError(f"获取任务失败（code={result.get('code')}）：{result.get('msg')}")
    members = result.get("data", {}).get("task", {}).get("members", [])

    def _pick(role_filter: str | None) -> str | None:
        for m in members:
            if role_filter and m.get("role") != role_filter:
                continue
            oid = m.get("id")
            if oid and oid not in exclude_set:
                return oid
        return None

    if rule == "first_follower":
        return _pick("follower")
    if rule == "first_assignee":
        return _pick("assignee")
    if rule == "first_member":
        return _pick(None)
    raise RuntimeError(f"未知 at_rule：{rule}（可选：first_follower / first_assignee / first_member）")


def resolve_task_guid(task_id: str) -> str:
    """8 位前缀 → 完整 GUID；已是完整 GUID 则原样返回。

    标准 UUID 长度 36（含 4 个连字符）。短前缀时通过 list_tasks 匹配。
    """
    if len(task_id) >= 36 and task_id.count("-") == 4:
        return task_id
    if len(task_id) < 4:
        raise RuntimeError(f"task_id 太短（至少 4 位）：{task_id}")

    token = get_user_token()
    for completed in (False, True):
        params = f"page_size=100&completed={str(completed).lower()}&user_id_type=user_id"
        try:
            result = http("GET", f"/open-apis/task/v2/tasks?{params}", token=token)
        except Exception:
            continue
        if result.get("code") != 0:
            continue
        for t in result.get("data", {}).get("items", []):
            if t.get("guid", "").startswith(task_id):
                return t["guid"]
    raise RuntimeError(f"在飞书任务列表中找不到匹配前缀的任务：{task_id}")


def send_release_card_with_mentions(params_json: str) -> dict:
    """一站式：组合带 @ 关注人的 changelog → 构建卡片 → 发送到飞书群。

    params_json 字段（JSON 字符串或 @file）:
      version       (必需) 版本号，如 "v3.9.1"
      date          (必需) 日期，如 "2026-05-28"
      chat_id       (必需) 飞书群 chat_id（oc_ 开头）
      sections      (必需) [{"title": "**✨ 新功能**",
                            "entries": [{"text": "...", "task_id": "..."(可选)}]}]
      doc_url       (可选) 末尾文档链接
      image_path    (可选) 本地图片路径（优先级高于 generate_image）
      generate_image (可选) true 时调用 OpenAI 随机生成发版图并上传
      image_prompt  (可选) 指定生成图片的提示词；传入时自动启用 generate_image
      image_model / image_size / image_quality (可选) OpenAI 图片生成参数
      at_rule       (可选) first_follower (默认) / first_assignee / first_member / none
      exclude_open_ids (可选) 黑名单 open_id 列表

    返回 {success, message_id, chat_id, image_key, generated_image, task_mentions, content_preview}
    """
    params = _load_json_param(params_json)
    version = params["version"]
    date = params["date"]
    chat_id = params["chat_id"]
    sections = params["sections"]
    doc_url = params.get("doc_url", "")
    image_path = params.get("image_path")

    # cardFeatures: 从 params > merged config > 默认 true
    _global_features = load_merged_config().get("cardFeatures", {})
    _param_features = params.get("card_features", {})
    _merged_features = {**{"linkTask": True, "atFollower": True, "image": True},
                        **_global_features, **_param_features}
    _image_enabled = _merged_features.get("image", True)
    _at_enabled = _merged_features.get("atFollower", True)

    # image=false 时跳过生成/上传，忽略 generate_image 和 image_path
    generate_image = _image_enabled and (
        _truthy(params.get("generate_image")) or bool(params.get("image_prompt"))
    )
    if not _image_enabled:
        image_path = None

    at_rule = params.get("at_rule", "first_follower") if _at_enabled else "none"
    exclude = list(params.get("exclude_open_ids", []))

    # 1. 为每个唯一 task_id 查 @ open_id 和完整 GUID
    task_mentions: dict[str, str | None] = {}
    task_guids: dict[str, str | None] = {}
    for sec in sections:
        for entry in sec.get("entries", []):
            tid = entry.get("task_id")
            if not tid or tid in task_mentions:
                continue
            try:
                task_guids[tid] = resolve_task_guid(tid)
            except Exception as e:
                task_guids[tid] = None
                print(f"[warn] resolve_task_guid({tid}): {e}", file=sys.stderr)
            if at_rule != "none":
                try:
                    task_mentions[tid] = pick_task_at_open_id(tid, at_rule, exclude)
                except Exception as e:
                    task_mentions[tid] = None
                    print(f"[warn] pick_task_at_open_id({tid}): {e}", file=sys.stderr)
            else:
                task_mentions[tid] = None

    # 2. 拼装 lark_md 内容（通过 card_builder，支持 cardFeatures 开关）
    import importlib.util as _ilu
    _cb_path = pathlib.Path(__file__).parent / "card_builder.py"
    _cb_spec = _ilu.spec_from_file_location("card_builder", _cb_path)
    _cb_mod = _ilu.module_from_spec(_cb_spec)
    _cb_spec.loader.exec_module(_cb_mod)
    cb_result = _cb_mod.build_lark_md({
        "sections": sections,
        "task_mentions": task_mentions,
        "task_guids": task_guids,
        "always_mention_open_ids": params.get("always_mention_open_ids", []),
        "card_features": params.get("card_features", {}),
    })
    content = cb_result["lark_md"]

    # 3. 生成/上传图片，拿到飞书 image_key 后写入卡片 img_key。
    image_params = dict(params)
    image_params["content"] = content
    image_params["generate_image"] = generate_image
    prepared_image = prepare_release_card_image(json.dumps(image_params, ensure_ascii=False))
    img_key = prepared_image.get("image_key")
    generated_image = prepared_image.get("generated_image")

    # 4. 构建卡片
    card_params: dict = {"version": version, "date": date, "content": content}
    if doc_url:
        card_params["doc_url"] = doc_url
    if img_key:
        card_params["img_key"] = img_key
    card = build_release_card(json.dumps(card_params, ensure_ascii=False))

    # 5. 发送
    result = send_card(chat_id, card)
    return {
        "success": result["success"],
        "message_id": result["message_id"],
        "chat_id": chat_id,
        "image_key": img_key,
        "generated_image": generated_image,
        "task_mentions": task_mentions,
        "task_guids": task_guids,
        "content_preview": content,
    }


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
    cfg = load_merged_config()
    release = cfg.get("release")
    if not release:
        return {"configured": False}
    return {"configured": True, "release": release}


def save_release_config(release_json: str) -> dict:
    release = json.loads(release_json)
    cfg = _read_project_config()
    cfg["release"] = release
    _write_project_config(cfg)
    project_file = _project_config_file()
    return {"success": True, "message": f"release 配置已保存到 {project_file}"}


# ── Bot / Webhook Config ──────────────────────────────────────────────────────

def get_bot_config() -> dict:
    cfg = load_merged_config()
    bot = cfg.get("bot")
    if not bot:
        return {"configured": False}
    return {"configured": True, "bot": bot}


def save_bot_config(bot_json: str) -> dict:
    bot = json.loads(bot_json)
    cfg = _read_project_config()
    cfg["bot"] = bot
    _write_project_config(cfg)
    project_file = _project_config_file()
    return {"success": True, "message": f"bot 配置已保存到 {project_file}"}


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
        elif cmd == "print_auth_url":
            out = print_auth_url()
        elif cmd == "exchange_code":
            out = exchange_code(args[1])
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
        elif cmd == "generate_release_mascot":
            out = generate_release_mascot(args[1])
        elif cmd == "generate_release_image":
            out = generate_release_image(args[1])
        elif cmd == "prepare_release_card_image":
            out = prepare_release_card_image(args[1])
        elif cmd == "resolve_task_guid":
            out = {"guid": resolve_task_guid(args[1])}
        elif cmd == "pick_task_at_open_id":
            tid = args[1]
            rule = args[args.index("--rule") + 1] if "--rule" in args else "first_follower"
            excl_arg = args[args.index("--exclude") + 1] if "--exclude" in args else ""
            excl = [s.strip() for s in excl_arg.split(",") if s.strip()]
            out = {"open_id": pick_task_at_open_id(tid, rule, excl)}
        elif cmd == "send_release_card_with_mentions":
            out = send_release_card_with_mentions(args[1])
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
