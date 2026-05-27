#!/usr/bin/env python3
"""
飞书 Bot 分析 & 执行核心 — 通用，不绑定任何具体项目或技术栈。

职责：
  1. analyze(task_id)          拉取任务 → claude --print 分类（L2/L3 × bug/feature）
  2. execute(task_id, ...)     无交互执行：拉分支 → claude --print 改代码 → push → MR
  3. pipeline(task_id)         完整流程入口（webhook 调用此函数）
  4. execute_from_pending(...)  处理"需求确认"按钮点击

通用化设计：
  - 不假设技术栈，claude 自己读 CLAUDE.md 和代码判断
  - MR 平台自动识别（GitLab / GitHub），解析 git remote URL
  - 所有配置从 config.json 读，支持环境变量覆盖
  - 可单独 CLI 调用，方便本地测试

用法：
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
CACHE_DIR   = PLUGIN_ROOT / ".cache"
CONFIG_FILE = CACHE_DIR / "config.json"
PENDING_DIR = CACHE_DIR / "pending"    # 存待确认的需求分析
LOG_DIR     = CACHE_DIR / "webhook_logs"

# claude --print 使用的模型，支持环境变量覆盖
ANALYSIS_MODEL  = os.environ.get("BOT_ANALYSIS_MODEL",  "claude-haiku-4-5-20251001")
EXECUTION_MODEL = os.environ.get("BOT_EXECUTION_MODEL", "claude-sonnet-4-6")


# ── 日志 ───────────────────────────────────────────────────────────────────────

def log(msg: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts   = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [analyzer] {msg}\n"
    with open(LOG_DIR / "webhook.log", "a", encoding="utf-8") as f:
        f.write(line)
    sys.stdout.write(line)
    sys.stdout.flush()


# ── 配置 ───────────────────────────────────────────────────────────────────────

def read_config() -> dict:
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    return {}


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

def _feishu_api(*args: str) -> dict:
    """调用同目录的 feishu_api.py，返回解析后的 JSON。"""
    script = str(PLUGIN_ROOT / "scripts" / "feishu_api.py")
    env    = {**os.environ, "CLAUDE_PLUGIN_ROOT": str(PLUGIN_ROOT)}
    r = subprocess.run(
        ["python3", script, *args],
        capture_output=True, text=True, timeout=20, env=env,
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

def run_claude(prompt: str, cwd: str, model: str = EXECUTION_MODEL,
               timeout: int = 600) -> str:
    """
    在 cwd 目录执行 claude --print <prompt>，返回完整 stdout。

    - cwd 决定了 claude 读哪个 CLAUDE.md，实现项目感知（通用化关键点）
    - model 分析用 haiku（快），执行用 sonnet（准）
    - timeout 默认 10 分钟，复杂任务可传更大值
    """
    env = {**os.environ, "CLAUDE_PLUGIN_ROOT": str(PLUGIN_ROOT)}
    cmd = ["claude", "--print", prompt, "--model", model]

    log(f"[claude] model={model} cwd={cwd} prompt_len={len(prompt)}")
    try:
        r = subprocess.run(
            cmd, cwd=cwd,
            capture_output=True, text=True,
            timeout=timeout, env=env,
        )
    except FileNotFoundError:
        raise RuntimeError(
            "claude 命令未找到。请先安装：npm install -g @anthropic-ai/claude-code"
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"claude 超时（>{timeout}s），任务可能过于复杂")

    if r.returncode != 0:
        raise RuntimeError(f"claude 退出码 {r.returncode}：{r.stderr[:300]}")

    return r.stdout


def parse_json_from_output(text: str) -> dict:
    """
    从 claude --print 的输出中提取 JSON。
    兼容三种格式：裸 JSON / ```json ... ``` / 混有解释文字的输出。
    """
    # 先尝试 ```json 代码块
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    # 再尝试找第一个完整 JSON 对象
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        return json.loads(m.group(0))
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


def build_l3_card(task_id: str, summary: str, analysis: dict) -> dict:
    """L3 复杂任务 — 橙色，仅报告，不含操作按钮。"""
    plan_md = "\n".join(f"- {p}" for p in analysis.get("plan", []))
    return {
        "schema": "2.0",
        "header": {
            "title":    {"tag": "plain_text", "content": "🔍 L3 复杂任务 · 建议人工拆分"},
            "template": "orange",
        },
        "body": {"elements": [
            {"tag": "div", "text": {"tag": "lark_md", "content": (
                f"**任务：** {summary}\n\n"
                f"**判断原因：** {analysis.get('l3_reason', '')}\n\n"
                f"**涉及范围：**\n{plan_md}"
            )}},
            {"tag": "hr"},
            {"tag": "action", "actions": [
                {"tag": "button", "text": {"tag": "plain_text", "content": "查看任务"},
                 "url": _task_link(task_id), "type": "default"},
            ]},
        ]},
    }


def build_feature_confirm_card(task_id: str, summary: str, analysis: dict) -> dict:
    """L2 需求 — 蓝色，含确认按钮，点击后才触发开发。"""
    plan_md = "\n".join(f"- {p}" for p in analysis.get("plan", []))
    return {
        "schema": "2.0",
        "header": {
            "title":    {"tag": "plain_text", "content": "📋 新需求待确认 · 点击开发"},
            "template": "blue",
        },
        "body": {"elements": [
            {"tag": "div", "text": {"tag": "lark_md", "content": (
                f"**任务：** {summary}\n\n"
                f"**摘要：** {analysis.get('summary', '')}\n\n"
                f"**初步 Plan：**\n{plan_md}"
            )}},
            {"tag": "hr"},
            {"tag": "action", "actions": [
                # value 传 task_id 给 card-action 回调
                {"tag": "button",
                 "text":  {"tag": "plain_text", "content": "✅ 确认开发"},
                 "type":  "primary",
                 "value": {"action": "confirm_dev", "task_id": task_id}},
                {"tag": "button", "text": {"tag": "plain_text", "content": "查看任务"},
                 "url": _task_link(task_id), "type": "default"},
            ]},
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
            {"tag": "action", "actions": actions},
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
            {"tag": "action", "actions": [
                {"tag": "button", "text": {"tag": "plain_text", "content": "查看任务"},
                 "url": _task_link(task_id), "type": "default"},
            ]},
        ]},
    }


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

def analyze(task_id: str) -> tuple[dict, dict]:
    """
    拉取任务全文，调用 claude --print 分析，返回 (task_data, analysis)。

    analysis 结构：
      {
        "level":     "L2" | "L3",
        "type":      "bug" | "feature",
        "summary":   "一句话概括",
        "plan":      ["改动点1", "改动点2"],
        "l3_reason": "若L3说明原因"
      }

    分析用 haiku 模型（快 + 便宜），只需要分类不需要写代码。
    """
    cfg        = bot_cfg()
    project    = cfg["project_path"]

    log(f"[analyze] task_id={task_id}")
    task_data  = _feishu_api("get_task_full", task_id)
    task       = task_data["task"]

    comments_text = "\n".join(
        f"- {c.get('content', '')}" for c in task.get("comments", [])
    ) or "（无评论）"

    prompt = f"""你是一个任务分类器。分析以下飞书任务，仅返回 JSON，不要其他内容。

