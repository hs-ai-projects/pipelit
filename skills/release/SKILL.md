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

**问题 6：发版卡片人物形象（可选，推荐）**
```
是否初始化发版卡片的品牌卡通人物？
  ● 是，上传公司 icon 或填写人物/系统形象描述
  ○ 暂不需要，之后再配置
```

选"是"时：
- 若用户有公司 icon / 吉祥物 / 品牌图，要求提供本地图片路径，写入 `company_icon_path`
- 若没有图片，让用户描述希望的系统人物形象，写入 `mascot_description`
- 先保存 release 基础配置，再调用 `generate_release_mascot` 生成稳定人物参考图，并自动写回 `release.mascotImagePath`

根据回答组装 JSON 并保存：

```bash
PYTHONIOENCODING=utf-8 python3 "${CLAUDE_PLUGIN_ROOT}/scripts/feishu_api.py" save_release_config '<release_json>'
```

若问题 6 选择了初始化人物形象，保存基础配置后继续调用：

```bash
PYTHONIOENCODING=utf-8 python3 "${CLAUDE_PLUGIN_ROOT}/scripts/feishu_api.py" generate_release_mascot '@mascot-params.json'
```

`mascot-params.json` 示例：
```json
{
  "project_name": "<projectName>",
  "company_icon_path": "<公司 icon 本地路径，可省略>",
  "mascot_description": "<系统人物形象描述，可省略>",
  "save_to_config": true
}
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
    "chatId": "oc_xxx",
    "atRule": "first_follower",
    "excludeOpenIds": ["ou_xxx"],
    "mascotImagePath": "C:/Users/me/.claude/pipelit/release_images/my-project-mascot.png",
    "mascotDescription": "蓝色卫衣的 3D 卡通助手，代表稳定发布和自动化流水线",
    "companyIconPath": "C:/Users/me/brand/icon.png"
  }
}
```

**`feishuWikiUrl`**（可选）：填写后，更新概述末尾自动附上该链接。留空或不填则省略。

**`chatId`**（可选）：飞书群 ID（`oc_` 开头）。填写后，发版完成时可一键发送更新概述卡片到该群。

**`atRule`**（可选，默认 `first_follower`）：发版卡片每条 changelog 末尾 @ 谁的规则。可选值：`first_follower` / `first_assignee` / `first_member` / `none`。

**`excludeOpenIds`**（可选，默认 `[]`）：@ 黑名单 open_id 列表，比如自己、机器人账号、已离职成员等。

**`mascotImagePath`**（可选，推荐）：发版卡片人物参考图路径。初始化后由 `generate_release_mascot` 自动写入；后续每次发版都会用它保持人物长相一致。

**`mascotDescription`**（可选）：系统人物形象描述，用于首次生成 mascot 和后续生成 release 图片时补充品牌语境。

**`companyIconPath`**（可选）：公司 icon / 品牌图路径，用于首次生成 mascot 时提取品牌颜色和图形语言。

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

- 每条：**标题行**（标签 + 加粗名称 + 飞书任务链接）+ **下一行**（描述，1 句话，勿加冒号）
- 标题 ≤ 10 字，描述 1 句话 ≤ 30 字，不解释技术细节
- 过滤：重构、改名、依赖升级、配置、lint、`chore:`、`ci:`、`build:` 类
- 无内容的分类整体省略

**飞书任务链接（每条 changelog 默认带）：**

1. 为每条 changelog 识别对应的飞书任务 task_id（同卡片 sections 的来源规则）：
   - merge commit 分支名 `feat/feishu-XXXXXXXX` → 前 8 位即 task_id 前缀
   - 直接 commit：调用 `list_tasks` 按 changelog 描述跟任务 summary 做语义匹配
