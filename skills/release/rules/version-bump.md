# 版本号判定规则

> 替代 SKILL.md Phase 1.3 的散文版本号建议。
> 每次判定必须输出 audit JSON，通过 `decision_log.py` 落盘。

---

## 主规则表

**按优先级自上而下匹配，命中即返回。**

| 优先级 | 条件 | 建议版本 | 规则名 |
|---|---|---|---|
| 1 | 任意 commit message/body 含 `BREAKING CHANGE` | major | rule-1-breaking-change |
| 2 | 静态扫描发现公共导出删除（见下方检测命令） | major | rule-2-deleted-export |
| 3 | 静态扫描发现 API 路径删除（见下方检测命令） | major | rule-3-deleted-api-route |
| 4 | 任意 commit 含 `feat:` 前缀 | minor | rule-4-feat |
| 5 | 仅含 `fix:` / `perf:` / `chore:` / 无规范格式 | patch | rule-5-fix-or-default |

多仓库取所有仓库 commit 中最高优先级。`versionStrategy: unified` 时前后端打同一版本号。

---

## 静态扫描（rule-2 / rule-3）

### 检测公共导出删除（TypeScript/JavaScript）

```bash
git -C "<repo_path>" diff <last_tag>..HEAD -- '*.ts' '*.tsx' '*.js' | grep '^-' | grep -E '^\-\s*export\s+(default\s+)?(function|class|const|let|var|type|interface|enum)\s+'
```

- 有输出 → 命中 rule-2，建议 major
- 无输出 → 跳过

### 检测 API 路径删除（Python FastAPI / Flask）

```bash
git -C "<repo_path>" diff <last_tag>..HEAD -- '*.py' | grep '^-' | grep -E '^\-\s*@(app|router)\.(get|post|put|patch|delete|head|options)\s*\('
```

- 有输出 → 命中 rule-3，建议 major
- 无输出 → 跳过

---

## 警告条件（不升级但强制展示 ⚠️）

即使主规则判定为 `patch` 或 `minor`，以下情况必须在 Phase 2 预览中强制显示警告，让用户选择是否升级：

| 警告 | 触发条件 | 警告文本 |
|---|---|---|
| warn-deleted-export | rule-5 命中但 rule-2 扫描发现有删除导出 | `⚠️ 检测到 <N> 处公共导出删除，但 commit 类型为 fix/patch。建议升级为 major，否则可能破坏调用方。` |
| warn-deleted-route | rule-5 命中但 rule-3 扫描发现有 API 路径删除 | `⚠️ 检测到 <N> 处 API 路径删除，建议升级为 major。` |
| warn-many-breaking | rule-4 命中（minor）但 rule-2/3 均有命中 | `⚠️ 检测到 breaking 变更，建议升级为 major。` |

警告出现时，Phase 2 预览中增加选项：
```
建议版本: v1.3.0 ⚠️（含潜在 breaking 变更）
  ● 保持 minor (v1.3.0)
  ○ 升级为 major (v2.0.0)
  ○ 手动输入版本号
```

---

## 输出格式

### 1. 必须输出一行 log

```
[1.3-version] 版本号建议：<major/minor/patch>，命中规则：<规则名>，警告=<有/无>，建议版本=<vX.Y.Z>
```

### 2. 必须写入 audit JSON

```json
{
  "decision_type": "version_bump",
  "rule": "rule-4-feat",
  "rule_priority": 4,
  "suggested_bump": "minor",
  "suggested_version": "v1.3.0",
  "warnings": [],
  "evidence": {
    "has_breaking_change": false,
    "deleted_exports": 0,
    "deleted_api_routes": 0,
    "has_feat_commit": true,
    "has_fix_only": false,
    "repos_scanned": ["frontend", "backend"]
  }
}
```

写入方式（落盘到 `decision_log.py` 的 `release` skill 日志）：

```bash
PYTHONIOENCODING=utf-8 python3 "${CLAUDE_PLUGIN_ROOT}/scripts/decision_log.py" phase <version> 1.3 @/tmp/phase-1.3-version-bump.json
```

---

## 阈值依据

| 规则 | 依据 |
|---|---|
| rule-2/3 静态扫描 | 历史上 2 次 minor 发版后用户报告"调用方挂了"，均因删了导出但没升 major |
| warn-deleted-export | 漏检代价高（破坏调用方）> 误检代价（用户手动降回 patch/minor） |
| rule-1 BREAKING CHANGE | Conventional Commits 标准；commit body 比 AI 判断更可靠 |
