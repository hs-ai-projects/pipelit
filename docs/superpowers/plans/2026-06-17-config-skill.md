# /pipelit:config Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增 `/pipelit:config` skill，提供配置一览、定位和常用字段修改功能。

**Architecture:** `scripts/config_manager.py` 负责读取三层配置和 hooks，输出标准 JSON；`skills/config/SKILL.md` 消费该 JSON 格式化展示，并处理 `set` 意图。Python 脚本通过 `sys.path.insert` 引用同目录的 `feishu_api` 和 `guance_api`。

**Tech Stack:** Python 3.10+, pathlib, json; Claude Code Skill (Markdown)

---

## 文件变更清单

| 操作 | 文件 |
|------|------|
| Create | `scripts/config_manager.py` |
| Create | `skills/config/SKILL.md` |
| Modify | `tests/test_regression.py` |

---

### Task 1：`config_manager.py` — `overview` 命令

**Files:**
- Create: `scripts/config_manager.py`
- Modify: `tests/test_regression.py`

- [ ] **Step 1：写失败测试**

在 `tests/test_regression.py` 末尾 `sys.exit` 之前追加：

```python
# ─── 15. config_manager overview ─────────────────────────────────────────────
print("\n=== 15. config_manager overview（config-skill）===")
spec_cm = importlib.util.spec_from_file_location("cm", ROOT / "scripts/config_manager.py")
cm = importlib.util.module_from_spec(spec_cm); spec_cm.loader.exec_module(cm)

with tempfile.TemporaryDirectory() as tmpdir_cm:
    # 写 L2 config
    pipelit_dir = pathlib.Path(tmpdir_cm) / ".pipelit"
    pipelit_dir.mkdir()
    (pipelit_dir / "config.json").write_text(json.dumps({
        "app_id": "cli_test", "app_secret": "secret",
        "frontend_path": tmpdir_cm,
        "release": {"projectName": "test-proj", "chatId": "oc_test"}
    }), encoding="utf-8")
    result = cm.overview(cwd=tmpdir_cm)
    check("overview 返回 l2 字段", "l2" in result)
    check("overview l2 app_id ok", result["l2"].get("app_id", {}).get("status") == "ok")
    check("overview l2 app_secret masked", result["l2"].get("app_secret", {}).get("masked") is True)
    check("overview l2 frontend_path ok（目录存在）", result["l2"].get("frontend_path", {}).get("status") == "ok")
    check("overview release.projectName ok", result["l2"].get("release.projectName", {}).get("value") == "test-proj")
    check("overview 返回 token 字段", "token" in result)
    check("overview 返回 hooks 字段", "hooks" in result)

    # section 过滤
    r_feishu = cm.overview(cwd=tmpdir_cm, section="feishu")
    check("overview feishu section 不含 release", "release.chatId" not in r_feishu.get("l2", {}))
    check("overview feishu section 含 app_id", "app_id" in r_feishu.get("l2", {}))
```

- [ ] **Step 2：运行测试确认失败**

```bash
cd C:/Users/otsan.li/Desktop/work/skill/pipelit
PYTHONIOENCODING=utf-8 python3 tests/test_regression.py 2>&1 | grep -A3 "=== 15"
```

期望：`ModuleNotFoundError` 或 `FileNotFoundError`（config_manager.py 不存在）

- [ ] **Step 3：创建 `scripts/config_manager.py`**

```python
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

# 引入同目录脚本
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

    # Hooks (~/.claude/settings.json)
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
```

- [ ] **Step 4：在文件末尾加 CLI 入口（仅 overview）**

```python
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
```

- [ ] **Step 5：运行测试确认通过**

```bash
PYTHONIOENCODING=utf-8 python3 tests/test_regression.py 2>&1 | tail -5
```

期望：`=== 15` 9 条全 `[PASS]`，合计通过数增加。

- [ ] **Step 6：提交**

```bash
git add scripts/config_manager.py tests/test_regression.py
git commit -m "feat(config): config_manager.py overview command"
```

---

### Task 2：`config_manager.py` — `set` 命令

