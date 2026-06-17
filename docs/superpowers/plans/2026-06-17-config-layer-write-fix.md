# Config 分层写入修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 pipelit 的项目级配置（凭据、路径、发版、bot）写入 L2（`<cwd>/.pipelit/config.json`），`user_id` 保持写 L1，token 缓存按 app_id 隔离。

**Architecture:** 只改 `scripts/feishu_api.py`。新增三个内部工具函数（`_project_config_file` / `_read_project_config` / `_write_project_config`）作为 L2 读写锚点；将四个 `save_*` 函数的写入目标从 L1 改为 L2；将所有读取凭据的函数从 `read_config()` 改为 `load_merged_config()`；token 缓存加 app_id 字段校验。

**Tech Stack:** Python 3.10+, pathlib, json, tempfile（测试用）

---

## 文件变更清单

| 操作 | 文件 |
|------|------|
| Modify | `scripts/feishu_api.py` |
| Modify | `tests/test_regression.py` |

---

### Task 1：新增 L2 工具函数

**Files:**
- Modify: `scripts/feishu_api.py`（在 `load_merged_config` 定义之前，约第 273 行）

- [ ] **Step 1：写失败测试**

在 `tests/test_regression.py` 末尾、`sys.exit` 之前加入：

```python
# ─── 9. L2 工具函数 ───────────────────────────────────────────────────────────
print("\n=== 9. L2 工具函数（config-layer-write-fix）===")
with tempfile.TemporaryDirectory() as tmpdir2:
    f = fa._project_config_file(cwd=tmpdir2)
    check("_project_config_file 返回正确路径",
          str(f) == str(pathlib.Path(tmpdir2) / ".pipelit" / "config.json"))

    fa._write_project_config({"app_id": "test_app"}, cwd=tmpdir2)
    read_back = fa._read_project_config(cwd=tmpdir2)
    check("_write_project_config 写入后 _read_project_config 可读",
          read_back.get("app_id") == "test_app")

    empty = fa._read_project_config(cwd="/tmp/nonexistent_9999")
    check("_read_project_config 目录不存在时返回空 dict", empty == {})
```

- [ ] **Step 2：运行测试确认失败**

```bash
cd C:/Users/otsan.li/Desktop/work/skill/pipelit
PYTHONIOENCODING=utf-8 python3 tests/test_regression.py 2>&1 | tail -20
```

期望：`AttributeError: module 'feishu_api' has no attribute '_project_config_file'`

- [ ] **Step 3：在 `feishu_api.py` 的 `load_merged_config` 函数之前插入工具函数**

找到约第 273 行 `def load_merged_config`，在其**正上方**插入：

```python
# ── L2 Project Config Helpers ─────────────────────────────────────────────────

def _project_config_file(cwd=None) -> pathlib.Path:
    base = pathlib.Path(cwd) if cwd else pathlib.Path.cwd()
    return base / ".pipelit" / "config.json"


def _read_project_config(cwd=None) -> dict:
    f = _project_config_file(cwd)
    if not f.exists():
        return {}
    return json.loads(f.read_text(encoding="utf-8"))


def _write_project_config(data: dict, cwd=None) -> None:
    f = _project_config_file(cwd)
    f.parent.mkdir(parents=True, exist_ok=True)
    _secure_write(f, json.dumps(data, indent=2, ensure_ascii=False))

```

- [ ] **Step 4：运行测试确认通过**

```bash
PYTHONIOENCODING=utf-8 python3 tests/test_regression.py 2>&1 | tail -20
```

期望：`=== 9. L2 工具函数` 三条全 `[PASS]`，其余测试不变。

- [ ] **Step 5：提交**

```bash
git add scripts/feishu_api.py tests/test_regression.py
git commit -m "feat(config): add L2 project config helper functions"
```

---

### Task 2：fix `save_config` → 写 L2

**Files:**
- Modify: `scripts/feishu_api.py`（`save_config` 函数，约第 222 行）

- [ ] **Step 1：写失败测试**

在 `tests/test_regression.py` 的 Task 1 测试块下方追加：

