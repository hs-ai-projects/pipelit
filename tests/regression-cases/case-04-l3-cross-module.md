# Case 04 — L3 跨前后端

> **目标**：验证多仓库一致的分支策略 + 跨模块复杂度判定。
> 对应反馈 #17（前端开分支后端 master 改）。

---

## 输入

### 触发方式

```
帮我做飞书任务 <task_id>
```

### 任务特征

- **影响前端 + 后端**两个仓库
- **预计影响文件 > 5**
- 描述清晰但范围大（典型 L3）

例如："广告创建流程加一个「审核中」状态，前端列表加状态过滤、详情页展示，后端接口返回新字段、状态机加流转。"

### Mock 版

`mocks/case-04/task.json`：

```json
{
  "task": {
    "id": "mock-l3-cross-004",
    "summary": "广告增加审核中状态",
    "description": "广告创建流程加一个「审核中」状态。前端：列表加状态过滤、详情页展示新状态。后端：接口返回新字段、状态机加流转、数据库加字段。涉及前后端共 6-8 个文件。"
  },
  "project_config": {
    "configured": true,
    "frontend_path": "/fake/frontend",
    "backend_path": "/fake/backend"
  }
}
```

---

## 期望关键判定

### 复杂度判定

| 优先级 | 条件 | 是否命中 | 判定 |
|---|---|---|---|
| 3 | grep 候选 > 5 | ✅（预计 6-8 个文件） | **L3** |

→ 进入 L3 分析报告流程，**不创建分支、不改代码**

### L3 报告关键字段

```
涉及范围:
  [前端] AdList.vue, AdDetail.vue, AdFilter.vue (3 文件)
  [后端] ad_service.py, ad_models.py, migration_xxx.py (3-4 文件)

建议拆分:
  1. 后端：先加字段 + migration（独立 PR）
  2. 后端：状态机改造 + 接口字段（独立 PR）
  3. 前端：列表过滤 + 详情展示（独立 PR）
```

---

## 假设走到 L2（手动 override 复杂度判定后）

测试 Phase 3.1 多仓库分支创建的一致性：

### 期望日志（Task 1.7）

```
[3.1-frontend] 当前分支: master → 创建 feat/feishu-mock-l3
[3.1-backend]  当前分支: master → 创建 feat/feishu-mock-l3
```

**不能出现**：

```
[3.1-frontend] 创建 feat/feishu-xxx
（后端没日志，直接在 master 上改）
```

### branching_decision.json

```json
{
  "task_id": "mock-l3-cross-004",
  "decisions": [
    {"repo": "frontend", "current_branch": "master", "action": "create", "new_branch": "feat/feishu-mock-l3"},
    {"repo": "backend", "current_branch": "master", "action": "create", "new_branch": "feat/feishu-mock-l3"}
  ]
}
```

---

## 失败场景

| 现象 | 可能根因 | 回到 |
|---|---|---|
| 判 L2（应判 L3） | 复杂度规则没生效 | Task 2.1 |
| 后端直接在 master 改 | Phase 3.1 没贯彻"每仓独立" | Task 1.7 |
| 只有 frontend 日志，backend 段缺失 | 显式表格 + 强制 log 没加 | Task 1.7 |
| branching_decision.json 没写 | audit trail 没接 | Task 1.7 |
