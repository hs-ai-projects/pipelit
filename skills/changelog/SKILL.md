---
name: changelog
description: >
  从 git 历史自动生成版本更新文档。
  当用户说"changelog"、"更新日志"、"发版说明"、"生成 release notes"时触发。
  也适用于用户指定 commit 范围要求总结变更的场景。
---

# Changelog 生成器

根据 git 变更自动生成版本更新文档，优先从 `release-manifest.json` 读取 range。

**核心原则：用业务语言，让非技术同事也能看懂。**

---

## Step 0：读取配置和 range

### 0.1 读取发版配置

```bash
PYTHONIOENCODING=utf-8 python3 "${CLAUDE_PLUGIN_ROOT}/scripts/feishu_api.py" get_release_config
```

从返回的 `release` 字段中读取 `repos`、`changelog.outputDir`、`changelog.audience`、`feishuWikiUrl`。

**受众解读：**
- `"business"` 或未配置 → 读者是业务/运营人员，用通俗语言，过滤所有技术细节
- `"technical"` → 读者是研发团队，可保留技术描述
- 其他字符串 → 以该字符串作为读者画像

`configured: false` 时：默认使用当前目录单仓库，`outputDir` 默认 `changelog-workspace/`，`audience` 默认 `business`。

### 0.2 确定 commit range

**优先：读取 release-manifest.json**

```bash
cat <changelog.outputDir>/release-manifest.json 2>/dev/null || echo "NOT_FOUND"
```

存在则直接使用 manifest 中各仓库的 `range`，跳过 tag 推断。

**Fallback：最近两个 tag**（仅在没有 manifest 时使用）

```bash
git -C "<repo_path>" tag --sort=-creatordate | head -3
```

- ≥ 2 个 tag → 范围 = 第二新 tag..最新 tag
- 1 个 tag → 范围 = 该 tag..HEAD
- 无 tag → 提示用户先打 tag（推荐 `/release`），或手动指定范围

**用户手动指定**：覆盖以上所有逻辑。

---

## Step 1：分析变更

**将多条命令合并为单次 bash 调用：**

```bash
git -C "<repo_path>" log <range> --oneline --no-merges && \
git -C "<repo_path>" diff <range> --stat
```

**过滤 release commit：** 排除 `chore: release` 格式。

**飞书任务链接提取：**

```bash
git -C "<repo_path>" log <range> --format="%H %s" --no-merges | while read hash msg; do
  feishu=$(git -C "<repo_path>" show $hash --format="%B" -s | grep "^Feishu-Task:" | head -1 | awk '{print $2}')
  echo "$hash|$msg|$feishu"
done
```

**合并原则：**
- 前后端同一功能的改动 → 合并为 1 条
- 无可见效果的变更 → 过滤

---

## Step 2：写作规则

### 2.1 过滤规则

**不写（无感知变更）：**
- 代码重构、变量改名、路径修正、格式化、lint
- 依赖升级、配置调整、内部文档、数据库表名修改
- `chore:`、`ci:`、`build:` 类提交（`chore: release` 本身不写）

**写（有实际效果）：**
- 新功能、新入口、新页面 → 「新功能」标签
- 改进已有功能、优化体验 → 「优化」标签
- 修复用户可感知的问题 → 「修复」标签
- 有实际系统效果的技术变更（性能提升、安全加固）→ 「优化」，从效果角度描述

### 2.2 语言规范

- **标题**：≤ 10 字，是什么功能/问题，直接说清楚
- **描述**：1 句话，≤ 30 字，说清楚"具体变了什么/解决了什么"，不解释技术实现

**Few-shot 示例：**

| 不要写 | 要写 |
|--------|------|
| 新增 Ad Group batch selector | 广告组全选 |
| （描述）重构了 usePaginationQuery | （描述）切换筛选条件后列表能正确刷新 |
| 重构了 usePaginationQuery queryKey 逻辑 | （不写，无用户感知） |
| upgrade axios to 1.7.0 | （不写，依赖升级） |
| fix: SBV video ad state display bug | 视频广告状态显示 |
| （描述）修复状态显示逻辑 | （描述）视频广告状态显示异常已修复 |

### 2.3 分类标准

- `feat:` → 新页面/新入口 = **新功能**，改进已有功能 = **优化**
- `fix:` → **修复**
- `perf:` / 有实际系统效果的重构 → **优化**
- 无内容的分类 → 整体省略，不出现空分类

---

## Step 3：生成文档

根据受众画像调整语言风格后生成两种格式。

### Markdown 格式

```markdown
## <tag>（YYYY-MM-DD）

### 新功能
- **功能名称**
  用业务语言描述，1 句话。[🔗 飞书任务](<url>)

### 优化
- **优化内容**
  从效果角度描述。

### 修复
- **修复内容**
  描述修复了什么问题。[🔗 飞书任务](<url>)
```

