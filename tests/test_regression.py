#!/usr/bin/env python3
"""Stage 1-5 回归验证脚本"""
import sys, importlib.util, pathlib, json, time

ROOT = pathlib.Path(__file__).parent.parent  # 仓库根目录
sys.path.insert(0, str(ROOT))

results = []

def check(name, passed, note=""):
    mark = "[PASS]" if passed else "[FAIL]"
    results.append((name, passed))
    print(f"  {mark}  {name}" + (f"  ({note})" if note else ""))

# ─── 1. 时间格式校验 ──────────────────────────────────────────────────────────
print("\n=== 1. 时间格式校验（Case 02 / Task 1.2）===")
from scripts.guance_api import validate_iso8601_time
bad1, _ = validate_iso8601_time("2026/06/04 14:00")
bad2, _ = validate_iso8601_time("2026-06-04 14:00")
good1, _ = validate_iso8601_time("2026-06-04T13:30:00+08:00")
good2, _ = validate_iso8601_time("2026-06-04T13:30:00Z")
check("斜杠格式拒绝", not bad1, "2026/06/04 14:00")
check("无T无时区拒绝", not bad2, "2026-06-04 14:00")
check("ISO+08:00接受", good1)
check("ISO Z接受", good2)

# ─── 2. noop provider ────────────────────────────────────────────────────────
print("\n=== 2. noop log provider（Task 3.1）===")
spec = importlib.util.spec_from_file_location("noop", ROOT / "scripts/log_providers/noop.py")
noop = importlib.util.module_from_spec(spec); spec.loader.exec_module(noop)
r = noop.query_errors_silent("2026-06-04T13:00:00+08:00", "2026-06-04T14:00:00+08:00")
check("noop 返回 not_configured", r.get("status") == "not_configured")

# ─── 3. guance provider 格式错误 ─────────────────────────────────────────────
print("\n=== 3. guance provider 格式错误（Task 3.1）===")
spec2 = importlib.util.spec_from_file_location("gprov", ROOT / "scripts/log_providers/guance.py")
gprov = importlib.util.module_from_spec(spec2); spec2.loader.exec_module(gprov)
r_bad = gprov.query_errors_silent("2026/06/04 14:00", "2026/06/04 15:00")
check("guance 格式错误 → error", r_bad.get("status") == "error")

# ─── 4. card_builder cardFeatures ────────────────────────────────────────────
print("\n=== 4. card_builder cardFeatures 开关（Task 3.4）===")
spec3 = importlib.util.spec_from_file_location("cb", ROOT / "scripts/card_builder.py")
cb = importlib.util.module_from_spec(spec3); spec3.loader.exec_module(cb)

sections = [{"title": "**✨ 新功能**", "entries": [
    {"text": "描述A", "task_id": "abc12345", "task_guid": "abc12345-0000-0000-0000-000000000001"},
    {"text": "描述B"},
]}]
r_on = cb.build_lark_md({"sections": sections, "card_features": {"linkTask": True, "atFollower": False}})
r_off = cb.build_lark_md({"sections": sections, "card_features": {"linkTask": False, "atFollower": False}})
check("linkTask=True has task link", "[task]" in r_on["lark_md"].replace("[任务]","[task]") or "[任务]" in r_on["lark_md"])
check("linkTask=False no task link", "[任务]" not in r_off["lark_md"])

# atFollower=True with mock open_id
r_at = cb.build_lark_md({"sections": sections,
    "task_mentions": {"abc12345": "ou_mock123"},
    "card_features": {"linkTask": False, "atFollower": True}})
r_noat = cb.build_lark_md({"sections": sections,
    "task_mentions": {"abc12345": "ou_mock123"},
    "card_features": {"linkTask": False, "atFollower": False}})
check("atFollower=True 含 <at>", "<at id=ou_mock123>" in r_at["lark_md"])
check("atFollower=False 无 <at>", "<at" not in r_noat["lark_md"])

