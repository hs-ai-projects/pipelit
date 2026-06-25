#!/usr/bin/env python3
"""
飞书 Bot 分析 & 执行核心 — 通用，不绑定任何具体项目或技术栈。

职责：
  1. _run_feishu_dev_analyze(task_id)  调用 feishu-dev BOT_ANALYZE_ONLY：Phase 1+2，输出分析结果
  2. execute(task_id, ...)             无交互执行：拉分支 → claude --print 改代码 → push → MR
  3. pipeline(task_id)                 完整流程入口（webhook 调用此函数）
  4. execute_from_pending(...)         处理"需求确认"按钮点击

通用化设计：
  - 不假设技术栈，claude 自己读 CLAUDE.md 和代码判断
  - MR 平台自动识别（GitLab / GitHub），解析 git remote URL
  - 所有配置从 config.json 读，支持环境变量覆盖
  - 可单独 CLI 调用，方便本地测试

用法：
  python3 feishu_bot_analyzer.py check                   检查所有配置项是否完整
  python3 feishu_bot_analyzer.py pipeline  <task_id>     完整流程
  python3 feishu_bot_analyzer.py analyze   <task_id>     只分析，输出 JSON
  python3 feishu_bot_analyzer.py execute   <task_id>     读 pending 直接执行
"""

import sys
import os
import json
import time
import re
import subprocess
import pathlib
import urllib.request
import urllib.parse
import urllib.error

# ── 路径 & 常量 ────────────────────────────────────────────────────────────────

PLUGIN_ROOT = pathlib.Path(
    os.environ.get("CLAUDE_PLUGIN_ROOT", pathlib.Path(__file__).parent.parent)
)
CACHE_DIR        = PLUGIN_ROOT / ".cache"
PENDING_DIR      = CACHE_DIR / "pending"         # 存待确认的需求分析
ANALYZED_DIR     = CACHE_DIR / "analyzed"        # 防抖：记录每个 task 上次分析时间
DEBOUNCE_SECONDS = int(os.environ.get("BOT_DEBOUNCE_SECONDS", 3600))  # 默认 1 小时

# 复用 feishu_api 的配置路径（~/.claude/pipelit/config.json），跟 longpoll 对齐
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from feishu_api import read_config, USER_CONFIG_DIR
LOG_DIR = USER_CONFIG_DIR / "webhook_logs"

# claude --print 使用的模型，支持环境变量覆盖
ANALYSIS_MODEL  = os.environ.get("BOT_ANALYSIS_MODEL",  "claude-sonnet-4-6")
EXECUTION_MODEL = os.environ.get("BOT_EXECUTION_MODEL", "claude-sonnet-4-6")


# ── 日志 ───────────────────────────────────────────────────────────────────────

def log(msg: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts   = time.strftime("%H:%M:%S")
    line = f"{ts} {msg}\n"
    with open(LOG_DIR / "webhook.log", "a", encoding="utf-8") as f:
        f.write(line)
    sys.stdout.write(line)
    sys.stdout.flush()


def log_section(title: str) -> None:
    """打印视觉分隔线，标识一个新的 pipeline 开始。"""
    bar  = "─" * 50
    line = f"\n{bar}\n{time.strftime('%H:%M:%S')} {title}\n{bar}"
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOG_DIR / "webhook.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


# ── 配置 ───────────────────────────────────────────────────────────────────────


def bot_cfg() -> dict:
    """
    读取 bot 配置，支持环境变量覆盖（适合多项目部署时用 env 区分）。

    环境变量优先级高于 config.json，方便在同一台服务器上用不同 env 跑多个项目：
      BOT_PROJECT_PATH   项目根目录（claude 在这里运行）
      BOT_NOTIFY_CHAT    通知发送目标 chat_id
      GITLAB_TOKEN       GitLab Personal Access Token
      GITHUB_TOKEN       GitHub Personal Access Token
    """
    cfg  = read_config().get("bot", {})
    return {
        "project_path":    os.environ.get("BOT_PROJECT_PATH",  cfg.get("project_path", "")),
        "notify_chat_id":  os.environ.get("BOT_NOTIFY_CHAT",   cfg.get("notify_chat_id", "")),
        "gitlab_token":    os.environ.get("GITLAB_TOKEN",      cfg.get("gitlab_token", "")),
        "github_token":    os.environ.get("GITHUB_TOKEN",      cfg.get("github_token", "")),
        "trigger_mode":    cfg.get("trigger_mode", "notify"),
        "user_id":         cfg.get("user_id", read_config().get("user_id", "")),
    }


# ── Feishu API 调用（复用 feishu_api.py）──────────────────────────────────────

def _detect_python() -> str:
    """检测本机可用的 Python 命令，按优先级依次尝试。"""
    for candidate in ["py", "python", "python3"]:
        try:
            r = subprocess.run([candidate, "--version"],
                               capture_output=True, timeout=5)
            if r.returncode == 0:
                return candidate
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    return "python3"  # 兜底，让错误信息更明确


def _feishu_api(*args: str) -> dict:
    """调用同目录的 feishu_api.py，返回解析后的 JSON。"""
    script = str(PLUGIN_ROOT / "scripts" / "feishu_api.py")
    env    = {**os.environ, "CLAUDE_PLUGIN_ROOT": str(PLUGIN_ROOT)}
    r = subprocess.run(
        [sys.executable, script, *args],
        capture_output=True, text=True, encoding='utf-8', timeout=20, env=env,
    )
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or "feishu_api error")
    return json.loads(r.stdout)


def send_card(chat_id: str, card: dict) -> None:
    if not chat_id:
        log("[send_card] notify_chat_id not set, skip")
        return
    try:
        _feishu_api("send_card", chat_id, json.dumps(card, ensure_ascii=False))
    except Exception as e:
        log(f"[send_card] failed: {e}")


def send_message(chat_id: str, text: str) -> None:
    if not chat_id:
        return
    try:
        _feishu_api("send_message", chat_id, text)
    except Exception as e:
        log(f"[send_message] failed: {e}")


# ── Claude 调用 ────────────────────────────────────────────────────────────────