**Files:**
- Modify: `scripts/config_manager.py`
- Modify: `tests/test_regression.py`

- [ ] **Step 1：写失败测试**

在 `tests/test_regression.py` 末尾 `sys.exit` 之前追加：

```python
# ─── 16. config_manager set ──────────────────────────────────────────────────
print("\n=== 16. config_manager set（config-skill）===")

with tempfile.TemporaryDirectory() as tmpdir_set:
    _old_cwd_set = os.getcwd()
    try:
        os.chdir(tmpdir_set)

        # set release.chatId
        r = cm.set_field("release.chatId", "oc_new_chat")
        check("set release.chatId 返回 success", r.get("success") is True)
        l2 = cm.feishu_api._read_project_config(cwd=tmpdir_set)
        check("set release.chatId 写入 L2", l2.get("release", {}).get("chatId") == "oc_new_chat")

        # set bot.trigger_mode
        r2 = cm.set_field("bot.trigger_mode", "spawn")
        check("set bot.trigger_mode 返回 success", r2.get("success") is True)
        l2b = cm.feishu_api._read_project_config(cwd=tmpdir_set)
        check("set bot.trigger_mode 写入 L2", l2b.get("bot", {}).get("trigger_mode") == "spawn")

        # set frontend_path
        r3 = cm.set_field("frontend_path", tmpdir_set)
        check("set frontend_path 返回 success", r3.get("success") is True)

        # set 不支持字段返回 error
        r4 = cm.set_field("unknown.field", "val")
        check("set 不支持字段返回 error", r4.get("error") == "unsupported_field")

        # set app_secret 无 app_id 时返回 pair_required
        r5 = cm.set_field("app_secret", "new_secret")
        check("set app_secret 无 app_id 返回 pair_required", r5.get("error") == "pair_required")

    finally:
        os.chdir(_old_cwd_set)
```

- [ ] **Step 2：运行测试确认失败**

```bash
PYTHONIOENCODING=utf-8 python3 tests/test_regression.py 2>&1 | grep -A3 "=== 16"
```

期望：`AttributeError: module 'config_manager' has no attribute 'set_field'`

- [ ] **Step 3：在 `config_manager.py` 中实现 `set_field`**

在 `overview` 函数之后、`main()` 之前插入：

```python
# ── set ───────────────────────────────────────────────────────────────────────

SUPPORTED_FIELDS = frozenset({
    "user_id",
    "app_id", "app_secret",
    "frontend_path", "backend_path",
    "release.chatId", "release.feishuWikiUrl", "release.projectName",
    "bot.notify_chat_id", "bot.trigger_mode",
    "guance.api_key", "guance.workspace_id",
})


def set_field(field: str, value: str, cwd: str | None = None) -> dict:
    if field not in SUPPORTED_FIELDS:
        return {
            "error": "unsupported_field",
            "field": field,
            "supported": sorted(SUPPORTED_FIELDS),
        }

    # user_id → L1
    if field == "user_id":
        cfg = feishu_api.read_config() or {}
        cfg["user_id"] = value
        feishu_api.USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        feishu_api._secure_write(feishu_api.CONFIG_FILE,
                                  json.dumps(cfg, indent=2, ensure_ascii=False))
        return {"success": True, "field": field, "value": value}

    # app_id / app_secret → 成对写 L2
    if field in ("app_id", "app_secret"):
        l2 = feishu_api._read_project_config(cwd=cwd)
        if field == "app_id":
            app_id, app_secret = value, l2.get("app_secret", "")
        else:
            app_id, app_secret = l2.get("app_id", ""), value
        if not app_id or not app_secret:
            missing = "app_id" if not app_id else "app_secret"
            return {"error": "pair_required",
                    "message": f"app_id 和 app_secret 必须同时存在，当前缺少 {missing}，请先配置另一个字段"}
        return feishu_api.save_config(app_id, app_secret)

    # frontend_path / backend_path → L2
    if field == "frontend_path":
        return feishu_api.save_project_config(frontend_path=value)
    if field == "backend_path":
        return feishu_api.save_project_config(backend_path=value)

    # release.* → L2
    if field.startswith("release."):
        key = field[len("release."):]
        l2 = feishu_api._read_project_config(cwd=cwd)
        release = l2.get("release") or {}
        release[key] = value
        l2["release"] = release
        feishu_api._write_project_config(l2, cwd=cwd)
        return {"success": True, "field": field, "value": value}

    # bot.* → L2
    if field.startswith("bot."):
        key = field[len("bot."):]
        l2 = feishu_api._read_project_config(cwd=cwd)
        bot = l2.get("bot") or {}
        bot[key] = value
        l2["bot"] = bot
        feishu_api._write_project_config(l2, cwd=cwd)
        return {"success": True, "field": field, "value": value}

    # guance.api_key / guance.workspace_id → 成对写 L2
    if field in ("guance.api_key", "guance.workspace_id"):
        g_file = guance_api._guance_config_file(cwd=cwd)
        g_cfg: dict = {}
        if g_file.exists():
            try:
                g_cfg = json.loads(g_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        if field == "guance.api_key":
            api_key, ws_id = value, g_cfg.get("workspace_id", "")
        else:
            api_key, ws_id = g_cfg.get("api_key", ""), value
        if not api_key or not ws_id:
            missing = "guance.api_key" if not api_key else "guance.workspace_id"
            return {"error": "pair_required",
                    "message": f"guance.api_key 和 guance.workspace_id 必须同时存在，当前缺少 {missing}"}
        return guance_api.save_config(api_key, ws_id)

    return {"error": "unsupported_field", "field": field}
```

