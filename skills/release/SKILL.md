---
name: release
description: >
  版本发布全流程：precheck → dry-run 预览 → 一次确认 → 自动执行。
  当用户说"发版"、"打 tag"、"release"、"发布新版本"、"准备上线"时使用。
---

# Release — 一键发版

**整个流程只需确认一次。**

precheck + dry-run 自动收集所有信息 → 展示预览 → 用户确认版本号 → 全自动执行。

---

## Phase 0：读取发版配置（首次自动引导）

检查 `.claude/release-config.json`：

```bash
cat .claude/release-config.json 2>/dev/null || echo "NOT_FOUND"
```

### 若已存在：直接读取，进入 Phase 1。

### 若不存在：通过 AskUserQuestion 询问 3 个问题，自动生成配置

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
  ○ 是，自定义描述
  ○ 否，不生成
```

选"自定义描述"时追加询问：读者是谁（如"电商运营人员"）。

映射规则：
- 选项 1 → `"enabled": true, "audience": "business"`
- 选项 2 → `"enabled": true, "audience": "technical"`
- 选项 3 → `"enabled": true, "audience": "<用户填写>"`
- 选项 4 → `"enabled": false`

根据回答生成并保存 `.claude/release-config.json`。

### 配置文件完整格式

```json
{
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
      "precheck": ["pnpm lint", "pnpm build"]
    },
    {
      "label": "backend",
      "path": "../my-api",
      "releaseBranch": "master",
      "remote": "origin",
      "versionFile": "pyproject.toml",
      "versionUpdater": "poetry",
      "precheck": ["pytest"]
    }
  ],
  "changelog": {
    "enabled": true,
    "outputDir": "changelog-workspace",
    "audience": "business"
  },
  "notify": {
    "enabled": false
  }
}
```

**字段说明：**

| 字段 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `projectName` | 否 | 目录名 | 项目名，用于 manifest 和通知 |
| `versionStrategy` | 否 | `"unified"` | `unified`：多仓库打同一 tag；`independent`：各自独立 |
| `defaultMode` | 否 | `"safe"` | `safe`：precheck 失败阻断；`force`：跳过 precheck |
| `repos[].label` | 是 | — | 仓库别名，用于日志和 manifest |
| `repos[].path` | 是 | — | 仓库本地路径（绝对或相对路径均可） |
| `repos[].releaseBranch` | 否 | `"master"` | 发版必须在此分支上 |
| `repos[].remote` | 否 | `"origin"` | 远端名称 |
| `repos[].versionFile` | 是 | — | `package.json` / `pyproject.toml` |
| `repos[].versionUpdater` | 否 | 自动检测 | `npm`/`pnpm`/`poetry`/`manual` |
| `repos[].precheck` | 否 | `[]` | 发版前必须通过的命令列表 |
| `changelog.enabled` | 否 | `true` | 是否生成 changelog |
| `changelog.outputDir` | 否 | `"changelog-workspace"` | changelog 输出目录 |
| `changelog.audience` | 否 | `"business"` | 读者画像：`business`（业务/运营）/ `technical`（技术团队）/ 任意字符串描述 |
| `notify.enabled` | 否 | `false` | 是否生成飞书群通知文案 |

> **安全提醒：** `.claude/release-config.json` 包含本地路径，必须加入 `.gitignore`，不要提交到 Git。

---

## Phase 1：Precheck（全自动，无需干预）

对 config 中**每个仓库**依次执行以下检查，**任意一条失败则阻断**，统一展示所有问题后让用户处理。

### 1.1 同步远端

```bash
git -C "<repo_path>" fetch origin --tags --prune
```

### 1.2 检查分支

```bash
git -C "<repo_path>" branch --show-current
```

必须等于 `releaseBranch`（默认 `master`），否则阻断：
```
❌ [frontend] 当前分支为 feature/xxx，发版必须在 master 分支
```

### 1.3 检查工作区

```bash
git -C "<repo_path>" status --porcelain
```

有未提交变更则阻断：
```
❌ [frontend] 工作区有未提交变更，请先 commit 或 stash
```

### 1.4 检查本地与远端同步状态

```bash
git -C "<repo_path>" rev-list --left-right --count origin/<releaseBranch>...HEAD
```

输出格式为 `<behind>\t<ahead>`：

| 情况 | 处理 |
|------|------|
| `behind > 0` | ❌ 阻断，提示 `git -C "<path>" pull` |
| `ahead > 0` | ❌ 默认阻断，提示本地有未推送的 commit |
| `behind > 0 && ahead > 0` | ❌ 阻断，分支已分叉，需人工处理 |
| `0\t0` | ✅ 通过 |

### 1.5 检查版本号文件是否存在

```bash
ls "<repo_path>/<versionFile>"
```

不存在则阻断：
```
❌ [backend] 未找到版本文件 pyproject.toml
```

### 1.6 检查远端是否已存在同名 tag（提前获取目标版本号后执行）

```bash
git -C "<repo_path>" ls-remote --tags origin v<version>
```

有输出则阻断：
```
❌ [frontend] 远端已存在 tag v1.3.0，请确认版本号是否正确
```

### 1.7 运行 precheck 命令

对每个 `repos[].precheck` 命令依次执行：

```bash
cd "<repo_path>" && <precheck_command>
```

失败时：
- `defaultMode: "safe"` → 阻断，展示失败输出
- 通过 AskUserQuestion 询问：
  ```
  precheck 失败：pnpm build
  
  是否强制继续？
    ○ 是，忽略 precheck 风险继续发版
    ● 否，先修复再重试
  ```

### 1.8 收集变更信息

```bash
# 获取最新 tag（按时间排序）
git -C "<repo_path>" describe --tags --abbrev=0 2>/dev/null || echo "NO_TAG"