```python
# ─── 10. save_config 写 L2 ───────────────────────────────────────────────────
print("\n=== 10. save_config 写 L2（config-layer-write-fix）===")
with tempfile.TemporaryDirectory() as tmpdir3:
    os.chdir(tmpdir3)
    fa.save_config("cli_test_app", "test_secret")
    l2 = fa._read_project_config(cwd=tmpdir3)
    check("save_config 写入 L2 app_id", l2.get("app_id") == "cli_test_app")
    check("save_config 写入 L2 app_secret", l2.get("app_secret") == "test_secret")
    # L1 不应被写入 app_id
    l1 = fa.read_config() or {}
    check("save_config 不写 L1 app_id", "app_id" not in l1 or l1.get("app_id") != "cli_test_app")
```

- [ ] **Step 2：运行测试确认失败**

```bash
PYTHONIOENCODING=utf-8 python3 tests/test_regression.py 2>&1 | grep -A3 "=== 10"
```

期望：`[FAIL] save_config 写入 L2 app_id`

- [ ] **Step 3：修改 `save_config`**

将原来的：

```python
def save_config(app_id: str, app_secret: str) -> dict:
    USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    cfg = read_config() or {}
    cfg["app_id"] = app_id
    cfg["app_secret"] = app_secret
    _secure_write(CONFIG_FILE, json.dumps(cfg, indent=2))
    TOKEN_CACHE_FILE.unlink(missing_ok=True)
    return {"success": True, "message": f"凭据已保存到 {CONFIG_FILE}"}
```

改为：

```python
def save_config(app_id: str, app_secret: str) -> dict:
    cfg = _read_project_config()
    cfg["app_id"] = app_id
    cfg["app_secret"] = app_secret
    _write_project_config(cfg)
    TOKEN_CACHE_FILE.unlink(missing_ok=True)
    project_file = _project_config_file()
    return {"success": True, "message": f"凭据已保存到 {project_file}"}
```

- [ ] **Step 4：运行测试确认通过**

```bash
PYTHONIOENCODING=utf-8 python3 tests/test_regression.py 2>&1 | grep -E "\[PASS\]|\[FAIL\]" | tail -10
```

期望：`=== 10` 三条全 `[PASS]`。

- [ ] **Step 5：提交**

```bash
git add scripts/feishu_api.py tests/test_regression.py
git commit -m "feat(config): save_config writes to L2 project config"
```

---

### Task 3：fix `save_project_config` → 写 L2

**Files:**
- Modify: `scripts/feishu_api.py`（`save_project_config` 函数，约第 260 行）

- [ ] **Step 1：写失败测试**

追加到测试文件：

```python
# ─── 11. save_project_config 写 L2 ──────────────────────────────────────────
print("\n=== 11. save_project_config 写 L2（config-layer-write-fix）===")
with tempfile.TemporaryDirectory() as tmpdir4:
    os.chdir(tmpdir4)
    fa.save_project_config(frontend_path="/proj/front", backend_path="/proj/back")
    l2 = fa._read_project_config(cwd=tmpdir4)
    check("save_project_config 写 L2 frontend_path", l2.get("frontend_path") == "/proj/front")
    check("save_project_config 写 L2 backend_path", l2.get("backend_path") == "/proj/back")
```

- [ ] **Step 2：运行测试确认失败**

```bash
PYTHONIOENCODING=utf-8 python3 tests/test_regression.py 2>&1 | grep -A3 "=== 11"
```

期望：`[FAIL] save_project_config 写 L2 frontend_path`

- [ ] **Step 3：修改 `save_project_config`**

将原来的：

```python
def save_project_config(frontend_path: str = None, backend_path: str = None) -> dict:
    USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    cfg = read_config() or {}
    if frontend_path:
        cfg["frontend_path"] = frontend_path.rstrip("/\\")
    if backend_path:
        cfg["backend_path"] = backend_path.rstrip("/\\")
    _secure_write(CONFIG_FILE, json.dumps(cfg, indent=2, ensure_ascii=False))
    return {
        "success": True,
        "frontend_path": cfg.get("frontend_path"),
        "backend_path": cfg.get("backend_path"),
    }
```

改为：

```python
def save_project_config(frontend_path: str = None, backend_path: str = None) -> dict:
    cfg = _read_project_config()
    if frontend_path:
        cfg["frontend_path"] = frontend_path.rstrip("/\\")
    if backend_path:
        cfg["backend_path"] = backend_path.rstrip("/\\")
    _write_project_config(cfg)
    return {
        "success": True,
        "frontend_path": cfg.get("frontend_path"),
        "backend_path": cfg.get("backend_path"),
    }
```

