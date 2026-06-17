# Config extends 支持 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 支持 `.pipelit/config.json` 中的 `extends` 字段，让前后端分离项目的两个目录都能使用同一份配置。

**Architecture:** 在 `feishu_api.py` 中新增 `_resolve_canonical_config(cwd)` 辅助函数，让 `_read_project_config` 和 `_write_project_config` 跟随 extends 读写到 canonical 文件；修改 `save_project_config` 在配置了两个路径时自动在另一个目录创建 extends 指针。

**Tech Stack:** Python 3.10+, pathlib, json

---

## 文件变更

| 操作 | 文件 |
|------|------|
| Modify | `scripts/feishu_api.py` |
| Modify | `tests/test_regression.py` |

---

### Task 1：实现 extends 支持

**Files:**
- Modify: `scripts/feishu_api.py`（`_read_project_config`、`_write_project_config`，约第 281-294 行）
- Modify: `tests/test_regression.py`

- [ ] **Step 1：写失败测试**

在 `tests/test_regression.py` 末尾 `sys.exit` 之前追加：

```python
# ─── 17. config extends 支持 ─────────────────────────────────────────────────
print("\n=== 17. config extends 支持（config-extends）===")
with tempfile.TemporaryDirectory() as dir_a, tempfile.TemporaryDirectory() as dir_b:
    # dir_a 是 canonical（主配置）
    fa._write_project_config({"app_id": "cli_main", "frontend_path": dir_a}, cwd=dir_a)

    # dir_b 放 extends 指针
    ptr_file = pathlib.Path(dir_b) / ".pipelit" / "config.json"
    ptr_file.parent.mkdir(parents=True, exist_ok=True)
    canonical_path = str(fa._project_config_file(cwd=dir_a))
    ptr_file.write_text(json.dumps({"extends": canonical_path}), encoding="utf-8")

    # _read_project_config 从 dir_b 读，应该得到 dir_a 的内容
    result = fa._read_project_config(cwd=dir_b)
    check("extends: 从指针目录读到 canonical 内容", result.get("app_id") == "cli_main")
    check("extends: 不含 extends 字段本身", "extends" not in result)

    # _write_project_config 从 dir_b 写，应该写到 dir_a
    fa._write_project_config({"app_id": "cli_updated"}, cwd=dir_b)
    canonical_content = fa._read_project_config(cwd=dir_a)
    check("extends: 写入操作路由到 canonical", canonical_content.get("app_id") == "cli_updated")
    ptr_content = json.loads(ptr_file.read_text(encoding="utf-8"))
    check("extends: 指针文件仍只含 extends 字段", list(ptr_content.keys()) == ["extends"])
```

- [ ] **Step 2：运行测试确认失败**

```bash
cd C:/Users/otsan.li/Desktop/work/skill/pipelit
PYTHONIOENCODING=utf-8 python3 tests/test_regression.py 2>&1 | grep -A3 "=== 17"
```

期望：`[FAIL] extends: 从指针目录读到 canonical 内容`（因为当前读不跟随 extends）

- [ ] **Step 3：新增 `_resolve_canonical_config` 并修改读写函数**

在 `scripts/feishu_api.py` 的 `_project_config_file` 之后、`_read_project_config` 之前（约第 279 行）插入：

```python
def _resolve_canonical_config(cwd: str | None = None) -> pathlib.Path:
    """返回 canonical 配置文件路径：若当前 cwd 的配置有 extends 字段，跟随一层。"""
    f = _project_config_file(cwd)
    if f.exists():
        try:
            raw = json.loads(f.read_text(encoding="utf-8"))
            target = raw.get("extends")
            if target:
                return pathlib.Path(target)
        except Exception:
            pass
    return f
```

将 `_read_project_config` 改为：

```python
def _read_project_config(cwd: str | None = None) -> dict:
    f = _resolve_canonical_config(cwd)
    if not f.exists():
        return {}
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        # 过滤掉 extends 字段，调用方不需要感知
        data.pop("extends", None)
        return data
    except Exception:
        return {}
```

将 `_write_project_config` 改为：

```python
def _write_project_config(data: dict, cwd: str | None = None) -> None:
    f = _resolve_canonical_config(cwd)
    f.parent.mkdir(parents=True, exist_ok=True)
    _secure_write(f, json.dumps(data, indent=2, ensure_ascii=False))
```

- [ ] **Step 4：运行测试确认通过**

```bash
PYTHONIOENCODING=utf-8 python3 tests/test_regression.py 2>&1 | tail -5
```

期望：`=== 17` 4 条全 `[PASS]`，其余不回退。

- [ ] **Step 5：提交**

```bash
git add scripts/feishu_api.py tests/test_regression.py
git commit -m "feat(config): support extends in project config for multi-dir projects"
```

---

### Task 2：save_project_config 自动创建 extends 指针

