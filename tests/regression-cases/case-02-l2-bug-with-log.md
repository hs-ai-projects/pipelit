# Case 02 — L2 + 日志辅证

> **目标**：验证 bug 任务的时间校验、接口路径定位、日志匹配三件套都对。
> 这个 case 直接对应用户反馈 #1 / #2 / #3。

---

## 输入

### 触发方式

```
帮我做飞书任务 <task_id>
```

### 任务特征

- **描述含时间**：例如"今天下午 14:30 左右点保存广告报告失败"
- **附件**：截图含 network 面板，能看到具体接口路径 `/api/ads/create-ads/report`（含子路径）
- **观测云**：该时段确实有错误日志（真任务）或 mock 数据

### Mock 版

`mocks/case-02/task.json`：

```json
{
  "task": {
    "id": "mock-l2-bug-002",
    "summary": "广告报告创建失败",
    "description": "今天下午两点半左右点「保存」创建广告报告失败，提示「服务器错误」，刷新后再试也不行。附 network 截图。",
    "created_at": "2026-06-04T14:35:00+08:00"
  },
  "has_images": true,
  "images": [{"path": "mocks/case-02/images/network-panel.png"}]
}
```

截图（手动构造一张）需包含：
- URL 栏 / Network 面板里清晰可见 `POST /api/ads/create-ads/report`
- Response status: 500
- 时间戳 14:32:xx

---

## 期望关键判定

### Phase 1.7 接口路径定位（Task 1.4）

| 检查项 | 期望 |
|---|---|
| 候选接口路径 | **`/api/ads/create-ads/report`**（含 `/report` 子路径） |
| 不能定位到 | `/api/ads/create-ads`（父路径，遗漏 report） |
| 候选数 > 3 时 | 强制收敛到最长公共前缀，AskUserQuestion |

### Phase 1.8a bug 判定

```
[1.8a] bug任务判断：是，理由：用户描述「失败」+「服务器错误」属于功能异常
```

### Phase 1.8c 时间推断

| 输入线索 | 期望 bug_start | bug_end |
|---|---|---|
| "今天下午两点半" + 创建于 14:35 | 13:30+08:00（往前 1h） | 14:45+08:00（推断点 + 15min） |

### Phase 1.8d 观测云调用（Task 1.2）

**输入校验**：

```
[1.8d] 调用观测云：start=2026-06-04T13:30:00+08:00 end=2026-06-04T14:45:00+08:00 interfaces=["/api/ads/create-ads/report"]
```

时间必须是带时区的 ISO 8601。**故意给错误格式测试**：

| 输入 | 期望返回 |
|---|---|
| `"2026/06/04 14:00"` | `GUANCE_TIME_INVALID:expected ISO 8601` |
| `"2026-06-04 14:00"`（无 T 无时区） | `GUANCE_TIME_INVALID:missing timezone` |
| `"2026-06-04T13:30:00+08:00"` | 正常查询 |

### Phase 1.8d 日志匹配（Task 1.3）

返回内容必须包含：

- 状态码（不仅 5xx，2xx 也要）
- 请求 payload（让 AI 能判断"是不是入参问题"）
- 响应 payload（让 AI 能判断"是不是返回数据为空"）

期望摘要类似：

```
高频报错:
  • POST /api/ads/create-ads/report → 500 Internal Server Error  ×3 次
    request: {"name":"测试报告","ads":[]}  ← ads 为空可能是入参问题
  • POST /api/ads/create-ads/report → 200 OK 但 data=null  ×1 次

可能关联: 入参 ads 数组为空时后端报 500
```

不该出现：

```
高频报错:
  • <空，只查了 ERROR 级别>
```

---

## 期望 audit JSON 关键字段

```json
{
  "task_id": "...",
  "level": "L2",
  "phase_1_8": {
    "is_bug_task": true,
    "interface_candidates": ["/api/ads/create-ads/report"],
    "time_window": {
      "start": "2026-06-04T13:30:00+08:00",
      "end": "2026-06-04T14:45:00+08:00",
      "inference_source": "description_time_hint"
    },
    "guance_result": "summary_returned"
  }
}
```

---

## 失败场景

| 现象 | 可能根因 | 回到 |
|---|---|---|
| 接口定位到 `/api/ads/create-ads`（少了 /report） | 没读截图 URL | Task 1.4 |
| 观测云查询时间格式错误导致接口 4xx | 时间校验缺失 | Task 1.2 |
| 日志摘要只有 5xx，看不到入参 | 查询逻辑只过滤 ERROR | Task 1.3 |
| 死循环（重试错误时间格式） | 没在脚本入口校验 | Task 1.2 |