- [ ] **Step 4：在 `main()` 里加 set 分支**

将 `main()` 中的 `else` 替换为：

```python
    elif cmd == "set":
        if len(args) < 3:
            print(json.dumps({"error": "usage: set <field_path> <value>"}))
            sys.exit(1)
        field, value = args[1], args[2]
        result = set_field(field, value)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if result.get("error"):
            sys.exit(1)
    else:
        print(json.dumps({"error": f"unknown command: {cmd}"}))
        sys.exit(1)
```

- [ ] **Step 5：运行测试确认通过**

```bash
PYTHONIOENCODING=utf-8 python3 tests/test_regression.py 2>&1 | tail -5
```

期望：`=== 16` 7 条全 `[PASS]`。

- [ ] **Step 6：提交**

```bash
git add scripts/config_manager.py tests/test_regression.py
git commit -m "feat(config): config_manager.py set command"
```

---

### Task 3：`skills/config/SKILL.md`

**Files:**
- Create: `skills/config/SKILL.md`

注意：skill 文件不需要测试，只需创建并手动验证格式正确。

- [ ] **Step 1：创建 `skills/config/` 目录并写 `SKILL.md`**

```markdown
---
name: config
description: >
  Pipelit 配置总览与修改。触发词："/pipelit:config"、"查看配置"、"配置总览"、"config set"。
  展示 L1/L2/guance/hooks 全部配置值，支持修改常用字段。
---

# Pipelit Config — 配置总览

## 触发后立即执行：读取配置总览

```bash
PYTHONIOENCODING=utf-8 python3 "${CLAUDE_PLUGIN_ROOT}/scripts/config_manager.py" overview
```

将输出的 JSON 按以下格式展示给用户：

```
━━━ Pipelit 配置总览 ━━━━━━━━━━━━━━━━━

📁 L1  ~/.claude/pipelit/config.json
  user_id        <值>                  <状态>

📁 L2  .pipelit/config.json
  飞书
    app_id       <值>                  <状态>
    app_secret   ••••••                <状态>
    token        <有效至/已过期>        <状态>
  项目路径
    前端          <值>                 <状态>
    后端          <值>                 <状态>
  发版
    项目名        <值>                  <状态>
    飞书群        <值>                  <状态>
    Wiki          <值>                  <状态>
  Bot
    通知群        <值>                  <状态>
    触发模式      <值>                  <状态>

📁 L2  .pipelit/guance_config.json
    api_key      ••••••                <状态>
    workspace    <值>                  <状态>
    endpoint     <值>                  <状态>

