#!/usr/bin/env python3
"""
Pipelit 决策日志查询工具

Usage:
  python3 audit.py recent [--n 10]          最近 N 次判定
  python3 audit.py why <task_id>            某次为什么判 L2/L3
  python3 audit.py diff <log1> <log2>       对比两次决策
"""

import json
import os
import sys
import pathlib
from datetime import datetime

LOG_BASE = pathlib.Path.home() / ".claude" / "pipelit" / "decision-logs"


def _all_logs() -> list[tuple[float, pathlib.Path]]:
    """返回所有日志文件，按修改时间倒序。"""
    logs = []
    if not LOG_BASE.exists():
        return logs
    for day_dir in LOG_BASE.iterdir():
        if not day_dir.is_dir():
            continue
        for f in day_dir.glob("*.json"):
            logs.append((f.stat().st_mtime, f))
    logs.sort(key=lambda x: -x[0])
    return logs


def _load(path: pathlib.Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _find_log(task_id_prefix: str) -> pathlib.Path | None:
    """按 task_id 前缀查找最新的日志文件。"""
    for _, path in _all_logs():
        if path.stem.startswith(task_id_prefix):
            return path
    return None


def _level_phase(data: dict) -> tuple[str, dict]:
    """从日志中提取 L2/L3 判定及 evidence。"""
    for phase in data.get("phases", []):
        if phase.get("decision_type") == "level_classification":
            return phase.get("level", "?"), phase
    # fallback: 检查 final_decision
    fd = data.get("final_decision", {})
    return fd.get("level", "?"), fd


def cmd_recent(args: list[str]) -> None:
    n = 10
    if "--n" in args:
        n = int(args[args.index("--n") + 1])

    logs = _all_logs()[:n]
    if not logs:
        print("暂无决策日志。运行 feishu-dev 后会自动生成。")
        return

    print(f"最近 {len(logs)} 条判定：\n")
    for _, path in logs:
        try:
            data = _load(path)
        except Exception:
            continue
        level, phase = _level_phase(data)
        rule = phase.get("matched_rule", "-")
        ts = data.get("started_at", "")[:16]
        summary = data.get("task_summary", "")[:40]
        tid = data.get("task_id", "")[:8]
        status = data.get("status", "")
        print(f"  [{ts}] {tid}  {level}  规则={rule}  {summary}  ({status})")


def cmd_why(args: list[str]) -> None:
    if not args:
        print("用法：audit.py why <task_id_前缀>")
        sys.exit(1)

    prefix = args[0]
    path = _find_log(prefix)
    if not path:
        print(f"未找到 task_id 前缀为 '{prefix}' 的日志。")
        sys.exit(1)

    data = _load(path)
    level, phase = _level_phase(data)
    evidence = phase.get("evidence", {})

    print(f"任务：{data.get('task_summary', '')}")
    print(f"ID  ：{data.get('task_id', '')}")
    print(f"时间：{data.get('started_at', '')[:16]}")
    print(f"状态：{data.get('status', '')}")
    print()
    print(f"判定结果：{level}")
    print(f"命中规则：{phase.get('matched_rule', '-')}")
    print()
    print("Evidence：")
    for k, v in evidence.items():
        print(f"  {k}: {v}")

    phases = data.get("phases", [])
    if len(phases) > 1:
        print()
        print("其他阶段决策：")
        for p in phases:
            if p.get("decision_type") != "level_classification":
                print(f"  phase={p.get('phase', '?')}  {p.get('decision_type', '')}  {json.dumps(p, ensure_ascii=False)[:80]}")


def cmd_diff(args: list[str]) -> None:
    if len(args) < 2:
        print("用法：audit.py diff <log1> <log2>")
        print("      log1/log2 可以是文件路径或 task_id 前缀")
        sys.exit(1)

    def resolve(arg: str) -> pathlib.Path:
        p = pathlib.Path(arg)
        if p.exists():
            return p
        found = _find_log(arg)
        if found:
            return found
        print(f"找不到日志：{arg}")
        sys.exit(1)

    path1, path2 = resolve(args[0]), resolve(args[1])
    d1, d2 = _load(path1), _load(path2)
    level1, phase1 = _level_phase(d1)
    level2, phase2 = _level_phase(d2)

    print(f"对比：{path1.name}  vs  {path2.name}\n")

    # 判定级别
    marker = "✅" if level1 == level2 else "⚠️ 不同"
    print(f"判定级别：{level1}  vs  {level2}  {marker}")

    # 命中规则
    r1, r2 = phase1.get("matched_rule", "-"), phase2.get("matched_rule", "-")
    marker = "✅" if r1 == r2 else "⚠️ 不同"
    print(f"命中规则：{r1}  vs  {r2}  {marker}")

    # Evidence 逐字段对比
    ev1 = phase1.get("evidence", {})
    ev2 = phase2.get("evidence", {})
    all_keys = sorted(set(ev1) | set(ev2))
    if all_keys:
        print("\nEvidence 对比：")
        for k in all_keys:
            v1, v2 = ev1.get(k, "—"), ev2.get(k, "—")
            marker = "✅" if v1 == v2 else "≠"
            print(f"  {k}: {v1}  vs  {v2}  {marker}")


def main() -> None:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(0)

    cmd = args[0]
    rest = args[1:]

    if cmd == "recent":
        cmd_recent(rest)
    elif cmd == "why":
        cmd_why(rest)
    elif cmd == "diff":
        cmd_diff(rest)
    else:
        print(f"未知命令：{cmd}\n{__doc__}")
        sys.exit(1)


if __name__ == "__main__":
    main()