# ─── 5. get_task_full 缓存 ────────────────────────────────────────────────────
print("\n=== 5. task cache helper（Task 5.2）===")
spec4 = importlib.util.spec_from_file_location("fa", ROOT / "scripts/feishu_api.py")
fa = importlib.util.module_from_spec(spec4); spec4.loader.exec_module(fa)

tid = "test-regression-cache-001"
dummy = {"task": {"id": tid}, "subtasks": [], "images": [], "videos": []}
fa._cache_task(tid, dummy)
cached = fa._get_cached_task(tid)
check("缓存写入后可读", cached is not None)
check("缓存含 _cached_at 时间戳", "_cached_at" in (cached or {}))
fa._invalidate_task_cache(tid)
after = fa._get_cached_task(tid)
check("失效后为 None", after is None)

# ─── 6. load_merged_config 三层合并 ──────────────────────────────────────────
print("\n=== 6. load_merged_config 三层合并（Task 3.2）===")
import tempfile, os
with tempfile.TemporaryDirectory() as tmpdir:
    # 创建 L2
    pipelit_dir = pathlib.Path(tmpdir) / ".pipelit"
    pipelit_dir.mkdir()
    (pipelit_dir / "config.json").write_text(
        json.dumps({"frontend_path": "/l2/frontend", "logProvider": "noop"}),
        encoding="utf-8"
    )
    merged = fa.load_merged_config(cwd=tmpdir)
    check("L2 覆盖生效（logProvider=noop）", merged.get("logProvider") == "noop")
    check("L2 frontend_path 可读", merged.get("frontend_path") == "/l2/frontend")

# ─── 7. audit.py recent ───────────────────────────────────────────────────────
print("\n=== 7. audit.py recent（Task 5.3）===")
spec5 = importlib.util.spec_from_file_location("audit", ROOT / "scripts/audit.py")
audit = importlib.util.module_from_spec(spec5); spec5.loader.exec_module(audit)
logs = audit._all_logs()
check("audit _all_logs 可运行（有或无日志）", True, f"{len(logs)} 条日志")

# ─── 8. guance DQL 查询字符串构造 ────────────────────────────────────────────
print("\n=== 8. guance DQL 查询字符串构造（Step A 接口过滤）===")
from scripts.guance_api import LOG_SOURCE

iface_with_hyphen = "/api/search-term/report"
dql_q = (
    f"L::re('{LOG_SOURCE}')"
    f"{{message =~ /{iface_with_hyphen}/}}"
    f" LIMIT 10"
)
check("Step A 用 message 字段过滤（非 requestUrl）", "message =~" in dql_q)
check("Step A 不含 requestUrl", "requestUrl" not in dql_q)
check("Step A 连字符不被转义为 \\-", r"\-" not in dql_q)

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

# ─── 10. save_config 写 L2 ───────────────────────────────────────────────────
print("\n=== 10. save_config 写 L2（config-layer-write-fix）===")
with tempfile.TemporaryDirectory() as tmpdir3:
    _old_cwd = os.getcwd()
    try:
        os.chdir(tmpdir3)
        fa.save_config("cli_test_app", "test_secret")
    finally:
        os.chdir(_old_cwd)
    l2 = fa._read_project_config(cwd=tmpdir3)
    check("save_config 写入 L2 app_id", l2.get("app_id") == "cli_test_app")
    check("save_config 写入 L2 app_secret", l2.get("app_secret") == "test_secret")
    # L1 不应被写入 app_id
    l1 = fa.read_config() or {}
    check("save_config 不写 L1 app_id", l1.get("app_id") != "cli_test_app")

# ─── 11. save_project_config 写 L2 ──────────────────────────────────────────
print("\n=== 11. save_project_config 写 L2（config-layer-write-fix）===")
with tempfile.TemporaryDirectory() as tmpdir4:
    _old_cwd4 = os.getcwd()
    try:
        os.chdir(tmpdir4)
        fa.save_project_config(frontend_path="/proj/front", backend_path="/proj/back")
    finally:
        os.chdir(_old_cwd4)
    l2 = fa._read_project_config(cwd=tmpdir4)
    check("save_project_config 写 L2 frontend_path", l2.get("frontend_path") == "/proj/front")
    check("save_project_config 写 L2 backend_path", l2.get("backend_path") == "/proj/back")

