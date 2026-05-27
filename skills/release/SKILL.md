---
name: release
description: >
  版本发布全流程：precheck → dry-run 预览 → 一次确认 → 自动执行。
  当用户说"发版"、"打 tag"、"release"、"发布新版本"、"准备上线"时使用。
---

# Release — 一键发版

**整个流程只需确认一次。**

precheck + dry-run 自动收集所有信息 → 展示预览 → 用户确认版本号 → **Phase 3 全自动执行，不再弹出任何确认，包括 push**。

---

## Phase 0：读取发版配置（首次自动引导）

```bash
PYTHONIOENCODING=utf-8 python3 "${CLAUDE_PLUGIN_ROOT}/scripts/feishu_api.py" get_release_config
```

### 若 `configured: true`：读取 `release` 字段，进入 Phase 1。

### 若 `configured: false`：通过 AskUserQuestion 询问以下问题

**问题 1：仓库数量**
```
这个项目有几个仓库需要发版？
  ● 1 个（当前目录）
  ○ 2 个（前端 + 后端，分别填路径）
```

**问题 2：版本号文件**
```
版本号存在哪里？
  ● package.json（前端/Node.js）
  ○ pyproject.toml（Python）
  ○ 两个都有
```

**问题 3：Changelog 受众**
```
发版后是否生成 changelog？面向谁？
  ● 是，面向业务/运营同事（默认）
  ○ 是，面向技术团队
  ○ 否，不生成
```

**问题 4：飞书 Wiki 链接（可选）**
```
是否有飞书 Wiki 页面用于存放版本说明？（用于更新概述末尾附链接）
  ○ 有，我来输入链接
  ● 暂无，跳过
```

选"有，我来输入链接"时追加输入框让用户填写完整 URL。

**问题 5：飞书群通知（可选）**
```
发版后是否自动发送更新概述到飞书群？
  ○ 是，我来输入群 chat_id（oc_xxx 开头）
  ● 暂不需要
```

选"是"时追加输入框让用户填写群 chat_id（以 `oc_` 开头）。

根据回答组装 JSON 并保存：

```bash
PYTHONIOENCODING=utf-8 python3 "${CLAUDE_PLUGIN_ROOT}/scripts/feishu_api.py" save_release_config '<release_json>'
```

### 配置文件格式

统一存储在 `~/.claude/pipelit/config.json` 的 `release` 字段中（跨工作目录共享）：

```json
{
  "app_id": "...",
  "app_secret": "...",
  "frontend_path": "...",
  "backend_path": "...",
  "release": {
    "projectName": "my-project",
    "versionStrategy": "unified",
    "defaultMode": "safe",
    "repos": [
      {
        "label": "frontend",
        "path": ".",
        "releaseBranch": "master",
        "remote": "origin",
        "versionFile": "package.json",
        "versionUpdater": "npm",
        "precheck": []
      },
      {
        "label": "backend",
        "path": "../my-api",
        "releaseBranch": "master",
        "remote": "origin",
        "versionFile": "pyproject.toml",
        "versionUpdater": "poetry",
        "precheck": []
      }
    ],
    "changelog": {
      "enabled": true,
      "outputDir": "changelog-workspace",
      "audience": "business"
    },
    "feishuWikiUrl": "https://hesung2020.feishu.cn/wiki/xxx",
    "chatId": "oc_xxx"
  }
}
```

**`feishuWikiUrl`**（可选）：填写后，更新概述末尾自动附上该链接。留空或不填则省略。

**`chatId`**（可选）：飞书群 ID（`oc_` 开头）。填写后，发版完成时可一键发送更新概述卡片到该群。

---

## Phase 1：Precheck（全自动，无需干预）

对 config 中**每个仓库**依次执行，**任意一条失败则阻断**，统一展示所有问题后让用户处理。

### 1.1 同步远端 + 检查分支/工作区/同步状态

将以下命令**合并为一次 bash 调用**以减少确认次数：

> **⚠️ 必须用 `git -C "<path>"` 形式，禁止用 `cd "<path>" && git`，否则会触发额外的权限提示。**

