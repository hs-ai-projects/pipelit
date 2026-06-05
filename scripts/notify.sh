#!/usr/bin/env bash
# Pipelit AskUserQuestion 通知脚本 (Mac / Linux)
# 由 Claude Code PreToolUse hook 调用。

MSG="${1:-Pipelit 需要你的输入}"

if command -v osascript &>/dev/null; then
    # macOS
    osascript -e "display notification \"$MSG\" with title \"Pipelit\"" 2>/dev/null || true
elif command -v notify-send &>/dev/null; then
    # Linux (libnotify)
    notify-send "Pipelit" "$MSG" 2>/dev/null || true
fi

exit 0