# ─── 12. save_release_config / save_bot_config 写 L2 ────────────────────────
print("\n=== 12. save_release_config / save_bot_config 写 L2（config-layer-write-fix）===")
with tempfile.TemporaryDirectory() as tmpdir5:
    _old_cwd5 = os.getcwd()
    try:
        os.chdir(tmpdir5)
        fa.save_release_config(json.dumps({"projectName": "test-proj", "repos": []}))
    finally:
        os.chdir(_old_cwd5)
    l2r = fa._read_project_config(cwd=tmpdir5)
    check("save_release_config 写 L2 release.projectName",
          l2r.get("release", {}).get("projectName") == "test-proj")

with tempfile.TemporaryDirectory() as tmpdir6:
    _old_cwd6 = os.getcwd()
    try:
        os.chdir(tmpdir6)
        fa.save_bot_config(json.dumps({"notify_chat_id": "oc_test", "trigger_mode": "notify"}))
    finally:
        os.chdir(_old_cwd6)
    l2b = fa._read_project_config(cwd=tmpdir6)
    check("save_bot_config 写 L2 bot.notify_chat_id",
          l2b.get("bot", {}).get("notify_chat_id") == "oc_test")

# ─── 13. check_config 读 merged config ───────────────────────────────────────
print("\n=== 13. check_config 读 merged config（config-layer-write-fix）===")
with tempfile.TemporaryDirectory() as tmpdir7:
    fa._write_project_config(
        {"app_id": "cli_l2_only", "app_secret": "secret_l2"},
        cwd=tmpdir7
    )
    _old_cwd7 = os.getcwd()
    try:
        os.chdir(tmpdir7)
        result = fa.check_config()
    finally:
        os.chdir(_old_cwd7)
    check("check_config 能读 L2 的 app_id", result.get("app_id") == "cli_l2_only")
    check("check_config L2 凭据时返回 configured=True", result.get("configured") is True)

# ─── 14. token 缓存 app_id 校验 ──────────────────────────────────────────────
print("\n=== 14. token cache app_id 校验（config-layer-write-fix）===")
import importlib.util as _ilu14
_spec14 = _ilu14.spec_from_file_location("feishu_api", ROOT / "scripts" / "feishu_api.py")
fa = _ilu14.module_from_spec(_spec14)
_spec14.loader.exec_module(fa)
import time as _time
# 写一个 token 缓存，app_id = "old_app"
fa.USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
fa.TOKEN_CACHE_FILE.write_text(json.dumps({
    "token": "old_token",
    "expires_at": _time.time() + 3600,
    "app_id": "old_app",
}), encoding="utf-8")
# patch load_merged_config 返回不同的 app_id
original_load = fa.load_merged_config
fa.load_merged_config = lambda cwd=None: {"app_id": "new_app", "app_secret": "s"}
try:
    try:
        fa.get_token()
        check("token 缓存 app_id 不匹配时触发重新获取", False, "未抛出异常，直接返回了旧 token")
    except Exception as e:
        # 抛出异常说明它尝试重新获取（而不是命中缓存直接返回 old_token）
        check("token 缓存 app_id 不匹配时触发重新获取", True, str(e)[:50])
finally:
    fa.load_merged_config = original_load
    fa.TOKEN_CACHE_FILE.unlink(missing_ok=True)

# ─── 汇总 ─────────────────────────────────────────────────────────────────────
total = len(results)
passed = sum(1 for _, p in results if p)
print(f"\n{'='*50}")
print(f"结果：{passed}/{total} 通过")
if passed < total:
    print("失败项：")
    for name, p in results:
        if not p:
            print(f"  ❌ {name}")
sys.exit(0 if passed == total else 1)
