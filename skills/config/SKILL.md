---
name: config
description: >
  Pipelit 配置总览与修改。触发词："/pipelit:config"、"查看配置"、"配置总览"、"config set"。
  展示 L1/L2/guance/hooks 全部配置值，支持修改常用字段。
---

# Pipelit Config — 配置总览

## 触发后立即执行：读取配置总览

执行以下命令获取配置数据：

```bash
PYTHONIOENCODING=utf-8 python3 "${CLAUDE_PLUGIN_ROOT}/scripts/config_manager.py" overview
```

将输出的 JSON 格式化展示给用户，格式如下：

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
- `app_id` / `app_secret`（需成对存在，缺一个会提示错误）
- `frontend_path` / `backend_path`
- `release.chatId` / `release.feishuWikiUrl` / `release.projectName`
- `bot.notify_chat_id` / `bot.trigger_mode`
- `guance.api_key` / `guance.workspace_id`（需成对存在）

修改成功后，重新运行 overview 展示最新值，让用户确认修改生效。

错误处理：
- 返回 `{"error": "pair_required", ...}` → 提示用户两个字段需同时配置，给出具体操作步骤
- 返回 `{"error": "unsupported_field", ...}` → 告知用户当前支持的字段列表
