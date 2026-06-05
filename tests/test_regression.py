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