# 获取自上次 tag 以来的 commits
git -C "<repo_path>" log <last_tag>..HEAD --oneline --no-merges
```

**版本号建议（基于所有仓库 commit 分析）：**
- 含 `feat:` → minor（次版本 +1）
- 全是 `fix:` / `perf:` → patch（修订号 +1）
- 含 `BREAKING CHANGE` → major
- 多仓库取最高版本号为基准，`versionStrategy: unified` 时统一递增
- 首次发版（无 tag）→ 建议 `v1.0.0`

---

## Phase 2：预览确认（唯一的人工交互）

展示完整发版预览，等待用户确认版本号：

```
━━━ 发版预览 ━━━━━━━━━━━━━━━━━━━━━━━━━━━

Precheck: ✅ 全部通过

仓库: frontend (.)       当前: v1.2.3
仓库: backend (../ads)   当前: v1.2.3

建议版本: v1.3.0（含新功能，minor 递增）

变更内容（20 commits）:
  [frontend] 12 commits
    feat: 新增广告创意多选
    feat: SBV 视频广告支持
    fix: 修复数据统计错误
    ...
  [backend] 8 commits
    feat: 新增创意批量接口
    fix: 修复报表查询超时
    ...

将执行:
  ✓ 更新版本号文件
  ✓ git commit + tag v1.3.0
  ✓ git push（前端 + 后端）
  ✓ 生成 release-manifest.json
  ✓ 生成 changelog

[版本号] v1.3.0   ← 直接回车确认，或输入自定义版本号
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## Phase 3：自动执行（确认后全自动，不再中断）

### 3.1 更新版本号文件

对每个仓库更新版本号（不带 v 前缀）：
- `package.json`：更新 `"version"` 字段
- `pyproject.toml`：更新 `version = "..."` 字段

### 3.2 Commit + Tag

```bash
git -C "<repo_path>" add <versionFile>
git -C "<repo_path>" commit -m "chore: release v<version>"
git -C "<repo_path>" tag -a v<version> -m "<从变更中提取的主题>"
```

### 3.3 Push

```bash
git -C "<repo_path>" push origin <releaseBranch>
git -C "<repo_path>" push origin v<version>
```

### 3.4 生成 release-manifest.json

push 成功后，在 `changelog.outputDir` 目录下写入 `release-manifest.json`：