def run_claude_api(prompt: str, model: str = ANALYSIS_MODEL, timeout: int = 60,
                   image_paths: list[str] | None = None) -> str:
    """
    直接调用 Anthropic SDK，不走 claude CLI，避免 CLAUDE.md / skill 路由干扰。
    支持传入本地图片路径列表（vision），图片会 base64 编码后附在消息里。
    """
    try:
        import anthropic, base64
    except ImportError:
        raise RuntimeError("请先安装：pip install anthropic")

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("环境变量 ANTHROPIC_API_KEY 未设置")

    # 构建 content：先放图片，再放文本
    content: list = []
    for img_path in (image_paths or []):
        try:
            p = pathlib.Path(img_path)
            if not p.exists():
                continue
            suffix  = p.suffix.lower().lstrip(".")
            media   = {"jpg": "image/jpeg", "jpeg": "image/jpeg",
                       "png": "image/png", "gif": "image/gif",
                       "webp": "image/webp"}.get(suffix, "image/png")
            b64data = base64.standard_b64encode(p.read_bytes()).decode("utf-8")
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": media, "data": b64data},
            })
            log(f"[claude-api] attached image: {p.name} ({len(b64data)//1024}KB)")
        except Exception as e:
            log(f"[claude-api] skip image {img_path}: {e}")
    content.append({"type": "text", "text": prompt})

    log(f"[claude-api] model={model} prompt_len={len(prompt)} images={len(image_paths or [])}")
    client = anthropic.Anthropic(api_key=api_key, timeout=timeout)
    msg = client.messages.create(
        model=model,
        max_tokens=1024,
        messages=[{"role": "user", "content": content}],
    )
    return msg.content[0].text



def _find_claude_bin() -> str:
    claude_bin = os.environ.get("CLAUDE_BIN", "claude")
    if claude_bin == "claude":
        for candidate in [
            r"D:\node\nodejs\claude.cmd",
            r"D:\node\nodejs\claude",
            "/usr/local/bin/claude",
        ]:
            if os.path.isfile(candidate):
                return candidate
    return claude_bin


