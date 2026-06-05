#!/usr/bin/env python3
"""
Guance log provider — 观测云实现，遵循 log-provider 接口契约。

委托给 guance_api.py 的 query_errors_silent，将旧 return_token 格式
转换为新的统一接口格式（status: ok/no_data/not_configured/error）。

Usage:
  python3 guance.py query_errors_silent --start ISO8601 --end ISO8601 [--interfaces path1,path2]
"""

import json
import sys
import os
import pathlib

# 允许从任意 CWD 导入 guance_api（通过 CLAUDE_PLUGIN_ROOT 或相对路径推算）
_provider_dir = pathlib.Path(__file__).parent
_scripts_dir = _provider_dir.parent
if str(_scripts_dir) not in sys.path:
    sys.path.insert(0, str(_scripts_dir))

import guance_api  # type: ignore


def query_errors_silent(start: str, end: str, interfaces: list[str] | None = None) -> dict:
    """调用观测云查询，将旧 return_token 格式翻译成新接口格式。"""
    raw = guance_api.query_errors_silent(start, end, interfaces)
    token = raw.get("return_token", "")

    if token == "summary_returned":
        # 把聚合结果转成精简摘要文本
        parts = []
        total = raw.get("total_count", 0)
        parts.append(f"时段 {start} ~ {end} 共 {total} 条日志")

        by_code = raw.get("by_status_code", [])
        if by_code:
            codes = ", ".join(f"{x['code']}({x['count']}次)" for x in by_code[:5])
            parts.append(f"状态码分布：{codes}")

        high_freq = raw.get("high_freq", [])
        if high_freq:
            paths = "; ".join(f"{x['path']} {x['count']}次" for x in high_freq[:5])
            parts.append(f"高频接口：{paths}")

        by_msg = raw.get("by_message", [])
        if by_msg:
            msgs = "; ".join(m["message"][:80] for m in by_msg[:3])
            parts.append(f"高频报错：{msgs}")

        summary = "\n".join(parts)
        return {"status": "ok", "summary": summary, "raw": raw}

    if token == "GUANCE_NOT_CONFIGURED":
        return {"status": "not_configured"}

    if token == "GUANCE_NO_DATA":
        return {"status": "no_data"}

    if token.startswith("GUANCE_TIME_INVALID"):
        return {"status": "error", "message": token}

    if token.startswith("GUANCE_ERROR"):
        return {"status": "error", "message": token}

    # 未知 token，视为错误
    return {"status": "error", "message": f"unknown return_token: {token}"}


def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] != "query_errors_silent":
        print(json.dumps({"status": "error", "message": f"unknown command: {args}"}))
        sys.exit(1)

    start = end = None
    interfaces = None
    i = 1
    while i < len(args):
        if args[i] == "--start" and i + 1 < len(args):
            start = args[i + 1]; i += 2
        elif args[i] == "--end" and i + 1 < len(args):
            end = args[i + 1]; i += 2
        elif args[i] == "--interfaces" and i + 1 < len(args):
            raw = args[i + 1]
            interfaces = [x.strip() for x in raw.split(",") if x.strip()]
            i += 2
        else:
            i += 1

    if not start or not end:
        print(json.dumps({"status": "error", "message": "--start and --end required"}))
        sys.exit(1)

    result = query_errors_silent(start, end, interfaces)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