```json
{
  "version": "v1.3.0",
  "date": "2026-05-19",
  "status": "success",
  "repos": [
    {
      "label": "frontend",
      "path": ".",
      "branch": "master",
      "prevTag": "v1.2.3",
      "currentTag": "v1.3.0",
      "range": "v1.2.3..v1.3.0",
      "commitCount": 12,
      "versionFile": "package.json"
    },
    {
      "label": "backend",
      "path": "../ads",
      "branch": "master",
      "prevTag": "v1.2.3",
      "currentTag": "v1.3.0",
      "range": "v1.2.3..v1.3.0",
      "commitCount": 8,
      "versionFile": "pyproject.toml"
    }
  ]
}
```

changelog skill 读取此文件获取每个仓库的 commit range，无需自行推断 tag。

### 3.5 Changelog 提示（若 `changelog.enabled: true`）

manifest 已写入，在完成总结末尾追加：

> 📝 运行 `/changelog` 即可生成更新文档（manifest 已就绪，将自动读取）。

### 3.6 生成发布通知（若 `notify.enabled: true`）

从 changelog 提炼飞书群通知：

```
**v<version> 更新概述（YYYY-MM-DD）**
新功能A、新功能B
优化A、优化B
问题A 已修复
```

---

## Phase 4：失败处理

### 状态定义

| 状态 | 含义 |
|------|------|
| `success` | 全部成功 |
| `failed` | 流程失败，未产生任何远端影响 |
| `partial_release` | 部分仓库或部分动作已推送，部分失败 |
| `cancelled` | 用户中途取消 |

### 失败场景与处理

**更新版本文件失败：**
```
❌ 更新 package.json 失败
状态: failed（本地无变更，可安全重试）
```

**precheck 失败：**
```
❌ pnpm build 失败（退出码 1）
状态: failed
选择：修复后重试 / 强制继续（风险自担）
```

**前端 push 成功，后端 push 失败（partial_release）：**
```
⚠️ partial_release

frontend ✅ 已推送 v1.3.0
backend  ❌ push 失败

本地状态:
  frontend commit: ✅ 已创建  tag: ✅ 已创建  远端: ✅ 已推送
  backend  commit: ✅ 已创建  tag: ✅ 已创建  远端: ❌ 未推送

建议手动执行（确认后可由 Claude 执行）:
  git -C "<backend_path>" push origin master
  git -C "<backend_path>" push origin v1.3.0

如需回滚 frontend（谨慎）:
  git -C "<frontend_path>" push origin :refs/tags/v1.3.0
  git -C "<frontend_path>" reset --soft HEAD~1
  git -C "<frontend_path>" push origin master --force-with-lease
```

**commit push 成功，tag push 失败：**
```
⚠️ partial_release

commit ✅ 已推送
tag    ❌ push 失败

手动补推:
  git -C "<repo_path>" push origin v1.3.0
```

**其他场景回滚命令（用户明确确认后才执行）：**

```bash
# 删除本地 tag
git -C "<repo_path>" tag -d v<version>

# 删除远端 tag
git -C "<repo_path>" push origin :refs/tags/v<version>

# 撤销本地 release commit
git -C "<repo_path>" reset --soft HEAD~1

# 恢复版本文件
git -C "<repo_path>" checkout -- package.json
git -C "<repo_path>" checkout -- pyproject.toml
```

**默认不自动执行回滚**，仅输出命令。用户明确说"执行回滚"时才代为运行。

---

## 完成总结

```
✅ 发版完成！

版本: v<version>
日期: YYYY-MM-DD

仓库状态:
  frontend ✅  backend ✅

Manifest: changelog-workspace/release-manifest.json

📝 运行 `/changelog` 即可生成更新文档（manifest 已就绪）

发布通知:
────────────────────
<通知文本>（若已生成）
────────────────────
```

---

## 注意事项

- 整个流程只有 Phase 2 需要用户交互，其他全自动
- partial_release 时不自动回滚，只输出恢复命令
- `.claude/release-config.json` 含本地路径，必须加入 `.gitignore`