📁 ~  ~/.claude/settings.json
  Hooks
    AskUserQuestion   <值>             <状态>
    ExitPlanMode      <值>             <状态>

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
修改：说"改 chatId 为 oc_xxx" 或 "set release.chatId oc_xxx"
```

状态规则：
- status = "ok" → ✅
- status = "missing" → ❌（未配置）
- status = "invalid" → ❌（路径不存在）
- status = "expired" → ⚠️（已过期）
- masked = true → 显示 ••••••

## 过滤展示

用户说"只看飞书"/"只看发版"/"只看观测云"/"只看 hooks" 时，执行对应命令：

```bash
# 飞书
PYTHONIOENCODING=utf-8 python3 "${CLAUDE_PLUGIN_ROOT}/scripts/config_manager.py" overview feishu

# 发版
PYTHONIOENCODING=utf-8 python3 "${CLAUDE_PLUGIN_ROOT}/scripts/config_manager.py" overview release

# 观测云
PYTHONIOENCODING=utf-8 python3 "${CLAUDE_PLUGIN_ROOT}/scripts/config_manager.py" overview guance

# Hooks
PYTHONIOENCODING=utf-8 python3 "${CLAUDE_PLUGIN_ROOT}/scripts/config_manager.py" overview hooks
```

## 修改字段

用户说"改 <字段> 为 <值>"或"set <field> <value>"时执行：

```bash
PYTHONIOENCODING=utf-8 python3 "${CLAUDE_PLUGIN_ROOT}/scripts/config_manager.py" set <field> <value>
```

支持的字段：
- `user_id`
- `app_id` / `app_secret`（需成对存在）
- `frontend_path` / `backend_path`
- `release.chatId` / `release.feishuWikiUrl` / `release.projectName`
- `bot.notify_chat_id` / `bot.trigger_mode`
- `guance.api_key` / `guance.workspace_id`（需成对存在）

修改后重新运行 overview 展示最新值。

若返回 `{"error": "pair_required", ...}`，提示用户两个字段需同时配置。
若返回 `{"error": "unsupported_field", ...}`，告知用户当前支持的字段列表。
```

- [ ] **Step 2：验证 SKILL.md 格式**

确认文件开头有 frontmatter（`---` 包裹的 name/description），且 bash 命令可直接在 skill 中执行。

- [ ] **Step 3：提交**

```bash
git add skills/config/SKILL.md
git commit -m "feat(config): add /pipelit:config skill"
```

---

### Task 4：全量回归 + 收尾

**Files:**
- 无新改动

- [ ] **Step 1：运行完整回归**

```bash
cd C:/Users/otsan.li/Desktop/work/skill/pipelit
PYTHONIOENCODING=utf-8 python3 tests/test_regression.py
```

期望：所有测试全部 `[PASS]`。

- [ ] **Step 2：手动冒烟测试 overview 命令**

```bash
cd C:/Users/otsan.li/Desktop/work/ads-web
PYTHONIOENCODING=utf-8 python3 "C:/Users/otsan.li/Desktop/work/skill/pipelit/scripts/config_manager.py" overview
```

确认输出 JSON 包含 l1/l2/guance/token/hooks 字段，l2.app_id status 为 ok。

- [ ] **Step 3：手动冒烟测试 set 命令**

```bash
cd C:/Users/otsan.li/Desktop/work/ads-web
PYTHONIOENCODING=utf-8 python3 "C:/Users/otsan.li/Desktop/work/skill/pipelit/scripts/config_manager.py" set release.projectName ads-test
```

确认输出 `{"success": true, ...}`，然后 overview 中 release.projectName 值变为 ads-test。

**还原：**

```bash
PYTHONIOENCODING=utf-8 python3 "C:/Users/otsan.li/Desktop/work/skill/pipelit/scripts/config_manager.py" set release.projectName ads
```

- [ ] **Step 4：提交收尾（若有修复）**

```bash
git add -A
git commit -m "fix(config): smoke test fixes"
```
