#!/usr/bin/env python3
"""
Card Builder — 通用飞书发版卡片构建器。

所有"飞书任务链接 / @ 关注人 / 图片 / Wiki 链接"均独立 if，
缺任何一项都不阻断其他项。通过 cardFeatures 配置按需开关。

Usage:
  python3 card_builder.py build_lark_md '<json>' | '@params.json'

params 字段：
  sections         (必需) [{"title": "...", "entries": [{"text": "...", "task_id": "..."(可选)}]}]
  card_features    (可选) {"linkTask": true, "atFollower": true, "image": true}
                          未传时读全局配置，全局未配置时默认全 true
  task_mentions    (可选) {task_id: open_id | null}  预查好的 @ 结果
  task_guids       (可选) {task_id: full_guid | null} 预查好的 GUID 结果
  always_mention_open_ids (可选) 每条都 @ 的固定 open_id 列表

Output: JSON {lark_md: str, features_applied: dict}
"""

import json
import sys
import pathlib

USER_CONFIG_DIR = pathlib.Path.home() / ".claude" / "pipelit"
CONFIG_FILE = USER_CONFIG_DIR / "config.json"


def _read_config() -> dict:
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    return {}


def _load_json_param(raw: str) -> dict:
    if isinstance(raw, dict):
        return raw
    raw = raw.strip()
    if raw.startswith("@"):
        return json.loads(pathlib.Path(raw[1:]).read_text(encoding="utf-8"))
    return json.loads(raw)


def _resolve_features(params: dict) -> dict:
    """合并 cardFeatures 优先级：params > L1 config > 默认 true。"""
    cfg = _read_config()
    defaults = {"linkTask": True, "atFollower": True, "image": True}
    global_features = cfg.get("cardFeatures", {})
    param_features = params.get("card_features", {})
    return {**defaults, **global_features, **param_features}


def build_lark_md(params: dict) -> dict:
    """把 sections 结构转成 lark_md 文本。

    独立 if 规则：
    - linkTask=false  → 不拼飞书任务链接（即使有 task_guid）
    - atFollower=false → 不 @ 任何人（即使有 task_mentions）
    - image=false     → 不影响文本内容（image key 由调用方处理）
    """
    sections = params.get("sections", [])
    task_mentions: dict = params.get("task_mentions", {})
    task_guids: dict = params.get("task_guids", {})
    always_mention = list(params.get("always_mention_open_ids", []))
    features = _resolve_features(params)

    features_applied = {
        "linkTask": features["linkTask"],
        "atFollower": features["atFollower"],
        "image": features["image"],
    }

    lines: list[str] = []
    for sec in sections:
        lines.append(sec["title"])
        for entry in sec.get("entries", []):
            line = entry["text"]
            tid = entry.get("task_id")

            # 飞书任务链接（独立 if）
            if features["linkTask"] and tid:
                task_guid = entry.get("task_guid") or (task_guids.get(tid) if tid else None)
                if task_guid:
                    task_url = f"https://applink.feishu.cn/client/todo/detail?guid={task_guid}"
                    line += f"  [任务]({task_url})"

            # @ 关注人（独立 if）
            if features["atFollower"]:
                oid = entry.get("_at_override") or (task_mentions.get(tid) if tid else None)
                at_parts = []
                if oid:
                    at_parts.append(f"<at id={oid}></at>")
                for fixed_oid in always_mention:
                    if fixed_oid and fixed_oid != oid:
                        at_parts.append(f"<at id={fixed_oid}></at>")
                if at_parts:
                    line += "\n" + " ".join(at_parts)

            lines.append(line)
        lines.append("")

    lark_md = "\n".join(lines).rstrip()
    return {"lark_md": lark_md, "features_applied": features_applied}


def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] != "build_lark_md":
        print(json.dumps({"error": f"unknown command: {args}"}))
        sys.exit(1)
    if len(args) < 2:
        print(json.dumps({"error": "usage: build_lark_md '<json>' | '@params.json'"}))
        sys.exit(1)

    params = _load_json_param(args[1])
    result = build_lark_md(params)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