def run_claude(prompt: str, cwd: str, model: str = EXECUTION_MODEL,
               timeout: int = 600,
               dangerously_skip_permissions: bool = False,
               system_prompt: str = "") -> str:
    """
    用 stream-json 模式运行 claude，实时打印工具调用过程，返回最终文本。

    stream-json 每行输出一个 JSON 事件，包括 tool_use、tool_result、text 等，
    比 --print 多了工具调用的实时可见性。
    """
    env = {**os.environ, "CLAUDE_PLUGIN_ROOT": str(PLUGIN_ROOT)}
    claude_bin = _find_claude_bin()
    cmd = [claude_bin, "--print", "--output-format", "stream-json", "--verbose",
           "--model", model, prompt]
    if dangerously_skip_permissions:
        cmd.append("--dangerously-skip-permissions")
    if system_prompt:
        cmd += ["--system-prompt", system_prompt]

    log(f"[claude] model={model} cwd={cwd} prompt_len={len(prompt)}")
    try:
        proc = subprocess.Popen(
            cmd, cwd=cwd, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
    except FileNotFoundError:
        raise RuntimeError(
            "claude 命令未找到。请先安装：npm install -g @anthropic-ai/claude-code"
        )

    import threading
    result_text: list[str] = []
    stderr_lines: list[str] = []

    def _read_stream(pipe):
        """解析 stream-json 事件，实时打出工具调用，收集最终文本。"""
        for raw_bytes in iter(pipe.readline, b""):
            raw = raw_bytes.decode("utf-8", errors="replace").rstrip()
            if not raw:
                continue
            try:
                ev = json.loads(raw)
            except json.JSONDecodeError:
                log(f"[claude:raw] {raw[:200]}")
                continue

            ev_type = ev.get("type", "")

            if ev_type == "assistant":
                # 消息块：可能包含 text 或 tool_use
                for block in ev.get("message", {}).get("content", []):
                    btype = block.get("type", "")
                    if btype == "text":
                        text = block.get("text", "").strip()
                        if text:
                            log(f"[claude:text] {text[:300]}")
                    elif btype == "tool_use":
                        name  = block.get("name", "")
                        inp   = block.get("input", {})
                        # 只展示最有用的字段
                        hint  = (inp.get("command") or inp.get("pattern") or
                                 inp.get("file_path") or str(inp)[:80])
                        log(f"[claude:tool] {name}({hint})")

            elif ev_type == "tool_result":
                content = ev.get("content", "")
                if isinstance(content, list):
                    content = " ".join(c.get("text", "") for c in content if isinstance(c, dict))
                log(f"[claude:result] {str(content)[:150]}")

            elif ev_type == "result":
                # 最终结果
                text = ev.get("result", "")
                if text:
                    result_text.append(text)
                cost = ev.get("cost_usd")
                if cost is not None:
                    log(f"[claude:done] cost=${cost:.4f}")

        pipe.close()

    def _read_stderr(pipe):
        for raw_bytes in iter(pipe.readline, b""):
            line = raw_bytes.decode("utf-8", errors="replace")
            stderr_lines.append(line)
            log(f"[claude:err] {line.rstrip()}")
        pipe.close()

    t_out = threading.Thread(target=_read_stream, args=(proc.stdout,), daemon=True)
    t_err = threading.Thread(target=_read_stderr, args=(proc.stderr,), daemon=True)
    t_out.start(); t_err.start()

    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise RuntimeError(f"claude 超时（>{timeout}s），任务可能过于复杂")

    t_out.join(); t_err.join()

    if proc.returncode != 0:
        stderr_text = "".join(stderr_lines)[:300]
        raise RuntimeError(f"claude 退出码 {proc.returncode}：{stderr_text}")

    return "".join(result_text)


def parse_json_from_output(text: str) -> dict:
    """
    从 claude --print 的输出中提取 JSON。
    兼容三种格式：裸 JSON / ```json ... ``` / 混有解释文字的输出。
    """
    # 先尝试 ```json 代码块
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    # 找第一个 { 开始位置，用 JSONDecoder 流式解析，只取第一个完整对象
    decoder = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch == '{':
            try:
                obj, _ = decoder.raw_decode(text, i)
                return obj
            except json.JSONDecodeError:
                continue
    raise ValueError(f"输出中未找到 JSON：{text[:200]}")


# ── Git 操作 ───────────────────────────────────────────────────────────────────

def git(args: list[str], cwd: str) -> str:
    """执行 git 命令，失败时抛出 RuntimeError。"""
    r = subprocess.run(
        ["git", *args], cwd=cwd,
        capture_output=True, text=True, timeout=30,
    )
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout.strip()


def get_default_branch(cwd: str) -> str:
    """获取仓库默认分支（main 或 master）。"""
    try:
        ref = git(["symbolic-ref", "refs/remotes/origin/HEAD"], cwd)
        return ref.split("/")[-1]   # refs/remotes/origin/main → main
    except Exception:
        return "main"               # 兜底


def parse_remote_url(cwd: str) -> tuple[str, str, str]:
    """
    解析 git remote URL，返回 (platform, host, project_path)。

    支持：
      git@gitlab.com:group/project.git  → (gitlab, gitlab.com, group/project)
      https://gitlab.com/group/proj.git → (gitlab, gitlab.com, group/project)
      git@github.com:user/repo.git      → (github, github.com, user/repo)
      https://github.com/user/repo      → (github, github.com, user/repo)

    其他 self-hosted GitLab（如 gitlab.company.com）同样支持。
    """
    url = git(["remote", "get-url", "origin"], cwd)

    # SSH 格式: git@host:path.git
    m = re.match(r"git@([^:]+):(.+?)(?:\.git)?$", url)
    if m:
        host, path = m.group(1), m.group(2)
    else:
        # HTTPS 格式: https://host/path.git
        m = re.match(r"https?://([^/]+)/(.+?)(?:\.git)?$", url)
        if not m:
            raise RuntimeError(f"无法解析 git remote URL：{url}")
        host, path = m.group(1), m.group(2)

    platform = "github" if "github.com" in host else "gitlab"
    return platform, host, path


# ── MR / PR 创建 ───────────────────────────────────────────────────────────────

def _http_post(url: str, body: dict, headers: dict) -> dict:
    data = json.dumps(body).encode()
    req  = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return json.loads(raw)
        except Exception:
            raise RuntimeError(f"HTTP {e.code}: {raw.decode(errors='replace')[:300]}")


def create_gitlab_mr(host: str, project_path: str, token: str,
                     source_branch: str, title: str, description: str,
                     default_branch: str = "main") -> str:
    """
    通过 GitLab API 创建 MR，返回 MR 网页 URL。
    project_path 如 "group/project"，自动 URL encode 处理斜杠。
    """
    project_id = urllib.parse.quote(project_path, safe="")
    url  = f"https://{host}/api/v4/projects/{project_id}/merge_requests"
    body = {
        "source_branch":        source_branch,
        "target_branch":        default_branch,
        "title":                title,
        "description":          description,
        "remove_source_branch": True,
    }
    result = _http_post(url, body, {
        "Content-Type":  "application/json",
        "PRIVATE-TOKEN": token,
    })
    mr_url = result.get("web_url", "")
    if not mr_url:
        raise RuntimeError(f"GitLab MR 创建失败：{result}")
    return mr_url


def create_github_pr(host: str, project_path: str, token: str,
                     source_branch: str, title: str, description: str,
                     default_branch: str = "main") -> str:
    """通过 GitHub API 创建 PR，返回 PR 网页 URL。"""
    url  = f"https://api.{host}/repos/{project_path}/pulls"
    body = {
        "head":  source_branch,
        "base":  default_branch,
        "title": title,
        "body":  description,
    }
    result = _http_post(url, body, {
        "Content-Type":  "application/json",
        "Authorization": f"token {token}",
        "Accept":        "application/vnd.github.v3+json",
    })
    pr_url = result.get("html_url", "")
    if not pr_url:
        raise RuntimeError(f"GitHub PR 创建失败：{result}")
    return pr_url


def create_mr(source_branch: str, title: str, description: str,
              project_path: str) -> str:
    """
    自动识别 GitLab / GitHub，创建 MR/PR，返回 URL。
    Token 优先读环境变量 GITLAB_TOKEN / GITHUB_TOKEN，其次读 config.json。
    """
    cfg               = bot_cfg()
    default_branch    = get_default_branch(project_path)
    platform, host, path = parse_remote_url(project_path)

    if platform == "gitlab":
        token = cfg["gitlab_token"]
        if not token:
            raise RuntimeError("未配置 gitlab_token，无法创建 MR")
        return create_gitlab_mr(host, path, token, source_branch,
                                title, description, default_branch)
    else:
        token = cfg["github_token"]
        if not token:
            raise RuntimeError("未配置 github_token，无法创建 PR")
        return create_github_pr(host, path, token, source_branch,
                                title, description, default_branch)


# ── 飞书卡片构建 ───────────────────────────────────────────────────────────────
# 每种卡片独立函数，方便单独修改样式

def _task_link(task_id: str) -> str:
    return f"https://applink.feishu.cn/client/todo/detail?guid={task_id}"


def _btn(text: str, action: str, task_id: str, btn_type: str = "default") -> dict:
    return {"tag": "button", "text": {"tag": "plain_text", "content": text},
            "type": btn_type, "value": {"action": action, "task_id": task_id}}


def _btn_url(text: str, url: str) -> dict:
    return {"tag": "button", "text": {"tag": "plain_text", "content": text},
            "type": "default", "url": url}


def _horizontal_buttons(*buttons) -> dict:
    """把多个按钮包进 column_set，实现横向排列。"""
    return {
        "tag": "column_set",
        "flex_mode": "none",
        "horizontal_spacing": "8px",
        "columns": [
            {"tag": "column", "width": "auto", "elements": [btn]}
            for btn in buttons
        ],
    }


def _common_actions(task_id: str, confirm: bool = False) -> dict:
    """所有卡片通用底部操作行：（确认开发）+ 分析有误 + 查看任务。"""
    buttons = []
    if confirm:
        buttons.append(_btn("✅ 确认开发", "confirm_dev", task_id, "primary"))
    buttons.append(_btn("✏️ 分析有误", "request_feedback", task_id))
    buttons.append(_btn_url("查看任务", _task_link(task_id)))
    return _horizontal_buttons(*buttons)


def build_l1_card(task_id: str, summary: str, analysis: dict) -> dict:
    """L1 低风险任务 — 绿色。"""
    return {
        "schema": "2.0",
        "header": {"title": {"tag": "plain_text", "content": f"✅ {summary}"}, "template": "green"},
        "body": {"elements": [
            {"tag": "div", "text": {"tag": "lark_md", "content": analysis.get("summary", "")}},
            {"tag": "hr"},
            _common_actions(task_id, confirm=False),
        ]},
    }


def build_l3_card(task_id: str, summary: str, analysis: dict) -> dict:
    """L3 复杂任务 — 红色，建议人工拆分。"""
    plan_lines = "\n".join(f"- {p}" for p in analysis.get("plan", []))
    body_text  = f"{analysis.get('summary', '')}\n\n**涉及范围：**\n{plan_lines}" if plan_lines else analysis.get("summary", "")
    return {
        "schema": "2.0",
        "header": {"title": {"tag": "plain_text", "content": f"⚠️ {summary}"}, "template": "red"},
        "body": {"elements": [
            {"tag": "div", "text": {"tag": "lark_md", "content": body_text}},
            {"tag": "hr"},
            _common_actions(task_id, confirm=False),
        ]},
    }


def build_bug_card(task_id: str, summary: str, analysis: dict) -> dict:
    """L2 Bug — 橙色。"""
    plan_lines = "\n".join(f"`{p}`" if " → " in p else f"- {p}"
                           for p in analysis.get("plan", []))
    body_text  = f"{analysis.get('summary', '')}\n\n**改哪里：**\n{plan_lines}"
    return {
        "schema": "2.0",
        "header": {"title": {"tag": "plain_text", "content": f"🐛 {summary}"}, "template": "orange"},
        "body": {"elements": [
            {"tag": "div", "text": {"tag": "lark_md", "content": body_text}},
            {"tag": "hr"},
            _common_actions(task_id, confirm=True),
        ]},
    }


def build_feature_card(task_id: str, summary: str, analysis: dict) -> dict:
    """L2 需求 — 蓝色。"""
    plan_lines = "\n".join(f"`{p}`" if " → " in p else f"- {p}"
                           for p in analysis.get("plan", []))
    body_text  = f"{analysis.get('summary', '')}\n\n**改哪里：**\n{plan_lines}"
    return {
        "schema": "2.0",
        "header": {"title": {"tag": "plain_text", "content": f"📋 {summary}"}, "template": "blue"},
        "body": {"elements": [
            {"tag": "div", "text": {"tag": "lark_md", "content": body_text}},
            {"tag": "hr"},
            _common_actions(task_id, confirm=True),
        ]},
    }


def build_feedback_input_card(task_id: str, summary: str) -> dict:
    """反馈输入卡片 — 点击"分析有误"后展示，含文字输入框。"""
    return {
        "schema": "2.0",
        "header": {
            "title":    {"tag": "plain_text", "content": f"✏️ {summary}"},
            "template": "grey",
        },
        "body": {"elements": [
            {"tag": "div", "text": {"tag": "lark_md",
             "content": "分析哪里有问题？补充说明后重新分析："}},
            {"tag": "input",
             "name":        "feedback",
             "placeholder": {"tag": "plain_text", "content": "如：应该是前端问题，不涉及后端..."},
             "width": "fill"},
            {"tag": "hr"},
            _horizontal_buttons(
                _btn("🔄 提交，重新分析", "submit_feedback", task_id, "primary"),
                _btn_url("查看任务", _task_link(task_id)),
            ),
        ]},
    }


def build_result_card(task_id: str, summary: str, result: dict,
                      task_type: str = "bug") -> dict:
    """修复 / 实现完成 — 绿色，含 MR 链接。task_type: 'bug' | 'feature'"""
    mr_url  = result.get("mr_url", "")
    branch  = result.get("branch", "")
    files   = result.get("files_changed", "")
    emoji   = "🐛" if task_type == "bug" else "✨"
    label   = "Bug 已自动修复" if task_type == "bug" else "需求已自动实现"
    mr_line = f"\n**MR：** [{mr_url}]({mr_url})" if mr_url else ""

    actions = []
    if mr_url:
        actions.append({"tag": "button",
                        "text": {"tag": "plain_text", "content": "查看 MR"},
                        "url": mr_url, "type": "primary"})
    actions.append({"tag": "button",
                    "text": {"tag": "plain_text", "content": "查看任务"},
                    "url": _task_link(task_id), "type": "default"})

    return {
        "schema": "2.0",
        "header": {
            "title":    {"tag": "plain_text", "content": f"{emoji} {label}"},
            "template": "green",
        },
        "body": {"elements": [
            {"tag": "div", "text": {"tag": "lark_md", "content": (
                f"**任务：** {summary}\n"
                f"**分支：** `{branch}`\n"
                f"**改动：** {files}"
                f"{mr_line}"
            )}},
            {"tag": "hr"},
            *actions,
        ]},
    }


def build_error_card(task_id: str, summary: str, error: str) -> dict:
    """执行失败 — 红色，展示错误信息。"""
    return {
        "schema": "2.0",
        "header": {
            "title":    {"tag": "plain_text", "content": "❌ 自动处理失败"},
            "template": "red",
        },
        "body": {"elements": [
            {"tag": "div", "text": {"tag": "lark_md", "content": (
                f"**任务：** {summary}\n\n"
                f"**错误：**\n```\n{error[:400]}\n```\n\n"
                f"请手动处理或查看日志。"
            )}},
            {"tag": "hr"},
            {"tag": "button", "text": {"tag": "plain_text", "content": "查看任务"},
             "url": _task_link(task_id), "type": "default"},
        ]},
    }


# ── 防抖（同一任务短时间内不重复分析）──────────────────────────────────────────────

def _is_debounced(task_id: str) -> bool:
    """返回 True 表示该任务在防抖窗口内已分析过，应跳过。"""
    path = ANALYZED_DIR / f"{task_id}.json"
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        elapsed = time.time() - data.get("analyzed_at", 0)
        if elapsed < DEBOUNCE_SECONDS:
            log(f"[debounce] task={task_id[:8]} 距上次分析 {int(elapsed)}s < {DEBOUNCE_SECONDS}s，跳过")
            return True
    except Exception:
        pass
    return False


def _mark_analyzed(task_id: str) -> None:
    """记录任务分析时间，用于防抖判断。"""
    ANALYZED_DIR.mkdir(parents=True, exist_ok=True)
    (ANALYZED_DIR / f"{task_id}.json").write_text(
        json.dumps({"task_id": task_id, "analyzed_at": time.time()}, ensure_ascii=False),
        encoding="utf-8"
    )


# ── Pending 存储（L2 需求确认缓存）─────────────────────────────────────────────

def save_pending(task_id: str, task_data: dict, analysis: dict) -> None:
    """保存待确认的需求分析，card-action 点击后读取。"""
    PENDING_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "task_id":    task_id,
        "task":       task_data,
        "analysis":   analysis,
        "created_at": int(time.time()),
    }
    (PENDING_DIR / f"{task_id}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def load_pending(task_id: str) -> dict | None:
    path = PENDING_DIR / f"{task_id}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    # 超过 7 天的缓存视为过期
    if time.time() - data.get("created_at", 0) > 7 * 86400:
        path.unlink(missing_ok=True)
        return None
    return data


def clear_pending(task_id: str) -> None:
    (PENDING_DIR / f"{task_id}.json").unlink(missing_ok=True)



# ── 核心流程 ───────────────────────────────────────────────────────────────────

def _run_feishu_dev_analyze(task_id: str, user_feedback: str = "") -> dict:
    """
    调用 feishu-dev skill BOT_ANALYZE_ONLY 模式：执行 Phase 1+2，不改代码。

    feishu-dev 会自主拉取任务、读代码库、做 L2/L3 分级，最后输出：
      [BOT_RESULT] {"level":"L2","type":"bug","summary":"...","plan":[...]}
      [BOT_ANALYZE_ONLY] done

    返回 analysis dict：{"level", "type", "summary", "plan"}
    """
    cfg          = bot_cfg()
    global_cfg   = read_config() or {}
    frontend     = global_cfg.get("frontend_path", "")
    backend      = global_cfg.get("backend_path", "") or cfg.get("project_path", "")
    project_path = cfg.get("project_path") or frontend or backend or "."

    prompt = f"BOT_ANALYZE_ONLY 帮我完成飞书任务 {task_id}"
    if user_feedback:
        prompt += f"\n\n## 用户反馈（上次分析有误，请重点参考）\n\n{user_feedback}"

    # 在 PLUGIN_ROOT 跑，避免业务项目 memory/skill 路由干扰
    cwd = str(PLUGIN_ROOT)
    log(f"[feishu-dev:analyze] task={task_id}")
    log(f"[feishu-dev:analyze] cwd={cwd}")

    output = run_claude(
        prompt, cwd=cwd,
        model=ANALYSIS_MODEL, timeout=300,
        dangerously_skip_permissions=True,
    )

    log(f"[feishu-dev:analyze] output_len={len(output)}")

    # 解析 [BOT_RESULT] JSON
    m = re.search(r'\[BOT_RESULT\]\s*(\{[^\n]+\})', output)
    if m:
        try:
            analysis = json.loads(m.group(1))
            log(f"[feishu-dev:analyze] result:\n{json.dumps(analysis, ensure_ascii=False, indent=2)}")
            return analysis
        except json.JSONDecodeError as e:
            log(f"[feishu-dev:analyze] JSON parse error: {e}, raw: {m.group(1)[:200]}")

    log(f"[feishu-dev:analyze] WARNING: [BOT_RESULT] not found, using fallback")
    return {"level": "L2", "type": "feature", "summary": task_id[:8], "plan": []}


def execute(task_id: str, task_data: dict, analysis: dict) -> dict:
    """
    无交互执行：拉分支 → claude --print 改代码 → push → 创建 MR。

    返回：
      { "success": bool, "branch": str, "mr_url": str,
        "files_changed": str, "error": str | None }

    通用化关键：
      - prompt 只传任务描述 + plan，不写死技术栈
      - claude 在 project_path 目录运行，自动读该项目的 CLAUDE.md
      - commit message 带飞书任务链接，方便溯源
    """
    cfg          = bot_cfg()
    project      = cfg["project_path"]
    task         = task_data["task"]
    summary      = task["summary"]
    description  = task.get("description", "")
    task_type    = analysis.get("type", "bug")
    plan_text    = "\n".join(f"- {p}" for p in analysis.get("plan", []))
    task_link    = _task_link(task_id)
    commit_type  = "fix" if task_type == "bug" else "feat"
    branch       = f"feat/feishu-{task_id[:8]}"

    log(f"[execute] task={task_id} type={task_type} branch={branch}")

    # 读取项目 CLAUDE.md 作为系统提示，绕过全局路由逻辑
    project_claude_md = ""
    claude_md_path = pathlib.Path(project) / "CLAUDE.md"
    if claude_md_path.exists():
        project_claude_md = claude_md_path.read_text(encoding="utf-8")

    system_prompt = f"""你是一个代码开发助手，直接执行给定的开发任务，不使用任何 skill 路由。

{project_claude_md}""".strip()

    head_before = git(["rev-parse", "HEAD"], cwd=project)

    # 创建分支
    try:
        git(["checkout", "-b", branch], cwd=project)
    except RuntimeError:
        git(["checkout", branch], cwd=project)

    prompt = f"""请按以下任务完成代码修改并提交，不要询问确认。

任务标题：{summary}
任务描述：{description or '（无描述）'}
类型：{'bug 修复' if task_type == 'bug' else '功能开发'}
当前分支：{branch}

改动计划：
{plan_text}

执行步骤：
1. 根据改动计划搜索并修改对应代码
2. 保持与项目现有代码风格一致
3. 只改计划中的内容，不做计划外修改
4. git add 改动的文件（禁止 git add -A 或 git add .）
5. git commit -m "{commit_type}: {summary}\\n\\nFeishu-Task: {task_link}\\nCo-Authored-By: Claude <noreply@anthropic.com>"
6. git push origin {branch}
7. 最后一行输出 DONE: <改动文件列表>，失败输出 FAILED: <原因>"""

    output = run_claude(prompt, cwd=project, model=EXECUTION_MODEL, timeout=600,
                        dangerously_skip_permissions=True,
                        system_prompt=system_prompt)
    log(f"[execute] claude output tail: {output[-300:]}")

    head_after = git(["rev-parse", "HEAD"], cwd=project)
    if head_before == head_after:
        failed_m = re.search(r"FAILED:\s*(.+)", output)
        reason   = failed_m.group(1).strip() if failed_m else "未检测到新 commit"
        raise RuntimeError(f"代码修改未提交：{reason}")

    done_m        = re.search(r"DONE:\s*(.+)", output)
    files_changed = done_m.group(1).strip() if done_m else (
        git(["diff", "--name-only", f"{head_before}..HEAD"], cwd=project).replace("\n", ", ")
    )

    # 创建 MR/PR
    mr_url = ""
    try:
        mr_url = create_mr(branch, f"{commit_type}: {summary}",
                           f"飞书任务：[{summary}]({task_link})\n\n*由 Pipelit Bot 自动创建*",
                           project)
        log(f"[execute] MR created: {mr_url}")
    except Exception as e:
        log(f"[execute] MR 创建失败（不影响代码）：{e}")

    return {
        "success":       True,
        "branch":        branch,
        "mr_url":        mr_url,
        "files_changed": files_changed,
        "error":         None,
    }


def pipeline(task_id: str) -> None:
    """
    完整流程入口，由 webhook 在后台线程中调用。

    notify 模式（默认）→ feishu-dev BOT_ANALYZE_ONLY → 发确认卡片 → 等用户点击
    spawn  模式        → feishu-dev BOT_AUTO_EXECUTE  → 全自动执行，不等确认
    """
    # if _is_debounced(task_id):
    #     return

    cfg          = bot_cfg()
    chat_id      = cfg["notify_chat_id"]
    trigger_mode = cfg.get("trigger_mode", "notify")

    log_section(f"pipeline  task={task_id[:8]}  mode={trigger_mode}")
    send_message(chat_id, f"🔍 收到任务 {task_id[:8]}，正在分析...")

    # 拉取任务基本信息（用于卡片标题和 pending 存储）
    try:
        task_data = _feishu_api("get_task_full", task_id)
    except Exception as e:
        err = str(e)
        if "1470403" in err or "unauthorized" in err.lower():
            log(f"[pipeline] no permission to read task {task_id[:8]}, skip")
            return
        log(f"[pipeline] fetch task failed: {e}")
        send_message(chat_id, f"❌ 拉取任务失败：{e}")
        return

    task    = task_data["task"]
    summary = task["summary"]

    # ── spawn 模式：直接调 feishu-dev 全自动执行 ────────────────────────────
    if trigger_mode == "spawn":
        log(f"[pipeline] spawn mode, calling feishu-dev BOT_AUTO_EXECUTE")
        send_message(chat_id, f"🚀 spawn 模式，自动开始执行：{summary}")
        try:
            result = _run_feishu_dev(task_id, task_data=task_data)
            _mark_analyzed(task_id)
            if result.get("is_l3"):
                # feishu-dev 判定 L3，只输出了分析报告，未改代码
                log(f"[pipeline] spawn: feishu-dev returned L3, sending analysis card")
                analysis = {"summary": summary, "plan": []}
                send_card(chat_id, build_l3_card(task_id, summary, analysis))
            else:
                t_type = "bug" if "fix" in result.get("branch", "") else "feature"
                send_card(chat_id, build_result_card(task_id, summary, result, t_type))
        except Exception as e:
            log(f"[pipeline] spawn execute failed: {e}")
            send_card(chat_id, build_error_card(task_id, summary, str(e)))
        return

    # ── notify 模式：先分析（BOT_ANALYZE_ONLY），再发确认卡片 ────────────────
    try:
        analysis = _run_feishu_dev_analyze(task_id)
    except Exception as e:
        log(f"[pipeline] analyze failed: {e}")
        send_message(chat_id, f"❌ 任务分析失败：{e}")
        return

    level  = analysis.get("level", "L2")
    t_type = analysis.get("type", "bug")

    _mark_analyzed(task_id)

    if level == "L1":
        send_card(chat_id, build_l1_card(task_id, summary, analysis))
        return

    if level == "L3":
        send_card(chat_id, build_l3_card(task_id, summary, analysis))
        return

    # L2：保存分析结果供"确认开发"按钮使用，再发确认卡片
    save_pending(task_id, task_data, analysis)

    if t_type == "bug":
        send_card(chat_id, build_bug_card(task_id, summary, analysis))
    else:
        send_card(chat_id, build_feature_card(task_id, summary, analysis))


def execute_from_pending(task_id: str) -> None:
    """
    处理"确认开发"按钮点击，调用 feishu-dev skill 完成编码。
    """
    cfg     = bot_cfg()
    chat_id = cfg["notify_chat_id"]

    pending = load_pending(task_id)
    if not pending:
        # 没有 pending 说明是 L1 或 L3 点击了确认，直接用 task_id 触发
        send_message(chat_id, f"🚀 正在调用 feishu-dev 处理任务...")
        try:
            result = _run_feishu_dev(task_id)
            send_card(chat_id, build_result_card(task_id, task_id[:8], result, "feature"))
        except Exception as e:
            log(f"[execute_from_pending] failed: {e}")
            send_message(chat_id, f"❌ 执行失败：{e}")
        return

    task_data = pending["task"]
    analysis  = pending["analysis"]
    summary   = task_data["task"]["summary"]

    log(f"[execute] task={task_id} level={analysis.get('level')} type={analysis.get('type')}")
    log(f"[execute] plan={analysis.get('plan')}")
    send_message(chat_id, f"🚀 开始实现：{summary}\n正在调用 feishu-dev，预计需要几分钟...")

    try:
        result = _run_feishu_dev(task_id, task_data=task_data, analysis=analysis)
        clear_pending(task_id)
        send_card(chat_id, build_result_card(task_id, summary, result, analysis.get("type", "feature")))
    except Exception as e:
        log(f"[execute_from_pending] failed: {e}")
        send_card(chat_id, build_error_card(task_id, summary, str(e)))


def show_feedback_input(task_id: str) -> None:
    """用户点击"分析有误"后，发送反馈输入卡片。"""
    cfg     = bot_cfg()
    chat_id = cfg["notify_chat_id"]
    pending = load_pending(task_id)
    summary = pending["task"]["task"]["summary"] if pending else task_id[:8]
    send_card(chat_id, build_feedback_input_card(task_id, summary))


def reanalyze_with_feedback(task_id: str, feedback: str) -> None:
    """收到用户反馈后重新分析，发新的分析卡片。"""
    cfg     = bot_cfg()
    chat_id = cfg["notify_chat_id"]

    log(f"[reanalyze] task={task_id[:8]} feedback={feedback[:100]}")
    send_message(chat_id, f"🔄 收到反馈，重新分析中...")

    try:
        task_data = _feishu_api("get_task_full", task_id)
        analysis  = _run_feishu_dev_analyze(task_id, user_feedback=feedback)
    except Exception as e:
        log(f"[reanalyze] failed: {e}")
        send_message(chat_id, f"❌ 重新分析失败：{e}")
        return

    task    = task_data["task"]
    summary = task["summary"]
    level   = analysis.get("level", "L2")
    t_type  = analysis.get("type", "bug")

    save_pending(task_id, task_data, analysis)

    if level == "L1":
        send_card(chat_id, build_l1_card(task_id, summary, analysis))
    elif level == "L3":
        send_card(chat_id, build_l3_card(task_id, summary, analysis))
    elif t_type == "bug":
        send_card(chat_id, build_bug_card(task_id, summary, analysis))
    else:
        send_card(chat_id, build_feature_card(task_id, summary, analysis))


def _run_feishu_dev(task_id: str, task_data: dict | None = None, analysis: dict | None = None) -> dict:
    """
    调用 feishu-dev skill 完成编码。
    把任务内容和分析结果全部塞进 prompt，feishu-dev 无需再调飞书 API。
    """
    cfg          = bot_cfg()
    global_cfg   = read_config() or {}
    frontend     = global_cfg.get("frontend_path", "")
    backend      = global_cfg.get("backend_path", "") or cfg.get("project_path", "")

    # 从 plan 判断前端还是后端
    plan_str    = " ".join(analysis.get("plan", [])) if analysis else ""
    is_frontend = any(k in plan_str for k in ("src/", ".vue", ".ts", ".js", ".css", ".scss", "components", "pages"))
    is_backend  = any(k in plan_str for k in (".py", "routes/", "models/", "process/", "executors/"))

    if is_frontend and not is_backend and frontend:
        project_path = frontend
    elif is_backend and not is_frontend and backend:
        project_path = backend
    else:
        project_path = cfg.get("project_path") or backend or frontend or "."

    # 任务详情（直接嵌入 prompt，跳过 feishu-dev 的 API 读取）
    task_info = ""
    if task_data:
        t = task_data.get("task", {})
        task_info = (
            f"\n\n## 任务详情（已预加载，无需再调 API）\n\n"
            f"任务标题：{t.get('summary', '')}\n"
            f"任务描述：{t.get('description', '（无描述）')}\n"
            f"任务链接：https://applink.feishu.cn/client/todo/detail?guid={task_id}\n"
        )
        comments = t.get("comments", [])
        if comments:
            task_info += "评论：\n" + "\n".join(f"- {c.get('content','')}" for c in comments)

    # 分析结果
    plan_text = ""
    if analysis:
        plan_items = "\n".join(f"- {p}" for p in analysis.get("plan", []))
        plan_text  = (
            f"\n\n## 已完成分析（直接按此计划执行，跳过 Phase 1）\n\n"
            f"任务概要：{analysis.get('summary', '')}\n"
            f"改动计划：\n{plan_items}"
        )

    prompt = f"BOT_AUTO_EXECUTE 帮我完成飞书任务 {task_id}{task_info}{plan_text}"

    # 在 PLUGIN_ROOT 跑，避免业务项目 memory/skill 路由干扰
    # feishu-dev skill 内部会 cd 到 frontend_path/backend_path 做 git 操作
    cwd = str(PLUGIN_ROOT)
    log(f"[feishu-dev] ── 开始执行 ──────────────────────────────")
    log(f"[feishu-dev] task      = {task_id}")
    log(f"[feishu-dev] cwd       = {cwd}")
    log(f"[feishu-dev] frontend  = {frontend}")
    log(f"[feishu-dev] backend   = {backend}")
    log(f"[feishu-dev] is_fe     = {is_frontend}  is_be = {is_backend}")
    log(f"[feishu-dev] model     = {EXECUTION_MODEL}")
    log(f"[feishu-dev] prompt_len= {len(prompt)}")
    log(f"[feishu-dev] prompt[:300]:\n{prompt[:300]}")
    log(f"[feishu-dev] ──────────────────────────────────────────")

    output = run_claude(
        prompt, cwd=cwd,
        model=EXECUTION_MODEL, timeout=600,
        dangerously_skip_permissions=True,
    )

    log(f"[feishu-dev] ── 执行完成 ──────────────────────────────")
    log(f"[feishu-dev] output_len = {len(output)}")
    log(f"[feishu-dev] output_head:\n{output[:500]}")
    log(f"[feishu-dev] output_tail:\n{output[-300:]}")
    log(f"[feishu-dev] ──────────────────────────────────────────")

    # 从输出里提取结果
    branch        = ""
    mr_url        = ""
    files_changed = ""
    commit_hash   = ""
    file_lines: list[str] = []
    in_files_section = False

    for line in output.splitlines():
        # Branch: feat/feishu-xxx
        if "Branch:" in line and not line.strip().startswith("#"):
            branch = line.split("Branch:")[-1].strip()
        # Commit: abc1234 feat: ...
        if "Commit:" in line:
            commit_hash = line.split("Commit:")[-1].strip().split()[0]
        # MR/PR URL
        urls = re.findall(r'https?://[^\s\)]+', line)
        for u in urls:
            if any(k in u for k in ("merge_requests", "pulls", "gitlab", "github")):
                mr_url = u
                break
        # 改了: 段落（feishu-dev 报告格式：改了:\n  • file (+N -M)）
        stripped = line.strip()
        if stripped.startswith("改了:"):
            in_files_section = True
            continue
        if in_files_section:
            if stripped.startswith("•"):
                file_lines.append(stripped.lstrip("• ").strip())
            elif stripped and not stripped.startswith("•"):
                in_files_section = False

    if file_lines:
        files_changed = ", ".join(file_lines)
    if commit_hash and files_changed:
        files_changed = f"{files_changed}  ({commit_hash})"

    # 检测 feishu-dev 是否因 L3 停止（只输出报告，没有执行代码改动）
    is_l3 = ("L3 分析报告" in output or "此任务复杂度较高" in output)

    log(f"[feishu-dev] branch={branch!r} mr_url={mr_url!r} files={files_changed!r} is_l3={is_l3}")
    return {"success": True, "branch": branch, "mr_url": mr_url,
            "files_changed": files_changed, "error": None, "is_l3": is_l3, "output": output}


# ── CLI 入口（方便本地测试）────────────────────────────────────────────────────

def check_config() -> None:
    """检查所有配置项是否完整，逐项输出 OK / MISSING / WARN。"""
    OK      = "  [OK]    "
    MISSING = "  [MISSING]"
    WARN    = "  [WARN]  "

    errors = 0

    def ok(label: str, value: str = "") -> None:
        suffix = f" = {value}" if value else ""
        print(f"{OK} {label}{suffix}")

    def missing(label: str, hint: str = "") -> None:
        nonlocal errors
        errors += 1
        suffix = f"  → {hint}" if hint else ""
        print(f"{MISSING} {label}{suffix}")

    def warn(label: str, hint: str = "") -> None:
        suffix = f"  → {hint}" if hint else ""
        print(f"{WARN} {label}{suffix}")

    print("\n=== Pipelit 配置检查 ===\n")

    # ── 1. config.json ───────────────────────────────────────────────────────
    print("[ config.json ]")
    cfg = read_config() or {}

    for field in ("app_id", "app_secret"):
        if cfg.get(field):
            ok(field, cfg[field][:8] + "...")
        else:
            missing(field, "运行 feishu_api.py save_config <App_ID> <App_Secret>")

    if cfg.get("user_id"):
        ok("user_id", cfg["user_id"])
    else:
        warn("user_id 未设置", "运行 feishu_api.py save_user 获取")

    # ── 2. bot 配置 ──────────────────────────────────────────────────────────
    print("\n[ config.json → bot ]")
    bot = cfg.get("bot", {})

    if bot.get("notify_chat_id") or os.environ.get("BOT_NOTIFY_CHAT"):
        ok("notify_chat_id", (bot.get("notify_chat_id") or os.environ.get("BOT_NOTIFY_CHAT", ""))[:12] + "...")
    else:
        missing("notify_chat_id", "卡片通知无法发送；运行 feishu_bot_webhook.py setup")

    if bot.get("project_path") or os.environ.get("BOT_PROJECT_PATH"):
        path = bot.get("project_path") or os.environ.get("BOT_PROJECT_PATH", "")
        exists = pathlib.Path(path).exists()
        if exists:
            ok("project_path", path)
        else:
            warn("project_path 路径不存在", path)
    else:
        missing("project_path", "自动执行代码时必须；运行 feishu_bot_webhook.py setup")

    user_id = bot.get("user_id") or cfg.get("user_id", "")
    if user_id:
        ok("bot.user_id", user_id)
    else:
        warn("bot.user_id 未设置", "任务过滤将失效（所有任务都会触发）")

    trigger_mode = bot.get("trigger_mode", "notify")
    ok("trigger_mode", trigger_mode)

    trigger_events = bot.get("trigger_events", [])
    if trigger_events:
        ok("trigger_events", ", ".join(trigger_events))
    else:
        warn("trigger_events 为空", "不会触发任何事件")

    # ── 3. 环境变量 ──────────────────────────────────────────────────────────
    print("\n[ 环境变量 ]")

    if os.environ.get("ANTHROPIC_API_KEY"):
        key = os.environ["ANTHROPIC_API_KEY"]
        ok("ANTHROPIC_API_KEY", key[:8] + "..." + key[-4:])
    else:
        missing("ANTHROPIC_API_KEY", "Claude 分析无法运行；在系统环境变量或 .env 中设置")

    gitlab_token = os.environ.get("GITLAB_TOKEN") or bot.get("gitlab_token", "")
    github_token = os.environ.get("GITHUB_TOKEN") or bot.get("github_token", "")
    if gitlab_token:
        ok("GITLAB_TOKEN", gitlab_token[:8] + "...")
    elif github_token:
        ok("GITHUB_TOKEN", github_token[:8] + "...")
    else:
        warn("GITLAB_TOKEN / GITHUB_TOKEN 均未设置", "自动创建 MR/PR 将失败")

    # claude 命令
    claude_bin = os.environ.get("CLAUDE_BIN", "claude")
    found = False
    for candidate in [claude_bin, r"D:\node\nodejs\claude.cmd", r"D:\node\nodejs\claude",
                      "/usr/local/bin/claude"]:
        if pathlib.Path(candidate).is_file():
            ok("claude 命令", candidate)
            found = True
            break
    if not found:
        try:
            import shutil
            path = shutil.which("claude")
            if path:
                ok("claude 命令", path)
                found = True
        except Exception:
            pass
    if not found:
        warn("claude 命令未找到", "execute 模式将失败；npm install -g @anthropic-ai/claude-code")

    # anthropic SDK
    print("\n[ Python 依赖 ]")
    try:
        import anthropic
        ok("anthropic SDK")
    except ImportError:
        missing("anthropic SDK", "pip install anthropic")

    try:
        import lark
        ok("lark-oapi SDK (长连接)")
    except ImportError:
        warn("lark-oapi 未安装", "长连接模式无法使用；pip install lark-oapi")

    # ── 结果 ─────────────────────────────────────────────────────────────────
    print(f"\n{'='*30}")
    if errors == 0:
        print("✓ 所有必填配置已就绪")
    else:
        print(f"✗ 发现 {errors} 个必填项缺失，请按提示补充后重试")
    print()


def main() -> None:
    args = sys.argv[1:]

    if not args or args[0] == "check":
        check_config()
        return

    if len(args) < 2:
        print(__doc__)
        sys.exit(1)

    cmd, task_id = args[0], args[1]

    if cmd == "pipeline":
        pipeline(task_id)
    elif cmd == "analyze":
        analysis = _run_feishu_dev_analyze(task_id)
        print(json.dumps(analysis, ensure_ascii=False, indent=2))
    elif cmd == "execute":
        pending = load_pending(task_id)
        if not pending:
            print(f"未找到 pending: {task_id}", file=sys.stderr)
            sys.exit(1)
        execute_from_pending(task_id)
    else:
        print(f"未知命令：{cmd}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