2. 用 `resolve_task_guid` CLI 把短前缀补全为完整 GUID：
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/feishu_api.py" resolve_task_guid <short_prefix>
   ```
3. 用完整 GUID 拼飞书任务 applink：`https://applink.feishu.cn/client/todo/detail?guid=<full_guid>`
4. 在 HTML 标题行末尾 / MD 描述后追加 a 标签或链接（见模板）
5. 找不到对应任务的条目：省略链接，不要写 `<feishu_task_url>` 占位符

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

  <!-- 默认：每条都附飞书任务链接（找不到对应任务时整段 a 标签省略，不留占位符） -->

  <!-- 新功能示例 -->
  <p style="margin-top: 28px; margin-bottom: 4px;">
    <span style="background: #e6f7ff; color: #1677ff; padding: 2px 8px; border-radius: 4px; font-size: 12px;">新功能</span>
    <b> 功能名称</b>
    <a href="https://applink.feishu.cn/client/todo/detail?guid=<full_guid>" target="_blank" style="margin-left: 8px; background: #e6f7ff; color: #1677ff; padding: 2px 8px; border-radius: 4px; font-size: 12px; text-decoration: none; vertical-align: middle;">🔗 飞书任务</a>
  </p>
  <p style="color: #555; margin-top: 0;">描述，不超过 30 字。</p>
  <p style="color: #aaa; font-size: 13px; margin-top: 0;">[图片]</p>

  <!-- 修复示例 -->
  <p style="margin-top: 20px; margin-bottom: 4px;">
    <span style="background: #fff2e8; color: #fa8c16; padding: 2px 8px; border-radius: 4px; font-size: 12px;">修复</span>
    <b> 修复内容</b>
    <a href="https://applink.feishu.cn/client/todo/detail?guid=<full_guid>" target="_blank" style="margin-left: 8px; background: #e6f7ff; color: #1677ff; padding: 2px 8px; border-radius: 4px; font-size: 12px; text-decoration: none; vertical-align: middle;">🔗 飞书任务</a>
  </p>
  <p style="color: #555; margin-top: 0;">描述。</p>

  <!-- 优化示例（无关联任务时不带链接） -->
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

### 构建并发送卡片（默认带 @ 关注人）

新版统一命令 `send_release_card_with_mentions` 一站式完成：组合 sections → 查每条对应任务的 @ open_id → 调用 OpenAI 随机生成发版图（或上传本地图片）→ 构建卡片 → 发送。

#### 1. 把版本更新概述结构化为 sections

把版本更新概述转成结构化 sections，**每条 entry 尽量关联一个飞书任务 task_id**：

```json
{
  "sections": [
    {"title": "**✨ 新功能**",
     "entries": [
       {"text": "描述 A", "task_id": "<8位前缀或完整GUID>"},
       {"text": "描述 B"}
     ]},
    {"title": "**⚡ 优化**", "entries": [...]},
    {"title": "**🐛 修复**", "entries": [...]}
  ]
}
```

**关联 task_id 的来源（按优先级）**：

1. **merge commit 分支名** — `feat/feishu-XXXXXXXX` 中的 `XXXXXXXX` 就是 task_id 前 8 位（命令支持短前缀自动补全）
2. **文本匹配** — 对没有 merge commit 关联的直接 commit，调用 `list_tasks` 拉本次发版前后的飞书任务（todo + done 各 100 条），根据 changelog 描述跟任务 summary 做语义匹配
3. **没匹配到** — 省略 task_id 字段，该条不 @

写作规则同前：每条描述独立一行，不加 `•` 前缀，无该类别整段省略。

#### 2. 写入参数文件（避免 Windows shell 引号转义）

参数文件路径建议：`<repo_path>/changelog-workspace/notify-<version>.json`

内容：

```json
{
  "version": "<new_tag>",
  "date": "YYYY-MM-DD",
  "chat_id": "<chat_id>",
  "doc_url": "<feishuWikiUrl 或省略>",
  "generate_image": true,
  "image_prompt": "<想要的图片描述，可省略；省略时脚本按版本内容随机生成>",
  "reference_image_path": "<可省略；默认读取 release.mascotImagePath>",
  "image_path": "<本地图片路径，可省略；填写后优先用本地图，不调用 OpenAI>",
  "at_rule": "first_follower",
  "exclude_open_ids": [],
  "sections": [...上一步结构...]
}
```