- [ ] **Step 4：运行测试确认通过**

```bash
PYTHONIOENCODING=utf-8 python3 tests/test_regression.py 2>&1 | grep -E "\[PASS\]|\[FAIL\]" | tail -10
```

期望：`=== 11` 两条全 `[PASS]`。

- [ ] **Step 5：提交**

```bash
git add scripts/feishu_api.py tests/test_regression.py
git commit -m "feat(config): save_project_config writes to L2"
```

---

### Task 4：fix `save_release_config` 和 `save_bot_config` → 写 L2

**Files:**
- Modify: `scripts/feishu_api.py`（`save_release_config` 约第 1530 行，`save_bot_config` 约第 1543 行）

- [ ] **Step 1：写失败测试**

追加到测试文件：

```python
# ─── 12. save_release_config / save_bot_config 写 L2 ────────────────────────
print("\n=== 12. save_release_config / save_bot_config 写 L2（config-layer-write-fix）===")
with tempfile.TemporaryDirectory() as tmpdir5:
    os.chdir(tmpdir5)
    fa.save_release_config(json.dumps({"projectName": "test-proj", "repos": []}))
    l2r = fa._read_project_config(cwd=tmpdir5)
    check("save_release_config 写 L2 release.projectName",
          l2r.get("release", {}).get("projectName") == "test-proj")

with tempfile.TemporaryDirectory() as tmpdir6:
    os.chdir(tmpdir6)
    fa.save_bot_config(json.dumps({"notify_chat_id": "oc_test", "trigger_mode": "notify"}))
    l2b = fa._read_project_config(cwd=tmpdir6)
    check("save_bot_config 写 L2 bot.notify_chat_id",
          l2b.get("bot", {}).get("notify_chat_id") == "oc_test")
```

- [ ] **Step 2：运行测试确认失败**

```bash
PYTHONIOENCODING=utf-8 python3 tests/test_regression.py 2>&1 | grep -A3 "=== 12"
```

期望：`[FAIL] save_release_config 写 L2 release.projectName`

- [ ] **Step 3：修改 `save_release_config`**

将原来的：

```python
def save_release_config(release_json: str) -> dict:
    release = json.loads(release_json)
    USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    cfg = read_config() or {}
    cfg["release"] = release
    _secure_write(CONFIG_FILE, json.dumps(cfg, indent=2, ensure_ascii=False))
    return {"success": True, "message": f"release 配置已保存到 {CONFIG_FILE}"}
```

改为：

```python
def save_release_config(release_json: str) -> dict:
    release = json.loads(release_json)
    cfg = _read_project_config()
    cfg["release"] = release
    _write_project_config(cfg)
    project_file = _project_config_file()
    return {"success": True, "message": f"release 配置已保存到 {project_file}"}
```

- [ ] **Step 4：修改 `save_bot_config`**

将原来的：

```python
def save_bot_config(bot_json: str) -> dict:
    bot = json.loads(bot_json)
    USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    cfg = read_config() or {}
    cfg["bot"] = bot
    _secure_write(CONFIG_FILE, json.dumps(cfg, indent=2, ensure_ascii=False))
    return {"success": True, "message": f"bot 配置已保存到 {CONFIG_FILE}"}
```

改为：

```python
def save_bot_config(bot_json: str) -> dict:
    bot = json.loads(bot_json)
    cfg = _read_project_config()
    cfg["bot"] = bot
    _write_project_config(cfg)
    project_file = _project_config_file()
    return {"success": True, "message": f"bot 配置已保存到 {project_file}"}
```

- [ ] **Step 5：运行测试确认通过**

```bash
PYTHONIOENCODING=utf-8 python3 tests/test_regression.py 2>&1 | grep -E "\[PASS\]|\[FAIL\]" | tail -10
```

期望：`=== 12` 两条全 `[PASS]`。

- [ ] **Step 6：提交**

```bash
git add scripts/feishu_api.py tests/test_regression.py
git commit -m "feat(config): save_release_config and save_bot_config write to L2"
```

---

### Task 5：fix 读取路径 → `load_merged_config()`

**Files:**
- Modify: `scripts/feishu_api.py`（多处，逐一替换）

- [ ] **Step 1：写失败测试**

追加到测试文件：

