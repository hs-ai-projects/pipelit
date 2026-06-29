# 容器内退出
exit          # 或 Ctrl+D

# 常用命令


# 进入容器
docker compose exec feishu-bot bash

# 启动 / 停止 / 重启
docker compose up -d
docker compose down
docker compose restart feishu-bot

# 重建镜像并启动
docker compose up -d --build

# 查日志（实时）
docker compose logs -f feishu-bot

# 查日志（最近100行）
docker compose logs --tail=100 feishu-bot

# 查容器状态
docker compose ps

# 查容器资源占用
docker stats