# Lesson Sniffer 试验 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现一个 SessionEnd hook 驱动的"用户纠正"自动抽取试验脚本，跑一周看效果，不污染 pipelit 主体。

**Architecture:** 单一 Python 脚本 `sniff.py` 由 Claude Code SessionEnd hook 触发；从 stdin JSON 拿 `session_id`/`transcript_path`（缺失则扫 `~/.claude/projects/` 找最新 jsonl 兜底），过滤 feishu-dev 会话，调 haiku 抽取一条 lesson，追加到 jsonl。失败全静默 (`exit 0`)。整个试验目录通过 `.gitignore` 隔离，pipelit 主体 0 改动。

**Tech Stack:** Python 3.10+ / `anthropic` SDK / pytest（仅纯函数单测）/ bash 脚本 / Python 处理 JSON（不依赖 jq）

**参考 design doc:** `docs/superpowers/specs/2026-06-03-lesson-sniffer-experiment-design.md`

---

## File Structure

| 文件 | 责任 | 操作 |
|---|---|---|
| `scripts/experiments/lesson_sniffer/sniff.py` | 主分析器 | Create |
| `scripts/experiments/lesson_sniffer/test_sniff.py` | 纯函数单测（pytest） | Create |
| `scripts/experiments/lesson_sniffer/install_hook.sh` | 装 hook | Create |
| `scripts/experiments/lesson_sniffer/uninstall_hook.sh` | 拔 hook | Create |
| `scripts/experiments/lesson_sniffer/README.md` | 试验说明 + 卸载步骤 | Create |
| `.gitignore` | 加一行 `scripts/experiments/` | Modify |

---

## Task 1: 建目录骨架 + .gitignore

**Files:**
- Modify: `.gitignore`
- Create: `scripts/experiments/lesson_sniffer/` (目录占位)

- [ ] **Step 1: 检查 .gitignore 当前内容**

读 `.gitignore`，确认没有现成的 `scripts/experiments/` 条目。

```bash
cat .gitignore | grep -i experiments || echo "no existing entry"
```

预期：输出 `no existing entry`

- [ ] **Step 2: 追加 .gitignore 条目**

在 `.gitignore` 末尾追加：

```
# Scratch experiments (per-engineer, never shared)
scripts/experiments/
```

- [ ] **Step 3: 创建试验目录**

```bash
mkdir -p scripts/experiments/lesson_sniffer
```

- [ ] **Step 4: 验证 .gitignore 生效**

```bash
touch scripts/experiments/lesson_sniffer/.placeholder
git status --short scripts/experiments/ 2>&1
```

预期：**空输出**（目录被 ignore，不显示 untracked）

```bash
rm scripts/experiments/lesson_sniffer/.placeholder
```

- [ ] **Step 5: Commit**

```bash
git add .gitignore
git commit -m "chore: gitignore scratch experiments dir"
```

---

## Task 2: README.md（试验说明）

**Files:**
- Create: `scripts/experiments/lesson_sniffer/README.md`

> 注意：这个文件**不进 git**（在 ignored 目录里），是给自己看的备忘。

- [ ] **Step 1: 写 README**

内容：

