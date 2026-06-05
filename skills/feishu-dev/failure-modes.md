# feishu-dev Failure Modes

> 每个失败模式包含：阶段 / 触发条件 / 用户感知 / 兜底行为 / 是否阻断。
> 对应的 regression case 见 `tests/regression-cases/`。

---

| ID | 阶段 | 触发条件 | 用户感知 | 兜底行为 | 阻断 |
|----|------|---------|---------|---------|------|
| F01 | Phase 0 RESUME-CHECK | `.feishu-dev-state.json` 存在但已超 24h | 无感知 | 静默跳过，正常走新任务流程 | 否 |
| F02 | Phase 1.1 | 飞书凭据未配置 | 返回 `{"error": "凭据未配置"}` | 输出引导配置步骤，停止执行 | 是 |
| F03 | Phase 1.1 | 任务 ID 不存在 / 无权限 | 接口返回非 0 code | 输出错误原因，停止执行 | 是 |
| F04 | Phase 1.2 | 图片 URL 无效 / 下载失败 | 静默（用户不知道图片没下载） | 跳过该附件，images 列表记录 error | 否 |
| F05 | Phase 1.3 | L2 → 执行中发现文件 > 5 个 | 用户已确认 Plan | 输出警告，继续执行（不降为 L3）；若用户希望停止可随时中断 | 否 |
| F06 | Phase 1.6 | 任务描述过短（< 20 字）且无截图 | 被询问 | AskUserQuestion 补问，等待用户输入后继续 | 暂停 |
| F07 | Phase 1.8b | 候选接口路径为空 | 无感知 | 空列表传给 1.8c，继续执行（log 注明"无接口候选"） | 否 |
| F08 | Phase 1.8c | 无任何时间线索 | 无感知 | 使用 task.created_at fallback，log 中注明 `(fallback: created_at)` | 否 |
| F09 | Phase 1.8d | log-provider 返回 error / no_data / not_configured | 无感知 | `log_summary = null`，静默跳过，不展示给用户 | 否 |
| F10 | Phase 1.8d | 时间格式错误（非 ISO 8601） | 无感知 | dispatch.py 返回 error，静默跳过 | 否 |
| F11 | Phase 3.1 | 分支已存在（其他仓库已创建同名分支） | 提示分支冲突 | 输出 `[3.1-<repo>] 跳过原因: 分支已存在`，使用已有分支 | 否 |
| F12 | Phase 3.6 | Commit 失败（lint/pre-commit hook 报错） | 见到错误信息 | 输出 hook 错误，等待用户修复或确认跳过（不使用 --no-verify） | 暂停 |
| F13 | Phase 3.7 | Push 失败（远端有新提交） | 见到错误信息 | 输出 `git pull --rebase` 建议，等待用户确认后重试 | 暂停 |
| F14 | Phase 4 | complete_task 飞书 API 失败 | 任务未标记完成 | 输出警告 + 手动操作链接，不重试 | 否 |

---

## 非阻断失败的处理原则

- **静默跳过**（F01, F04, F07, F08, F09, F10, F14）：不展示给用户，仅写 log 行
- **日志注明**：所有跳过行为在对应 phase 的 log 输出中记录原因
- **不回滚**：已完成的步骤不因后续失败而撤销

## 阻断失败的处理原则

- F02, F03：配置/权限问题，用户需要手动解决
- F06：需要用户提供更多信息
- F12, F13：需要用户决策（是否接受 hook 失败 / 如何处理冲突）

---

## Regression Case 映射

| ID | Case |
|----|------|
| F02 | case-02（缺凭据时的行为） |
| F06 | case-03（模糊描述触发补问） |
| F09 | case-02（观测云静默跳过） |
| F12 | case-04（跨前后端 commit hook） |
