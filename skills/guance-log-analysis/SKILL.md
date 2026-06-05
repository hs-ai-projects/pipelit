---
name: guance
description: >
  观测云日志分析。手动触发：/guance-log-analysis。
  语义触发词："观测云"、"查日志"、"查报错"、"接口报错"、"分析错误"、"guance logs"。
  拉取 ads-backend 指定时段的错误日志，按状态码/接口路径/错误信息三维聚合，输出分析报告。
---

# 观测云日志分析

分析 `ads-backend` 的错误日志，定位接口报错根因。

## 静默模式（GUANCE_SILENT_MODE）

当 prompt 包含 `GUANCE_SILENT_MODE` 时，进入静默模式，由其他 skill 程序化调用：

**跳过**：Phase 0 配置引导交互、Phase 1 时间段询问
**直接使用** prompt 中传入的参数：
- `start`：查询开始时间，**必须为 ISO 8601 带时区格式**：`YYYY-MM-DDTHH:MM:SS+08:00` 或 `YYYY-MM-DDTHH:MM:SSZ`
- `end`：查询结束时间，格式同上
- `interfaces`：接口路径前缀列表（用于过滤，可为空数组），示例：`["/api/v1/campaigns", "/api/ads"]`

**时间格式契约（强制）**：
- 调用方必须传入 ISO 8601 带时区格式，否则直接返回 `GUANCE_TIME_INVALID:<reason>`
- 不接受 `2026/06/04 14:00`（斜杠分隔）、`2026-06-04 14:00`（无 T 无时区）等格式
- 脚本入口 `validate_iso8601_time()` 做格式校验，不合法立即返回，不发起查询

**执行策略（懒加载兜底）**：

```
Step A：若 interfaces 不为空 → 带接口关键词过滤的精准查询（查询所有 status 级别，包括 2xx/3xx/4xx/5xx）
        有结果 → 输出精简摘要（含 request/response payload），结束
        无结果 → 执行 Step B

Step B：全量查询（不带过滤，查询所有 status 级别），取 top 高频；若 prompt 包含 bug 描述则优先匹配相关报错
```

**查询范围**：不再只查 `error/warning/critical` 级别，改为查询**所有日志**（包括 2xx 正常请求），让 AI 能判断"是不是入参问题导致返回空数据"或"正常请求和异常请求的差异"。

**调用命令**（静默模式用）：

```bash
PYTHONIOENCODING=utf-8 python3 "${CLAUDE_PLUGIN_ROOT}/scripts/guance_api.py" \
  query_errors_silent "<start>" "<end>" --interfaces '["/api/v1/campaigns"]' --limit 500
```

**配置未就绪**：直接输出 `GUANCE_NOT_CONFIGURED`，不展示引导。
**查询报错**（网络失败、401 等）：输出 `GUANCE_ERROR:<原因>`，不展示引导。

**输出格式**（精简摘要，供调用方嵌入）：

```
━━ 🔍 观测云 Log 摘要 ━━━━━━━━━━━━━━━━━
时间段: <start> ~ <end>
错误总数: <N> 条
关联接口: <接口路径，若有>

高频报错:
  • <接口路径> → <错误信息>  ×N 次
    request: <请求 payload 摘要>
    response: <响应 payload 摘要>
  • <接口路径> → <错误信息>  ×N 次
    request: <请求 payload 摘要>

可能关联: <结合 bug 描述推断的关联点>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

无数据时输出：
```
该时段未发现相关错误日志（共查询 <N> 条记录）
```

---

脚本：`${CLAUDE_PLUGIN_ROOT}/scripts/guance_api.py`

---

## Phase 0：配置检查

```bash
PYTHONIOENCODING=utf-8 python3 "${CLAUDE_PLUGIN_ROOT}/scripts/guance_api.py" check_config
```

若 `configured: false`，引导用户配置：

```
【观测云凭据未配置】请提供以下信息：

1. API Key：
   观测云控制台 → 管理 → API Key 管理 → 新建 Key

2. Workspace ID：
   控制台 URL 中 w=wksp_xxx 部分，例：wksp_530d1a63bc4e4ff59a480101bd0305fd