```markdown
# Lesson Sniffer (scratch experiment)

> **状态**：一周试验中。**不**进 pipelit marketplace、**不**给别人用。
> **设计文档**：`docs/superpowers/specs/2026-06-03-lesson-sniffer-experiment-design.md`

## 目的

测试：用 SessionEnd hook + haiku，能否自动从对话里抽出"用户纠正过 AI"的边界 case 沉淀成 jsonl。

## 安装（一次性）

需要环境变量 `ANTHROPIC_API_KEY`（已有就跳过）。

```bash
cd <pipelit-repo>
bash scripts/experiments/lesson_sniffer/install_hook.sh
```

会往 `~/.claude/settings.json` 的 `hooks.SessionEnd` 数组追加一项。已存在就 skip 不重复加。

## 使用

零交互。正常用 Claude Code 跑 `feishu-dev`。会话结束时（关终端 / `/exit` / `/clear` / `/resume`），后台触发 sniff，结果写到本目录 `lessons.jsonl`。

## 一周后评价

```bash
cat scripts/experiments/lesson_sniffer/lessons.jsonl | python -m json.tool
```

逐条评分 `useful` / `noise` / `wrong`，门槛 useful ≥ 50% 且非 null ≥ 5 条。

## 卸载

```bash
bash scripts/experiments/lesson_sniffer/uninstall_hook.sh
rm -rf scripts/experiments/lesson_sniffer/
```

## 调试

- 静默失败的 stderr 写到 `sniff.err.log`
- 手工触发：`echo '{"session_id":"...","reason":"clear"}' | python sniff.py`
```

- [ ] **Step 2: 验证文件存在**

```bash
ls -la scripts/experiments/lesson_sniffer/README.md
```

预期：文件存在，约 1-2 KB

- [ ] **Step 3: 不需要 commit**（在 .gitignore 里）

跳过。

---

## Task 3: sniff.py 纯函数 + 单测（TDD 部分）

抽出 3 个纯函数做 TDD：
- `session_involves_feishu_dev(log_path: Path) -> bool`：扫 log 文件找 feishu-dev 关键词
- `extract_dialogue(log_path: Path) -> str`：从 jsonl session log 抽 user+assistant 文本
- `parse_llm_output(raw: str) -> dict`：解析 haiku 返回的 JSON（容错）

**Files:**
- Create: `scripts/experiments/lesson_sniffer/test_sniff.py`
- Create: `scripts/experiments/lesson_sniffer/sniff.py`（暂时只放纯函数）

### Step 3.1: 写 session_involves_feishu_dev 测试

- [ ] **Step 3.1.1: 写测试**

`scripts/experiments/lesson_sniffer/test_sniff.py`:

```python
"""Lesson sniffer pure-function tests. Run: pytest test_sniff.py -v"""
import json
from pathlib import Path

import pytest

from sniff import session_involves_feishu_dev, extract_dialogue, parse_llm_output


def make_log(tmp_path: Path, entries: list[dict]) -> Path:
    """Helper: write list of dicts as jsonl, return path."""
    log = tmp_path / "session.jsonl"
    log.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")
    return log


# --- session_involves_feishu_dev ---

def test_session_with_feishu_dev_keyword_is_detected(tmp_path):
    log = make_log(tmp_path, [
        {"role": "user", "content": "/feishu-dev 7234"},
        {"role": "assistant", "content": "..."},
    ])
    assert session_involves_feishu_dev(log) is True


def test_session_with_skill_name_is_detected(tmp_path):
    log = make_log(tmp_path, [
        {"role": "user", "content": "帮我做飞书任务"},
        {"role": "assistant", "content": "我用 feishu-dev skill 处理"},
    ])
    assert session_involves_feishu_dev(log) is True


def test_unrelated_session_returns_false(tmp_path):
    log = make_log(tmp_path, [
        {"role": "user", "content": "帮我看下这段 Python 代码"},
        {"role": "assistant", "content": "好的"},
    ])
    assert session_involves_feishu_dev(log) is False


def test_missing_file_returns_false(tmp_path):
    assert session_involves_feishu_dev(tmp_path / "nope.jsonl") is False
```

- [ ] **Step 3.1.2: 跑测试看它 fail**

```bash
cd scripts/experiments/lesson_sniffer
python -m pytest test_sniff.py::test_session_with_feishu_dev_keyword_is_detected -v 2>&1 | head -20
```

预期：`ImportError` 或 `AttributeError`，因为 sniff.py 还没有 `session_involves_feishu_dev`

- [ ] **Step 3.1.3: 实现 session_involves_feishu_dev**

