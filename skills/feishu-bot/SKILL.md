---
name: feishu-bot
description: >
  飞书机器人 Webhook 配置手册。触发词：
  "配置飞书机器人"、"feishu-bot setup"、"webhook 怎么配"、"机器人收不到事件"。
  包含服务器环境、飞书应用、GitLab Token、Bot 初始化、systemd 部署、排障全流程。
---

# 飞书 Bot × feishu-dev 联动手册

> **适用场景**：云服务器部署，飞书任务事件自动触发 Claude Code 完成开发。

---

## 目录

1. [架构总览](#1-架构总览)
2. [服务器环境配置](#2-服务器环境配置)
3. [飞书应用配置](#3-飞书应用配置)
4. [GitLab Token 配置](#4-gitlab-token-配置)
5. [Bot 初始化配置](#5-bot-初始化配置)
6. [启动服务](#6-启动服务)
7. [验证 & 排障](#7-验证--排障)

---

## 1. 架构总览

```
飞书平台
  │  POST 事件（任务创建 / 指派）
  ▼
云服务器 :8765
  feishu_bot_webhook.py       ← 接收事件、验签、路由
  feishu_bot_analyzer.py      ← 调用 claude --print 分析 + 执行
  │
  ├── L3 → 发分析报告卡片到飞书群
  ├── L2 需求 → 发确认卡片 → 用户点按钮 → 无交互实现 → MR → 结果卡片
  └── L2 Bug → 全自动修复 → push → GitLab MR → 结果卡片
```

**前置条件清单**

| 项目 | 说明 |
|------|------|
| 云服务器 | Ubuntu 20.04+ / CentOS 8+ / Rocky 9+，已有公网 IP |
| Node.js 18+ | 用于安装 Claude Code CLI |
| Python 3.10+ | 运行 feishu_api.py 等脚本 |
| Git | 项目代码已 clone 到服务器 |
| 飞书自建应用 | 需企业管理员审批 |
| GitLab Personal Token | `api` 权限 |
| Anthropic API Key | 用于 `claude --print` 无交互模式 |

---

## 2. 服务器环境配置

### 2.1 安装 Node.js（如未安装）

**Ubuntu / Debian：**

```bash
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install -y nodejs
node -v   # 应显示 v20.x
```

**CentOS / RHEL / Rocky / Alma：**

```bash
curl -fsSL https://rpm.nodesource.com/setup_20.x | bash -
dnf install -y nodejs    # 注意包名是 nodejs，不是 node.js
node -v                   # 应显示 v20.x
```

> CentOS 8 已 EOL（2021-12），默认 yum 源失效。但 NodeSource 自带独立 RPM 源，
> 不依赖 CentOS 官方源，所以装 Node 不受影响。

### 2.2 安装 Claude Code CLI

```bash
npm install -g @anthropic-ai/claude-code
claude --version   # 验证安装成功
```

### 2.3 配置 Anthropic API Key

服务器上 Claude Code 必须用 API Key 驱动（无法交互式登录）：

```bash
# 写入 ~/.bashrc 持久化
echo 'export ANTHROPIC_API_KEY="sk-ant-xxxxxxxxxxxxxxxx"' >> ~/.bashrc
source ~/.bashrc

# 验证
claude --print "ping" --model claude-haiku-4-5-20251001
# 输出任意内容即代表 Key 有效
```

> Key 在 https://console.anthropic.com/settings/keys 申请。

### 2.4 克隆 pipelit 插件到服务器

```bash
git clone <你的 pipelit 仓库地址> ~/pipelit
export CLAUDE_PLUGIN_ROOT=~/pipelit
echo 'export CLAUDE_PLUGIN_ROOT=~/pipelit' >> ~/.bashrc
```

### 2.5 克隆项目代码到服务器

```bash
# 把你要开发的项目也 clone 到服务器，claude 在这里改代码
git clone git@gitlab.com:your-group/your-project.git ~/project
```

### 2.6 安装 Python 依赖（stdlib only，无需 pip）

脚本使用 PEP 604 联合类型语法（`str | None`），**必须 Python 3.10+**。
代码全部 stdlib，不需要 pip 安装任何第三方包。

```bash
python3 --version   # 期望 3.10+
```

**如果系统 Python < 3.10（典型场景：CentOS 8 自带 3.6.8）：**

不要动系统 Python（系统工具依赖它）。用 `uv` 装一个隔离的 Python：

```bash
# 装 uv（Astral 出品的 Python 版本/包管理器，类似 nvm + pnpm 的合体）
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.bashrc

# 装 Python 3.11
uv python install 3.11

# 验证：用 uv 提供的 python 跑
uv run --python 3.11 python3 --version   # 应显示 Python 3.11.x
```

之后所有 `python3 ~/pipelit/scripts/xxx.py` 改为
`uv run --python 3.11 python3 ~/pipelit/scripts/xxx.py`。
systemd service 的 `ExecStart` 也要相应替换。

**隔离机制（关键，避免误伤系统）：**

uv 装的 Python 放在 `~/.local/share/uv/python/cpython-3.11.*/bin/python3`，
**不会**替换 `/usr/bin/python3`，**不会**改系统 PATH。
只有显式 `uv run` 或调用 uv 那条绝对路径时才用 3.11，
系统脚本、yum、其他 Python 项目继续用系统 3.6，互不打扰。

**装完一定要验证（确认没污染系统环境）：**

```bash
which python3                            # 应该还是 /usr/bin/python3
/usr/bin/python3 --version               # 应该还是 3.6.8
uv run --python 3.11 python3 --version   # 应该是 3.11.x
```

**避雷：先确认机器上没有冲突的 Python 管理器：**

```bash
which pyenv conda 2>&1 | head -5
# 无输出 = 干净，放心装 uv
# 有输出 = 已有 pyenv/conda，会和 uv 抢 PATH，需要单独评估
```

---

## 3. 飞书应用配置

> 需要飞书企业**管理员账号**操作，或联系管理员代为审批。

### 3.1 创建自建应用

1. 打开 https://open.feishu.cn/ → 开发者后台
2. 点击「创建应用」→ 选择「自建应用」
3. 填写名称（如 `pipelit-bot`）、描述，上传图标
4. 保存后进入应用详情页

### 3.2 获取凭据

在「凭证与基础信息」页面，记录：

```
App ID:     cli_xxxxxxxxxxxxxxxx
App Secret: xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

在服务器上保存凭据：

```bash
PYTHONIOENCODING=utf-8 python3 ~/pipelit/scripts/feishu_api.py \
  save_config <App_ID> <App_Secret>
```

### 3.3 申请应用权限

进入「权限管理」→ 搜索并开启以下权限：

| 权限 | 用途 |
|------|------|
| `task:task:read` | 读取任务详情 |
| `task:task:write` | 完成任务、修改状态 |
| `task:comment:write` | 添加任务评论 |
| `task:attachment:read` | 下载附件图片 |
| `im:message:send_as_bot` | 机器人发消息 |
| `im:message` | 发送卡片 |

### 3.4 获取 Encrypt Key（可选，推荐开启）

「安全设置」→「Encrypt Key」→ 点击「启用」→ 复制 Encrypt Key

Encrypt Key 用于验证飞书发来的请求是否合法，防伪造请求。

### 3.5 配置事件订阅

**先启动 webhook 服务器**（见第 6 节），再来填 URL，否则飞书校验会失败。

1. 「事件与回调」→「事件订阅」
2. 填写 Request URL：
   ```
   https://your-server-ip:8765/feishu/event
   ```
   或用域名：
   ```
   https://bot.your-domain.com/feishu/event
   ```
3. 填写 Encrypt Key（如步骤 3.4 已开启）
4. 点击「验证」→ 服务器正常运行时会自动通过
5. 订阅以下事件（搜索并添加）：

| 事件名 | 用途 |
|--------|------|
| `task.v2.task_created_v1` | 新任务创建时触发 |
| `task.v2.task_updated_v1` | 任务更新（含成员变更/指派）时触发 |

### 3.6 配置卡片回调 URL

「事件与回调」→「卡片回调」→ 填写：

```
https://your-server-ip:8765/feishu/card-action
```

L2 需求卡片的「确认开发」按钮点击后会回调到这里。

### 3.7 获取你的飞书 user_id

Bot 需要知道"你"的 user_id，才能判断任务是否指派给你。

```bash
# 方式一：通过邮箱查询
PYTHONIOENCODING=utf-8 python3 ~/pipelit/scripts/feishu_api.py \
  save_user --email your@company.com

# 方式二：通过手机号查询
PYTHONIOENCODING=utf-8 python3 ~/pipelit/scripts/feishu_api.py \
  save_user --mobile 13812345678
```

执行后 user_id 自动写入配置文件。

### 3.8 获取通知群的 chat_id

把 bot 拉入目标群后：

1. 打开飞书网页版，进入目标群
2. 地址栏 URL 中有 `?chat_id=oc_xxxxxxxx`，复制该值
3. 或通过飞书 API：「获取群列表」接口

### 3.9 发布应用版本

1. 「版本管理与发布」→「创建版本」
2. 填写版本号 + 更新说明
3. 点击「申请发布」→ 联系管理员审批
4. 审批通过后应用才能正常调用 API

---

## 4. GitLab Token 配置

### 4.1 创建 Personal Access Token

1. GitLab → 右上角头像 → Preferences → Access Tokens
2. 填写 Token 名称（如 `pipelit-bot`）
3. 勾选权限：`api`（包含 MR 创建权限）
4. 生成并**立即保存** Token（只显示一次）

### 4.2 保存到配置

Token 会在第 5 节 Bot 初始化时一并配置。

---

## 5. Bot 初始化配置

> **CentOS 8 / 系统 Python < 3.10 的环境**：把下文所有 `python3` 替换成
> `uv run --python 3.11 python`（参考第 2.6 节）。下面的命令会同时给出两种形式。

在服务器上运行配置向导：

```bash
# Ubuntu / Python 3.10+ 的系统
PYTHONIOENCODING=utf-8 python3 ~/pipelit/scripts/feishu_bot_webhook.py setup

# CentOS 8 等系统 Python 太老的场景
PYTHONIOENCODING=utf-8 uv run --python 3.11 \
  python ~/pipelit/scripts/feishu_bot_webhook.py setup
```

按提示填入：

```
监听端口 [8765]:              8765
Encrypt Key [空]:             （飞书后台复制的 Encrypt Key）
notify_chat_id:               oc_xxxxxxxxxxxxxxxxxxxxxxxx
trigger_mode [notify]:        spawn
project_path:                 /home/ubuntu/project
GitLab Token:                 glpat-xxxxxxxxxxxxxxxxxxxx
```

> **trigger_mode 说明**
> - `spawn`：事件到达后直接在服务器运行 `claude --print`（全自动，推荐）
> - `notify`：只发卡片通知，不自动运行（调试用）

配置完成后验证：

```bash
# Ubuntu / Python 3.10+
PYTHONIOENCODING=utf-8 python3 ~/pipelit/scripts/feishu_api.py get_bot_config

# CentOS 8 等老系统
PYTHONIOENCODING=utf-8 uv run --python 3.11 \
  python ~/pipelit/scripts/feishu_api.py get_bot_config
```

输出 `"configured": true` 即配置成功。

---

## 6. 启动服务

### 6.1 手动启动（测试用）

```bash
# Ubuntu / Python 3.10+
CLAUDE_PLUGIN_ROOT=~/pipelit \
ANTHROPIC_API_KEY=sk-ant-xxx \
python3 ~/pipelit/scripts/feishu_bot_webhook.py serve

# CentOS 8 等系统 Python 太老的场景
CLAUDE_PLUGIN_ROOT=~/pipelit \
ANTHROPIC_API_KEY=sk-ant-xxx \
uv run --python 3.11 python ~/pipelit/scripts/feishu_bot_webhook.py serve

# 输出类似：
# {
#   "status": "running",
#   "port": 8765,
#   "trigger_mode": "spawn",
#   ...
# }
```

### 6.2 systemd 服务（生产用）

创建服务文件：

```bash
sudo tee /etc/systemd/system/pipelit-bot.service > /dev/null <<EOF
[Unit]
Description=Pipelit Feishu Bot Webhook Server
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/project
Environment="CLAUDE_PLUGIN_ROOT=/home/ubuntu/pipelit"
Environment="ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxxxxxx"
ExecStart=/usr/bin/python3 /home/ubuntu/pipelit/scripts/feishu_bot_webhook.py serve
# CentOS 8 等老系统改用 uv（先 which uv 看实际路径，常见 /root/.local/bin/uv）：
# ExecStart=/root/.local/bin/uv run --python 3.11 python /root/pipelit/scripts/feishu_bot_webhook.py serve
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF
```

启动并设置开机自启：

```bash
sudo systemctl daemon-reload
sudo systemctl enable pipelit-bot
sudo systemctl start pipelit-bot
sudo systemctl status pipelit-bot   # 应显示 active (running)
```

### 6.3 开放端口（如有防火墙）

```bash
# UFW
sudo ufw allow 8765/tcp

# 或使用 nginx 反向代理（推荐生产环境）
```

**Nginx 反向代理示例：**

```nginx
server {
    listen 443 ssl;
    server_name bot.your-domain.com;

    ssl_certificate     /path/to/fullchain.pem;
    ssl_certificate_key /path/to/privkey.pem;

    location /feishu/ {
        proxy_pass http://127.0.0.1:8765;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Lark-Request-Timestamp $http_x_lark_request_timestamp;
        proxy_set_header X-Lark-Request-Nonce $http_x_lark_request_nonce;
        proxy_set_header X-Lark-Signature $http_x_lark_signature;
    }

    location /health {
        proxy_pass http://127.0.0.1:8765;
    }
}
```

> 飞书生产环境要求 HTTPS，建议用 Nginx + Let's Encrypt。

### 6.4 长连接模式（推荐：bot 在内网，没有公网入口）

如果 bot 部署在内网，**没法暴露公网 URL 给飞书 push 事件**，
就用飞书 SDK 的 WebSocket 长连接：**bot 主动连飞书，飞书通过这条连接 push 事件**。

```
传统 webhook 模式：飞书 → POST 你的公网 URL → bot
长连接模式：      bot → 主动 WSS 连接 → 飞书   （只需要"出方向"公网可达）
```

入口脚本是 `scripts/feishu_bot_longpoll.py`，业务逻辑与 webhook 模式完全相同
（复用 `feishu_bot_webhook.py` 的事件解析和 analyzer 调用）。

**前置条件**：服务器能访问公网（用 `curl https://open.feishu.cn` 测试）。

**步骤 1：安装 SDK**

```bash
# Ubuntu / Python 3.10+
pip3 install lark-oapi

# CentOS 8 等老系统（系统 Python 太老，走 uv）
uv pip install --python 3.11 lark-oapi

# 国内 PyPI 慢则加镜像
uv pip install --python 3.11 lark-oapi -i https://pypi.tuna.tsinghua.edu.cn/simple
```

**步骤 2：启动**

```bash
# Ubuntu / Python 3.10+
CLAUDE_PLUGIN_ROOT=~/pipelit \
ANTHROPIC_API_KEY=sk-ant-xxx \
python3 ~/pipelit/scripts/feishu_bot_longpoll.py serve

# CentOS 8 / uv
CLAUDE_PLUGIN_ROOT=~/pipelit \
ANTHROPIC_API_KEY=sk-ant-xxx \
uv run --python 3.11 python ~/pipelit/scripts/feishu_bot_longpoll.py serve
```

**步骤 3：飞书后台配置**

- **不需要**填事件订阅 URL、不需要填卡片回调 URL
- 仍然要在「事件订阅」里**订阅事件**：`task.v2.task_created_v1`、`task.v2.task_updated_v1`
- 应用必须已发布 + 权限审批通过

**与 webhook 模式的差别**：

| 项 | webhook | longpoll |
|---|---|---|
| 公网入口 | 必须 | 不需要 |
| 飞书后台 URL 配置 | 必填 | 留空 |
| 服务器监听端口 | 8765 | 不监听端口 |
| 网络模型 | 飞书 → 服务器（入站） | 服务器 → 飞书（出站） |
| 依赖 | 仅 stdlib | + lark-oapi |

**systemd 部署**：跟 6.2 节相同，把 `ExecStart` 换成 `feishu_bot_longpoll.py serve` 的命令即可。

---

## 7. 验证 & 排障

### 7.1 健康检查

```bash
curl http://localhost:8765/health
# 返回：{"status": "ok", "port": 8765, ...}
```

### 7.2 手动触发测试

```bash
# 用真实 task_id 测试全流程（不需要飞书事件）
CLAUDE_PLUGIN_ROOT=~/pipelit python3 ~/pipelit/scripts/feishu_bot_webhook.py \
  test <task_id>
```

### 7.3 查看运行日志

```bash
# webhook 主日志
tail -f ~/pipelit/.cache/webhook_logs/webhook.log

# 某个任务的 claude 执行日志
ls ~/pipelit/.cache/webhook_logs/dev-*.log
tail -f ~/pipelit/.cache/webhook_logs/dev-<task_id_前8位>-*.log

# systemd 日志
sudo journalctl -u pipelit-bot -f
```

### 7.4 常见问题

**问：飞书 URL 验证失败（verify failed）**
- 确认服务器已启动，端口可访问
- 检查防火墙是否开放 8765 端口
- 检查是否用了 HTTPS（飞书生产环境要求）

**问：收到事件但不触发**
- 检查 `user_id` 是否配置正确（任务被指派给你才触发）
- 检查 `trigger_events` 包含 `task_assigned` 或 `task_created`
- 查看 `webhook.log` 中的 `[event]` 行

**问：`claude --print` 报错 `API key invalid`**
- 确认 `ANTHROPIC_API_KEY` 已在 systemd service 的 `Environment` 中配置
- 运行 `claude --print "hello"` 手动测试

**问：GitLab MR 创建失败**
- 确认 `gitlab_token` 有 `api` 权限
- 确认 token 未过期
- 检查 git remote URL 格式（支持 `git@` 和 `https://` 两种）

**问：卡片确认按钮点了没反应**
- 确认「卡片回调 URL」已在飞书后台配置
- 检查 `webhook.log` 中是否有 `[card-action]` 记录

### 7.5 配置文件位置

```
~/pipelit/.cache/
  config.json              # 主配置（含 bot、飞书凭据、GitLab Token）
  .token_cache.json        # 飞书 tenant token 缓存
  webhook_logs/
    webhook.log            # 主日志
    dev-<id>-<ts>.log      # 每次 claude 执行日志
  pending/
    <task_id>.json         # 待确认的需求分析缓存
```

---

## 附：完整配置文件示例

```json
{
  "app_id": "cli_xxxxxxxxxxxxxxxx",
  "app_secret": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "user_id": "ou_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "frontend_path": "/home/ubuntu/project/frontend",
  "backend_path": "/home/ubuntu/project/backend",
  "bot": {
    "port": 8765,
    "encrypt_key": "xxxxxxxxxxxxxxxx",
    "notify_chat_id": "oc_xxxxxxxxxxxxxxxxxxxxxxxx",
    "trigger_mode": "spawn",
    "project_path": "/home/ubuntu/project",
    "gitlab_token": "glpat-xxxxxxxxxxxxxxxxxxxx",
    "trigger_events": ["task_assigned", "task_created"]
  }
}
```