```python
# ─── 13. check_config 读 merged config ───────────────────────────────────────
print("\n=== 13. check_config 读 merged config（config-layer-write-fix）===")
with tempfile.TemporaryDirectory() as tmpdir7:
    # 只在 L2 放凭据，L1 不含 app_id
    fa._write_project_config(
        {"app_id": "cli_l2_only", "app_secret": "secret_l2"},
        cwd=tmpdir7
    )
    os.chdir(tmpdir7)
    result = fa.check_config()
    check("check_config 能读 L2 的 app_id", result.get("app_id") == "cli_l2_only")
    check("check_config L2 凭据时返回 configured=True", result.get("configured") is True)
```

- [ ] **Step 2：运行测试确认失败**

```bash
PYTHONIOENCODING=utf-8 python3 tests/test_regression.py 2>&1 | grep -A3 "=== 13"
```

期望：`[FAIL] check_config 能读 L2 的 app_id`

- [ ] **Step 3：修改 `check_config`**

将原来的：

```python
def check_config() -> dict:
    cfg = read_config()
```

改为：

```python
def check_config() -> dict:
    cfg = load_merged_config()
```

- [ ] **Step 4：修改 `check_project_config`**

将原来的：

```python
def check_project_config() -> dict:
    cfg = read_config() or {}
```

改为：

```python
def check_project_config() -> dict:
    cfg = load_merged_config()
```

- [ ] **Step 5：修改 `get_release_config`**

将原来的：

```python
def get_release_config() -> dict:
    cfg = read_config() or {}
```

改为：

```python
def get_release_config() -> dict:
    cfg = load_merged_config()
```

- [ ] **Step 6：修改 `get_bot_config`**

将原来的：

```python
def get_bot_config() -> dict:
    cfg = read_config() or {}
```

改为：

```python
def get_bot_config() -> dict:
    cfg = load_merged_config()
```

- [ ] **Step 7：修改 `_get_app_token`**

将原来的：

```python
def _get_app_token() -> str:
    cfg = read_config()
```

改为：

```python
def _get_app_token() -> str:
    cfg = load_merged_config()
```

- [ ] **Step 8：修改 `_resolve_reference_image`**

将原来的（约第 914 行）：

```python
cfg = read_config() or {}
```

改为：

```python
cfg = load_merged_config()
```

- [ ] **Step 9：修改 `_release_brand_context`**

将原来的（约第 932 行）：

```python
cfg = read_config() or {}
```

改为：

```python
cfg = load_merged_config()
```

- [ ] **Step 10：修改 `_save_release_mascot_config`**

将原来的（约第 1075 行）：

```python
cfg = read_config() or {}
```

改为：

```python
cfg = load_merged_config()
```

注意：该函数写入时仍用 `_secure_write(CONFIG_FILE, ...)` 写 L1——这是 mascot 图片路径，属于用户级配置，**保持不变**，只改读取那一行。

- [ ] **Step 12：运行测试确认通过**

```bash
PYTHONIOENCODING=utf-8 python3 tests/test_regression.py 2>&1 | grep -E "\[PASS\]|\[FAIL\]"
```

期望：`=== 13` 两条 `[PASS]`，全部其他测试不回退。

- [ ] **Step 13：提交**

```bash
git add scripts/feishu_api.py tests/test_regression.py
git commit -m "feat(config): all readers use load_merged_config instead of read_config"
```

---

### Task 6：fix token 缓存 app_id 校验

**Files:**
- Modify: `scripts/feishu_api.py`（`get_token` 函数，约第 312 行）

- [ ] **Step 1：写失败测试**

追加到测试文件：

```python
# ─── 14. token 缓存 app_id 校验 ──────────────────────────────────────────────
print("\n=== 14. token cache app_id 校验（config-layer-write-fix）===")
import time as _time
with tempfile.TemporaryDirectory() as tmpdir8:
    # 写一个 token 缓存，app_id = "old_app"
    cache_file = fa.TOKEN_CACHE_FILE
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps({
        "token": "old_token",
        "expires_at": _time.time() + 3600,
        "app_id": "old_app",
    }), encoding="utf-8")
    # 当前项目 app_id = "new_app"，与缓存不符，应视为失效
    # 用 load_merged_config patch 来模拟
    original_load = fa.load_merged_config
    fa.load_merged_config = lambda cwd=None: {"app_id": "new_app", "app_secret": "s"}
    try:
        # get_token 会因为 app_id 不匹配而尝试重新获取，由于没有真实飞书 → RuntimeError
        try:
            fa.get_token()
            check("token 缓存 app_id 不匹配时应触发重新获取", False, "未抛出异常")
        except Exception as e:
            # 只要它尝试重新获取（而不是直接返回 old_token）就算通过
            check("token 缓存 app_id 不匹配时触发重新获取", "old_token" not in str(e))
    finally:
        fa.load_merged_config = original_load
```

