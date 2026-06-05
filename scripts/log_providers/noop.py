#!/usr/bin/env python3
"""
Noop log provider — 无日志源时的兜底实现。

始终返回 not_configured，让 feishu-dev 静默跳过日志查询步骤。
"""

import json
import sys


def query_errors_silent(
    start: str, end: str, interfaces: list | None = None
) -> dict:
    return {"status": "not_configured"}


def main() -> None:
    print(json.dumps({"status": "not_configured"}))


if __name__ == "__main__":
    main()
