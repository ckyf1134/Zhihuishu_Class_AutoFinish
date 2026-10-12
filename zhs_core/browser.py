"""浏览器启动策略。

关键经验（都是实测出来的坑）：
1. 视频是 H.264/AAC 的 .mp4。Playwright 自带的开源 Chromium 不含这些专有编解码器，
   播放时会直接走到 <video> 的 error.code=4（MEDIA_ERR_SRC_NOT_SUPPORTED），
   页面上表现为“视频无法播放，请尝试切换其他线路”。因此必须优先使用
   Google Chrome / Microsoft Edge 这类带完整编解码器的浏览器。
2. 智慧树学习页按设计尺寸绝对定位（播放器区域 x=0..1580）。
   视口不要强制设成比真实窗口大很多，也不要全屏最大化（页面会 zoom 导致坐标错位）。
   给一个略小于设计尺寸的窗口最稳。
3. 用户手动关掉浏览器窗口后，脚本必须能干净退出，而不是对着已关闭的页面空转。
"""
from __future__ import annotations

from playwright.async_api import Browser, BrowserContext, Playwright
from playwright.async_api import Error as PlaywrightError

from .logger import get_logger

log = get_logger()

# 按可靠性排序：完整编解码器优先
CHANNEL_PREFERENCE = ("chrome", "msedge")

CODEC_PROBE_JS = """() => {
  const v = document.createElement('video');
  return {
    h264: v.canPlayType('video/mp4; codecs="avc1.42E01E"'),
    aac:  v.canPlayType('audio/mp4; codecs="mp4a.40.2"'),
  };
}"""


class BrowserClosedError(RuntimeError):
    """用户关闭了浏览器窗口，脚本应优雅退出。"""


def is_page_alive(page) -> bool:
    """页面（及其上下文）是否仍然可用。"""
    try:
        if page.is_closed():
            return False
        _ = page.context.browser
        return True
    except PlaywrightError:
        return False
    except Exception:
        return False


async def _try_launch(pw: Playwright, channel: str | None, width: int, height: int, headless: bool):
    """尝试用指定 channel 启动；返回 (browser, context, page)。"""
    kwargs = dict(
        headless=headless,
        args=["--mute-audio", f"--window-size={width},{height}", "--autoplay-policy=no-user-gesture-required"],
    )
    if channel:
        kwargs["channel"] = channel

    browser = await pw.chromium.launch(**kwargs)
    context = await browser.new_context(
        viewport={"width": width, "height": height},
        locale="zh-CN",
    )
    page = await context.new_page()
    return browser, context, page


async def launch_browser(pw: Playwright, config):
    """按 chrome -> msedge -> 内置 chromium 顺序启动，返回 (browser, context, page, channel_label)。

    内置 chromium 只作为最后兜底：能跑页面，但大概率播不了视频（会给出明确警告）。
    """
    errors: list[str] = []

    if config.browser_channel and config.browser_channel != "auto":
        order: list[str | None] = [config.browser_channel]
    else:
        order = list(CHANNEL_PREFERENCE) + [None]

    for channel in order:
        label = channel or "chromium(playwright 内置)"
        try:
            browser, context, page = await _try_launch(
                pw, channel, config.window_width, config.window_height, config.headless
            )
        except Exception as exc:  # 未安装该 channel / 启动失败
            errors.append(f"{label}: {str(exc).splitlines()[0][:120]}")
            log.info("启动 %s 失败，尝试下一个…", label)
            continue

        log.info("浏览器已启动：%s（窗口 %dx%d）", label, config.window_width, config.window_height)

        codec = await probe_codecs(page)
        if codec and codec.get("h264") in ("", "no"):
            log.warning(
                "当前浏览器不支持 H.264 视频解码（%s）。智慧树课程视频为 H.264，"
                "将出现“视频无法播放”。建议安装 Google Chrome 或改用 Edge。",
                label,
            )
        return browser, context, page, label

    raise RuntimeError(
        "无法启动任何浏览器。已尝试:\n  " + "\n  ".join(errors) +
        "\n提示: 可执行 `python -m playwright install chromium`，或先安装 Google Chrome。"
    )


async def probe_codecs(page) -> dict:
    """探测页面所在浏览器对 H.264/AAC 的支持情况。"""
    try:
        return await page.evaluate(CODEC_PROBE_JS)
    except Exception:
        return {}
