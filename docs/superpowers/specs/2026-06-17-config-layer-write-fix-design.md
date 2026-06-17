# Config 分层写入修复设计

**日期：** 2026-06-17  
**状态：** 待实现  
**影响文件：** `scripts/feishu_api.py`

---

## 背景

pipelit 的配置读取支持三层合并（L1 用户级 < L2 项目级 < L3 仓库级），但所有 `save_*` 函数都写死写入 L1（`~/.claude/pipelit/config.json`）。这导致多项目场景下，切换项目时配置互相覆盖，无法为不同项目配置不同飞书应用。

---

## 目标

- 项目级配置（凭据、路径、发版、bot）写入 L2（`<cwd>/.pipelit/config.json`）
- `user_id` 保持写入 L1（真正全局，跨项目不变）
- token 缓存按 app_id 隔离（单文件 + app_id 字段校验）
- 不写任何迁移代码，不兼容旧 L1 配置

---

## 配置分层职责

| 层 | 位置 | 内容 |
|----|------|------|
| L1 用户级 | `~/.claude/pipelit/config.json` | `user_id` 只放这里 |
| L2 项目级 | `<cwd>/.pipelit/config.json` | `app_id`、`app_secret`、`frontend_path`、`backend_path`、`release`、`bot` |
| L3 仓库级 | `<cwd>/.pipelit.json`（可选）| precheck 命令、特殊规则 |

---

## 实现细节

### 1. 新增工具函数

```python
def _project_config_file(cwd=None) -> pathlib.Path:
    base = pathlib.Path(cwd) if cwd else pathlib.Path.cwd()
    return base / ".pipelit" / "config.json"

def _read_project_config(cwd=None) -> dict:
    f = _project_config_file(cwd)
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}

def _write_project_config(data: dict, cwd=None):
    f = _project_config_file(cwd)
    f.parent.mkdir(parents=True, exist_ok=True)
    _secure_write(f, json.dumps(data, indent=2, ensure_ascii=False))
```

### 2. save_* 写入目标变更

| 函数 | 修改前 | 修改后 |
|------|--------|--------|
| `save_config(app_id, app_secret)` | → L1 | → L2（cwd） |
| `save_project_config(frontend, backend)` | → L1 | → L2（cwd） |
| `save_release_config(json)` | → L1 | → L2（cwd） |
| `save_bot_config(json)` | → L1 | → L2（cwd） |
| `save_user(email/mobile)` | → L1 | → L1（不变） |

各函数改法一致：将 `cfg = read_config() or {}` + `_secure_write(CONFIG_FILE, ...)` 替换为 `cfg = _read_project_config()` + `_write_project_config(cfg)`。

### 3. 读取路径修复

以下函数目前用 `read_config()`（只读 L1），改为 `load_merged_config()`：

- `check_config()`
- `check_project_config()`
- `get_token()`
- `get_release_config()`
- `get_bot_config()`
- `_resolve_reference_image()`
- `_release_brand_context()`

### 4. token 缓存 app_id 隔离

**读取时**：校验 `cache["app_id"] == cfg["app_id"]`，不一致则视为缓存失效，重新获取。

**写入时**：缓存中额外存 `"app_id": cfg["app_id"]`。

```python
def get_token() -> str:
    cfg = load_merged_config()  # 改用 merged config
    if TOKEN_CACHE_FILE.exists():
        cache = json.loads(TOKEN_CACHE_FILE.read_text())
        if (time.time() < cache.get("expires_at", 0)
                and cache.get("app_id") == cfg.get("app_id")):
            return cache["token"]
    # ... 获取 token ...
    _secure_write(TOKEN_CACHE_FILE, json.dumps({
        "token": token,
        "expires_at": expires_at,
        "app_id": cfg["app_id"],
    }))
    return token
```

### 5. 引导提示文案更新

`check_config` 返回未配置时的提示语，补充说明写入位置：

> 凭据将保存到当前项目 `.pipelit/config.json`，不同项目可配置不同飞书应用。

---

## 不在范围内

- 迁移旧 L1 配置（不做）
- bot `--cwd` 参数支持（不做，bot 继续从 L2 读，启动目录由用户控制）
- L3 相关改动（无需修改）
- skill 文件改动（`save_*` 函数签名不变，skill 调用无需更新）

---

## 验证方式

1. 在项目A目录运行 `save_config` → 确认写入 `项目A/.pipelit/config.json`，L1 不变
2. 在项目B目录运行 `save_config` → 确认写入 `项目B/.pipelit/config.json`，不影响项目A
3. 切换到项目A，`check_config` 返回项目A的 app_id
4. token 缓存：项目A获取 token 后切换到项目B，验证重新获取（app_id 不同）
5. `save_user` 仍写 L1，`user_id` 全局可用
