#!/bin/bash
set -e

PIPELIT_DIR="/app/pipelit"
FRONTEND_DIR="/app/ads-web"
BACKEND_DIR="/app/ads"

git config --global --add safe.directory '*'

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

# ── 4. 覆盖项目级 claude settings（本地 Windows 路径在容器里无效）──────
mkdir -p "$PIPELIT_DIR/.claude"
cat > "$PIPELIT_DIR/.claude/settings.json" << 'EOF'
{
  "permissions": {
    "allow": ["Bash(*)", "Read(*)", "Write(*)", "Edit(*)", "Glob(*)", "Grep(*)", "LS(*)"],
    "additionalDirectories": ["/app", "/tmp", "/root"]
  }
}
EOF
rm -f "$PIPELIT_DIR/.claude/settings.local.json"

# ── 5. 配置 git 身份 ──────────────────────────────────────────────
git config --global user.email "pipelit-bot@bot.local"
git config --global user.name "pipelit-bot"

# ── 5. 启动 bot ───────────────────────────────────────────────────
export CLAUDE_PLUGIN_ROOT="$PIPELIT_DIR"
export BOT_FRONTEND_PATH="$FRONTEND_DIR"
export BOT_BACKEND_PATH="$BACKEND_DIR"
export ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY}"
export ANTHROPIC_BASE_URL="${ANTHROPIC_BASE_URL}"
export ANTHROPIC_AUTH_TOKEN="${ANTHROPIC_AUTH_TOKEN}"
export ANTHROPIC_DEFAULT_SONNET_MODEL="${ANTHROPIC_DEFAULT_SONNET_MODEL}"
export BOT_ANALYSIS_MODEL="${BOT_ANALYSIS_MODEL}"
export BOT_EXECUTION_MODEL="${BOT_EXECUTION_MODEL}"
export BOT_SKIP_PERMS=1

echo "[entrypoint] starting feishu bot..."
cd "$FRONTEND_DIR"
exec python3 "$PIPELIT_DIR/scripts/feishu_bot_longpoll.py" serve
