# Pipelit FAQ

> 已知坑 + 解决方法。遇到问题先查这里。

---

## 飞书 / 凭据

**Q: `{"error": "凭据未配置"}` 怎么办？**

运行以下命令初始化凭据：

```bash
PYTHONIOENCODING=utf-8 python3 scripts/feishu_api.py save_config <app_id> <app_secret>
```

然后需要完成飞书 OAuth 授权（用于访问个人任务）：

```bash
python3 scripts/feishu_api.py print_auth_url   # 打印授权链接
# 浏览器打开链接，授权后复制 code
python3 scripts/feishu_api.py exchange_code <code>
```

---

**Q: 任务拉不到 / 权限报错**

确认飞书应用已申请并获批以下权限：
- `task:task:read`
- `task:task:writeonly`
- `task:comment:write`
- `task:attachment:read`

应用需要发布审核通过才能调用 API。

---

**Q: 任务里有视频附件，但 AI 没分析**

视频附件不做自动分析，只下载到本地。路径会在 Phase 1.2 输出：

```
[1.2] 发现 1 个视频附件，已下载到本地，需人工查看：
  - C:\Users\xxx\.claude\pipelit\attachments\<task_id>\video.mp4
```

用本地播放器查看后告知 AI 关键内容即可。

---

## 日志分析

**Q: `GUANCE_NOT_CONFIGURED` 是什么？**

观测云凭据未配置，属于正常静默跳过，不影响后续流程。AI 会在 Phase 1.8d 输出一行 log 说明，Plan 里不显示日志摘要。

配置观测云：

```bash
python3 scripts/guance_api.py save_config <api_key> <workspace_id>
```

---

**Q: 不用观测云，想关掉日志查询**

在 `~/.claude/pipelit/config.json` 设置：

```json
{"logProvider": "noop"}
```

此后 Phase 1.8d 直接跳过，不做任何日志查询。

---

**Q: 时间格式报错 `GUANCE_TIME_INVALID`**

时间必须是带时区的 ISO 8601 格式：

```
正确：2026-06-04T13:30:00+08:00
正确：2026-06-04T13:30:00Z
错误：2026/06/04 13:30
错误：2026-06-04 13:30
```

AI 在 Phase 1.8c 推断时间时应自动生成正确格式，如果报错说明时间推断逻辑有问题，可以手动指定时间窗口后重试。

---

## 发版

**Q: Push 成功了一半（PARTIAL_PUSHED）怎么恢复？**

说"继续发版"或 `/release resume`，会从 `.release-state.json` 读取状态，只补推失败的仓库。

---

**Q: 版本号判定不准（patch/minor/major 选错）**

版本号规则见 `skills/release/rules/version-bump.md`。如果触发了 breaking change 警告但你认为不是，Phase 2 预览时选"保持建议版本"。

---

**Q: 发版卡片里没有 @ 关注人**

两种可能：
1. commit body 没有 `Feishu-Task:` 字段 → 卡片没有任务关联，无法查关注人
2. `cardFeatures.atFollower` 被关掉 → 检查 `~/.claude/pipelit/config.json`

---

**Q: 不想要发版图片（不想依赖 OpenAI）**

在参数里设置 `"generate_image": false`，或全局关闭：

```json
{"cardFeatures": {"image": false}}
```

---

## feishu-dev 开发流程

**Q: 任务被判成 L3 但我觉得应该是 L2**

L3 通常因为：描述过短 / 候选文件 > 5 / 包含 L3 关键词（重构/架构/跨模块）。

可以在 Claude 对话里说"用 L2 流程处理这个任务"来 override。

---

**Q: Phase 3.5 要求用户验证但我想跳过（BOT_AUTO_EXECUTE）**

在 Claude Code 对话最开头加 `BOT_AUTO_EXECUTE`，feishu-dev 会跳过 Phase 3.5 的等待（但 Phase 3.5b 卡片预览仍会显示）。

---

**Q: `[MODE-CHECK] BOT_AUTO_EXECUTE: no` 是什么**

feishu-dev 启动时强制输出的模式检查行，正常现象。说明当前不在自动化模式，Phase 3.5 需要人工确认。

---

**Q: context 压缩后任务进度丢失怎么办**

feishu-dev 会在每个 Phase 结束时写 `.feishu-dev-state.json`。下次启动时说任务 ID，AI 会检测到状态文件并询问是否续接。

---

## Windows 特有问题

**Q: Python 命令报编码错误**

所有 python3 命令前加 `PYTHONIOENCODING=utf-8`：

```bash
PYTHONIOENCODING=utf-8 python3 scripts/feishu_api.py get_task_full <task_id>
```

---

**Q: git 命令报权限错误**

所有 git 命令用 `git -C "<path>"` 形式，不要用 `cd "<path>" && git`，否则触发额外权限提示。

---

**Q: 通知 hook 没有弹出**

检查 `.claude/settings.json` 里是否有：

```json
{
  "hooks": {
    "PreToolUse": [{"matcher": "AskUserQuestion", "hooks": [...]}]
  }
}
```

如果没有，运行 `/using-pipelit` 按提示配置，或手动复制 `docs/settings-template.json` 的 hooks 段。

---

## 调试

**Q: 查看最近的 L2/L3 判定记录**

```bash
python3 scripts/audit.py recent
```

**Q: 同一个任务跑两次结果不一样**

```bash
python3 scripts/audit.py diff <第一次日志路径> <第二次日志路径>
```

对比 `matched_rule` 和 `evidence` 字段，找出哪个因素变了。

---

**Q: 回归测试怎么跑**

```bash
PYTHONIOENCODING=utf-8 python3 tests/test_regression.py
```

16 个自动化验证点，通常 < 3 秒。改完 `scripts/` 后跑一遍再提交。