> 标题与描述**分两行**，中间不加冒号。

### HTML 格式（飞书可粘贴）

**按以下模板严格输出，不改变标签结构和 style 属性：**

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <title><tag>（YYYY-MM-DD）</title>
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'PingFang SC', 'Microsoft YaHei', sans-serif; max-width: 800px; margin: 40px auto; padding: 0 20px; color: #333; line-height: 1.8;">

  <h3 style="font-size: 24px; border-bottom: 2px solid #1677ff; padding-bottom: 8px;"><tag>（YYYY-MM-DD）</h3>

  <!-- 新功能（有界面变化的功能加 [图片] 占位，纯后端不加） -->
  <p style="margin-top: 28px; margin-bottom: 4px;">
    <span style="background: #e6f7ff; color: #1677ff; padding: 2px 8px; border-radius: 4px; font-size: 12px;">新功能</span>
    <b> 功能名称</b>
  </p>
  <p style="color: #555; margin-top: 0;">描述，1 句话，不超过 30 字。</p>
  <p style="color: #aaa; font-size: 13px; margin-top: 0;">[图片]</p>

  <!-- 修复（有飞书任务链接时，在 b 标签后追加 a 标签） -->
  <p style="margin-top: 20px; margin-bottom: 4px;">
    <span style="background: #fff2e8; color: #fa8c16; padding: 2px 8px; border-radius: 4px; font-size: 12px;">修复</span>
    <b> 修复内容</b>
    <a href="<feishu_task_url>" target="_blank" style="margin-left: 8px; background: #e6f7ff; color: #1677ff; padding: 2px 8px; border-radius: 4px; font-size: 12px; text-decoration: none; vertical-align: middle;">🔗 飞书任务</a>
  </p>
  <p style="color: #555; margin-top: 0;">描述。</p>

  <!-- 优化 -->
  <p style="margin-top: 20px; margin-bottom: 4px;">
    <span style="background: #f6ffed; color: #52c41a; padding: 2px 8px; border-radius: 4px; font-size: 12px;">优化</span>
    <b> 优化内容</b>
  </p>
  <p style="color: #555; margin-top: 0;">描述。</p>

</body>
</html>
```

**飞书兼容强制要求（违反任意一条将导致粘贴失效）：**
1. **禁用** `<style>` 块和 class，所有样式必须内联
2. **用 `<p>` + `<b>`**，不用 `<div>`
3. 标题 `<p>` 和描述 `<p>` 分开，描述 `<p>` 设 `margin-top: 0`
4. 飞书任务链接（若有）放在同一个标题 `<p>` 内的 `<b>` 标签之后
5. 无飞书链接的条目不加链接 `<a>` 标签

---

## Step 4：输出文件

保存到 `<changelog.outputDir>`（默认 `changelog-workspace/`）：

```bash
mkdir -p <outputDir>
# Markdown: <outputDir>/changelog-<tag>.md
# HTML:     <outputDir>/changelog-<tag>.html
```

告知用户文件路径。

**飞书粘贴方法：** 浏览器打开 HTML → Ctrl+A → Ctrl+C → 飞书文档 Ctrl+V

---

## Step 5：生成版本更新概述

**在代码块外单独输出**，标题渲染为加粗文字，可直接复制到飞书群。

格式：每条独立一行，emoji 区分类型：

---
**<tag> 版本更新概述（YYYY-MM-DD）**
✨ 描述新功能对用户的实际价值
⚡ 描述优化带来的体验改善
🔧 描述修复了什么问题
<feishuWikiUrl>（若 config 中配置了则附上，否则省略此行）
---

**写作指令：**
- 从 diff 和 commit 中找"用户原来要做什么操作 / 遇到什么问题"，而不是从 commit message 里抄功能名
- 每条 1 句话，≤ 20 字，口语化，让非技术同事秒懂
- ✨ 新功能：说清楚"能做什么了"或"不用再……了"
- ⚡ 优化：说清楚"更快/更稳/更少操作了"
- 🔧 修复：说清楚"之前……的问题修好了"
- 同类多条可合并为一行（用顿号），也可拆开（视内容重要程度）
- 过滤技术变更（重构、依赖升级等用户无感的不写）
- 无该类别则省略整行

若 config 中 `feishuWikiUrl` 为空，输出概述后用 AskUserQuestion 询问：

```
概述末尾是否附上飞书 Wiki 链接？
  ● 是，我来输入链接
  ○ 不需要
```

选"是"时：追加输入框让用户填写 URL，填写后通过 `save_release_config` 更新 `feishuWikiUrl` 字段，并补充输出含链接的完整概述。
选"不需要"时：不再询问，流程结束。
