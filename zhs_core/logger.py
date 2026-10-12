"""统一日志：控制台 + 可选文件。"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

_CONFIGURED = False


def setup_logging(log_file: Path | None = None, level: int = logging.INFO) -> logging.Logger:
    global _CONFIGURED
    logger = logging.getLogger("zhs")
    if _CONFIGURED:
        return logger

    logger.setLevel(level)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")

    # Windows 控制台默认 GBK，中文日志容易炸；强制 UTF-8
    try:
        stream = sys.stdout
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(sh)

    if log_file is not None:
        try:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            fh = logging.FileHandler(log_file, encoding="utf-8")
            fh.setFormatter(fmt)
            logger.addHandler(fh)
        except Exception:
            pass

    logger.propagate = False
    _CONFIGURED = True
    return logger


def get_logger() -> logging.Logger:
    return logging.getLogger("zhs")