```bash
git -C "<repo_path>" fetch origin --tags --prune && \
git -C "<repo_path>" branch --show-current && \
git -C "<repo_path>" status --porcelain && \
git -C "<repo_path>" rev-list --left-right --count origin/<releaseBranch>...HEAD
```

检查项（全部通过才能继续）：
- 当前分支必须等于 `releaseBranch`
- 工作区必须干净（`status --porcelain` 无输出）
- `behind > 0` → 阻断，提示 `git pull`
- `ahead > 0` → 阻断，有未推送的本地 commit
- 分叉（`behind > 0 && ahead > 0`）→ 阻断，需人工处理

### 1.2 检查版本号文件

```bash
ls "<repo_path>/<versionFile>"
```

### 1.3 收集变更信息 + 检测 tag 格式

```bash
git -C "<repo_path>" tag --sort=-creatordate | head -5
```

**Tag 格式检测（关键）：**

读取最新 tag 后检查是否以 `v` 开头：
- 最新 tag = `v1.2.3` → `TAG_PREFIX="v"`
- 最新 tag = `1.2.3` → `TAG_PREFIX=""`（无前缀）
- 无 tag → `TAG_PREFIX="v"`（默认，首次发版用 `v1.0.0`）

后续所有 tag 名称、manifest range 均使用检测到的格式，**不强制添加或删除 `v`**。

```bash
git -C "<repo_path>" log <last_tag>..HEAD --oneline --no-merges
git -C "<repo_path>" log <last_tag>..HEAD --oneline --merges
```

**Merge commit 处理规则（关键，防止内容错乱）：**

当存在 merge commit（如 `Merge branch 'feature/xxx' into 'master'`）时：
- **直接取 merge commit 的分支名作为一条 changelog 条目**，不展开该分支内的所有子 commit
- 分支内部的 `fix:` / `bugfix` commit 视为该 feature 的组成部分，**不单独列为独立修复条目**
- 只有直接提交到 releaseBranch 上的 `fix:` commit（非 feature 分支内的）才单独列为修复

例：
```
Merge branch 'feature/walmart-ads-module' → 归为一条「新功能：沃尔玛广告模块」
  └─ fix: eslint错误          ← 分支内，忽略
  └─ fix: 沃尔玛报表数据补全  ← 分支内，忽略
fix: 今日时间逻辑             ← 直接在 master，单独列出
```

**版本号建议（优先级从高到低）：**

1. commit message 或 body 含 `BREAKING CHANGE` → **major**（主版本 +1，次版本和修订号归零）
2. 任意 commit 含 `feat:` → **minor**（次版本 +1，修订号归零）
3. 仅含 `fix:` / `perf:` / `chore:` → **patch**（修订号 +1）
4. 无 conventional commit 格式 → **patch**（默认）

多仓库取所有仓库 commit 中最高优先级。`versionStrategy: unified` 时前后端打同一版本号。

新版本号 = `TAG_PREFIX` + 递增后的 `X.Y.Z`（如 `v1.3.0` 或 `1.3.0`）。

### 1.4 检查远端 tag 是否已存在

```bash
git -C "<repo_path>" ls-remote --tags origin "<proposed_tag>"
```

有输出则阻断：`❌ [frontend] 远端已存在 tag <tag>，请确认版本号是否正确`

### 1.5 运行 precheck 命令

对每个 `repos[].precheck` 命令依次执行（若列表为空则跳过）：

```bash
cd "<repo_path>" && <precheck_command>
```

失败时通过 AskUserQuestion 询问是否强制继续（默认否）。

---

## Phase 2：预览确认（唯一的人工交互）

展示完整预览，**通过 AskUserQuestion 等待用户确认版本号**：

