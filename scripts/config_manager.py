#!/usr/bin/env python3
"""
Pipelit 配置总览与修改工具。

Usage:
  python3 config_manager.py overview [feishu|release|guance|hooks]
  python3 config_manager.py set <field_path> <value>
"""

import sys
import json
import time
import pathlib
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import feishu_api
import guance_api


# ── helpers ───────────────────────────────────────────────────────────────────

def _f(value, status: str = "ok") -> dict:
    return {"value": value, "status": status}


def _masked(has_value: bool) -> dict:
    return {"masked": True, "status": "ok"} if has_value else {"value": None, "status": "missing"}


def _path_status(p: str | None) -> str:
    if not p:
        return "missing"
    return "ok" if pathlib.Path(p).exists() else "invalid"


def _sub(obj: dict, key: str) -> dict:
    val = obj.get(key)
    return _f(val, "ok" if val else "missing")


# ── overview ──────────────────────────────────────────────────────────────────

def overview(cwd: str | None = None, section: str | None = None) -> dict:
    result: dict = {}

    # L1
    l1_cfg = feishu_api.read_config() or {}
    result["l1"] = {
        "file": str(feishu_api.CONFIG_FILE),
        "user_id": _f(l1_cfg.get("user_id"), "ok" if l1_cfg.get("user_id") else "missing"),
    }

    # L2 main config
    l2_cfg = feishu_api._read_project_config(cwd=cwd)
    l2_file = feishu_api._project_config_file(cwd=cwd)
    release = l2_cfg.get("release") or {}
    bot = l2_cfg.get("bot") or {}
    frontend = l2_cfg.get("frontend_path")
    backend = l2_cfg.get("backend_path")

    result["l2"] = {
        "file": str(l2_file),
        "app_id": _f(l2_cfg.get("app_id"), "ok" if l2_cfg.get("app_id") else "missing"),
        "app_secret": _masked(bool(l2_cfg.get("app_secret"))),
        "frontend_path": {"value": frontend, "status": _path_status(frontend)},
        "backend_path": {"value": backend, "status": _path_status(backend)},
        "cardFeatures": _f(l2_cfg.get("cardFeatures"), "ok" if l2_cfg.get("cardFeatures") else "missing"),
        "release.projectName": _sub(release, "projectName"),
        "release.chatId": _sub(release, "chatId"),
        "release.feishuWikiUrl": _sub(release, "feishuWikiUrl"),
        "bot.notify_chat_id": _sub(bot, "notify_chat_id"),
        "bot.trigger_mode": _sub(bot, "trigger_mode"),
    }

    # Guance L2
    g_file = guance_api._guance_config_file(cwd=cwd)
    g_cfg: dict = {}
    if g_file.exists():
        try:
            g_cfg = json.loads(g_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    result["guance"] = {
        "file": str(g_file),
        "api_key": _masked(bool(g_cfg.get("api_key"))),
        "workspace_id": _sub(g_cfg, "workspace_id"),
        "base_url": _sub(g_cfg, "base_url"),
    }

    # Token
    token_file = feishu_api.TOKEN_CACHE_FILE
    if token_file.exists():
        try:
            cache = json.loads(token_file.read_text(encoding="utf-8"))
            expires_at = cache.get("expires_at", 0)
            if time.time() < expires_at:
                dt = datetime.fromtimestamp(expires_at, tz=timezone.utc).astimezone()
                result["token"] = {"status": "ok", "expires_at": dt.isoformat()}
            else:
                result["token"] = {"status": "expired", "expires_at": None}
        except Exception:
            result["token"] = {"status": "missing"}
    else:
        result["token"] = {"status": "missing"}

    # Hooks
    hooks_file = pathlib.Path.home() / ".claude" / "settings.json"
    hooks_result: dict = {"file": str(hooks_file)}
    if hooks_file.exists():
        try:
            settings = json.loads(hooks_file.read_text(encoding="utf-8"))
            all_hooks: list = []
            for phase in ("PreToolUse", "PostToolUse"):
                all_hooks.extend(settings.get("hooks", {}).get(phase, []))
            for matcher in ("AskUserQuestion", "ExitPlanMode"):
                entry = next((h for h in all_hooks if h.get("matcher") == matcher), None)
                if entry:
                    cmd = (entry.get("hooks") or [{}])[0].get("command", "")
                    script_name = pathlib.Path(cmd.split()[-1]).name if cmd else cmd
                    hooks_result[matcher] = {"value": script_name, "status": "ok"}
                else:
                    hooks_result[matcher] = {"value": None, "status": "missing"}
        except Exception:
            hooks_result["AskUserQuestion"] = {"value": None, "status": "missing"}
            hooks_result["ExitPlanMode"] = {"value": None, "status": "missing"}
    else:
        hooks_result["AskUserQuestion"] = {"value": None, "status": "missing"}
        hooks_result["ExitPlanMode"] = {"value": None, "status": "missing"}
    result["hooks"] = hooks_result

    # Section filter
    if section == "feishu":
        feishu_keys = {"file", "app_id", "app_secret"}
        return {
            "l1": result["l1"],
            "l2": {k: v for k, v in result["l2"].items() if k in feishu_keys},
            "token": result["token"],
        }
    if section == "release":
        release_keys = {"file", "frontend_path", "backend_path",
                        "release.projectName", "release.chatId", "release.feishuWikiUrl"}
        return {"l2": {k: v for k, v in result["l2"].items() if k in release_keys}}
    if section == "guance":
        return {"guance": result["guance"]}
    if section == "hooks":
        return {"hooks": result["hooks"]}

    return result


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    args = sys.argv[1:]
    if not args:
        print(json.dumps({"error": "usage: config_manager.py overview [section] | set <field> <value>"}))
        sys.exit(1)

    cmd = args[0]
    if cmd == "overview":
        section = args[1] if len(args) > 1 else None
        print(json.dumps(overview(section=section), ensure_ascii=False, indent=2))
    else:
        print(json.dumps({"error": f"unknown command: {cmd}"}))
        sys.exit(1)


if __name__ == "__main__":
    main()
