# Case 03 — L3 模糊描述

> **目标**：验证 L3 触发规则 + 决策稳定性（跑两次 audit JSON 一致）。
> 对应反馈 #14（换 AI 模型一致性）+ #15（同任务跑两次一致）。

---

## 输入

### 触发方式

```
帮我做飞书任务 <task_id>
```

### 任务特征

- **描述极短**：< 20 字，例如"优化下登录"
- **无附件**
- **无报错信息**

### Mock 版

`mocks/case-03/task.json`：

```json
{
  "task": {
    "id": "mock-l3-vague-003",
    "summary": "优化下登录",
    "description": "登录不太顺，看看"
  },
  "has_images": false,
  "images": []
}
```

---

## 期望关键判定

### 决策规则匹配（Task 2.1）

按 `skills/feishu-dev/rules/classification.md` 决策树：

| 优先级 | 条件 | 是否命中 | 判定 |
|---|---|---|---|
| 1 | 关键词 "线上事故" / "P0" | ❌ | - |
| 2 | 飞书标签含"架构"/"重构" | ❌ | - |
| 3 | grep 候选 > 5 | ⚠️ 没到这一步 | - |
| 4 | grep 候选 = 0 且补问无收敛 | ❌ | - |
| 5 | **描述 < 20 字 且 无截图 且 无附件** | ✅ | **L3-clarify** |
| 6 | 其他 | - | - |

### 流程

1. Phase 1.6 补问："登录哪个环节？错误信息？复现步骤？"
2. 用户拒绝补充或仍模糊 → 直接进入 L3 分析报告
3. **不创建分支、不改代码、不 commit**

### 跑两次一致性

同一个 task 跑两次，audit JSON 除 `timestamp` 外完全相同：

```json
{
  "task_id": "mock-l3-vague-003",
  "level": "L3",
  "matched_rule": "rule-5-vague-description",
  "evidence": {
    "desc_length": 6,
    "has_screenshot": false,
    "has_attachment": false,
    "clarification_attempted": true,
    "clarification_resolved": false
  }
}
```

---

## 期望 L3 报告输出

```
━━━ L3 分析报告 ━━━
任务: 优化下登录
链接: <飞书任务链接>

问题定位:
  描述过于模糊，无法定位具体环节

建议补充信息:
  1. 登录流程哪一步出问题？（账号密码输入 / 验证码 / 跳转）
  2. 错误表现？（无响应 / 报错 / 进了错误页面）
  3. 触发条件？（特定账号 / 特定浏览器 / 必现还是偶发）

建议拆分:
  1. 用户先补充信息
  2. 根据信息确定属于"功能优化"还是"bug 修复"
  3. 再走 L2 流程

⚠️ 此任务复杂度较高，建议人工拆分后逐个处理。
━━━━━━━━━━━━━━━━━
```

---

## 期望 audit JSON 关键字段

跑第 1 次：

```json
{"task_id": "...", "level": "L3", "matched_rule": "rule-5-vague-description", "timestamp": "2026-06-05T10:00:00+08:00"}
```

跑第 2 次：

```json
{"task_id": "...", "level": "L3", "matched_rule": "rule-5-vague-description", "timestamp": "2026-06-05T10:05:00+08:00"}
```

**diff 除 timestamp 外应为空**。

---

## 失败场景

| 现象 | 可能根因 | 回到 |
|---|---|---|
| 跑两次结果不一致（L2 vs L3） | 判定靠 AI 主观，没规则化 | Task 2.1 |
| 直接跳过补问进 L3 | 漏了 Phase 1.6 | Task 2.1 |
| 进了 L2 流程开始改代码 | 描述长度规则没生效 | Task 2.1 阈值配置错 |
| audit JSON 没落盘 | Stage 0.2 schema 没集成进 SKILL.md | Task 2.1 |