```
━━━ 发版预览 ━━━━━━━━━━━━━━━━━━━━━━━━━━━

Precheck: ✅ 全部通过

仓库: frontend (.)       当前: <tag>
仓库: backend (../ads)   当前: <tag>

建议版本: <new_tag>（含新功能，minor 递增）

变更内容（N commits）:
  [frontend] 12 commits
    feat: 新增广告创意多选
    feat: SBV 视频广告支持
    fix: 修复数据统计错误
  [backend] 8 commits
    feat: 新增创意批量接口
    fix: 修复报表查询超时

将执行（确认后全自动，不再打断）:
  ✓ 更新版本号文件
  ✓ git commit + tag
  ✓ git push（前端 + 后端，无需再次确认）
  ✓ 生成 changelog（HTML + Markdown）
  ✓ 生成版本更新概述

[版本号] <new_tag>   ← 直接回车确认，或输入自定义版本号
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## Phase 3：自动执行

> **⚠️ 重要：Phase 2 用户确认即视为对整个 Phase 3 的一次性授权。**
> **所有 bash 命令直接执行，不再询问用户确认，包括 git push。**
> **将多步 git 命令合并为单次 bash 调用，减少权限提示次数。**

### 3.1 更新版本号文件

- `package.json`：更新 `"version"` 字段（不带前缀，只写 `X.Y.Z`）
- `pyproject.toml`：更新 `version = "..."` 字段

### 3.2 Commit + Tag

> **⚠️ 必须用 `git -C "<path>"` 形式，禁止用 `cd "<path>" && git`。**

```bash
git -C "<repo_path>" add <versionFile> && \
git -C "<repo_path>" commit -m "chore: release <new_tag>" && \
git -C "<repo_path>" tag -a <new_tag> -m "<从变更中提取的主题关键词>"
```

### 3.3 Push（已授权，直接执行，不再确认）

```bash
git -C "<repo_path>" push origin <releaseBranch> && git -C "<repo_path>" push origin <new_tag>
```

多仓库依次执行。

### 3.4 生成 release-manifest.json

push 成功后写入 `<changelog.outputDir>/release-manifest.json`：

```json
{
  "version": "<new_tag>",
  "date": "YYYY-MM-DD",
  "status": "success",
  "repos": [
    {
      "label": "frontend",
      "path": ".",
      "branch": "master",
      "prevTag": "<prev_tag>",
      "currentTag": "<new_tag>",
      "range": "<prev_tag>..<new_tag>",
      "commitCount": 12,
      "versionFile": "package.json"
    }
  ]
}
```

> **注意：`prevTag`、`currentTag`、`range` 全部使用实际 tag 名称（保持检测到的 `v` 格式），不强制添加或删除前缀。**

### 3.5 生成 Changelog（若 `changelog.enabled: true`）

**直接内联生成，无需用户再运行 `/changelog`。**

读取 manifest 中各仓库的 `range`，依次执行：

```bash
git -C "<repo_path>" log <range> --oneline --no-merges
git -C "<repo_path>" log <range> --oneline --merges
git -C "<repo_path>" diff <range> --stat
```

**过滤规则：**
- 排除 `chore: release` 格式的 commit
- 排除 `eslint`、`lint`、`revert`、`chore:`、`ci:`、`build:` 类 commit
- **feature 分支（merge commit）内部的所有 commit 一律忽略，只保留 merge commit 本身**
- 只有直接 commit 到 releaseBranch 的 `fix:` 才列为独立修复条目

**写作规则（`audience: "business"` 下）：**

- 每条：**标题行**（标签 + 加粗名称）+ **下一行**（描述，1 句话，勿加冒号）
- 标题 ≤ 10 字，描述 1 句话 ≤ 30 字，不解释技术细节
- 过滤：重构、改名、依赖升级、配置、lint、`chore:`、`ci:`、`build:` 类
- 无内容的分类整体省略

**HTML 模板（飞书兼容，必须按此结构输出）：**

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <title><new_tag>（YYYY-MM-DD）</title>
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'PingFang SC', 'Microsoft YaHei', sans-serif; max-width: 800px; margin: 40px auto; padding: 0 20px; color: #333; line-height: 1.8;">

  <h3 style="font-size: 24px; border-bottom: 2px solid #1677ff; padding-bottom: 8px;"><new_tag>（YYYY-MM-DD）</h3>

  <!-- 新功能示例 -->
  <p style="margin-top: 28px; margin-bottom: 4px;">
    <span style="background: #e6f7ff; color: #1677ff; padding: 2px 8px; border-radius: 4px; font-size: 12px;">新功能</span>
    <b> 功能名称</b>
  </p>
  <p style="color: #555; margin-top: 0;">描述，不超过 30 字。</p>
  <p style="color: #aaa; font-size: 13px; margin-top: 0;">[图片]</p>

  <!-- 修复示例（有飞书任务链接时追加 a 标签） -->
  <p style="margin-top: 20px; margin-bottom: 4px;">
    <span style="background: #fff2e8; color: #fa8c16; padding: 2px 8px; border-radius: 4px; font-size: 12px;">修复</span>
    <b> 修复内容</b>
    <a href="<feishu_task_url>" target="_blank" style="margin-left: 8px; background: #e6f7ff; color: #1677ff; padding: 2px 8px; border-radius: 4px; font-size: 12px; text-decoration: none; vertical-align: middle;">🔗 飞书任务</a>
  </p>
  <p style="color: #555; margin-top: 0;">描述。</p>

  <!-- 优化示例 -->
  <p style="margin-top: 20px; margin-bottom: 4px;">
    <span style="background: #f6ffed; color: #52c41a; padding: 2px 8px; border-radius: 4px; font-size: 12px;">优化</span>
    <b> 优化内容</b>
  </p>
  <p style="color: #555; margin-top: 0;">描述。</p>

</body>
</html>
```