创建 `scripts/experiments/lesson_sniffer/sniff.py`（暂时只放这一个函数 + 必要 imports）：

```python
"""Lesson sniffer — SessionEnd hook analyzer (scratch experiment).

Reads conversation log of a just-ended Claude Code session, decides whether
it involved feishu-dev, and if so asks haiku to extract one user-correction
lesson, appended to lessons.jsonl. All failures are silent (exit 0).
"""
from __future__ import annotations

from pathlib import Path


FEISHU_DEV_MARKERS = ("feishu-dev", "/feishu-dev", "飞书任务", "feishu_api")


def session_involves_feishu_dev(log_path: Path) -> bool:
    """Return True if the session log mentions feishu-dev markers."""
    try:
        text = log_path.read_text(encoding="utf-8", errors="ignore")
    except (FileNotFoundError, OSError):
        return False
    return any(m in text for m in FEISHU_DEV_MARKERS)
```

- [ ] **Step 3.1.4: 跑测试看它 pass**

```bash
python -m pytest test_sniff.py::test_session_with_feishu_dev_keyword_is_detected test_sniff.py::test_session_with_skill_name_is_detected test_sniff.py::test_unrelated_session_returns_false test_sniff.py::test_missing_file_returns_false -v
```

预期：4 个 test 全 PASS

- [ ] **Step 3.1.5: Commit**

> 注：`scripts/experiments/` 在 .gitignore 里，所以这次 commit 实际只在本地工作区有效，不会进 git 历史。**这步直接跳过**，进 Step 3.2。

跳过。

### Step 3.2: extract_dialogue 测试 + 实现

- [ ] **Step 3.2.1: 追加测试**

把以下内容追加到 `test_sniff.py`:

```python
# --- extract_dialogue ---

def test_extract_keeps_user_and_assistant_text(tmp_path):
    log = make_log(tmp_path, [
        {"role": "user", "content": "请帮我"},
        {"role": "assistant", "content": "好的"},
        {"role": "user", "content": "再来一次"},
    ])
    out = extract_dialogue(log)
    assert "请帮我" in out
    assert "好的" in out
    assert "再来一次" in out


def test_extract_drops_tool_results(tmp_path):
    log = make_log(tmp_path, [
        {"role": "user", "content": "跑 ls"},
        {"role": "assistant", "content": "好"},
        {"role": "tool_result", "content": "file1\nfile2"},
        {"role": "user", "content": "好的"},
    ])
    out = extract_dialogue(log)
    assert "file1" not in out
    assert "跑 ls" in out


def test_extract_skips_malformed_lines(tmp_path):
    log = tmp_path / "session.jsonl"
    log.write_text(
        '{"role":"user","content":"ok"}\n'
        'this is not json\n'
        '{"role":"assistant","content":"fine"}\n',
        encoding="utf-8",
    )
    out = extract_dialogue(log)
    assert "ok" in out
    assert "fine" in out


def test_extract_handles_missing_file(tmp_path):
    assert extract_dialogue(tmp_path / "nope.jsonl") == ""
```

- [ ] **Step 3.2.2: 跑测试看它 fail**

```bash
python -m pytest test_sniff.py -k extract -v 2>&1 | head -20
```

预期：`ImportError: cannot import name 'extract_dialogue'`

- [ ] **Step 3.2.3: 实现 extract_dialogue**

追加到 `sniff.py`:

```python
import json

DIALOGUE_ROLES = ("user", "assistant")


def extract_dialogue(log_path: Path) -> str:
    """Read jsonl session log, return concatenated user+assistant text.

    Tool results, system messages, and malformed lines are dropped.
    """
    try:
        raw = log_path.read_text(encoding="utf-8", errors="ignore")
    except (FileNotFoundError, OSError):
        return ""
    chunks: list[str] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        role = obj.get("role")
        if role not in DIALOGUE_ROLES:
            continue
        content = obj.get("content")
        if isinstance(content, str):
            chunks.append(f"[{role}] {content}")
        elif isinstance(content, list):
            # claude format: content is list of {type, text} blocks
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    chunks.append(f"[{role}] {block.get('text', '')}")
    return "\n".join(chunks)
```

