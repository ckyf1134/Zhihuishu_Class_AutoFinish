"""配置加载：从 .env 读取并做基本校验。

设计要点：
- 所有字段一次性解析成不可变 dataclass，避免各函数到处 os.getenv。
- 缺省值集中在 DEFAULTS，便于 README 与代码保持一致。
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_ROOT / ".env"

DEFAULTS = {
    "DEEPSEEK_BASE_URL": "https://api.deepseek.com/v1",
    "ANSWER_MODEL": "deepseek-flash",
    "ENABLE_LLM_ANSWER": "true",
    "ENABLE_REASONING": "false",
    "BROWSER_CHANNEL": "auto",
    "WINDOW_WIDTH": "1600",
    "WINDOW_HEIGHT": "860",
    "HEADLESS": "false",
}

_TRUE = {"true", "1", "yes", "y", "是", "on"}


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None or str(value).strip() == "":
        return default
    return str(value).strip().lower() in _TRUE


@dataclass(frozen=True)
class Config:
    username: str
    password: str
    course_name: str
    api_key: str
    base_url: str
    answer_model: str
    enable_llm_answer: bool
    enable_reasoning: bool
    browser_channel: str
    window_width: int
    window_height: int
    headless: bool

    @property
    def llm_ready(self) -> bool:
        return self.enable_llm_answer and bool(self.api_key)


class ConfigError(RuntimeError):
    """配置缺失或非法。"""


def _pick(env: dict, *names: str) -> str | None:
    """按优先级取第一个非空值（大小写与引号已由 dotenv 处理）。"""
    for name in names:
        raw = env.get(name)
        if raw is not None and str(raw).strip() != "":
            return str(raw).strip()
    return None


def load_config() -> Config:
    env = dict(dotenv_values(ENV_PATH)) if ENV_PATH.exists() else {}

    # 同时兼容进程环境变量，方便 CI / 命令行覆盖
    def get(name: str) -> str | None:
        return env.get(name) if env.get(name) not in (None, "") else os.getenv(name)

    missing: list[str] = []

    username = _pick(env, "ZHIHUISHU_USERNAME", "ZH_USERNAME", "USERNAME")
    password = _pick(env, "ZHIHUISHU_PASSWORD", "PASSWORD")
    course_name = _pick(env, "COURSE_NAME")

    if not username:
        missing.append("ZHIHUISHU_USERNAME")
    if not password:
        missing.append("ZHIHUISHU_PASSWORD")
    if not course_name:
        missing.append("COURSE_NAME")
    if missing:
        raise ConfigError(
            "缺少必填配置: " + ", ".join(missing) + f"\n请在 {ENV_PATH} 中补齐（可参考 .env.example）"
        )

    api_key = _pick(env, "DEEPSEEK_API_KEY", "DASHSCOPE_API_KEY", "QWEN_API_KEY") or ""
    base_url = _pick(env, "DEEPSEEK_BASE_URL", "DASHSCOPE_BASE_URL") or DEFAULTS["DEEPSEEK_BASE_URL"]

    width = int(get("WINDOW_WIDTH") or DEFAULTS["WINDOW_WIDTH"])
    height = int(get("WINDOW_HEIGHT") or DEFAULTS["WINDOW_HEIGHT"])

    return Config(
        username=username,
        password=password,
        course_name=course_name,
        api_key=api_key,
        base_url=base_url.rstrip("/"),
        answer_model=get("ANSWER_MODEL") or DEFAULTS["ANSWER_MODEL"],
        enable_llm_answer=_as_bool(get("ENABLE_LLM_ANSWER") or DEFAULTS["ENABLE_LLM_ANSWER"], True),
        enable_reasoning=_as_bool(get("ENABLE_REASONING") or DEFAULTS["ENABLE_REASONING"], False),
        browser_channel=(get("BROWSER_CHANNEL") or DEFAULTS["BROWSER_CHANNEL"]).lower(),
        window_width=width,
        window_height=height,
        headless=_as_bool(get("HEADLESS") or DEFAULTS["HEADLESS"], False),
    )
