#!/usr/bin/env python3
"""
Guance (观测云) Log API helper — stdlib only, zero external dependencies.

Requires: Python 3.10+

Usage:
  python3 guance_api.py check_config
  python3 guance_api.py save_config <api_key> <workspace_id>
  python3 guance_api.py query_errors <start> <end> [--limit N]

Time format for <start>/<end>:
  Relative: "1h", "30m", "2d"   (from now, e.g. start="1h" end="now")
  Absolute: "2024-01-01 09:00"

Output: JSON to stdout. Errors to stderr, exit code 1.
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
from datetime import datetime, timezone, timedelta

PLUGIN_ROOT = pathlib.Path(
    os.environ.get("CLAUDE_PLUGIN_ROOT", pathlib.Path(__file__).parent.parent)
)
USER_CONFIG_DIR = pathlib.Path.home() / ".claude" / "plugins" / "cache" / "pipelit"
GUANCE_CONFIG_FILE = USER_CONFIG_DIR / "guance_config.json"

HTTP_TIMEOUT = 30
LOG_SOURCE = "ads-backend"
# 观测云 OpenAPI 端点（按优先级尝试）
QUERY_PATHS = [
    "/api/v1/df_query_data",
    "/api/v1/dql/query",
    "/api/v1/query/data",
]


# ── 工具函数 ──────────────────────────────────────────────────────────────────

def _secure_write(path: pathlib.Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except (AttributeError, NotImplementedError, OSError):
        pass


def parse_time(t: str) -> int:
    """时间字符串 → 毫秒时间戳（UTC）。
    支持：'now'、'1h'、'30m'、'2d'、'2024-01-01 09:00'
    """
    t = t.strip()
    if t == "now":
        return int(time.time() * 1000)

    # 相对时间：1h / 30m / 2d / 1h30m
    if re.match(r'^[\ddhm]+$', t) and any(c in t for c in 'dhm'):
        days = int(re.search(r'(\d+)d', t).group(1)) if 'd' in t else 0
        hours = int(re.search(r'(\d+)h', t).group(1)) if 'h' in t else 0
        minutes = int(re.search(r'(\d+)m', t).group(1)) if 'm' in t else 0
        offset = days * 86400 + hours * 3600 + minutes * 60
        return int((time.time() - offset) * 1000)

    # 绝对时间（本地时间）
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            dt = datetime.strptime(t, fmt)
            local_offset = timedelta(seconds=time.timezone if time.daylight == 0 else time.altzone)
            utc_dt = dt - local_offset  # 本地 → UTC（使用 replace 避免 pytz 依赖）
            return int(utc_dt.replace(tzinfo=timezone.utc).timestamp() * 1000)
        except ValueError:
            continue

    raise ValueError(f"无法解析时间：'{t}'，支持格式：'1h'、'30m'、'2024-01-01 09:00'")


def fmt_ts(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M:%S")


# ── HTTP ──────────────────────────────────────────────────────────────────────

def _post(url: str, api_key: str, workspace_id: str, body: dict) -> dict:
    data = json.dumps(body).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "DF-API-KEY": api_key,
        "DF-WORKSPACE-UUID": workspace_id,
    }
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return json.loads(raw)
        except Exception:
            return {"code": e.code, "message": raw.decode(errors="replace")}
    except urllib.error.URLError as e:
        raise RuntimeError(f"网络请求失败：{e.reason}") from e


# ── 配置管理 ──────────────────────────────────────────────────────────────────

def read_config() -> dict | None:
    if GUANCE_CONFIG_FILE.exists():
        return json.loads(GUANCE_CONFIG_FILE.read_text(encoding="utf-8"))
    return None


def save_config(api_key: str, workspace_id: str) -> dict:
    USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    # 从 workspace_id 推断 base_url（cn6 → https://cn6-openapi.guance.com）
    m = re.search(r'(cn\d+)', workspace_id.lower()) if 'cn' in workspace_id.lower() else None
    # 也允许 workspace_id 已经是 URL 格式
    if workspace_id.startswith("http"):
        base_url = workspace_id.rstrip("/")
        workspace_id = ""
    else:
        region = m.group(1) if m else None
        base_url = f"https://{region}-openapi.guance.com" if region else "https://openapi.guance.com"

    cfg = {"api_key": api_key, "workspace_id": workspace_id, "base_url": base_url}
    _secure_write(GUANCE_CONFIG_FILE, json.dumps(cfg, indent=2))
    return {
        "success": True,
        "base_url": base_url,
        "workspace_id": workspace_id,
        "message": f"配置已保存 → {GUANCE_CONFIG_FILE}",
    }


def check_config() -> dict:
    cfg = read_config()
    if not cfg or not cfg.get("api_key"):
        return {
            "configured": False,
            "message": (
                "观测云凭据未配置，请按以下步骤操作：\n\n"
                "1. 登录观测云 → 管理 → API Key 管理 → 新建 Key\n"
                "2. 复制 API Key\n"
                "3. 找到 Workspace UUID（控制台 URL 中 w=wksp_xxx 部分）\n\n"
                "然后运行：\n"
                "  python3 guance_api.py save_config <api_key> <workspace_id>"
            ),
        }
    return {
        "configured": True,
        "base_url": cfg["base_url"],
        "workspace_id": cfg.get("workspace_id", ""),
        "api_key_prefix": cfg["api_key"][:8] + "...",
    }


def _get_cfg() -> dict:
    cfg = read_config()
    if not cfg or not cfg.get("api_key"):
        raise RuntimeError("观测云凭据未配置，请先运行 check_config")
    return cfg


# ── DQL 查询核心 ──────────────────────────────────────────────────────────────

def _dql(cfg: dict, q: str, start_ms: int, end_ms: int, limit: int) -> list[dict]:
    """执行 DQL，返回日志行列表（每行是 {字段名: 值} 的 dict）。"""
    body = {
        "queries": [{
            "qtype": "dql",
            "query": {
                "q": q,
                "timeRange": [start_ms, end_ms],
                "maxPoint": limit,
                "highlight": False,
            }
        }]
    }

    last_err = None
    for path in QUERY_PATHS:
        url = cfg["base_url"] + path
        try:
            result = _post(url, cfg["api_key"], cfg.get("workspace_id", ""), body)
            # 成功判断：code 为 200/0 或无 code
            code = result.get("code")
            if code not in (None, 200, 0, "200"):
                last_err = result.get("message") or result.get("errorMessage") or str(result)
                if code == 404:
                    continue  # 尝试下一个 path
                raise RuntimeError(f"查询失败 (code={code})：{last_err}")

            # 解析 series → list[dict]
            content = result.get("content") or result.get("data") or []
            if not isinstance(content, list) or not content:
                return []
            item = content[0]
            if isinstance(item, dict):
                series_list = item.get("series") or item.get("data", {}).get("series") or []
            else:
                series_list = []

            rows = []
            for s in series_list:
                cols = s.get("columns", [])
                for vals in s.get("values", []):
                    rows.append(dict(zip(cols, vals)))
            return rows

        except RuntimeError:
            raise
        except Exception as e:
            last_err = str(e)
            continue

    raise RuntimeError(
        f"所有 DQL 端点均失败，最后错误：{last_err}\n"
        "请检查 base_url 和网络连接。"
    )


# ── 日志分析 ──────────────────────────────────────────────────────────────────

def _parse_message(raw: str) -> dict:
    """从 message 字段提取结构化信息。
    支持两种格式：
      1. JSON 对象：{"name": ..., "requestUri": "POST /api/...", "status_code": 500}
      2. 纯文本（含 JSON 片段的混合行）
    """
    raw = (raw or "").strip()

    # 尝试直接 JSON 解析
    if raw.startswith("{"):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass

    # 尝试从文本中提取 JSON 片段
    m = re.search(r'\{.*\}', raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass

    return {"_raw": raw}


def _normalize_url(request_uri: str) -> str:
    """'POST http://ad.hesung.com/api/v1/foo?bar=1' → 'POST /api/v1/foo'"""
    if not request_uri:
        return ""
    # 分离 method 和 url
    parts = request_uri.strip().split(" ", 1)
    method = parts[0] if len(parts) == 2 else ""
    url = parts[1] if len(parts) == 2 else parts[0]

    # 去掉域名，保留路径
    m = re.search(r'https?://[^/]+(/.+?)(?:\?|$)', url)
    path = m.group(1) if m else url.split("?")[0]

    # 将 UUID/数字 ID 归一化
    path = re.sub(r'/[0-9a-f]{8}-[0-9a-f-]{27}', '/:uuid', path)
    path = re.sub(r'/\d+', '/:id', path)

    return f"{method} {path}".strip()


def _cluster_message(msg: str) -> str:
    """将错误信息归一化以便聚类（去掉变量部分）。"""
    # 去掉 UUID、IP、数字
    msg = re.sub(r'[0-9a-f]{8}-[0-9a-f-]{27}', 'UUID', msg)
    msg = re.sub(r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}', 'IP', msg)
    msg = re.sub(r'\b\d{4,}\b', 'N', msg)
    return msg[:200].strip()


def query_errors(start: str, end: str, limit: int = 500) -> dict:
    cfg = _get_cfg()
    start_ms = parse_time(start)
    end_ms = parse_time(end)

    q = f"L::re('{LOG_SOURCE}')[status IN ['error','warning','critical']] LIMIT {limit}"
    rows = _dql(cfg, q, start_ms, end_ms, limit)

    # ── 三维聚合 ──────────────────────────────────────────────────────────────
    by_status_code: dict[str, int] = {}   # HTTP status_code
    by_path: dict[str, int] = {}          # 接口路径
    by_message: dict[str, int] = {}       # 错误信息聚类

    samples = []  # 保留前 5 条原始样本

    for row in rows:
        msg_raw = row.get("message") or row.get("msg") or ""
        parsed = _parse_message(msg_raw)

        # 接口路径
        req_uri = parsed.get("requestUri") or parsed.get("requestUrl") or ""
        path = _normalize_url(req_uri)
        if path:
            by_path[path] = by_path.get(path, 0) + 1

        # HTTP 状态码
        code = str(parsed.get("status_code") or parsed.get("statusCode") or "")
        if code and code != "200":
            by_status_code[code] = by_status_code.get(code, 0) + 1

        # 错误信息聚类
        err_text = (
            parsed.get("error") or parsed.get("detail") or
            parsed.get("_raw") or
            (msg_raw if not msg_raw.startswith("{") else "")
        )
        if err_text:
            key = _cluster_message(err_text)
            by_message[key] = by_message.get(key, 0) + 1

        # 原始样本
        if len(samples) < 5:
            samples.append({
                "time": fmt_ts(row["time"]) if "time" in row else "",
                "status": row.get("status", ""),
                "module": row.get("module", ""),
                "message_preview": msg_raw[:300],
            })

    return {
        "time_range": {"start": fmt_ts(start_ms), "end": fmt_ts(end_ms)},
        "source": LOG_SOURCE,
        "total_errors": len(rows),
        "by_status_code": [
            {"code": k, "count": v}
            for k, v in sorted(by_status_code.items(), key=lambda x: -x[1])
        ],
        "by_path": [
            {"path": k, "count": v}
            for k, v in sorted(by_path.items(), key=lambda x: -x[1])[:15]
        ],
        "by_message": [
            {"message": k, "count": v}
            for k, v in sorted(by_message.items(), key=lambda x: -x[1])[:15]
        ],
        "samples": samples,
    }


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
            if len(args) < 3:
                raise RuntimeError("用法：save_config <api_key> <workspace_id>")
            out = save_config(args[1], args[2])
        elif cmd == "query_errors":
            if len(args) < 3:
                raise RuntimeError("用法：query_errors <start> <end> [--limit N]")
            limit = int(args[args.index("--limit") + 1]) if "--limit" in args else 500
            out = query_errors(args[1], args[2], limit)
        else:
            raise RuntimeError(f"未知命令：{cmd}")

        print(json.dumps(out, ensure_ascii=False, indent=2))

    except Exception as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