- [ ] **Step 3.2.4: 跑测试看它 pass**

```bash
python -m pytest test_sniff.py -k extract -v
```

预期：4 个 test 全 PASS

### Step 3.3: parse_llm_output 测试 + 实现

- [ ] **Step 3.3.1: 追加测试**

```python
# --- parse_llm_output ---

def test_parse_valid_lesson():
    raw = '{"lesson": "use venv python", "why": "no lark_oapi", "tags": ["server"]}'
    out = parse_llm_output(raw)
    assert out["lesson"] == "use venv python"
    assert out["why"] == "no lark_oapi"
    assert out["tags"] == ["server"]


def test_parse_null_lesson():
    raw = '{"lesson": null, "reason": "no correction"}'
    out = parse_llm_output(raw)
    assert out["lesson"] is None
    assert out["reason"] == "no correction"


def test_parse_with_markdown_fence():
    # haiku sometimes wraps JSON in ```json ... ```
    raw = '```json\n{"lesson": "x", "why": "y", "tags": []}\n```'
    out = parse_llm_output(raw)
    assert out["lesson"] == "x"


def test_parse_malformed_returns_malformed_marker():
    out = parse_llm_output("definitely not json")
    assert out["lesson"] is None
    assert "malformed" in out["reason"].lower()
```

- [ ] **Step 3.3.2: 跑测试看它 fail**

```bash
python -m pytest test_sniff.py -k parse -v 2>&1 | head -10
```

预期：`ImportError`

- [ ] **Step 3.3.3: 实现 parse_llm_output**

追加到 `sniff.py`:

```python
import re

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def parse_llm_output(raw: str) -> dict:
    """Parse haiku's response. Tolerate markdown fences and malformed output.

    Returns a dict with at minimum a `lesson` key (str or None).
    Malformed output returns {"lesson": None, "reason": "llm output malformed"}.
    """
    text = raw.strip()
    # strip markdown fence if present
    m = _JSON_FENCE_RE.search(text)
    if m:
        text = m.group(1)
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        return {"lesson": None, "reason": "llm output malformed"}
    if not isinstance(obj, dict):
        return {"lesson": None, "reason": "llm output not an object"}
    return obj
```

- [ ] **Step 3.3.4: 跑测试看它 pass**

```bash
python -m pytest test_sniff.py -v
```

预期：所有 test 全 PASS（4 + 4 + 4 = 12 个）

---

## Task 4: sniff.py main() 串联

把纯函数串起来，加 stdin 解析、log 路径定位、haiku 调用、jsonl 写入。**这部分不写单测**，靠 Task 6 端到端 smoke 验证。

**Files:**
- Modify: `scripts/experiments/lesson_sniffer/sniff.py`

- [ ] **Step 4.1: 加 main 函数与入口**

追加到 `sniff.py` 末尾：