**Files:**
- Modify: `scripts/feishu_api.py`（`save_project_config`，约第 260 行）
- Modify: `tests/test_regression.py`

- [ ] **Step 1：写失败测试**

在 `tests/test_regression.py` 末尾 `sys.exit` 之前追加：

```python
# ─── 18. save_project_config 自动创建 extends 指针 ───────────────────────────
print("\n=== 18. save_project_config extends 指针（config-extends）===")
with tempfile.TemporaryDirectory() as front, tempfile.TemporaryDirectory() as back:
    _old_cwd18 = os.getcwd()
    try:
        os.chdir(front)
        fa.save_project_config(frontend_path=front, backend_path=back)
    finally:
        os.chdir(_old_cwd18)

    # front 应有完整配置
    front_cfg = fa._read_project_config(cwd=front)
    check("save_project_config: canonical 有 frontend_path", front_cfg.get("frontend_path") == front)
    check("save_project_config: canonical 有 backend_path", front_cfg.get("backend_path") == back)

    # back 应有 extends 指针指向 front
    back_ptr_file = pathlib.Path(back) / ".pipelit" / "config.json"
    check("save_project_config: 指针文件存在于 backend 目录", back_ptr_file.exists())
    back_ptr = json.loads(back_ptr_file.read_text(encoding="utf-8"))
    check("save_project_config: 指针含 extends 字段", "extends" in back_ptr)

    # 从 back 目录读，应得到完整配置
    back_cfg = fa._read_project_config(cwd=back)
    check("save_project_config: 从 backend 读到完整配置", back_cfg.get("frontend_path") == front)
```

- [ ] **Step 2：运行测试确认失败**

```bash
PYTHONIOENCODING=utf-8 python3 tests/test_regression.py 2>&1 | grep -A3 "=== 18"
```

期望：`[FAIL] save_project_config: 指针文件存在于 backend 目录`

- [ ] **Step 3：修改 `save_project_config`**

将原来的：

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

改为：

```python
def save_project_config(frontend_path: str = None, backend_path: str = None) -> dict:
    cfg = _read_project_config()
    if frontend_path:
        cfg["frontend_path"] = frontend_path.rstrip("/\\")
    if backend_path:
        cfg["backend_path"] = backend_path.rstrip("/\\")
    _write_project_config(cfg)

    # 若同时配置了前后端路径，在另一个目录创建 extends 指针
    _maybe_create_extends_pointer(cfg)

    return {
        "success": True,
        "frontend_path": cfg.get("frontend_path"),
        "backend_path": cfg.get("backend_path"),
    }


def _maybe_create_extends_pointer(cfg: dict) -> None:
    """若 cfg 同时含 frontend_path 和 backend_path，为非 cwd 的那个目录创建 extends 指针。"""
    fp = cfg.get("frontend_path")
    bp = cfg.get("backend_path")
    if not fp or not bp:
        return

    cwd = pathlib.Path.cwd()
    canonical = _resolve_canonical_config()  # 当前 cwd 的 canonical

    fp_path = pathlib.Path(fp)
    bp_path = pathlib.Path(bp)

    # 判断当前 cwd 更接近哪个路径（canonical 在哪边）
    try:
        cwd.relative_to(fp_path)
        other = bp_path  # cwd 在 frontend 下，给 backend 创建指针
    except ValueError:
        try:
            cwd.relative_to(bp_path)
            other = fp_path  # cwd 在 backend 下，给 frontend 创建指针
        except ValueError:
            # cwd 不在任何一个路径下，取 canonical 所在目录判断
            if fp_path in canonical.parents or canonical.is_relative_to(fp_path):
                other = bp_path
            else:
                other = fp_path

    ptr_file = other / ".pipelit" / "config.json"
    # 如果另一个目录已经有完整配置（不只是指针），不覆盖
    if ptr_file.exists():
        try:
            existing = json.loads(ptr_file.read_text(encoding="utf-8"))
            if "extends" not in existing and len(existing) > 1:
                return  # 已有实质配置，不覆盖
        except Exception:
            pass

    ptr_file.parent.mkdir(parents=True, exist_ok=True)
    _secure_write(ptr_file, json.dumps({"extends": str(canonical)}, indent=2, ensure_ascii=False))
```

- [ ] **Step 4：运行测试确认通过**

```bash
PYTHONIOENCODING=utf-8 python3 tests/test_regression.py 2>&1 | tail -5
```

期望：`=== 18` 5 条全 `[PASS]`。

- [ ] **Step 5：全量回归确认**

```bash
PYTHONIOENCODING=utf-8 python3 tests/test_regression.py
```

期望：所有测试全部 `[PASS]`。

- [ ] **Step 6：提交**

```bash
git add scripts/feishu_api.py tests/test_regression.py
git commit -m "feat(config): save_project_config auto-creates extends pointer for multi-dir projects"
```
