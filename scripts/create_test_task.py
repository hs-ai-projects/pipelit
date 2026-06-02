#!/usr/bin/env python3
"""
快速创建测试任务，指派给自己。

用法：
  py create_test_task.py                     # 交互模式，输入标题和描述
  py create_test_task.py "任务标题"           # 快速创建，无描述
  py create_test_task.py "任务标题" "描述内容"
"""
import sys
import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent))

from feishu_api import get_token, http, read_config


def create_task(summary: str, description: str = "") -> None:
    cfg     = read_config() or {}
    user_id = cfg.get("user_id") or cfg.get("bot", {}).get("user_id", "")
    if not user_id:
        print("❌ 未找到 user_id，请先运行：py feishu_api.py save_user")
        sys.exit(1)

    token  = get_token()
    body   = {"summary": summary, "members": [{"id": user_id, "type": "user", "role": "assignee"}]}
    if description:
        body["description"] = description

    result = http("POST", "/open-apis/task/v2/tasks?user_id_type=user_id", body=body, token=token)
    task   = result["data"]["task"]

    print(f"✅ 任务创建成功")
    print(f"   task_id : {task['task_id']}")
    print(f"   guid    : {task['guid']}")
    print(f"   标题    : {task['summary']}")
    print(f"   链接    : {task['url']}")


def main():
    args = sys.argv[1:]

    if len(args) >= 2:
        create_task(args[0], args[1])
    elif len(args) == 1:
        create_task(args[0])
    else:
        # 交互模式
        summary = input("任务标题：").strip()
        if not summary:
            print("标题不能为空")
            sys.exit(1)
        description = input("任务描述（可留空，直接回车）：").strip()
        create_task(summary, description)


if __name__ == "__main__":
    main()