```python
import os
import sys
from datetime import datetime


HOME = Path.home()
LESSONS_FILE = Path(__file__).parent / "lessons.jsonl"
ERR_LOG = Path(__file__).parent / "sniff.err.log"
HAIKU_MODEL = "claude-haiku-4-5-20251001"
LLM_TIMEOUT = 30


PROMPT_TEMPLATE = """你是会话审计员。下面是一段我和 AI 助手的对话日志。

任务：判断对话中是否出现「用户纠正/反驳/补充了 AI 的某个行为或假设」。

规则：
- 「纠正」=用户明确指出 AI 做错、做漏、做反、用错工具/路径/方式
- 一般性补充信息（"项目用的是 Vue 3"）不算纠正
- 用户的"嗯"、"好"、"你说得对"不算纠正
- 一次会话最多抽 1 条最重要的纠正

输出（严格 JSON，无 markdown 包裹）：
- 有纠正 → {{"lesson": "...", "why": "...", "tags": ["...", "..."]}}
- 没纠正 → {{"lesson": null, "reason": "..."}}

对话日志：
<<<
{conversation}
>>>"""


def find_session_log(stdin_payload: dict) -> Path | None:
    """Locate the session log file.

    Strategy:
      1. If stdin_payload has `transcript_path` and it exists → use it
      2. Else scan ~/.claude/projects/**/*.jsonl, return newest by mtime
    """
    candidate = stdin_payload.get("transcript_path")
    if candidate:
        p = Path(candidate)
        if p.exists():
            return p
    projects_dir = HOME / ".claude" / "projects"
    if not projects_dir.exists():
        return None
    jsonls = list(projects_dir.rglob("*.jsonl"))
    if not jsonls:
        return None
    return max(jsonls, key=lambda p: p.stat().st_mtime)


def call_haiku(dialogue: str) -> str | None:
    """Send dialogue to haiku, return raw response text or None on failure."""
    try:
        from anthropic import Anthropic  # type: ignore
    except ImportError:
        return None
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    try:
        client = Anthropic(api_key=api_key, timeout=LLM_TIMEOUT)
        resp = client.messages.create(
            model=HAIKU_MODEL,
            max_tokens=512,
            messages=[{"role": "user", "content": PROMPT_TEMPLATE.format(conversation=dialogue)}],
        )
        # response.content is a list of blocks; first text block is what we want
        for block in resp.content:
            if getattr(block, "type", None) == "text":
                return block.text
        return None
    except Exception:
        return None


def append_lesson(record: dict) -> None:
    """Append a single record to lessons.jsonl (best-effort)."""
    try:
        LESSONS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LESSONS_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass


def _log_err(msg: str) -> None:
    try:
        with ERR_LOG.open("a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().isoformat()}] {msg}\n")
    except OSError:
        pass


def main() -> int:
    try:
        payload_raw = sys.stdin.read()
        payload = json.loads(payload_raw) if payload_raw.strip() else {}
    except json.JSONDecodeError:
        _log_err("stdin not valid json")
        return 0

    log_path = find_session_log(payload)
    if not log_path:
        _log_err("session log not found")
        return 0

    if not session_involves_feishu_dev(log_path):
        return 0  # not a feishu-dev session, skip silently

    dialogue = extract_dialogue(log_path)
    if not dialogue:
        _log_err("empty dialogue extracted")
        return 0

    raw = call_haiku(dialogue)
    if raw is None:
        append_lesson({
            "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
            "session_id": payload.get("session_id"),
            "lesson": None,
            "reason": "haiku unavailable or failed",
        })
        return 0

    parsed = parse_llm_output(raw)
    record = {
        "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
        "session_id": payload.get("session_id"),
        **parsed,
    }
    append_lesson(record)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4.2: 跑单元测试确保纯函数没坏**

```bash
python -m pytest test_sniff.py -v
```

预期：12 个 test 全 PASS

- [ ] **Step 4.3: 手工 smoke test（不调真 haiku）**

构造一个最小 stdin + 一个假的 session log，看 sniff.py 行为：

```bash
# 准备假 log
TMPLOG=$(mktemp --suffix=.jsonl)
cat > "$TMPLOG" <<'EOF'
{"role":"user","content":"/feishu-dev 7234"}
{"role":"assistant","content":"我开始处理"}
{"role":"user","content":"不对，服务器要用 venv 的 python"}
EOF

# 跑 sniff（先不带 API key，期望 lesson=null with reason）
ANTHROPIC_API_KEY="" python sniff.py <<EOF
{"session_id":"smoke-001","reason":"clear","transcript_path":"$TMPLOG"}
EOF

# 看产物
cat lessons.jsonl