图片规则：
- 默认传 `"generate_image": true`，由脚本调用 OpenAI Images API 生成一张 1:1 发版卡片图；脚本会继续调用飞书图片上传接口拿到 `image_key`，并把这个值写入卡片模板的 `img_key`
- 默认读取 `release.mascotImagePath` 作为参考图，保持初始化时生成的人物长相、服装轮廓、颜色和 logo 语言一致
- 如需临时更换参考图，传 `reference_image_path`；若未初始化 mascot，本仓库开发环境会回退使用项目根目录 `feilun.png`
- 若用户描述了想要的画面，把描述写入 `image_prompt`；若没有描述，可省略，脚本会结合版本号和更新内容随机生成提示词
- 每次生成都会随机挑选人物表情/动作，但要求保持同一个人物身份
- 若配置了 `image_path`，优先上传本地图片，不调用 OpenAI；上传成功后同样返回 `image_key` 并替换卡片 `img_key`
- 生成图片需要运行环境设置 `OPENAI_API_KEY`；可选环境变量：`OPENAI_IMAGE_MODEL`、`OPENAI_IMAGE_SIZE`、`OPENAI_IMAGE_QUALITY`

`at_rule` 可选值：
- `first_follower`（默认） — @ 任务关注人列表第一个
- `first_assignee` — @ 任务负责人
- `first_member` — @ members 第一个（不区分 role）
- `none` — 不 @

`exclude_open_ids` 是黑名单（如自己、机器人账号等）。若 release config 里配置了 `release.atRule` / `release.excludeOpenIds`，可从那里读默认值。

#### 3. 调用一站式命令

```bash
PYTHONIOENCODING=utf-8 python3 "${CLAUDE_PLUGIN_ROOT}/scripts/feishu_api.py" send_release_card_with_mentions "@$params_file"
```

> **`@` 前缀** 表示从文件读取 JSON，避免命令行长字符串的引号转义问题。

返回值包含：`message_id`、`image_key`（飞书图片 ID，已写入卡片 `img_key`）、`generated_image.image_path`、`task_mentions`（task_id → open_id 映射）、`content_preview`（最终拼好的 lark_md，含 `<at id=...>` 标签）。

#### 4. 输出结果

发送成功后输出：

```
✅ 版本更新概述已发送到飞书群
任务 @ 关注人映射：
  <task_id 前 8 位> → <open_id>
  ...
```

若有 task_id 在 `task_mentions` 中为 `null`（任务没有符合规则的关注人，或全被 exclude），告知用户哪几条没 @ 上。

发送失败不阻断流程（发版本身已完成）。

---

### 简化模式（无 @，回退到旧流程）

若用户明确不需要 @ 关注人，或本次发版没有任何能关联的飞书任务，走旧两步流程：

1. 拼 lark_md 字符串 content（每条描述独立一行）
2. 调用 `build_release_card` 构建卡片，再调用 `send_card` 发送

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/feishu_api.py" build_release_card '@params.json'
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/feishu_api.py" send_card '<chat_id>' '<card_json>'
```

---

## 注意事项

- 整个流程只有 Phase 2 需要用户交互，Phase 3 全自动，包括 push
- **所有 git 命令必须用 `git -C "<path>"` 形式，禁止用 `cd "<path>" && git`，否则触发额外权限提示**
- 将多个 git 命令合并为单次 bash 调用（用 `&&` 连接），减少权限提示次数
- partial_release 时不自动回滚，只输出恢复命令
- 所有配置统一存储在 `~/.claude/pipelit/config.json`（用户主目录，跨工作目录共享，凭据不进任何仓库）
- **长 JSON 参数用 `@file` 语法**：`build_release_card` 和 `send_release_card_with_mentions` 支持 `'@/path/to/params.json'`，把参数写到文件里再传路径，避免 Windows shell 对中文/双引号的转义问题
- **发送卡片时 receive_id_type 默认 `chat_id`，不要用 `user_id`（需要额外权限）**
- **`send_release_card_with_mentions` 内部按 `at_rule` 自动查飞书任务关注人；调用 `pick_task_at_open_id` 时若传 8 位前缀，函数会自动调 list_tasks 补全完整 GUID**
