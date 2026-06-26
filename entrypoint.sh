#!/bin/bash
set -e

PIPELIT_DIR="/app/pipelit"
FRONTEND_DIR="/app/ads-web"
BACKEND_DIR="/app/ads"

# ── 1. Clone pipelit ──────────────────────────────────────────────
echo "[entrypoint] syncing pipelit..."
if [ -d "$PIPELIT_DIR/.git" ]; then
  git -C "$PIPELIT_DIR" pull --ff-only
else
  git clone "https://oauth2:${GITLAB_TOKEN}@${PIPELIT_REPO#https://}" "$PIPELIT_DIR"
fi

# ── 2. Clone 前端 ─────────────────────────────────────────────────
echo "[entrypoint] syncing frontend (ads-web)..."
if [ -d "$FRONTEND_DIR/.git" ]; then
  git -C "$FRONTEND_DIR" pull --ff-only
else
  git clone "http://oauth2:${GITLAB_TOKEN}@${FRONTEND_REPO#http://}" "$FRONTEND_DIR"
fi

# ── 3. Clone 后端 ─────────────────────────────────────────────────
echo "[entrypoint] syncing backend (ads)..."
if [ -d "$BACKEND_DIR/.git" ]; then
  git -C "$BACKEND_DIR" pull --ff-only
else
  git clone "http://oauth2:${GITLAB_TOKEN}@${BACKEND_REPO#http://}" "$BACKEND_DIR"
fi

# ── 4. 配置 git 身份 ──────────────────────────────────────────────
git config --global user.email "${GIT_USER_EMAIL}"
git config --global user.name "${GIT_USER_NAME:-pipelit-bot}"

# ── 5. 启动 bot ───────────────────────────────────────────────────
export CLAUDE_PLUGIN_ROOT="$PIPELIT_DIR"
export ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY}"

echo "[entrypoint] starting feishu bot..."
cd "$FRONTEND_DIR"
exec python3 "$PIPELIT_DIR/scripts/feishu_bot_longpoll.py" serve
