# L1/L2/L3 分级规则

> 替代 SKILL.md Phase 1.3 的散文判定。
> 每次判定必须输出 audit JSON，落盘到 `~/.claude/pipelit/decision-logs/`。
> Schema 定义见 `docs/decision-log-schema.md` Phase 1.3。

## 决策树

**按优先级自上而下匹配，命中即返回，不再继续。**

| 优先级 | 条件 | 判定 | 规则名 |
|---|---|---|---|
| 1 | 任务标签含"线上事故" / "P0" / "紧急" | L3 | rule-1-incident-tag |
| 2 | 描述含"架构调整" / "重构" / "迁移" / "整体改版" 或 feishu_tags 含 `架构` / `重构` / `迁移` | L3 | rule-2-arch-refactor |
| 3 | 1.7 grep 候选文件数 > 5 | L3 | rule-3-many-files |
| 4 | 1.7 grep 候选文件 = 0，且 1.6 补问后仍无法定位 | L3 | rule-4-unlocatable |
| 5 | 描述长度 < 20 字 **且** 无截图 **且** 无附件 | L3 | rule-5-vague-description |
| 6 | 其他 | L2 | default-l2 |

## 阈值依据

| 规则 | 阈值 | 依据 |
|---|---|---|
| rule-3 | > 5 文件 | 历史任务统计，> 5 文件的任务平均耗时 4h，AI 一次性改完出错率 60% |
| rule-5-vague-description | < 20 字 | "优化一下登录" = 8 字，"修复广告搜索框翻页后选中态丢失" = 19 字。经验上 < 20 字基本无法直接定位 |
| rule-1 | 关键词列表 | 来自过去 3 次事故复盘的高频标签 |

## 输出格式

判定完成后，**必须**输出一行 log：

```
[1.3] 分级结果：<L2/L3>，命中规则：<规则名>，候选文件数=<N>，描述长度=<N>，截图=<有/无>
```

并写入 audit JSON（内容同 decision-log-schema.md Phase 1.3 结构）：

```json
{
  "phase": "1.3",
  "decision_type": "level_classification",
  "level": "L2",
  "matched_rule": "default-l2",
  "rule_priority": 6,
  "evidence": {
    "candidate_files": 2,
    "desc_length": 132,
    "has_screenshot": true,
    "has_attachment": false,
    "is_bug_task": false,
    "matched_keywords": [],
    "feishu_tags": []
  },
  "fallback_attempted": false
}
```

## 注意事项

- **rule-2**：`feishu_tags` 来自 `get_task_full` 的 task 对象中的 tags 字段。若 API 未返回该字段，仅按描述关键词匹配。
- **rule-4**：依赖 1.6 和 1.7 的执行结果。只有在"补问后仍为 0"时才触发。若用户拒绝补问（1.6 被跳过），走 rule-2 语义判断。
- **default-l2**：兜底规则。不满足前 5 条的任何任务都归入 L2。