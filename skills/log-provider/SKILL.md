# Log Provider — 接口定义

> 统一封装"从日志系统查 bug 日志"能力，让 feishu-dev 不感知具体实现。

---

## 接口契约

所有 log provider 脚本均位于 `scripts/log_providers/`，遵循统一 CLI 接口：

```bash
PYTHONIOENCODING=utf-8 python3 "${CLAUDE_PLUGIN_ROOT}/scripts/log_providers/<provider>.py" \
  query_errors_silent \
  --start  <ISO8601>  \
  --end    <ISO8601>  \
  [--interfaces <逗号分隔路径列表>]
```

### 返回格式（stdout JSON）

**有数据时：**
```json
{
  "status": "ok",
  "summary": "...",        // 精简摘要，直接放进 log_summary
  "entries": [...]         // 可选详情
}
```

**无数据时：**
```json
{"status": "no_data"}
```

**未配置时：**
```json
{"status": "not_configured"}
```

**错误时：**
```json
{"status": "error", "message": "..."}
```

---

## 可用 Provider

| provider | 描述 | 配置键 |
|----------|------|--------|
| `guance` | 观测云（默认） | `logProvider: "guance"` |
| `noop`   | 无日志源兜底   | `logProvider: "noop"` |

> 未来扩展：`sentry`、`datadog` 等只需新增同名脚本并遵循上述接口。

---

## 配置

在 `~/.claude/pipelit/config.json`（L1 用户级）：

```json
{
  "logProvider": "guance"
}
```

未配置时默认 `"guance"`（向后兼容）。

---

## 调用入口（feishu-dev 内部使用）

feishu-dev Phase 1.8d 统一通过以下脚本调用：

```bash
PYTHONIOENCODING=utf-8 python3 "${CLAUDE_PLUGIN_ROOT}/scripts/log_providers/dispatch.py" \
  query_errors_silent \
  --start  <ISO8601>  \
  --end    <ISO8601>  \
  [--interfaces <逗号分隔路径列表>]
```

`dispatch.py` 读取 config 的 `logProvider` 字段，转发到对应 provider。

---

## 返回值处理规则（feishu-dev Phase 1.8d）

| 返回 status | log_summary | log 输出 |
|-------------|-------------|---------|
| `ok` | `summary` 原文 | `[1.8d] log-provider 返回：有日志摘要，已写入 log_summary` |
| `not_configured` | `null` | `[1.8d] log-provider 返回：not_configured，静默跳过` |
| `error` | `null` | `[1.8d] log-provider 返回：错误 <message>，静默跳过` |
| `no_data` | `null` | `[1.8d] log-provider 返回：无日志数据，静默跳过` |
