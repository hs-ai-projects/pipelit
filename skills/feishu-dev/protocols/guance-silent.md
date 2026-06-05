# Log Provider Silent 协议

> feishu-dev 与 log-provider 之间的跨 skill 契约。
> 在 Phase 1.8d 调用，保证无论 provider 配置如何都不阻断主流程。

---

## 调用方（feishu-dev Phase 1.8d）

```bash
PYTHONIOENCODING=utf-8 python3 "${CLAUDE_PLUGIN_ROOT}/scripts/log_providers/dispatch.py" \
  query_errors_silent \
  --start <bug_start>  \
  --end   <bug_end>    \
  [--interfaces <path1,path2>]
```

- `bug_start` / `bug_end`：**必须是 ISO 8601 带时区格式**（见 `rules/time-window.md`）
- `interfaces`：逗号分隔的接口路径前缀，可为空（不传 `--interfaces` 即全量查询）

---

## 响应契约（provider 侧）

| 返回 `status` | 含义 | feishu-dev 处理 |
|--------------|------|----------------|
| `ok` | 有日志数据 | `log_summary = result.summary`，继续 |
| `no_data` | 无数据 | `log_summary = null`，静默跳过 |
| `not_configured` | 未配置 provider | `log_summary = null`，静默跳过 |
| `error` | 查询失败 | `log_summary = null`，静默跳过 |

**所有非 `ok` 的情况都不阻断主流程**，feishu-dev 直接进入下一步。

---

## 测试用例

### Case A — 正常有数据

输入：
```
--start 2026-06-04T13:00:00+08:00
--end   2026-06-04T14:00:00+08:00
--interfaces /api/v1/report
```

期望输出：
```json
{
  "status": "ok",
  "summary": "时段 ... 共 N 条日志 ..."
}
```

feishu-dev 期望行为：`log_summary` 写入摘要，Phase 2 Plan 中插入日志节。

---

### Case B — noop provider（无日志源）

配置：`"logProvider": "noop"`

期望输出：
```json
{"status": "not_configured"}
```

feishu-dev 期望行为：`log_summary = null`，Plan 不插入日志节，用户不感知。

---

### Case C — 时间格式错误

输入：`--start "2026/06/04 13:00"`

期望输出（guance provider）：
```json
{"status": "error", "message": "GUANCE_TIME_INVALID:..."}
```

feishu-dev 期望行为：静默跳过，**不向用户展示错误**。

---

### Case D — 无数据

正确格式，但该时段无日志：

```json
{"status": "no_data"}
```

feishu-dev 期望行为：静默跳过，Plan 中不插入日志节。

---

## 切换 Provider

在 `~/.claude/pipelit/config.json` 设置：

```json
{"logProvider": "noop"}
```

即可在不修改任何代码的情况下禁用日志查询。

---

## 已知限制

- `guance` provider 仅支持 ads-backend log source（LOG_SOURCE = "ads-backend"）
- 未来支持其他 log source 需修改 `scripts/log_providers/guance.py` 的 `LOG_SOURCE` 常量或扩展为配置项
