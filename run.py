#!/usr/bin/env python3
"""智慧树课程自动学习工具 —— 入口。

用法:
    python run.py

配置全部来自项目根目录的 .env（见 .env.example）。
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from zhs_core.config import ConfigError, load_config  # noqa: E402
from zhs_core.logger import setup_logging  # noqa: E402


def main() -> int:
    log = setup_logging(log_file=ROOT / "logs" / "run.log")

    try:
        config = load_config()
    except ConfigError as exc:
        print(f"[配置错误] {exc}", file=sys.stderr)
        return 2

    log.info("课程: %s", config.course_name)
    log.info("账号: %s", config.username)

    try:
        asyncio.run(_run(config))
    except KeyboardInterrupt:
        print("\n已手动中断。")
        return 130
    except Exception as exc:
        log.error("运行失败: %s", exc)
        return 1
    return 0


async def _run(config) -> None:
    from zhs_core import study

    await study.run(config)


if __name__ == "__main__":
    raise SystemExit(main())