获取后运行：
python3 guance_api.py save_config <api_key> <workspace_id>
```

配置成功后继续 Phase 1。

---

## Phase 1：确认查询参数

用 AskUserQuestion 询问：

```
要分析哪个时间段的错误日志？

选项（可直接选，也可自定义）：
  ● 最近 1 小时
  ● 最近 6 小时
  ● 最近 24 小时
  ○ 自定义（格式：2024-01-01 09:00 ~ 10:00）
```

可选追加：
- 有无关注的关键词？（接口路径、错误信息片段，留空则查全量错误）

记录：`start`、`end`（转为 guance_api.py 接受的格式）、`keyword`（可选）

时间格式转换规则：
- "最近 1 小时" → start=`1h` end=`now`
- "最近 6 小时" → start=`6h` end=`now`
- "最近 24 小时" → start=`24h` end=`now`
- 自定义绝对时间 → start=`"2024-01-01 09:00"` end=`"2024-01-01 10:00"`

---

## Phase 2：执行查询

```bash
PYTHONIOENCODING=utf-8 python3 "${CLAUDE_PLUGIN_ROOT}/scripts/guance_api.py" \
  query_errors "<start>" "<end>" --limit 500
```

若返回 `error` 字段，处理如下：

| 错误信息 | 处理 |
|---------|------|
| 凭据未配置 | 回到 Phase 0 |
| 网络请求失败 | 提示检查网络/VPN，重试一次 |
| 查询失败 (code=401) | API Key 无效，引导重新配置 |
| 所有端点失败 | 提示用户确认 base_url（控制台 URL 是否 cn6 区域） |
| total_errors = 0 | 告知该时段无错误日志，建议扩大时间范围 |

---

## Phase 3：分析并输出报告

拿到 JSON 数据后，Claude 综合分析并输出：

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  观测云日志分析报告
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
数据源:  ads-backend
时间段:  <start> ~ <end>
错误总数: <total_errors> 条

━━ 📊 按 HTTP 状态码 ━━━━━━━━━━━━━━━━━
  <code>  <count> 次    <比例>%
  ...

━━ 📍 按接口路径 Top 10 ━━━━━━━━━━━━━━
  <method> <path>    <count> 次
  ...

━━ ❌ 按错误信息聚类 Top 10 ━━━━━━━━━━
  "<message pattern>"    <count> 次
  ...

━━ 💡 分析结论 ━━━━━━━━━━━━━━━━━━━━━━━
  主要问题：<根据数据推断>
  集中接口：<出错最多的接口>
  可能原因：<结合错误信息和状态码推断>
  建议排查：<具体行动建议>

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### 报告撰写规则

**状态码分析**：
- `4xx`：客户端错误，重点看请求参数/权限
- `5xx`：服务端错误，重点看 Amazon API 限流、数据库、异常堆栈
- `429`：Amazon API 限流，建议降频或检查 retry 逻辑
- `401/403`：鉴权失败，检查 token 是否过期

**接口路径分析**：
- 路径含 `/power-bi/` → Amazon 广告 API 相关
- 路径含 `/amc/` → AMC 受众相关
- 路径含 `/walmart/` → Walmart 广告相关

**消息聚类分析**：
- 若错误信息为空（`by_message` 为空）但 `by_path` 有数据，说明报错都是 HTTP 非 2xx，无异常堆栈
- 若有 "database" / "connection" 关键词，优先排查 DB 连接
- 若有 "timeout" / "timed out"，优先排查外部 API 超时

**无数据时**：
```
该时段 ads-backend 未发现 error/warning 级别日志。
建议：
  1. 扩大查询时间范围
  2. 确认 DataKit 日志采集是否正常（观测云 → 基础设施 → 查看最新日志时间）
```

---

## 异常处理

| 场景 | 处理方式 |
|------|---------|
| 凭据未配置 | 引导配置 |
| 网络失败 | 重试一次，仍失败提示检查 VPN/内网 |
| 查询超时 | 缩小时间范围重试 |
| API 返回 404 | 自动尝试备用端点（脚本内部处理） |
| 无日志数据 | 提示扩大范围或检查采集状态 |
