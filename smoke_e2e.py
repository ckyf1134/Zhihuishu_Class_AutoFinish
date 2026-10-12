"""端到端冒烟测试：驱动新实现跑到登录提交为止（不进入课程学习循环）。"""
import asyncio
import io
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from playwright.async_api import async_playwright  # noqa: E402

from zhs_core import study  # noqa: E402
from zhs_core.browser import launch_browser, probe_codecs  # noqa: E402
from zhs_core.config import load_config  # noqa: E402
from zhs_core.logger import setup_logging  # noqa: E402


async def main():
    setup_logging()
    config = load_config()
    print(f"配置: 课程={config.course_name} 账号={config.username} 窗口={config.window_width}x{config.window_height}")

    async with async_playwright() as pw:
        browser, context, page, channel = await launch_browser(pw, config)
        print(f"\n>>> 启动成功，实际使用: {channel}")

        codec = await probe_codecs(page)
        print(f">>> 编解码探测: {codec}")
        h264 = (codec or {}).get("h264")
        print(f">>> H.264 支持: {h264!r}  ->  {'可以播放课程视频' if h264 in ('probably', 'maybe') else '无法播放视频！'}")

        try:
            await study.login(page, config)
            print("\n>>> 登录流程完成，当前 URL:", page.url)
        except Exception as exc:
            print(f"\n>>> 登录流程异常: {type(exc).__name__}: {str(exc)[:200]}")
            print(">>> 当前 URL:", page.url)

        # 校验关键元素在新实现下可命中
        print("\n>>> 页面校验:")
        for name, sel in [
            ("课程名 div.courseName", study.SEL_COURSE_NAME),
            ("目录 ul.list", study.SEL_CATALOG),
            ("视频区域 div.videoArea", study.SEL_VIDEO_AREA),
        ]:
            try:
                n = await page.locator(sel).count()
            except Exception as e:
                n = f"err {str(e)[:50]}"
            print(f"    {name}: count={n}")

        if await page.locator(study.SEL_CATALOG).count():
            items = await study._collect_catalog(page)
            print(f"    目录视频条目: {len(items)} 个")
            for _, title, done in items[:5]:
                print(f"      [{'已完成' if done else '未完成'}] {title}")
            pending = [t for _, t, d in items if not d]
            print(f"    未完成: {len(pending)} 个 -> {pending[:3]}")

        await page.screenshot(path=str(ROOT / "_diag" / "new_impl_smoke.png"), full_page=True)
        await context.close()
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
