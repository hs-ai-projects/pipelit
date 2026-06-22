# Pipelit 架构说明

> 面向贡献者。说明各 skill / 脚本之间的关系、数据流向、以及扩展点。

---

## 整体结构

```
用户输入（Claude Code 对话）
      │
      ▼
using-pipelit（路由指南，首次使用时激活）
      │
      ├─ feishu 任务 ID ──→ feishu-dev
      ├─ "发版"           ──→ release
      ├─ "changelog"      ──→ changelog
      └─ "观测云"         ──→ guance-log-analysis
```

---

## feishu-dev 内部流程

```
Phase 1：拉取 + 理解
  1.1 get_task_full()          ← feishu_api.py（含 TTL 缓存）
  1.2 附件处理（图片/视频）
  1.3 L2/L3 分级              ← rules/classification.md
        │ audit trail          ← decision_log.py
  1.4 子任务
  1.5 项目规范
  1.6 清晰度检查
  1.7 定位目标文件（并行 grep）
  1.8 Bug 日志辅助（仅 bug 任务）
      1.8a bug判定            ← rules/bug-triggers.md
      1.8b 接口预定位
      1.8c 时间推断           ← rules/time-window.md
      1.8d log-provider 调用  ← log_providers/dispatch.py
            │
            └─ guance.py / noop.py / ...

Phase 2：Plan 确认（L2）
Phase 3：执行（改代码 + 验证 + commit + push）
Phase 4：收尾（飞书标记完成 + 输出报告）
```

输出契约 schema 见 `skills/feishu-dev/output-contracts/`。

---

## release 内部流程

```
Phase 0：读配置（三层合并）
Phase 1：Precheck（全自动）
  1.1 git sync 检查
  1.3 收集 commits（git log --format="%B" 读 Feishu-Task: body）
  1.3 版本号判定              ← release/rules/version-bump.md
Phase 2：预览确认（唯一人工介入）
Phase 3：执行
  3.1 写状态文件              ← .release-state.json（状态机）
  3.3 commit + tag
  3.4 push（双仓并行）
  3.5 release-manifest.json
  3.6 changelog              ← changelog skill
  3.7 版本更新概述
Phase 卡片：飞书通知
  card_builder.py            ← cardFeatures 独立 if
  send_release_card_with_mentions() ← feishu_api.py
```

状态机完整定义见 `skills/release/state-machine.md`。
失败模式见 `skills/release/failure-modes.md`（R01-R15）。

---

## log-provider 抽象层

```
feishu-dev Phase 1.8d
      │
      ▼
scripts/log_providers/dispatch.py
      │ 读 config.logProvider
      ├─ "guance" → guance.py → guance_api.py（观测云 DQL）
      └─ "noop"   → noop.py（始终返回 not_configured）
      
接口契约见 skills/log-provider/SKILL.md
协议契约见 skills/feishu-dev/protocols/guance-silent.md
```

**扩展新 provider**：在 `scripts/log_providers/` 新增 `<name>.py`，实现 `query_errors_silent(start, end, interfaces)` 函数，返回 `{status: ok/no_data/not_configured/error, summary: ...}`，配置 `logProvider: "<name>"` 即可生效。

---

## 配置三层合并

```
L1 ~/.claude/pipelit/config.json      凭据、全局默认
L2 <cwd>/.claude/pipelit/config.json  项目路径、发版配置
L3 <cwd>/.pipelit.json                仓库级覆盖（可选）

合并：{...L1, ...L2, ...L3}（浅合并，高层优先）
调用：feishu_api.load_merged_config(cwd)
```

---

## 跨 skill 数据流

| 数据 | 生产方 | 消费方 |
|------|--------|--------|
| `Feishu-Task: <url>` in commit body | feishu-dev Phase 3.6 | release Phase 1.3 |
| `release-manifest.json` | release Phase 3.5 | changelog |
| `.feishu-dev-state.json` | feishu-dev 各 Phase | feishu-dev RESUME-CHECK |
| `.release-state.json` | release Phase 3.1 | release resume |
| `decision-logs/<date>/<task_id>-<skill>.json` | feishu-dev Phase 1.3 | audit.py |
| `task-cache/<task_id>.json` | feishu_api.get_task_full | feishu_api.get_task_full（下次调用） |

---

## 关键文件索引

| 文件 | 职责 |
|------|------|
| `scripts/feishu_api.py` | 飞书 API 封装（任务/卡片/发版/缓存） |
| `scripts/guance_api.py` | 观测云 DQL API |
| `scripts/log_providers/dispatch.py` | log-provider 路由 |
| `scripts/card_builder.py` | 飞书卡片 lark_md 构建（独立 if） |
| `scripts/decision_log.py` | 决策审计日志写入 |
| `scripts/audit.py` | 决策日志查询（recent/why/diff） |
| `skills/feishu-dev/rules/classification.md` | L2/L3 分级决策树 |
| `skills/feishu-dev/rules/bug-triggers.md` | bug 任务判定特征表 |
| `skills/feishu-dev/rules/time-window.md` | 时间窗口推断规则 |
| `skills/feishu-dev/failure-modes.md` | 失败模式矩阵（F01-F14） |
| `skills/release/state-machine.md` | release 状态机 |
| `skills/release/rules/version-bump.md` | 版本号判定规则 |
| `skills/release/failure-modes.md` | release 失败模式（R01-R15） |
| `docs/config-hierarchy.md` | 三层配置规范 |
| `tests/test_regression.py` | 自动化回归（16 个验证点） |

---

## 新增 skill 的流程

1. 在 `skills/<name>/SKILL.md` 定义 skill（参考 feishu-dev 格式）
2. 若需要新 API 调用，在 `scripts/` 新增脚本
3. 在 `skills/using-pipelit/SKILL.md` 的 Skill 速查表和决策树里注册
4. 在 `tests/test_regression.py` 补充验证点
5. 更新本文件的关键文件索引