任务标题：{task['summary']}
任务描述：{task.get('description', '（无描述）')}
评论：
{comments_text}

返回格式（严格 JSON）：
{{
  "level":     "L2" 或 "L3",
  "type":      "bug" 或 "feature",
  "summary":   "一句话概括要做什么",
  "plan":      ["具体改动点1", "具体改动点2"],
  "l3_reason": "若为L3说明原因，否则空字符串"
}}

L3 判断（满足任一即为 L3）：
- 需要修改 5 个以上文件
- 涉及架构调整或多模块重构
- bug 根因不明，影响范围不确定
- 描述极度模糊，无法确定具体改动

bug 判断：标题/描述含"报错"、"异常"、"不生效"、"修复"、"fix"、"bug"、"问题"、"错误"视为 bug。"""

    output   = run_claude(prompt, cwd=project, model=ANALYSIS_MODEL, timeout=60)
    analysis = parse_json_from_output(output)
    log(f"[analyze] result={json.dumps(analysis, ensure_ascii=False)}")
    return task_data, analysis


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
    branch       = f"feat/feishu-{task_id[:8]}"
    commit_type  = "fix" if task_type == "bug" else "feat"

    log(f"[execute] task={task_id} type={task_type} branch={branch}")

    # 1. 创建分支（已存在则切换）
    try:
        git(["checkout", "-b", branch], cwd=project)
    except RuntimeError:
        git(["checkout", branch], cwd=project)

    # 记录执行前的 HEAD commit，后面用来判断是否有新 commit
    head_before = git(["rev-parse", "HEAD"], cwd=project)

    # 2. 调用 claude --print 完成代码改动
    verb   = "修复这个 Bug" if task_type == "bug" else "实现这个需求"
    prompt = f"""请{verb}，直接修改代码并提交，不要询问确认。

任务：{summary}
描述：{description}
改动计划：
{plan_text}
当前分支：{branch}（已创建好，你在这个分支上）

