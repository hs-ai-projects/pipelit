# Pipelit TODO

## 当前进度

Bot 自动化链路：**Step 1 已完成** — 服务器监听飞书任务事件，自动分析发送卡片

---

## 待完成

### Step 2：Bot 监听 bug 任务时联动观测云日志分析
- [ ] 识别到 bug 型任务时，调用 `guance-log-analysis` 拉取相关日志
- [ ] 把日志分析结果合并到分析卡片（主要问题 / 可能原因 / 建议排查）
- [ ] 确定触发条件：任务标题含"报错/异常/bug"等关键词时自动关联

### Step 3：打通分析 → 编码链路
- [ ] 卡片确认后触发本地 feishu-dev 自动完成编码
- [ ] 复用 feishu-dev 已验证的代码质量（不在服务器上重写编码逻辑）
- [ ] 完成后推送分支，发结果卡片（含分支名 / 改动文件）

### 稳定性优化（来自 cc-connect 参考）
- [ ] 旧消息过滤：longpoll 重启后忽略启动前 2 秒内的事件，防止重复触发
- [ ] 消息级去重：同一事件 60 秒内只处理一次（比现有防抖更精准）
- [ ] 同步过滤链：收到事件先同步过滤，通过后再启线程，减少无效线程

### 多用户支持
- [ ] sessionKey 隔离：支持多人使用同一 bot，pending 缓存按用户隔离
- [ ] config 支持多 user_id，每个人的任务互不干扰

---

## 已完成

- [x] 服务器部署飞书 Bot 长连接（WebSocket）
- [x] 监听 task_user_access / task_created 事件
- [x] 事件过滤：只响应"被指派为负责人"，过滤关注人变更等噪音
- [x] 调用 Claude API 分析任务（L1 / L2 / L3 分级）
- [x] 结合项目代码上下文（grep 文件树 + 关键词命中）
- [x] 读取任务附件图片传给 Claude 分析
- [x] 发送飞书卡片（标题=原始任务名，正文=分析概要 + 改哪里）
- [x] check 命令：检查所有配置项是否完整

1. 三层防重复（你现在只有 1 层防抖）

# 第1层：消息级去重（60秒 TTL）
class MessageDedup:
    def is_duplicate(self, msg_id):
        # 60秒内同一 msg_id 只处理一次

# 第2层：旧消息过滤
BOT_START_TIME = time.time()
def is_old_message(ts):
    return ts < (BOT_START_TIME - 2)  # 重启后忽略2秒前的消息

# 第3层：消息撤回追踪
recalled_msgs = {}  # msg_id → recall_time

2. 事件过滤链（同步先过滤，异步再处理）

收到事件（同步）
  → 去重检查（快速失败）
  → 权限检查（白名单）
  → 判断是否需要处理
  → ✓ 放入线程池异步处理
  → ✗ 直接丢弃

3.多用户 sessionKey 隔离

def make_session_key(chat_id, user_id, task_id=None):
    if task_id:
        return f'{chat_id}:{task_id}:{user_id}'
    return f'{chat_id}:{user_id}'