rm "$TMPLOG"
```

预期：
- `lessons.jsonl` 多了一行 `{"ts":"...","session_id":"smoke-001","lesson":null,"reason":"haiku unavailable or failed"}`
- 退出码 0

- [ ] **Step 4.4: 手工 smoke test（带真 haiku，可选）**

需要 `ANTHROPIC_API_KEY` 已设置。

```bash
# 同上准备假 log
TMPLOG=$(mktemp --suffix=.jsonl)
cat > "$TMPLOG" <<'EOF'
{"role":"user","content":"/feishu-dev 7234"}
{"role":"assistant","content":"我用 python3 启动 bot"}
{"role":"user","content":"不对，服务器要用 ~/pipelit/.venv/bin/python，不能用系统 python3，找不到 lark_oapi"}
{"role":"assistant","content":"了解，改用 venv"}
EOF

python sniff.py <<EOF
{"session_id":"smoke-002","reason":"clear","transcript_path":"$TMPLOG"}
EOF

cat lessons.jsonl
rm "$TMPLOG"
```

预期：`lessons.jsonl` 末尾多一行 `lesson` 非 null，内容大致是"服务器用 venv 的 python"。

如果失败 → 看 `sniff.err.log`，调整 prompt 或代码。

---

## Task 5: install_hook.sh / uninstall_hook.sh

**Files:**
- Create: `scripts/experiments/lesson_sniffer/install_hook.sh`
- Create: `scripts/experiments/lesson_sniffer/uninstall_hook.sh`

不写自动化测试，靠手工跑 + 检查 settings.json diff 验证。

- [ ] **Step 5.1: 写 install_hook.sh**

```bash
#!/usr/bin/env bash
# Install lesson-sniffer SessionEnd hook into ~/.claude/settings.json.
# Idempotent: skips if already installed.
set -euo pipefail

SETTINGS="$HOME/.claude/settings.json"
HOOK_DIR="$(cd "$(dirname "$0")" && pwd)"
SNIFF_PY="$HOOK_DIR/sniff.py"
MARKER="lesson_sniffer/sniff.py"

if [[ ! -f "$SETTINGS" ]]; then
  echo "ERROR: $SETTINGS not found. Is Claude Code installed?" >&2
  exit 1
fi

if [[ ! -f "$SNIFF_PY" ]]; then
  echo "ERROR: $SNIFF_PY not found." >&2
  exit 1
fi

# Idempotency check
if grep -q "$MARKER" "$SETTINGS"; then
  echo "Already installed. Skipping."
  exit 0
fi

# Backup
cp "$SETTINGS" "$SETTINGS.bak.$(date +%Y%m%d-%H%M%S)"

# Use Python (not jq) for cross-platform JSON edit
python3 - "$SETTINGS" "$SNIFF_PY" <<'PY'
import json, sys
from pathlib import Path

settings_path = Path(sys.argv[1])
sniff_path = sys.argv[2]

obj = json.loads(settings_path.read_text(encoding="utf-8"))
hooks = obj.setdefault("hooks", {})
session_end = hooks.setdefault("SessionEnd", [])

# python may live at different paths; use sys.executable as the canonical command
python_cmd = sys.executable

session_end.append({
    "hooks": [
        {
            "type": "command",
            "command": f'"{python_cmd}" "{sniff_path}"',
            "timeout": 45,
        }
    ]
})

settings_path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"Installed. Backup saved alongside.")
PY
```

- [ ] **Step 5.2: 写 uninstall_hook.sh**

```bash
#!/usr/bin/env bash
# Remove lesson-sniffer SessionEnd hook from ~/.claude/settings.json.
set -euo pipefail

SETTINGS="$HOME/.claude/settings.json"
MARKER="lesson_sniffer/sniff.py"

if [[ ! -f "$SETTINGS" ]]; then
  echo "ERROR: $SETTINGS not found." >&2
  exit 1
fi

