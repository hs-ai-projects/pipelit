#!/bin/bash
set -e

PIPELIT_DIR="/app/pipelit"
PROJECT_DIR="/app/project"

# ── 1. Clone pipelit ──────────────────────────────────────────────
echo "[entrypoint] cloning pipelit..."
if [ -d "$PIPELIT_DIR/.git" ]; then
  git -C "$PIPELIT_DIR" pull --ff-only
else
  git clone "https://oauth2:${GITLAB_TOKEN}@${PIPELIT_REPO#https://}" "$PIPELIT_DIR"
fi

# ── 2. Clone 业务项目 ─────────────────────────────────────────────
echo "[entrypoint] cloning project..."
if [ -d "$PROJECT_DIR/.git" ]; then
  git -C "$PROJECT_DIR" pull --ff-only
else
  git clone "https://oauth2:${GITLAB_TOKEN}@${PROJECT_REPO#https://}" "$PROJECT_DIR"
fi

# ── 3. 配置 git 身份（push MR 需要）─────────────────────────────
git config --global user.email "${GIT_USER_EMAIL}"
git config --global user.name "${GIT_USER_NAME:-pipelit-bot}"

# ── 4. 写 L1 配置：~/.claude/pipelit/config.json（user_id）──────
L1_DIR="$HOME/.claude/pipelit"
mkdir -p "$L1_DIR"
if [ ! -f "$L1_DIR/config.json" ]; then
  echo "[entrypoint] writing L1 config (user_id)..."
  cat > "$L1_DIR/config.json" <<EOF
{
  "user_id": "${FEISHU_USER_ID}"
}
EOF
fi

# ── 5. 写 L2 配置：$PROJECT_DIR/.claude/pipelit/config.json ──────
L2_DIR="$PROJECT_DIR/.claude/pipelit"
mkdir -p "$L2_DIR"
if [ ! -f "$L2_DIR/config.json" ]; then
  echo "[entrypoint] writing L2 config (app credentials + bot)..."
  cat > "$L2_DIR/config.json" <<EOF
{
  "app_id": "${FEISHU_APP_ID}",
  "app_secret": "${FEISHU_APP_SECRET}",
  "bot": {
    "port": 8765,
    "encrypt_key": "${FEISHU_ENCRYPT_KEY}",
    "notify_chat_id": "${FEISHU_CHAT_ID}",
    "trigger_mode": "spawn",
    "project_path": "${PROJECT_DIR}",
    "gitlab_token": "${GITLAB_TOKEN}",
    "trigger_events": ["task_assigned", "task_created"]
  }
}
EOF
fi

# ── 6. 启动 bot（cwd 必须是 project_dir，L2 config 靠 cwd 定位）──
export CLAUDE_PLUGIN_ROOT="$PIPELIT_DIR"
export ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY}"

echo "[entrypoint] starting feishu bot (longpoll) from $PROJECT_DIR..."
cd "$PROJECT_DIR"
exec python3 "$PIPELIT_DIR/scripts/feishu_bot_longpoll.py" serve