执行要求：
1. 根据任务描述和改动计划，搜索并修改相关代码
2. 保持与项目现有代码风格一致（参考周围代码）
3. 只改计划中的内容，不做计划外的修改
4. git add 改动的文件（禁止 git add -A 或 git add .）
5. git commit -m "{commit_type}: {summary}\\n\\nFeishu-Task: {task_link}\\nCo-Authored-By: Claude <noreply@anthropic.com>"
6. 完成后最后一行输出：DONE: <改动的文件列表>
   若无法完成输出：FAILED: <原因>"""

    output = run_claude(prompt, cwd=project, model=EXECUTION_MODEL, timeout=600)
    log(f"[execute] claude output tail: {output[-300:]}")

    # 3. 判断执行结果
    head_after = git(["rev-parse", "HEAD"], cwd=project)
    committed  = head_before != head_after

    if not committed:
        # 检查 claude 是否报告失败
        failed_m = re.search(r"FAILED:\s*(.+)", output)
        reason   = failed_m.group(1).strip() if failed_m else "未知（未检测到新 commit）"
        raise RuntimeError(f"代码修改未提交：{reason}")

    # 提取改动文件列表（从 DONE: 行或 git diff）
    done_m         = re.search(r"DONE:\s*(.+)", output)
    files_changed  = done_m.group(1).strip() if done_m else (
        git(["diff", "--name-only", f"{head_before}..HEAD"], cwd=project)
        .replace("\n", ", ")
    )

    # 4. Push
    git(["push", "origin", branch], cwd=project)
    log(f"[execute] pushed branch={branch}")

    # 5. 创建 MR/PR
    mr_url = ""
    try:
        mr_description = (
            f"**飞书任务：** [{summary}]({task_link})\n\n"
            f"**改动说明：**\n{plan_text}\n\n"
            f"*由 Pipelit Bot 自动创建*"
        )
        mr_url = create_mr(branch, f"{commit_type}: {summary}",
                           mr_description, project)
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

    L3  → 发分析报告卡片
    L2 feature → 发确认卡片（用户点击后触发 execute）
    L2 bug     → 直接 execute → 发结果卡片
    """
    cfg     = bot_cfg()
    chat_id = cfg["notify_chat_id"]

    # 先发"分析中"提示，避免用户以为没响应
    send_message(chat_id, f"🔍 收到任务 {task_id[:8]}，正在分析...")

    try:
        task_data, analysis = analyze(task_id)
    except Exception as e:
        log(f"[pipeline] analyze failed: {e}")
        send_message(chat_id, f"❌ 任务分析失败：{e}")
        return

    task    = task_data["task"]
    summary = task["summary"]
    level   = analysis.get("level", "L2")
    t_type  = analysis.get("type", "bug")

    if level == "L3":
        send_card(chat_id, build_l3_card(task_id, summary, analysis))
        return

    if t_type == "feature":
        # 保存分析结果，等用户确认
        save_pending(task_id, task_data, analysis)
        send_card(chat_id, build_feature_confirm_card(task_id, summary, analysis))
        return

    # L2 Bug：全自动执行
    try:
        result = execute(task_id, task_data, analysis)
        send_card(chat_id, build_result_card(task_id, summary, result, "bug"))
    except Exception as e:
        log(f"[pipeline] execute failed: {e}")
        send_card(chat_id, build_error_card(task_id, summary, str(e)))


def execute_from_pending(task_id: str) -> None:
    """
    处理"需求确认"按钮点击，由 webhook card-action 回调触发。
    从 pending 缓存读取之前的分析结果，直接执行。
    """
    cfg     = bot_cfg()
    chat_id = cfg["notify_chat_id"]

    pending = load_pending(task_id)
    if not pending:
        send_message(chat_id,
                     f"⚠️ 未找到任务 {task_id[:8]} 的待确认记录（可能已过期），请手动处理。")
        return

    task_data = pending["task"]
    analysis  = pending["analysis"]
    summary   = task_data["task"]["summary"]

    send_message(chat_id, f"🚀 开始实现需求：{summary}")

    try:
        result = execute(task_id, task_data, analysis)
        clear_pending(task_id)
        send_card(chat_id, build_result_card(task_id, summary, result, "feature"))
    except Exception as e:
        log(f"[execute_from_pending] failed: {e}")
        send_card(chat_id, build_error_card(task_id, summary, str(e)))


# ── CLI 入口（方便本地测试）────────────────────────────────────────────────────

def main() -> None:
    args = sys.argv[1:]
    if len(args) < 2:
        print(__doc__)
        sys.exit(1)

    cmd, task_id = args[0], args[1]

    if cmd == "pipeline":
        pipeline(task_id)
    elif cmd == "analyze":
        task_data, analysis = analyze(task_id)
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
