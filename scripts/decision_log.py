#!/usr/bin/env python3
"""
Decision log tool — write and query audit trail JSON files.

Usage:
  python3 decision_log.py start <skill> <task_id> [--summary "<summary>"] [--bot-auto]
  python3 decision_log.py phase <task_id> <phase> @decision.json
  python3 decision_log.py finish <task_id> <status>

All files written to ~/.claude/pipelit/decision-logs/<date>/<task_id>-<skill>.json
"""

import json
import os
import sys
from datetime import datetime, timezone


def log_dir():
    home = os.path.expanduser("~")
    today = datetime.now().strftime("%Y-%m-%d")
    return os.path.join(home, ".claude", "pipelit", "decision-logs", today)


def file_path(task_id, skill):
    return os.path.join(log_dir(), f"{task_id}-{skill}.json")


def cmd_start(args):
    """Create a new decision log skeleton."""
    skill = args[0]
    task_id = args[1]

    summary = ""
    bot_auto = False
    i = 2
    while i < len(args):
        if args[i] == "--summary" and i + 1 < len(args):
            summary = args[i + 1]
            i += 2
        elif args[i] == "--bot-auto":
            bot_auto = True
            i += 1
        else:
            i += 1

    os.makedirs(log_dir(), exist_ok=True)
    path = file_path(task_id, skill)

    data = {
        "schema_version": "1.0",
        "skill": skill,
        "task_id": task_id,
        "task_summary": summary[:100] if summary else "",
        "started_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "completed_at": None,
        "status": "in_progress",
        "bot_auto_execute": bot_auto,
        "model_hint": os.environ.get("PIPELIT_MODEL", ""),
        "phases": [],
        "final_decision": {}
    }

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"created: {path}")
    return path


def cmd_phase(args):
    """Append a phase decision to an existing log."""
    task_id = args[0]
    phase = args[1]

    # Read decision JSON: @file, plain file path, inline JSON, or stdin
    if len(args) > 2:
        arg = args[2]
        # @file syntax: explicit file reference
        if arg.startswith("@"):
            with open(arg[1:], "r", encoding="utf-8") as f:
                decision = json.load(f)
        elif os.path.isfile(arg):
            with open(arg, "r", encoding="utf-8") as f:
                decision = json.load(f)
        else:
            decision = json.loads(arg)
    else:
        decision = json.loads(sys.stdin.read())

    # Find matching log file (prefix match on task_id)
    candidates = []
    for fn in os.listdir(log_dir()):
        if fn.startswith(task_id) and fn.endswith(".json"):
            candidates.append(fn)

    if not candidates:
        print(f"error: no log found for task_id prefix '{task_id}'")
        sys.exit(1)
    if len(candidates) > 1:
        print(f"error: multiple logs match '{task_id}': {candidates}")
        sys.exit(1)

    path = os.path.join(log_dir(), candidates[0])
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    decision["phase"] = phase
    data["phases"].append(decision)

    # Auto-set final_decision from phase 1.3
    if phase == "1.3" and decision.get("decision_type") == "level_classification":
        data["final_decision"] = {
            "level": decision["level"],
            "matched_rule": decision["matched_rule"]
        }

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"appended phase '{phase}' to: {path}")


def cmd_finish(args):
    """Mark a decision log as completed/cancelled/failed."""
    task_id = args[0]
    status = args[1] if len(args) > 1 else "completed"

    candidates = []
    for fn in os.listdir(log_dir()):
        if fn.startswith(task_id) and fn.endswith(".json"):
            candidates.append(fn)

    if not candidates:
        print(f"error: no log found for task_id prefix '{task_id}'")
        sys.exit(1)

    path = os.path.join(log_dir(), candidates[0])
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    data["status"] = status
    data["completed_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+08:00")

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"finished ({status}): {path}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "start":
        cmd_start(sys.argv[2:])
    elif cmd == "phase":
        cmd_phase(sys.argv[2:])
    elif cmd == "finish":
        cmd_finish(sys.argv[2:])
    else:
        print(f"unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()