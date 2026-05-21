---
name: feishu-commit
description: >
  普通 commit，自动在 message 末尾注入飞书任务链接。
  触发方式：/feishu-commit <task_id_or_url>。
  当用户说"feishu-commit"、"带飞书链接提交"时使用。
---

# feishu-commit

提交当前改动，commit message 末尾自动追加飞书任务链接。

## Step 1：提取任务 ID

从用户输入提取任务 ID（纯 UUID 或飞书 URL 均可），构建链接：
```
https://applink.feishu.cn/client/todo/detail?guid=<task_id>
```

## Step 2：预览变更

提交前先展示将要提交的内容，让用户确认：

```bash
git status
git diff HEAD
git log --oneline -5
```

根据 diff 内容生成 commit message（type + 简短描述，匹配仓库现有风格）。

向用户展示：
```
将要提交：
  修改文件: src/pages/xxx.vue, src/api/urls.js
  
Commit message:
  feat: 新增广告创意多选功能

  Feishu-Task: https://applink.feishu.cn/client/todo/detail?guid=<task_id>
  Co-Authored-By: Claude <noreply@anthropic.com>

确认提交？
```

## Step 3：执行提交

用户确认后，只 add 改动的文件，绝不使用 `git add -A` 或 `git add .`，过滤 `.env`、`node_modules/`、`__pycache__/`、`*.log`。

```bash
git add <具体文件列表>
git commit -m "$(cat <<'EOF'
<type>: <根据实际 diff 写的简短描述>

Feishu-Task: https://applink.feishu.cn/client/todo/detail?guid=<task_id>
Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

提交完成后输出 commit hash，不自动 push。
