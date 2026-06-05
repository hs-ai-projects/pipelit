# Case 05 — Release 双仓发版

> **目标**：验证 commit body 完整收集、卡片预览确认、无飞书任务降级。
> 对应反馈 #20（commit body 丢失）+ #22（预览确认）+ #4（无任务降级）。

---

## 输入

### 触发方式

```
发版
```

或 `/release`。

### 仓库状态

- 前端 + 后端两个仓库，都在 `master`，工作区干净
- 两个仓库自上次 tag 以来都有 commit
- **关键**：commit body 含 `Feishu-Task: <url>` 字段

### Mock commit 历史

构造 4 类 commit 覆盖测试：

```
commit A (feature merge, 有 Feishu-Task):
  Merge branch 'feat/feishu-12345678' into 'master'

  feat: 新增广告创意多选

  Feishu-Task: https://applink.feishu.cn/client/todo/detail?guid=12345678-aaaa-bbbb-cccc-...

commit B (直接 master 上的 fix, 有 Feishu-Task):
  fix: 修复数据统计错误

  Feishu-Task: https://applink.feishu.cn/client/todo/detail?guid=87654321-...

commit C (直接 master 上的 fix, 无 Feishu-Task):
  fix: 修一个小排版

commit D (chore):
  chore: 升级依赖
```

---

## 期望关键判定

### Phase 1.3 commit 收集（Task 1.1）

**正确命令**：

```bash
git log <last_tag>..HEAD --format="=== %h ===%n%B" --no-merges
git log <last_tag>..HEAD --format="=== %h ===%n%B" --merges
```

**不能用** `--oneline`（会丢 body）。

**解析期望**：

| Commit | 提取的 Feishu-Task | 来源 |
|---|---|---|
| A | `https://applink.feishu.cn/...12345678...` | merge commit body |
| B | `https://applink.feishu.cn/...87654321...` | fix commit body |
| C | （无） | body 无字段 |
| D | （过滤掉，chore 不进 changelog） | - |

### Phase 1.3 版本号判定（Task 2.3）

- 含 `feat:` → 建议 minor
- **但 Stage 2 Task 2.3 之后**：还要检测公共导出删除 / API 删除
- 如果只有 `fix:` → 建议 patch（修正反馈 #21）

### Phase 3.5b 卡片预览确认（Task 1.6 / #22 问题 2）

**必须出现预览**：

```
━━━ 卡片预览 ━━━
版本: v1.3.0
日期: 2026-06-05

新功能:
  • 广告创意多选  🔗 飞书任务（12345678）@ ou_xxx
修复:
  • 修复数据统计错误  🔗 飞书任务（87654321）@ ou_yyy
  • 修一个小排版  （无 @ 无链接）

图片来源: mascot 参考图 → OpenAI 生成

[请确认]
  ● 发送
  ○ 修改内容
  ○ 取消
━━━━━━━━━━━━━━━━━
```

### 无飞书任务降级（Task 1.5）

把所有 commit 的 `Feishu-Task:` 字段去掉重跑一遍：

- 预览里所有条目都不带 🔗
- 所有条目都不 @
- 发送流程不报错、不询问、不阻断
- 最终卡片正常发出（lark_md 没有 `<at id=...>` 标签）

---

## 期望 audit JSON 关键字段

```json
{
  "release_version": "v1.3.0",
  "tag_prefix": "v",
  "commits": [
    {"hash": "AAAA", "feishu_task": "...12345678...", "from": "merge_body"},
    {"hash": "BBBB", "feishu_task": "...87654321...", "from": "fix_body"},
    {"hash": "CCCC", "feishu_task": null, "from": "no_field"},
    {"hash": "DDDD", "filtered": "chore"}
  ],
  "version_bump_decision": {
    "rule": "rule-4-feat",
    "suggested": "minor",
    "warnings": []
  },
  "card_preview_confirmed": true
}
```

---

## 失败场景

| 现象 | 可能根因 | 回到 |
|---|---|---|
| changelog 飞书链接全错 / 全空 | `--oneline` 没改 body 格式 | Task 1.1 |
| commit A 的链接靠 fuzzy 匹配 | 没优先用 body 字段 | Task 1.1 |
| 卡片发送前没预览，直接发了 | Phase 3.5b 没插入 | Task 1.6 |
| 无 Feishu-Task 的 commit 导致流程报错 | 降级没做 | Task 1.5 |
| `fix:` 一堆但建议 minor | 版本号规则错 | Task 2.3 |
| 删了一个公共 export 但建议 patch | Task 2.3 检测未生效（Stage 2 之后才有） | Task 2.3 |

---

## 中断恢复测试（Stage 2 Task 2.2）

跑到 Phase 3 PUSHING 阶段，**手动 kill backend push**（断网或 ctrl+C）。

期望：

```
⚠️ partial_release
frontend ✅ 已推送 v1.3.0
backend  ❌ push 失败

.release-state.json 已写入
重启会话说"继续发版"或 /release resume 可续接
```

下一会话说"继续发版"：

- 读取 `.release-state.json`
- state = PARTIAL_PUSHED
- 跳过 precheck / dry-run / commit / tag
- 重试 backend push → 成功 → 进入 PUSHED → 生成 manifest/changelog/卡片

**不能**重新跑整个流程（重复 commit/tag 会冲突）。
