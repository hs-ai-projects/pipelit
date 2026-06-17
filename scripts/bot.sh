#!/bin/bash
# Pipelit Bot 管理脚本
# 用法：./bot.sh [start|stop|restart|status|log]

PYTHON="$HOME/pipelit/.venv/bin/python"
SCRIPT="$HOME/pipelit/scripts/feishu_bot_longpoll.py"
LOG="$HOME/.claude/pipelit/webhook_logs/webhook.log"
PNAME="feishu_bot_longpoll"

case "$1" in
  start)
    if pgrep -f "$PNAME" > /dev/null; then
      echo "Bot 已在运行，无需重复启动"
      exit 0
    fi
    mkdir -p "$(dirname "$LOG")"
    cd "$HOME/pipelit" || exit 1
    git pull
    nohup "$PYTHON" "$SCRIPT" serve >> "$LOG" 2>&1 &
    sleep 1
    if pgrep -f "$PNAME" > /dev/null; then
      echo "✅ Bot 启动成功（PID: $(pgrep -f $PNAME)）"
    else
      echo "❌ Bot 启动失败，查看日志："
      tail -20 "$LOG"
    fi
    ;;
  stop)
    if pkill -f "$PNAME"; then
      echo "✅ Bot 已停止"
    else
      echo "Bot 未在运行"
    fi
    ;;
  restart)
    "$0" stop
    sleep 1
    "$0" start
    ;;
  status)
    if pgrep -f "$PNAME" > /dev/null; then
      echo "✅ Bot 运行中（PID: $(pgrep -f $PNAME)）"
    else
      echo "❌ Bot 未运行"
    fi
    ;;
  log)
    tail -f "$LOG"
    ;;
  *)
    echo "用法：$0 {start|stop|restart|status|log}"
    exit 1
    ;;
esac
