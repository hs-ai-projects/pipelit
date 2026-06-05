# Case 01 — L2 清晰需求

> **目标**：验证典型 L2 路径走得通，不该弹的问题不弹、该自动的步骤自动。

---

## 输入

### 触发方式

```
帮我做飞书任务 <task_id>
```

或者直接发任务 URL。

### 任务特征（手动构造或选真实任务）

- **描述长度**：80-200 字之间
- **附件**：至少 1 张截图（含具体页面）
- **范围**：单文件改动可解决（例如"广告列表页加一列预算"）
- **非 bug 任务**：纯小需求，不需要查日志

### Mock 版（无真任务时用）

`mocks/case-01/task.json`：

```json
{
  "task": {
    "id": "mock-l2-clear-001",
    "summary": "广告列表页增加预算列",
    "description": "广告列表当前只显示名称和状态，业务希望加一列「日预算」，从接口已有字段读取即可，不需要后端改造。请在表头加列、表体加单元格，金额格式 ¥1,234.56。"
  },
  "has_images": true,
  "images": [{"path": "mocks/case-01/images/ad-list-page.png"}],
  "has_subtasks": false,
  "project_config": {"configured": true, "frontend_path": "/fake/frontend"}
}
```

---

## 期望关键判定

| 检查项 | 期望 | 关联 Task |
|---|---|---|
| Phase 1.6 清晰度补问 | **不补问**（描述清晰 + 有截图） | Task 1.8 |
| Phase 1.7 grep 候选 | 1-2 个，命中 AdList / AdTable 类组件 | Task 1.4 |
| Phase 1.8a bug 判定 | **跳过整个 1.8**（非 bug 任务） | - |
| L2/L3 判定 | **L2** | Task 2.1 |
| Phase 2 Plan 输出 | 包含目标文件 + 不超过 3 个改动点 | - |
| Phase 3.5 用户验证暂停 | **必须暂停**（非 BOT_AUTO_EXECUTE） | Task 1.8 |
| Phase 3.6 commit 类型 | `feat:` | - |
| Phase 3.7 复杂度 | 单仓库 push 完成 | - |

---

## 期望 audit JSON 关键字段

```json
{
  "task_id": "...",
  "level": "L2",
  "matched_rule": "default-l2",
  "evidence": {
    "candidate_files": 1,
    "desc_length": 132,
    "has_screenshot": true,
    "is_bug_task": false
  }
}
```

---

## 失败场景

| 现象 | 可能根因 | 回到 |
|---|---|---|
| Phase 1.6 弹了"页面在哪" | 没用上截图信息 | Task 1.4 |
| Phase 3.5 直接跳过没等用户 | BOT_AUTO_EXECUTE 判定漏 | Task 1.8 |
| 判 L3 | 复杂度规则阈值过严 | Task 2.1 调阈值 |
