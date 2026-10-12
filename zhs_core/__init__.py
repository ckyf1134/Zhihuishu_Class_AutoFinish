"""智慧树课程自动学习工具 —— 核心包。"""
from .config import Config, ConfigError, load_config

__all__ = ["Config", "ConfigError", "load_config"]
__version__ = "2.0.0"
