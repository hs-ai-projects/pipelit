---
name: guance-log-analysis
description: >
  观测云日志分析。触发词："观测云"、"查日志"、"查报错"、"接口报错"、"分析错误"、"guance logs"。
  拉取 ads-backend 指定时段的错误日志，按状态码/接口路径/错误信息三维聚合，输出分析报告。
---

# 观测云日志分析

分析 `ads-backend` 的错误日志，定位接口报错根因。

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