if ! grep -q "$MARKER" "$SETTINGS"; then
  echo "Not installed. Nothing to do."
  exit 0
fi

cp "$SETTINGS" "$SETTINGS.bak.$(date +%Y%m%d-%H%M%S)"

python3 - "$SETTINGS" <<'PY'
import json, sys
from pathlib import Path

settings_path = Path(sys.argv[1])
obj = json.loads(settings_path.read_text(encoding="utf-8"))
hooks = obj.get("hooks", {})
session_end = hooks.get("SessionEnd", [])

# Filter out any hook entry whose command contains the marker
filtered = []
for entry in session_end:
    cmds = entry.get("hooks", [])
    cmds_kept = [c for c in cmds if "lesson_sniffer/sniff.py" not in c.get("command", "")]
    if cmds_kept:
        entry["hooks"] = cmds_kept
        filtered.append(entry)
hooks["SessionEnd"] = filtered

# Clean up empty SessionEnd key
if not filtered:
    hooks.pop("SessionEnd", None)

settings_path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")
print("Uninstalled.")
PY
```

- [ ] **Step 5.3: 给两个脚本加执行权限**

```bash
chmod +x scripts/experiments/lesson_sniffer/install_hook.sh
chmod +x scripts/experiments/lesson_sniffer/uninstall_hook.sh
```

- [ ] **Step 5.4: 跑 install 验证**

**Pre-check**：先看 settings.json 现状

```bash
python3 -c "import json; print(json.dumps(json.load(open('$HOME/.claude/settings.json'))['hooks'].keys() if 'hooks' in json.load(open('$HOME/.claude/settings.json')) else {}, default=list))"
```

记录当前 `hooks` 有哪些 keys。

```bash
bash scripts/experiments/lesson_sniffer/install_hook.sh
```

预期输出：`Installed. Backup saved alongside.`

**验证**：

```bash
python3 -c "
import json
obj = json.load(open('$HOME/.claude/settings.json'))
se = obj.get('hooks', {}).get('SessionEnd', [])
print(f'SessionEnd entries: {len(se)}')
for e in se:
    for h in e.get('hooks', []):
        print(' -', h.get('command'))
