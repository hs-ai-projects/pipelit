# Pipelit 配置三层化规范

> 目标：从"otsan 的专用工具"变成"任何项目 30 分钟上手"。

---

## 三层结构

| 层级 | 位置 | 负责内容 |
|------|------|---------|
| **L1 用户级** | `~/.claude/pipelit/config.json` | 飞书凭据、观测云凭据、全局默认值 |
| **L2 项目级** | `<cwd>/.claude/pipelit/config.json` | 项目路径、发版配置、项目特有覆盖 |
| **L3 仓库级** | `<repo>/.pipelit.json`（可选） | 单仓库 precheck 命令、特殊规则 |

合并优先级：**L3 > L2 > L1**（高层覆盖低层，浅合并）。

---

## L1 — 用户级（`~/.claude/pipelit/config.json`）

凭据类、跨项目共享的默认值，**不进任何仓库**。

```json
{
  "app_id": "cli_xxxx",
  "app_secret": "xxxx",
  "logProvider": "guance",
  "cardFeatures": {
    "linkTask": true,
    "atFollower": true,
    "image": true
  }
}
```

| 字段 | 说明 | 默认 |
|------|------|------|
| `app_id` / `app_secret` | 飞书应用凭据 | 必填 |
| `logProvider` | 日志提供商：`guance` \| `noop` | `"guance"` |
| `cardFeatures.linkTask` | 卡片是否附飞书任务链接 | `true` |
| `cardFeatures.atFollower` | 卡片是否 @ 任务关注人 | `true` |
| `cardFeatures.image` | 卡片是否附发版图 | `true` |

---

## L2 — 项目级（`<cwd>/.claude/pipelit/config.json`）

项目路径、发版配置，放入仓库（不含凭据）。

```json
{
  "frontend_path": "/path/to/frontend",
  "backend_path": "/path/to/backend",
  "release": {
    "repos": [...],
    "changelog": {...}
  }
}
```

| 字段 | 说明 |
|------|------|
| `frontend_path` / `backend_path` | 项目绝对路径 |
| `release` | 发版配置（同 using-pipelit 引导时写入的格式） |

---

## L3 — 仓库级（`<repo>/.pipelit.json`，可选）

单仓库覆盖，放在对应 repo 根目录，**可提交**。

```json
{
  "precheck": ["npm run lint", "npm run test:unit"],
  "logProvider": "noop"
}
```

---

## 合并逻辑（`load_merged_config()`）

```python
# scripts/feishu_api.py
def load_merged_config(cwd: str | None = None) -> dict:
    """三层配置合并：L1 < L2 < L3。"""
```

合并规则：
1. 读 L1（`~/.claude/pipelit/config.json`）
2. 读 L2（`<cwd>/.claude/pipelit/config.json`，若存在）
3. 读 L3（`<cwd>/.pipelit.json`，若存在）
4. 浅合并（dict 顶层覆盖，不递归合并嵌套对象）

---

## 迁移指南

已有用户（原 `~/.claude/pipelit/config.json` 全量配置）：
- **无需迁移**，旧格式继续作为 L1 生效
- 可选：把 `frontend_path` / `backend_path` / `release` 挪到项目级 `.claude/pipelit/config.json`

新项目上手：
1. 全局配置凭据：`python3 feishu_api.py save_config <app_id> <app_secret>`
2. 项目级配置路径：`python3 feishu_api.py save_project_config --frontend /path --backend /path`
3. （可选）配置日志源：在 L1 config 中设置 `"logProvider": "guance"` 并配置观测云凭据
