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
cat .claude/release-config.json 2>/dev/null || echo "NOT_FOUND"
```

读取 `repos` 仓库列表、`changelog.outputDir`、`changelog.audience`。

**受众解读（写作时始终以此视角审查每一条描述）：**
- `"business"` 或未配置 → 读者是业务/运营人员，用通俗语言，过滤所有技术细节
- `"technical"` → 读者是研发团队，可保留技术描述（涉及模块、接口名等）
- 其他字符串 → 直接以该字符串作为读者画像，按对应认知水平调整语言

不存在时：默认使用当前目录单仓库，输出到 `changelog-workspace/`，audience 默认 `business`。

### 0.2 确定 commit range（优先级顺序）

**优先：读取 release-manifest.json**

```bash
cat <changelog.outputDir>/release-manifest.json 2>/dev/null || echo "NOT_FOUND"
```

若存在，从 manifest 中读取每个仓库的 `range`（如 `v1.2.3..v1.3.0`），直接使用，不再推断 tag。

**Fallback：最近两个 tag**（仅在没有 manifest 时使用）

```bash
git -C "<repo_path>" tag --sort=-creatordate
```

- ≥ 2 个 tag → 范围 = 第二新 tag..最新 tag
- 1 个 tag → 范围 = 该 tag..HEAD
- 无 tag → 提示用户先打 tag，或手动指定范围

**用户手动指定**：覆盖以上所有逻辑。

---

## Step 1：分析变更

### 1.1 获取 commits

```bash
git -C "<repo_path>" log <range> --oneline --no-merges
```

**过滤 release commit：** 排除 `chore: release vX.Y.Z` 格式的提交，这类 commit 不代表业务变更。

### 1.2 分析文件变更

```bash
git -C "<repo_path>" diff <range> --stat
```

- `src/pages/` 新增或修改 → 新功能或改版
- `src/components/` 修改 → UI / 交互优化
- `src/api/` 变更 → 可能对应新功能
- Controller / Service 变更 → 后端业务逻辑变化

### 1.3 提取飞书任务链接

```bash
git -C "<repo_path>" log <range> --format="%H %s" --no-merges | while read hash msg; do
  feishu=$(git -C "<repo_path>" show $hash --format="%B" -s | grep "^Feishu-Task:" | head -1 | awk '{print $2}')
  echo "$hash|$msg|$feishu"
done
```

### 1.4 合并分析

- 前后端同一功能的改动 → 合并为 1 条描述
- 无可见效果的变更 → 过滤掉（见 Step 2 过滤规则）

---

## Step 2：写作规则

### 2.1 过滤规则

**不写（无感知变更）：**
- 代码重构、变量改名、路径修正
- 依赖升级、配置调整、内部文档
- 数据库表名修改、格式化、lint 修复
- `chore:`、`ci:`、`build:` 类提交

**写（有实际效果）：**
- 新功能、新入口、新页面 → 「新功能」标签
- 改进已有功能、优化体验 → 「优化」标签
- 修复用户可感知的问题 → 「修复」标签
- 有实际系统效果的技术变更（性能提升、安全加固）→ 从效果角度描述，「优化」标签

### 2.2 语言规范

每条 1 句话，读完知道「具体变了什么」。用业务语言，不用技术术语。

**Few-shot 示例：**

| 不要写 | 要写 |
|--------|------|
| 新增 Ad Group batch selector | 选定广告活动后，系统会自动勾选全部广告组，减少重复选择操作 |
| 重构 usePaginationQuery 的 queryKey 逻辑 | 广告列表翻页更稳定，减少切换筛选条件后数据错乱的情况 |
| 优化 API request debounce | 搜索输入时请求更平稳，减少重复加载和卡顿 |
| fix: SBV video ad state display bug | 视频广告状态显示异常已修复 |
| refactor campaign selector component | （不写，无用户感知） |
| upgrade axios to 1.7.0 | （不写，依赖升级） |
| 修复 usePaginationQuery queryKey 不更新 | 切换筛选条件后广告列表能正确刷新 |

### 2.3 分类标准

- `feat:` → 新页面/新入口 = **新功能**，改进已有功能 = **优化**
- `fix:` → **修复**
- `perf:` / 有实际系统效果的重构 → **优化**
- 无内容的分类 → 省略，不出现空分类

---

## Step 3：生成文档

根据 Step 0 解读的受众画像调整语言风格后生成文档。

### Markdown 格式

```markdown
## v<version>（YYYY-MM-DD）

### 新功能
- **功能名称**：用业务语言描述。[🔗 飞书任务](<url>)

### 优化
- **优化内容**：从效果角度描述（如"减少一层网络跳转，响应更快"）。

### 修复
- **修复内容**：描述修复了什么问题。[🔗 飞书任务](<url>)
```

### HTML 格式（飞书可粘贴）

所有样式内联，不使用 `<style>` 块，可直接 Ctrl+C 粘贴到飞书文档：

- 新功能标签：蓝色 `background:#e6f7ff; color:#1677ff`
- 优化标签：绿色 `background:#f6ffed; color:#52c41a`
- 修复标签：橙色 `background:#fff2e8; color:#fa8c16`
- 有飞书任务链接时，标题行末尾追加：
  ```html
  <a href="<url>" target="_blank" style="margin-left:8px;background:#e6f7ff;color:#1677ff;padding:2px 8px;border-radius:4px;font-size:12px;text-decoration:none;">🔗 飞书任务</a>
  ```
- 有界面变化的功能点保留 `[图片]` 占位，纯后端/无界面变化不放

---

## Step 4：输出文件

保存到 `changelog.outputDir`（默认 `changelog-workspace/`）：

```bash
mkdir -p <outputDir>
# Markdown: changelog-workspace/changelog-v<version>.md
# HTML:     changelog-workspace/changelog-v<version>.html
```

告知用户文件路径，询问描述是否准确、有无遗漏。

**飞书粘贴方法（HTML）：** 浏览器打开 HTML → Ctrl+A → Ctrl+C → 飞书文档 Ctrl+V