"
```

预期：至少 1 个 entry，command 含 `lesson_sniffer/sniff.py`

- [ ] **Step 5.5: 跑 install 第二次验证幂等**

```bash
bash scripts/experiments/lesson_sniffer/install_hook.sh
```

预期输出：`Already installed. Skipping.`

- [ ] **Step 5.6: 跑 uninstall 验证**

```bash
bash scripts/experiments/lesson_sniffer/uninstall_hook.sh
```

预期：`Uninstalled.`

```bash
python3 -c "
import json
obj = json.load(open('$HOME/.claude/settings.json'))
se = obj.get('hooks', {}).get('SessionEnd', [])
print(f'SessionEnd entries: {len(se)}')
"
```

预期：`SessionEnd entries: 0` 或 SessionEnd 整个 key 不存在

- [ ] **Step 5.7: 重新装回，准备做端到端 smoke**

```bash
bash scripts/experiments/lesson_sniffer/install_hook.sh
```

预期：`Installed.`

---

## Task 6: 端到端 smoke + 启动一周试验

**Files:** 不创建新文件，纯验证 + 记录

- [ ] **Step 6.1: 端到端 smoke test**

在一个**新的 Claude Code 会话**里：

1. 打开 Claude Code
2. 跑 `/feishu-dev` 列出任务（或随便和它聊几句包含 "feishu-dev" 关键词）
3. 故意纠正它一次（"不对，X 应该用 Y"）
4. `/exit` 或 `/clear` 关闭会话

会话结束后，检查产物：

```bash
cat scripts/experiments/lesson_sniffer/lessons.jsonl | tail -5
cat scripts/experiments/lesson_sniffer/sniff.err.log 2>/dev/null | tail -10
```

**期望（pass）**：`lessons.jsonl` 多了至少一行新记录

**常见 fail 模式**：
| 现象 | 排查 |
|---|---|
| jsonl 没新行 | 看 sniff.err.log。常见：找不到 session log、hook 没触发 |
| hook 没触发 | `python3 -c "import json; print(json.load(open('$HOME/.claude/settings.json'))['hooks'].get('SessionEnd'))"` |
| `haiku unavailable` | 检查 `ANTHROPIC_API_KEY` |
| 找不到 session log | sniff 的 fallback 是按 mtime 找最新 jsonl；检查 `~/.claude/projects/` 是否存在 |

- [ ] **Step 6.2: 标记试验开始时间**

```bash
echo "Trial started: $(date -Iseconds)" > scripts/experiments/lesson_sniffer/TRIAL_START.txt
cat scripts/experiments/lesson_sniffer/TRIAL_START.txt
```

- [ ] **Step 6.3: 一周后评价（占位提醒）**

在日历 / TODO 系统里设一个 2026-06-10 的提醒：
- 打开 `lessons.jsonl`
- 逐条标 `useful` / `noise` / `wrong`
- 看 design doc §8 的门槛
- 决定继续 / 改 prompt / 删

---

## 自查

**Spec coverage（对照 design doc）**：

| Design doc 节 | 对应 Task |
|---|---|
| §3 文件清单 | Task 1, 2, 3, 4, 5 |
| §4 触发链路 | Task 4（main 函数实现）|
| §5 数据 schema | Task 4 Step 4.1（append_lesson 调用处）|
| §6 LLM prompt | Task 4 Step 4.1（PROMPT_TEMPLATE）|
| §7 隔离设计 | Task 1（.gitignore）+ 文件树都在 experiments/ |
| §8 评价标准 | Task 6 Step 6.3 |
| §9 错误处理 | Task 4 Step 4.1（全 try/except + exit 0）|

**Placeholder scan**: 无 TBD / TODO / "implement later"。

**Type consistency**:
- `session_involves_feishu_dev`、`extract_dialogue`、`parse_llm_output`、`find_session_log`、`call_haiku`、`append_lesson`、`main` 在 Task 3-4 内命名前后一致 ✓
- `Path` import 在 Step 3.1.3、`json` import 在 Step 3.2.3、`re` import 在 Step 3.3.3 都有定义 ✓
- 已知小问题：`Step 4.1` 里 `import json` 已经在 Step 3.2.3 里 import 过了，重复 import 不会出错但风格不好。**fix**: Step 4.1 不再单独 import json/sys/os/datetime，假设它们在 sniff.py 顶部已经有了一份。让我标注一下。

> **Note 给执行者**：sniff.py 顶部的 import 区在 Step 3.1.3 / 3.2.3 / 3.3.3 / 4.1 累积。最终的 imports 区应该是：
> ```python
> from __future__ import annotations
> import json
> import os
> import re
> import sys
> from datetime import datetime
> from pathlib import Path
> ```
> 把它们合并到文件顶部，不要散落在多处。

**风险点**：
1. `find_session_log` 的"按 mtime 找最新"是 best-effort，可能在并发会话时拿错文件。试验阶段可接受。
2. `transcript_path` 字段名是猜测（Claude Code 文档没明确确认）。如果 stdin payload 里实际叫别的名（如 `session_log_path`），fallback 会兜底。
3. SessionEnd 触发条件可能不包括所有"退出方式"（如直接关终端窗口）。Trial 期间观察 sniff.err.log 看是否有遗漏。

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-03-lesson-sniffer-experiment.md`.

**Two execution options:**

1. **Subagent-Driven (recommended)** — 我用 fresh subagent 跑每个 Task，task 间 review。隔离干净、迭代快
2. **Inline Execution** — 在当前会话直接跑 task，带 checkpoint review

**告诉我选哪个。或者你想先看一遍 plan、改完再执行也行。**