- [ ] **Step 2：运行测试确认失败**

```bash
PYTHONIOENCODING=utf-8 python3 tests/test_regression.py 2>&1 | grep -A3 "=== 14"
```

期望：`[FAIL] token 缓存 app_id 不匹配时触发重新获取`（因为现在直接返回缓存 token，不校验 app_id）

- [ ] **Step 3：修改 `get_token`**

将原来的：

```python
def get_token() -> str:
    if TOKEN_CACHE_FILE.exists():
        cache = json.loads(TOKEN_CACHE_FILE.read_text())
        if time.time() < cache.get("expires_at", 0):
            return cache["token"]

    cfg = read_config()
    if not cfg:
        raise RuntimeError("凭据未配置，请先运行 check_config")

    result = http("POST", "/open-apis/auth/v3/tenant_access_token/internal", body={
        "app_id": cfg["app_id"],
        "app_secret": cfg["app_secret"],
    })
    if result.get("code") != 0:
        raise RuntimeError(f"获取 token 失败（code={result.get('code')}）：{result.get('msg')}")

    token = result["tenant_access_token"]
    expires_at = time.time() + result.get("expire", 7200) - 60

    USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    _secure_write(TOKEN_CACHE_FILE, json.dumps({"token": token, "expires_at": expires_at}))
    return token
```

改为：

```python
def get_token() -> str:
    cfg = load_merged_config()
    if not cfg.get("app_id") or not cfg.get("app_secret"):
        raise RuntimeError("凭据未配置，请先运行 check_config")

    if TOKEN_CACHE_FILE.exists():
        cache = json.loads(TOKEN_CACHE_FILE.read_text())
        if (time.time() < cache.get("expires_at", 0)
                and cache.get("app_id") == cfg["app_id"]):
            return cache["token"]

    result = http("POST", "/open-apis/auth/v3/tenant_access_token/internal", body={
        "app_id": cfg["app_id"],
        "app_secret": cfg["app_secret"],
    })
    if result.get("code") != 0:
        raise RuntimeError(f"获取 token 失败（code={result.get('code')}）：{result.get('msg')}")

    token = result["tenant_access_token"]
    expires_at = time.time() + result.get("expire", 7200) - 60

    USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    _secure_write(TOKEN_CACHE_FILE, json.dumps({
        "token": token,
        "expires_at": expires_at,
        "app_id": cfg["app_id"],
    }))
    return token
```

- [ ] **Step 4：运行测试确认通过**

```bash
PYTHONIOENCODING=utf-8 python3 tests/test_regression.py 2>&1 | grep -E "\[PASS\]|\[FAIL\]"
```

期望：所有测试包括 `=== 14` 全 `[PASS]`。

- [ ] **Step 5：提交**

```bash
git add scripts/feishu_api.py tests/test_regression.py
git commit -m "feat(config): token cache validates app_id to support multi-project"
```

---

### Task 7：全量回归 + 收尾

**Files:**
- 无新改动

- [ ] **Step 1：运行完整回归**

```bash
cd C:/Users/otsan.li/Desktop/work/skill/pipelit
PYTHONIOENCODING=utf-8 python3 tests/test_regression.py
```

期望：所有测试全部 `[PASS]`，结果行显示 `N/N 通过`。

- [ ] **Step 2：更新 README 配置文件说明**

在 `README.md` 的"配置文件"章节，将 L1 说明中的字段列表从：

```
| L1 用户级 | ~/.claude/pipelit/config.json | 飞书/观测云凭据、logProvider、cardFeatures |
```

改为：

```
| L1 用户级 | ~/.claude/pipelit/config.json | user_id（跨项目全局）|
| L2 项目级 | <cwd>/.pipelit/config.json    | app_id、app_secret、frontend_path、backend_path、release、bot |
```

- [ ] **Step 3：提交收尾**

```bash
git add README.md
git commit -m "docs: update config layer description to reflect L1/L2 split"
```
