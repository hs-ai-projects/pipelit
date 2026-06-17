# /pipelit:config Skill 设计

**日期：** 2026-06-17  
**状态：** 待实现

---

## 背景

pipelit 配置分散在 3 个位置（L1 用户级、L2 项目级、hooks），用户记不住也找不到。`/pipelit:config` 提供统一的配置一览、定位和修改入口。

---

## 新增文件

| 文件 | 说明 |
|------|------|
| `skills/config/SKILL.md` | 新增 skill |
| `scripts/config_manager.py` | 新增 Python 后端 |

---

## Skill 触发

- `/pipelit:config` — 展示完整配置总览
- 在 skill 上下文中说"只看飞书"、"只看发版"、"改 chatId 为 oc_xxx"、`set release.chatId oc_xxx` — skill 内部判断意图并执行

---

## `config_manager.py` CLI 接口

内部工具，skill 调用，用户不直接使用。

```bash
# 总览（可选 section 过滤）
python3 config_manager.py overview [feishu|release|guance|hooks]

# 修改字段
python3 config_manager.py set <field_path> <value>
```

### `overview` 输出 JSON 结构

```json
{
  "l1": {
    "file": "~/.claude/pipelit/config.json",
    "user_id": {"value": "gbffe7d6", "status": "ok"}
  },
  "l2": {
    "file": ".pipelit/config.json",
    "app_id": {"value": "cli_xxxx", "status": "ok"},
    "app_secret": {"masked": true, "status": "ok"},
    "frontend_path": {"value": "C:/…/ads-web", "status": "ok"},
    "backend_path": {"value": "C:/…/ads", "status": "ok"},
    "cardFeatures": {"value": {"linkTask": true, "atFollower": true, "image": true}, "status": "ok"},
    "release.projectName": {"value": "ads", "status": "ok"},
    "release.chatId": {"value": "oc_cf9e…", "status": "ok"},
    "release.feishuWikiUrl": {"value": "https://…", "status": "ok"},
    "bot.notify_chat_id": {"value": "oc_fc8…", "status": "ok"},
    "bot.trigger_mode": {"value": "notify", "status": "ok"}
  },
  "guance": {
    "file": ".pipelit/guance_config.json",
    "api_key": {"masked": true, "status": "ok"},
    "workspace_id": {"value": "wksp_xxx", "status": "ok"},
    "base_url": {"value": "https://cn6-openapi.guance.com", "status": "ok"}
  },
  "token": {
    "status": "ok",
    "expires_at": "2026-06-17T18:00:00+08:00"
  },
  "hooks": {
    "file": "~/.claude/settings.json",
    "AskUserQuestion": {"value": "notify.ps1", "status": "ok"},
    "ExitPlanMode": {"value": "notify.ps1", "status": "ok"}
  }
}
```

**status 值：**
- `"ok"` — 已配置且有效
- `"missing"` — 字段不存在
- `"invalid"` — 路径字段对应目录不存在
- `"expired"` — token 已过期（仅 token 字段）

**脱敏规则：**
- `app_secret`、`guance.api_key`：不输出原值，`"masked": true`
- `app_id`、`release.chatId` 等：输出完整值（非敏感）

**token 状态检测：**
读 `~/.claude/pipelit/.token_cache.json`，比较 `expires_at` 与当前时间。

**hooks 读取：**
读 `~/.claude/settings.json`，取 `hooks.PreToolUse` 和 `hooks.PostToolUse` 中 matcher 为 `AskUserQuestion`、`ExitPlanMode` 的条目，提取 command 字段文件名。

**section 过滤：**

| section | 包含字段 |
|---------|---------|
| `feishu` | l1.user_id、l2.app_id、l2.app_secret、token |
| `release` | l2.frontend_path、l2.backend_path、l2.release.* |
| `guance` | guance.* |
| `hooks` | hooks.* |
| （无）| 全部 |

---

### `set` 支持字段

| 字段路径 | 写入目标 | 调用函数 |
|---------|---------|---------|
| `user_id` | L1 `config.json` | `feishu_api.save_user` 或直接写 |
| `app_id` | L2 `config.json` | `feishu_api.save_config` |
| `app_secret` | L2 `config.json` | `feishu_api.save_config`（需同时有 app_id）|
| `frontend_path` | L2 `config.json` | `feishu_api.save_project_config` |
| `backend_path` | L2 `config.json` | `feishu_api.save_project_config` |
| `release.chatId` | L2 `config.json` | 读 L2 release → 更新字段 → 写回 |
| `release.feishuWikiUrl` | L2 `config.json` | 同上 |
| `release.projectName` | L2 `config.json` | 同上 |
| `bot.notify_chat_id` | L2 `config.json` | 读 L2 bot → 更新字段 → 写回 |
| `bot.trigger_mode` | L2 `config.json` | 同上 |
| `guance.api_key` | L2 `guance_config.json` | `guance_api.save_config`（需同时有 workspace_id）|
| `guance.workspace_id` | L2 `guance_config.json` | 同上 |

不在上表中的字段：返回 `{"error": "unsupported_field", "field": "<name>"}` 并提示支持的字段列表。

`set app_id` / `set app_secret` / `set guance.api_key` / `set guance.workspace_id` 特殊处理：这些字段必须成对写入（`save_config` 需要 app_id+app_secret 同时存在）。`set` 命令先读现有 L2 配置取到配对字段，再一起写入。若配对字段缺失，返回错误提示用户两个字段一起配置（建议用 `save_config` 引导）。

---

## Skill 展示格式

```
━━━ Pipelit 配置总览 ━━━━━━━━━━━━━━━━━

📁 L1  ~/.claude/pipelit/config.json
  user_id        gbffe7d6              ✅

📁 L2  .pipelit/config.json  (ads-web)
  飞书
    app_id       cli_a92ce3…           ✅
    app_secret   ••••••                ✅
    token        有效至 06-17 18:00    ✅
  项目路径
    前端          C:/…/ads-web         ✅
    后端          C:/…/ads             ✅
  发版
    项目名        ads                   ✅
    飞书群        oc_cf9e4d…           ✅
    Wiki          https://hesung…      ✅
  Bot
    通知群        oc_fc835…            ✅
    触发模式      notify                ✅

📁 L2  .pipelit/guance_config.json
    api_key      ••••••                ✅
    workspace    wksp_xxx              ✅
    endpoint     cn6-openapi…          ✅

📁 ~  ~/.claude/settings.json
  Hooks
    AskUserQuestion   notify.ps1       ✅
    ExitPlanMode      notify.ps1       ✅

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
修改：说"改 chatId 为 oc_xxx" 或 "set release.chatId oc_xxx"
```

`❌` 标注：字段 status 为 missing/invalid/expired 时显示 ❌ 并附说明。

---

## 不在范围内

- hooks 的 `set`（结构复杂，展示即可，修改引导用户手动或 /using-pipelit）
- cardFeatures 的 `set`（当前不常改，总览展示即可）
- L3 `.pipelit.json` 内容（precheck 命令，总览不展示）

---

## 测试验证

- `overview` 在有 L2 配置的目录输出正确 JSON
- `overview` 在无 L2 配置的目录，所有 L2 字段 status 为 missing
- `set release.chatId oc_test` 写入 L2 并可读回
- `set guance.api_key xxx` 在无 workspace_id 时返回错误
- token 过期时 status 为 expired
- 路径字段目录不存在时 status 为 invalid
