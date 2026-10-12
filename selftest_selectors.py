"""校验 study.py 中所有选择器都能被 Playwright 正确解析（不打开页面也能查出语法错误）。"""
import asyncio
import io
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from playwright.async_api import async_playwright  # noqa: E402

from zhs_core import study  # noqa: E402


def collect_selectors():
    found = []
    for name in dir(study):
        if name.startswith("SEL_") or name.endswith("_CANDIDATES") or name == "POPUP_CLOSERS":
            value = getattr(study, name)
            if isinstance(value, str):
                found.append((name, value))
            elif isinstance(value, (tuple, list)):
                for i, v in enumerate(value):
                    found.append((f"{name}[{i}]", v))
    return found


async def main():
    selectors = collect_selectors()
    print(f"共 {len(selectors)} 个选择器待校验\n")

    bad = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto("data:text/html,<html><body><p>t</p></body></html>")

        for name, sel in selectors:
            try:
                await page.locator(sel).count()
                print(f"PASS  {name:26s} {sel}")
            except Exception as exc:
                bad.append((name, sel, str(exc).splitlines()[0][:110]))
                print(f"FAIL  {name:26s} {sel}\n        -> {str(exc).splitlines()[0][:110]}")

        # 动态拼出来的选择器
        dynamic = [
            ("_dismiss_popups 关闭", f"{study.SEL_QUIZ_DIALOG} .close"),
            ("quiz 第一项", f"{study.SEL_QUIZ_DIALOG} {study.SEL_QUIZ_OPTIONS}:first-child"),
            ("courseName filter", f'{study.SEL_COURSE_NAME} >> text=军事理论'),
        ]
        print("\n--- 动态拼接的选择器 ---")
        for name, sel in dynamic:
            try:
                await page.locator(sel).count()
                print(f"PASS  {name:26s} {sel}")
            except Exception as exc:
                bad.append((name, sel, str(exc).splitlines()[0][:110]))
                print(f"FAIL  {name:26s} {sel}\n        -> {str(exc).splitlines()[0][:110]}")

        await browser.close()

    print("\n=== 结果 ===")
    if bad:
        print(f"{len(bad)} 个选择器非法:")
        for name, sel, err in bad:
            print(f"  - {name}: {err}")
        sys.exit(1)
    print("全部选择器语法正确")


if __name__ == "__main__":
    asyncio.run(main())
