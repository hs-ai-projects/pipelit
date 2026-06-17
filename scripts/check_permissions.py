#!/usr/bin/env python3
"""
检测 Claude Code 全局权限配置是否满足 pipelit 运行需求。

输出 JSON：
  {"bash_ok": bool, "hook_ok": bool}

bash_ok: ~/.claude/settings.json 有 git / python3 权限规则
hook_ok: 有 AskUserQuestion PreToolUse hook
"""

import sys
import json
import pathlib

settings_file = pathlib.Path.home() / ".claude" / "settings.json"

bash_ok = False
hook_ok = False

if settings_file.exists():
    try:
        settings = json.loads(settings_file.read_text(encoding="utf-8"))
        allow = settings.get("permissions", {}).get("allow", [])

        bash_patterns = ["Bash(git", "Bash(PYTHONIOENCODING=utf-8 python3", "Bash(python3"]
        bash_ok = any(
            any(rule.startswith(p) for p in bash_patterns)
            for rule in allow
        )

        all_hooks = []
        hooks = settings.get("hooks", {})
        for phase in ("PreToolUse", "PostToolUse"):
            all_hooks.extend(hooks.get(phase, []))
        hook_ok = any(h.get("matcher") == "AskUserQuestion" for h in all_hooks)

    except Exception:
        pass

print(json.dumps({"bash_ok": bash_ok, "hook_ok": hook_ok}))