**飞书兼容强制要求：**
1. 所有样式内联，禁用 `<style>` 块和 class
2. 用 `<p>` + `<b>`，不用 `<div>`
3. 标签用 `<span>`，样式内联
4. 描述段 `<p>` 设 `margin-top: 0` 避免多余空行
5. `[图片]` 占位只加在有界面变化的功能点，纯后端不加

保存到：
- `<outputDir>/changelog-<new_tag>.html`
- `<outputDir>/changelog-<new_tag>.md`

### 3.6 生成版本更新概述

从 3.5 生成的内容中提炼。**此部分在代码块外单独输出**，标题渲染为加粗文字。

格式：每条独立一行，emoji 区分类型，描述从用户视角写价值而非功能名。

**<new_tag> 版本更新概述（YYYY-MM-DD）**
✨ 描述新功能对用户的实际价值（原来要怎么做，现在怎么了）
⚡ 描述优化带来的体验改善
🔧 描述修复了什么问题
<feishuWikiUrl>（若 config 中配置了则附上，否则省略此行）

**写作指令：**
- 从 diff 和 commit 中找"用户原来要做什么操作 / 遇到什么问题"，而不是从 commit message 里抄功能名
- 每条 1 句话，≤ 20 字，口语化，让非技术同事秒懂
- ✨ 新功能：说清楚"能做什么了"或"不用再……了"
- ⚡ 优化：说清楚"更快/更稳/更少操作了"
- 🔧 修复：说清楚"之前……的问题修好了"
- 同类多条可合并为一行（用顿号），也可拆开（视内容重要程度）
- 过滤技术变更（重构、依赖升级等用户无感的不写）
- 无该类别则省略整行

---

## Phase 4：失败处理

### 状态定义

| 状态 | 含义 |
|------|------|
| `success` | 全部成功 |
| `failed` | 流程失败，无远端影响 |
| `partial_release` | 部分已推送，部分失败 |
| `cancelled` | 用户取消 |

### partial_release 示例

```
⚠️ partial_release

frontend ✅ 已推送 <new_tag>
backend  ❌ push 失败

建议手动执行（确认后可由 Claude 执行）:
  git -C "<backend_path>" push origin master
  git -C "<backend_path>" push origin <new_tag>
```

**默认不自动回滚**，仅输出命令。用户明确说"执行回滚"时才代为运行。

---

## 完成总结

先输出发版状态（代码块）：

