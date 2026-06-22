# Release 状态机

> 替代 SKILL.md Phase 3/4 的隐式流程。
> 每次状态转换持久化到 `<outputDir>/.release-state.json`。
> 支持中断恢复：用户说"继续发版"或 `/release resume`。

---

## 状态

```
┌─────────┐ precheck失败  ┌──────────┐
│  IDLE   │ ────────────→ │ BLOCKED  │
└────┬────┘                └──────────┘
     │ precheck通过
     ↓
┌───────────┐ 用户取消    ┌──────────┐
│ PREVIEWED │ ──────────→ │CANCELLED │
└────┬──────┘              └──────────┘
     │ 用户确认
     ↓
┌───────────┐ commit/tag失败  ┌──────────┐
│ COMMITTED │ ──────────────→ │ BLOCKED  │（输出手动操作命令）
└────┬──────┘                  └──────────┘
     │
     ↓
┌──────────┐ 任一push失败  ┌──────────────┐
│ PUSHING  │ ────────────→ │PARTIAL_PUSHED│
└────┬─────┘                └──────┬───────┘
     │ 全部成功                   │ resume
     ↓                            ↓
┌──────────┐                  ┌───────────┐
│  PUSHED  │ ←────────────────│  重试push  │
└────┬─────┘                  └───────────┘
     │ changelog/卡片完成
     ↓
┌───────────┐
│ COMPLETED │
└───────────┘
```

## 状态定义

| 状态 | Phase 对应 | 含义 |
|------|-----------|------|
| `IDLE` | 启动 | 未开始 |
| `BLOCKED` | — | precheck 失败，需人工处理 |
| `PREVIEWED` | Phase 2 完成 | 预览已展示给用户 |
| `CANCELLED` | — | 用户在预览阶段取消 |
| `COMMITTED` | Phase 3.2 完成 | commit + tag 已完成，未 push |
| `PUSHING` | Phase 3.3 进行中 | 正在推送各仓库 |
| `PARTIAL_PUSHED` | 部分仓库 push 失败 | 至少一个仓库未推送 |
| `PUSHED` | Phase 3.3 全部完成 | 所有仓库已推送 |
| `COMPLETED` | Phase 3.6 全部完成 | changelog + 卡片已发送 |

## 状态持久化

每次状态转换写 `<changelog.outputDir>/.release-state.json`：

```json
{
  "state": "PARTIAL_PUSHED",
  "version": "v1.3.0",
  "date": "2026-06-05",
  "started_at": "2026-06-05T10:00:00+08:00",
  "last_updated": "2026-06-05T10:05:00+08:00",
  "repos": [
    {
      "label": "frontend",
      "path": ".",
      "branch": "master",
      "committed": true,
      "tagged": true,
      "pushed": true,
      "tag": "v1.3.0"
    },
    {
      "label": "backend",
      "path": "../ads",
      "branch": "master",
      "committed": true,
      "tagged": true,
      "pushed": false,
      "tag": "v1.3.0"
    }
  ],
  "next_action": "resume-from-push",
  "manifest": {
    "frontend": {"range": "v1.2.5..v1.3.0", "commitCount": 12},
    "backend": {"range": "v1.2.5..v1.3.0", "commitCount": 8}
  }
}
```

## 恢复协议

### 触发方式

- 用户说"继续发版" / `/release resume`
- 或在新的会话中发现 `.release-state.json` 存在且 `last_updated` 在 24h 内

### 恢复流程

1. 读取 `<outputDir>/.release-state.json`
2. 根据 `state` 字段跳到对应步骤：

| state | 恢复动作 |
|-------|---------|
| `BLOCKED` | 列出失败原因 → 等用户修复 → 重新 precheck |
| `PREVIEWED` | 直接展示预览 → 等用户确认 |
| `COMMITTED` | 输出手动操作命令，进入 PUSHING（重新 push） |
| `PUSHING` | 继续 push 未完成的仓库 |
| `PARTIAL_PUSHED` | 重试 `pushed: false` 的仓库 → 成功后进入 PUSHED |
| `PUSHED` | 生成 manifest + changelog + 卡片 |

3. 恢复成功 → 更新 state 为 `COMPLETED`

## 关键不变量

- **COMMITTED → PUSHING 不能停**：commit 后必须 push，否则 next release 的 `range` 会错位
- **PUSHED → COMPLETED 可失败**：manifest / changelog / 卡片失败不影响发版本身
- **图片生成失败不阻断卡片发送**：降级链见 SKILL.md Phase 3.5b

