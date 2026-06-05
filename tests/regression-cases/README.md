# Pipelit 回归测试用例集

> 每次改 skill 后跑一遍这 5 个 case，对比"期望结果"和实际表现，回归保护。
> Stage 0 产物 —— 后续所有 Task 都基于这套验证。

---

## 怎么用

### 跑某个 case

1. 打开 case 文件，阅读"输入"段
2. 在 Claude Code 里按"触发方式"启动 skill
3. 跑完后对照"期望关键判定"勾选
4. 把实际 audit JSON / 输出截图存到 `runs/<日期>/<case-id>/`

### 跑全集

```
case-01 → case-02 → case-03 → case-04 → case-05
```

任一失败 → 记录 → 回到对应 Stage Task 修 → 修完再全跑一遍。

---

## Case 列表

| ID | 名称 | 验证什么 | 关联 Task |
|---|---|---|---|
| case-01 | L2 清晰需求 | 典型路径走得通 | Stage 1 全部 |
| case-02 | L2 + 日志辅证 | 时间校验、接口定位、日志匹配 | Task 1.2 / 1.3 / 1.4 |
| case-03 | L3 模糊描述 | 复杂度判定 + 跑两次稳定 | Task 1.8 / 2.1 |
| case-04 | L3 跨前后端 | 分支策略、多仓库一致 | Task 1.7 |
| case-05 | Release 双仓发版 | commit body 收集、预览确认、无任务降级 | Task 1.1 / 1.5 / 1.6 |

---

## Mock 数据约定

不依赖真实飞书任务的 case，用 `mocks/<case-id>/` 下的固定文件：

- `task.json` — 模拟 `get_task_full` 返回值
- `images/*.png` — 模拟附件截图
- `git-log.txt` — 模拟 `git log` 输出

真实任务的 case 用 `task_id` 直接拉，但需要在备注里记"什么时间拉的 / 任务当时状态"，方便复现。

---

## Audit 输出落位

每次跑完，把 audit JSON 存到：

```
~/.claude/pipelit/decision-logs/<date>/<task_id>-<skill>.json
```

跑两次同一个 case 后用：

```bash
python3 scripts/audit.py diff <log1> <log2>
```

对比决策稳定性（Stage 5 Task 5.3 产物，目前手动 diff）。