```
✅ 发版完成！

版本: <new_tag>
日期: YYYY-MM-DD

仓库状态:
  frontend ✅  backend ✅

Changelog: <outputDir>/changelog-<new_tag>.html
（浏览器打开 → Ctrl+A → Ctrl+C → 飞书文档 Ctrl+V）
```

然后在代码块外，另起行输出版本更新概述（标题渲染为加粗，可直接复制到飞书群）：

---
**<new_tag> 版本更新概述（YYYY-MM-DD）**
新功能A、新功能B
优化A、优化B
问题A、问题B 已修复
<feishuWikiUrl>（若配置了则附上）
---

若 config 中 `feishuWikiUrl` 为空，完成总结输出后，用 AskUserQuestion 询问：

```
概述末尾是否附上飞书 Wiki 链接？
  ● 是，我来输入链接
  ○ 不需要
```

选"是"时：追加输入框让用户填写 URL，填写后通过 `save_release_config` 更新 `feishuWikiUrl` 字段，并补充输出含链接的完整概述。
选"不需要"时：继续下一步。

---

## 发送卡片到飞书群

在完成总结和 Wiki 链接处理之后触发。

### 判断 chatId

读取 config 中 `release.chatId`：

**若 chatId 不存在**，用 AskUserQuestion 询问：

```
是否将版本更新概述发送到飞书群？
  ● 是，我来输入群 chat_id（oc_xxx 开头）
  ○ 不发送
```

选"是"时：追加输入框让用户填写 chat_id，填写后通过 `save_release_config` 更新 `chatId` 字段。
选"不发送"时：流程结束。

**若 chatId 已存在**，用 AskUserQuestion 询问：

```
是否将版本更新概述发送到飞书群？
  ● 发送到已配置的群
  ○ 更换群（重新输入 chat_id）
  ○ 不发送
```

选"发送"时：使用已有 chatId。
选"更换群"时：追加输入框填写新 chat_id，更新 config。
选"不发送"时：流程结束。

### 构建并发送卡片

1. 将版本更新概述转为 lark_md 格式的卡片内容 content：

将完成总结中生成的版本更新概述（emoji + 描述列表）转为以下格式：

```
**✨ 新功能**
描述A
描述B

**⚡ 优化**
描述C

**🐛 修复**
描述E
```

> **注意：每条描述直接换行，不加 `•` 圆点前缀。无该类别则省略对应段落。**

2. 调用 `build_release_card` 构建卡片 JSON：

```bash
PYTHONIOENCODING=utf-8 python3 "${CLAUDE_PLUGIN_ROOT}/scripts/feishu_api.py" build_release_card '<params_json>'
```

params_json 格式：
```json
{
  "version": "<new_tag>",
  "date": "YYYY-MM-DD",
  "content": "<上述 lark_md 内容>",
  "doc_url": "<feishuWikiUrl 或空>"
}
```

3. 调用 `send_card` 发送：

```bash
PYTHONIOENCODING=utf-8 python3 "${CLAUDE_PLUGIN_ROOT}/scripts/feishu_api.py" send_card '<chat_id>' '<card_json>'
```

其中 `<card_json>` 为上一步 `build_release_card` 返回的完整 JSON。

4. 发送成功后输出：

```
✅ 版本更新概述已发送到飞书群
```

发送失败则输出错误信息，不阻断流程（发版本身已完成）。

---

## 注意事项

- 整个流程只有 Phase 2 需要用户交互，Phase 3 全自动，包括 push
- **所有 git 命令必须用 `git -C "<path>"` 形式，禁止用 `cd "<path>" && git`，否则触发额外权限提示**
- 将多个 git 命令合并为单次 bash 调用（用 `&&` 连接），减少权限提示次数
- partial_release 时不自动回滚，只输出恢复命令
- 所有配置统一存储在 `~/.claude/pipelit/config.json`（用户主目录，跨工作目录共享，凭据不进任何仓库）
- **send_card 调用：将 params_json 写入临时 Python 脚本文件再执行，避免 Windows shell 引号转义问题**
- **发送卡片时 receive_id_type 默认 `chat_id`，不要用 `user_id`（需要额外权限）**
