#!/usr/bin/env python3
"""
Log Provider Dispatcher — 读取配置的 logProvider 字段，转发到对应 provider。

Usage:
  python3 dispatch.py query_errors_silent --start ISO8601 --end ISO8601 [--interfaces path1,path2]
"""

import json
import sys
import os
import pathlib

_provider_dir = pathlib.Path(__file__).parent
_scripts_dir = _provider_dir.parent
USER_CONFIG_DIR = pathlib.Path.home() / ".claude" / "pipelit"
CONFIG_FILE = USER_CONFIG_DIR / "config.json"


def _read_config() -> dict:
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    return {}


def _resolve_provider(cfg: dict) -> str:
    """从合并配置中解析 logProvider，默认 guance（向后兼容）。"""
    return cfg.get("logProvider", "guance")


def _import_provider(name: str):
    """动态导入 provider 模块。"""
    import importlib.util
    provider_file = _provider_dir / f"{name}.py"
    if not provider_file.exists():
        raise RuntimeError(f"未找到 log provider '{name}'（{provider_file}），可用：guance、noop")
    spec = importlib.util.spec_from_file_location(f"log_providers.{name}", provider_file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] != "query_errors_silent":
        print(json.dumps({"status": "error", "message": f"unknown command: {args}"}))
        sys.exit(1)

    # 解析参数
    start = end = None
    interfaces = None
    # 也支持 --provider 覆盖（用于测试）
    provider_override = None

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
        elif args[i] == "--provider" and i + 1 < len(args):
            provider_override = args[i + 1]; i += 2
        else:
            i += 1

    if not start or not end:
        print(json.dumps({"status": "error", "message": "--start and --end required"}))
        sys.exit(1)

    cfg = _read_config()
    provider_name = provider_override or _resolve_provider(cfg)

    try:
        provider = _import_provider(provider_name)
    except RuntimeError as e:
        print(json.dumps({"status": "error", "message": str(e)}))
        sys.exit(1)

    result = provider.query_errors_silent(start, end, interfaces)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
