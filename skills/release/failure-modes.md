# release Failure Modes

> 每个失败模式包含：阶段 / 触发条件 / 用户感知 / 兜底行为 / 是否阻断。
> 状态机完整定义见 `state-machine.md`。

---

| ID | 阶段 | 触发条件 | 用户感知 | 兜底行为 | 阻断 |
|----|------|---------|---------|---------|------|
| R01 | Phase 0 | `config.json` 不存在或 `configured: false` | 进入引导流程 | AskUserQuestion 收集配置，首次配置后写入并继续 | 暂停（引导） |
| R02 | Phase 1.1 | 工作区有未提交改动 | 检测到脏状态 | 输出 `git status` 结果，要求用户提交或暂存后重试 | 是 |
| R03 | Phase 1.1 | 本地分支落后远端 | 检测到落后 N 个提交 | 输出 `git pull` 建议，等待用户确认后重试 | 暂停 |
| R04 | Phase 1.3 | 无 commit 可发布（与上个 tag 相同） | 提示无新变更 | 停止发版，输出原因 | 是 |
| R05 | Phase 1.4 | 远端 tag 已存在 | 提示 tag 冲突 | 停止发版，输出已有 tag 信息，建议修改版本号后重试 | 是 |
| R06 | Phase 1.5 | precheck 命令失败（exit code ≠ 0） | 见到错误输出 | 输出失败命令及错误，停止发版 | 是 |
| R07 | Phase 2 | 用户选择"取消" | 用户主动取消 | 输出"发版已取消"，不执行任何 git 操作 | 是（用户决策） |
| R08 | Phase 3.2 | 版本号文件更新失败（文件不存在） | 报错 | 停止发版，输出文件路径和错误原因 | 是 |
| R09 | Phase 3.3 | `git commit` 失败（pre-commit hook 拦截） | 见到 hook 错误 | 输出 hook 错误，**不使用 --no-verify**，等待用户修复后重试 | 暂停 |
| R10 | Phase 3.4 | frontend push 成功，backend push 失败 | 只推了一半 | 状态 → `PARTIAL_PUSHED`，输出恢复命令，不自动回滚 | 是（partial） |
| R11 | Phase 3.4 | 网络超时 / push 中断 | push 没有完成 | 同 R10 处理，状态记录到 `.release-state.json` | 是（partial） |
| R12 | Phase 卡片发送 | `send_release_card_with_mentions` 失败 | 发版完成但卡片没发 | 输出警告 + 失败原因，**不影响已完成的 tag/push** | 否 |
| R13 | Phase 卡片发送 | OpenAI 图片生成失败 | 无图片的卡片 | 跳过图片，用纯文字卡片继续发送 | 否 |
| R14 | Phase 卡片发送 | 任务关注人查询失败（飞书 API 报错） | @ 不到关注人 | 跳过该 entry 的 @，不影响其他 entry 和卡片发送 | 否 |
| R15 | Phase resume | `.release-state.json` 存在但版本已被手动 tag | 用户说"继续发版" | 检测到 tag 已存在，提示当前状态，让用户决策 | 暂停（确认） |

---

## PARTIAL_PUSHED 恢复流程

触发条件：R10 / R11

```
状态：PARTIAL_PUSHED
已推送：frontend ✅ / backend ❌

恢复命令（backend）：
  git -C "<backend_path>" push origin <branch> --tags

或重新说"继续发版"，状态机会跳到 backend push 步骤。
```

## 非阻断失败原则

- R12, R13, R14：卡片发送问题不影响发版结果，只输出警告
- 发版完成标志：tag 已推送到所有 repos，卡片只是锦上添花

## Regression Case 映射

| ID | Case |
|----|------|
| R02 | case-05（脏工作区检测） |
| R09 | case-05（pre-commit hook 拦截） |
| R10 | case-05（partial push 恢复） |
| R12 | case-05（卡片发送失败不影响发版） |
