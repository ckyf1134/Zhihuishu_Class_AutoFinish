"""大模型答题：OpenAI 兼容 Chat Completions 调用与答案解析。

关键修复（否则答题会静默全部答错）：
- httpx 默认 trust_env=True，会读取 Windows 系统代理。本机装了 Steam++ / Watt Toolkit
  之类带 TLS 中间人的加速器时（注册表 ProxyEnable=1、ProxyServer=127.0.0.1:26561），
  httpx 会因代理证书不被 Python 信任而抛 CERTIFICATE_VERIFY_FAILED。
  一旦抛错，旧逻辑是“回退选第一个选项”，于是每道题都变成选 A —— 静默全错。
  这里显式 trust_env=False 直连，并对失败做明确告警而不是当作正常答题。
"""
from __future__ import annotations

import re

import httpx

from .logger import get_logger

log = get_logger()

_THINK_PATTERNS = (
    re.compile(r"<think>.*?</think>", re.DOTALL),
    re.compile(r"\[thinking\].*?\[/thinking\]", re.DOTALL),
)

SYSTEM_PROMPT = "你是一名严谨的答题助手。只输出答案序号，不输出任何解释。"

USER_PROMPT_TEMPLATE = """请根据题目和选项选择正确答案。
只返回选项的数字序号，不要返回其他任何内容。
单选题返回一个数字（如 2）；多选题返回多个数字用分号分隔（如 1;3;4）。

题目：{title}

选项：
{options}
"""


class LLMError(RuntimeError):
    """调用大模型失败。"""


def strip_thinking(text: str) -> str:
    """去掉模型可能带出的思考过程。"""
    if not text:
        return ""
    for pattern in _THINK_PATTERNS:
        text = pattern.sub("", text)
    return text.strip()


def extract_content(response: dict) -> str:
    """从 Chat Completions 响应中取出正文。"""
    choices = response.get("choices") or []
    if choices:
        message = choices[0].get("message") or {}
        content = message.get("content")
        if content:
            return str(content).strip()
        # 部分实现把内容放在 reasoning_content
        reasoning = message.get("reasoning_content")
        if reasoning:
            return str(reasoning).strip()

    if response.get("output_text"):
        return str(response["output_text"]).strip()

    parts: list[str] = []
    for item in response.get("output") or []:
        if item.get("type") != "message":
            continue
        for chunk in item.get("content") or []:
            if chunk.get("text"):
                parts.append(str(chunk["text"]))
    return "\n".join(parts).strip()


def parse_choice_indices(answer_text: str, option_count: int) -> list[int]:
    """把模型回答解析成 0 基索引列表。

    兼容 "2"、"1;3;4"、"1、3"、"答案是B"、"AC" 等写法。
    """
    text = strip_thinking(answer_text)
    if not text:
        return []

    indices: list[int] = []

    # 先看字母选项（A/B/C/D），兼容 "答案是B"、"AC"、"A、C"
    # 注意不能用 \b([A-Za-z])\b：连续的 "AC" 会被当成一个词而匹配不到。
    letters = re.findall(r"[A-Za-z]", text)
    letter_hits = [ord(ch.upper()) - ord("A") for ch in letters]
    letter_hits = [i for i in letter_hits if 0 <= i < option_count]

    # 再看数字
    numbers = re.findall(r"\d+", text)
    number_hits = []
    for token in numbers:
        value = int(token)
        if 1 <= value <= option_count:
            number_hits.append(value - 1)

    # 数字优先（提示词要求返回数字）；若数字越界则退回字母
    indices = number_hits or letter_hits

    # 去重且保持顺序
    seen: set[int] = set()
    unique: list[int] = []
    for idx in indices:
        if idx not in seen:
            seen.add(idx)
            unique.append(idx)
    return unique


async def ask_question(config, title: str, options: list[str]) -> list[int]:
    """向大模型提问，返回 0 基选项索引。失败抛 LLMError。"""
    if not config.api_key:
        raise LLMError("未配置 API Key")

    options_text = "\n".join(f"{i + 1}. {text}" for i, text in enumerate(options))
    payload = {
        "model": config.answer_model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": USER_PROMPT_TEMPLATE.format(title=title, options=options_text)},
        ],
        "temperature": 0,
    }
    if config.enable_reasoning:
        payload["extra_body"] = {"enable_thinking": True}

    endpoint = f"{config.base_url}/chat/completions"
    headers = {"Authorization": f"Bearer {config.api_key}", "Content-Type": "application/json"}

    log.debug("提示词:\n%s", payload["messages"][-1]["content"])

    try:
        # trust_env=False: 绕过系统代理，避免本地 TLS 中间人代理导致证书校验失败
        async with httpx.AsyncClient(timeout=60, trust_env=False) as client:
            resp = await client.post(endpoint, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:300]
        raise LLMError(f"HTTP {exc.response.status_code}: {detail}") from exc
    except httpx.HTTPError as exc:
        raise LLMError(f"网络错误: {exc}") from exc

    content = extract_content(data)
    if not content:
        raise LLMError(f"模型返回空内容: {str(data)[:200]}")

    log.info("模型回答: %s", strip_thinking(content))
    return parse_choice_indices(content, len(options))
