"""智慧树课程学习主流程。

流程：登录(含滑块等待) -> 进入课程 -> 关弹窗 -> 逐个播放未完成视频 -> 处理随堂测验。
每一步都带超时与兜底，且能感知“浏览器被用户关闭”并立即退出。
"""
from __future__ import annotations

import asyncio
import re

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from . import llm
from .browser import BrowserClosedError, is_page_alive
from .logger import get_logger

log = get_logger()

HOME_URL = "https://www.zhihuishu.com"
STUDY_URL_RE = re.compile(r"studyvideoh5\.zhihuishu\.com/stuStudy")
COURSE_LIST_RE = re.compile(r"onlineweb\.zhihuishu\.com/onlinestuh5")

# ---------- 选择器集中管理 ----------
# 注意：选择器里不要出现未被引号保护的逗号。a:has-text("登录") 中的逗号看似在引号内，
# 但 Playwright 会把整串按顶层逗号切成多个选择器，导致 "Unexpected token" 报错。
# 需要多个候选时用 "|" 合并（或 .or_()），不要用逗号。
SEL_LOGIN_ENTRY = 'a:has-text("登录")'
# 登录入口的候选，逐个尝试（顺序即优先级）
LOGIN_ENTRY_CANDIDATES = (
    'text=登录',
    '[class*="login"]:has-text("登录")',
    'text=登录 / 注册',
)
SEL_LOGIN_USER = 'input[name="mobile"], input[placeholder*="手机号"], input[name="username"]'
SEL_LOGIN_PWD = 'input[type="password"], input[placeholder*="密码"], input[name="password"]'
SEL_ACCOUNT_TAB = '.el-tabs__item:has-text("账号登录")'
SEL_PRIVACY_CHECKBOX = '.privacy-checkbox input[type="checkbox"], input[type="checkbox"].el-checkbox__original'
SEL_LOGIN_SUBMIT = ".btn-block__grandient_login"

SEL_COURSE_NAME = "div.courseName"
SEL_CATALOG = "ul.list"
SEL_CATALOG_ITEMS = "ul.list li.video, ul.list div li.video, ul.list div ul li.video"
SEL_CURRENT_VIDEO = "ul.list li.video.current_play, ul.list div li.video.current_play, ul.list div ul li.video.current_play"
SEL_ITEM_TITLE = "span.catalogue_title"
SEL_ITEM_FINISHED = "b.fl.time_icofinish"

SEL_VIDEO_AREA = "div.videoArea"
SEL_VIDEO_TAG = "video"
SEL_SPEED_BOX = "div.speedBox"
SEL_SPEED_15 = 'div.speedTab15[rate="1.5"]'
SEL_DEFINI_BOX = "div.definiBox"
SEL_SWITCH_LINE = "b.line1bq.switchLine"

SEL_QUIZ_DIALOG = "div#playTopic-dialog"
SEL_QUIZ_TITLE = "p.topic-title"
SEL_QUIZ_OPTIONS = "ul.topic-list li.topic-item"

SEL_CAPTCHA = "div.yidun_modal"

# 各类弹窗的关闭按钮，按优先级尝试
POPUP_CLOSERS = (
    "i.iconfont.iconguanbi",
    ".el-dialog__headerbtn",
    'div[role="dialog"] i[class*="close"]',
    'img.ai-close-icon',
    'img.icon',
)

POLL_INTERVAL = 5.0          # 完成状态检测间隔（避免高 CPU）
MAX_VIDEOS_PER_RUN = 200     # 安全阀


async def _ensure_alive(page) -> None:
    if not is_page_alive(page):
        raise BrowserClosedError("浏览器窗口已关闭")


async def _safe_click(page, selector: str, *, timeout: int = 8000, force: bool = False) -> bool:
    """点击第一个匹配元素；失败返回 False 而不抛异常。"""
    try:
        locator = page.locator(selector).first
        if await locator.count() == 0:
            return False
        await locator.click(timeout=timeout, force=force)
        return True
    except (PlaywrightTimeoutError, PlaywrightError):
        return False


async def _dismiss_popups(page) -> int:
    """反复尝试关闭各种弹窗，返回成功关闭的次数。"""
    closed = 0
    for _ in range(3):  # 有些弹窗是多层的
        progressed = False
        for selector in POPUP_CLOSERS:
            try:
                locator = page.locator(selector)
                count = await locator.count()
            except PlaywrightError:
                continue
            for index in range(min(count, 4)):
                try:
                    item = locator.nth(index)
                    if await item.is_visible():
                        await item.click(timeout=2500)
                        closed += 1
                        progressed = True
                        await asyncio.sleep(0.6)
                except (PlaywrightTimeoutError, PlaywrightError):
                    continue
        if not progressed:
            break
    # “不再提示”类的按钮
    try:
        no_hint = page.locator('a:has-text("不再提示")').first
        if await no_hint.count() and await no_hint.is_visible():
            await no_hint.click(timeout=3000)
    except (PlaywrightTimeoutError, PlaywrightError):
        pass

    if closed:
        log.info("已关闭 %d 个弹窗", closed)
    return closed


async def _handle_captcha(page, wait_seconds: int = 300) -> bool:
    """检测滑块验证码；出现则等待人工完成。"""
    try:
        modal = page.locator(SEL_CAPTCHA).first
        if await modal.count() == 0 or not await modal.is_visible():
            return False
    except PlaywrightError:
        return False

    print("\n" + "=" * 60)
    print("【需要你操作】检测到滑块验证码，请在浏览器中手动完成。")
    print(f"完成后脚本会自动继续（最多等待 {wait_seconds // 60} 分钟）。")
    print("=" * 60)
    try:
        await page.wait_for_selector(SEL_CAPTCHA, state="hidden", timeout=wait_seconds * 1000)
        log.info("验证码已完成")
        return True
    except PlaywrightTimeoutError:
        log.warning("等待验证码超时，继续尝试后续流程")
        return False


async def login(page, config) -> None:
    """打开智慧树并完成登录。"""
    log.info("打开智慧树首页")
    await page.goto(HOME_URL, wait_until="domcontentloaded")

    if await page.locator(SEL_COURSE_NAME).count() == 0:
        log.info("点击右上角登录入口")
        clicked = False
        for selector in LOGIN_ENTRY_CANDIDATES:
            if await _safe_click(page, selector, timeout=5000):
                clicked = True
                break
        if not clicked:
            log.warning("未找到登录入口，可能页面结构变化")

        try:
            await page.wait_for_selector(SEL_LOGIN_USER, timeout=20000)
        except PlaywrightTimeoutError as exc:
            await _ensure_alive(page)
            raise RuntimeError("未出现登录表单，可能智慧树登录页改版或网络异常") from exc

        # 切到“账号登录”标签
        try:
            tab = page.locator(SEL_ACCOUNT_TAB).first
            if await tab.count():
                classes = await tab.get_attribute("class") or ""
                if "is-active" not in classes:
                    await tab.click()
                    await asyncio.sleep(0.6)
        except PlaywrightError:
            pass

        log.info("填写账号密码")
        await page.locator(SEL_LOGIN_USER).first.fill(config.username)
        await page.locator(SEL_LOGIN_PWD).first.fill(config.password)

        await _tick_privacy_checkbox(page)

        log.info("提交登录")
        if not await _safe_click(page, SEL_LOGIN_SUBMIT, timeout=15000):
            raise RuntimeError("点击登录按钮失败，请检查智慧树登录页是否改版")

    await _handle_captcha(page, wait_seconds=300)

    try:
        await page.wait_for_url(COURSE_LIST_RE, timeout=120000)
        log.info("登录成功，已进入课程列表")
    except PlaywrightTimeoutError:
        if await page.locator(SEL_COURSE_NAME).count():
            log.info("已在课程列表页")
        else:
            raise RuntimeError("登录后未能进入课程列表页，请检查账号密码或验证码是否完成")


async def _tick_privacy_checkbox(page) -> None:
    """勾选《用户协议》——新版智慧树不勾选无法登录。

    坑：真实 input 被 el-checkbox 隐藏（尺寸 0），直接点 input 会一直等到超时。
    必须点外层容器；再不行用脚本方式置位。
    """
    try:
        checkbox = page.locator(SEL_PRIVACY_CHECKBOX).first
        if await checkbox.count() == 0:
            return
        if await checkbox.is_checked():
            return

        for selector in (".el-checkbox.privacy-checkbox", ".el-checkbox__inner", ".el-checkbox"):
            locator = page.locator(selector).first
            try:
                if await locator.count():
                    await locator.click(timeout=3000)
                    if await checkbox.is_checked():
                        log.info("已勾选用户协议")
                        return
            except (PlaywrightTimeoutError, PlaywrightError):
                continue

        await checkbox.evaluate("el => { if (!el.checked) el.click(); }")
        log.info("已勾选用户协议（脚本方式）")
    except PlaywrightError as exc:
        log.debug("勾选协议时忽略异常: %s", exc)


async def enter_course(page, course_name: str) -> None:
    """在课程列表页点击目标课程并等待学习页加载。"""
    await page.wait_for_selector(SEL_COURSE_NAME, timeout=30000)

    link = page.locator(SEL_COURSE_NAME).filter(has_text=course_name).first
    if await link.count() == 0:
        available = await page.locator(SEL_COURSE_NAME).all_inner_texts()
        raise RuntimeError(
            f"未找到课程《{course_name}》。当前课程列表: {[t.strip() for t in available][:10]}"
        )

    log.info("进入课程《%s》", course_name)
    await link.click()

    try:
        await page.wait_for_url(STUDY_URL_RE, timeout=60000)
    except PlaywrightTimeoutError:
        log.warning("等待学习页 URL 超时，继续按页面元素判断")

    await page.wait_for_selector(SEL_CATALOG, timeout=60000)
    await asyncio.sleep(3)
    await _dismiss_popups(page)


async def _is_finished(item) -> bool:
    """该章节视频是否已完成。"""
    try:
        marker = await item.query_selector(SEL_ITEM_FINISHED)
        return marker is not None and await marker.is_visible()
    except PlaywrightError:
        return False


async def _collect_catalog(page):
    """返回 [(element, 标题, 是否完成)]，仅视频条目。"""
    items = await page.query_selector_all(SEL_CATALOG_ITEMS)
    result = []
    for item in items:
        classes = await item.get_attribute("class") or ""
        if "video" not in classes:
            continue
        title_el = await item.query_selector(SEL_ITEM_TITLE)
        title = (await title_el.inner_text()).strip() if title_el else ""
        result.append((item, title, await _is_finished(item)))
    return result


async def _set_playback(page) -> None:
    """1.5 倍速 + 流畅清晰度。失败不致命。"""
    try:
        await page.hover(SEL_VIDEO_AREA)
        await asyncio.sleep(0.4)

        if await _safe_click(page, SEL_SPEED_BOX, timeout=5000):
            await asyncio.sleep(0.3)
            if await _safe_click(page, SEL_SPEED_15, timeout=5000):
                log.info("已切换到 1.5 倍速")
            else:
                log.info("未找到 1.5 倍速选项")

        await page.hover(SEL_DEFINI_BOX)
        await asyncio.sleep(0.3)
        if await _safe_click(page, SEL_SWITCH_LINE, timeout=5000):
            log.info("已切换到流畅清晰度")
    except PlaywrightError as exc:
        log.debug("调节播放参数时忽略异常: %s", exc)


async def _video_state(page) -> dict:
    """读取 <video> 的播放状态。"""
    try:
        return await page.evaluate(
            """() => {
              const v = document.querySelector('video');
              if (!v) return {present: false};
              return {present: true, paused: v.paused, current: v.currentTime,
                      duration: isNaN(v.duration) ? null : v.duration,
                      readyState: v.readyState,
                      error: v.error ? {code: v.error.code, message: v.error.message} : null};
            }"""
        )
    except PlaywrightError:
        return {"present": False}


async def _answer_quiz(page, config, use_llm: bool) -> bool:
    """处理随堂测验弹窗。"""
    try:
        dialog = page.locator(SEL_QUIZ_DIALOG).first
        if await dialog.count() == 0 or not await dialog.is_visible():
            return False
    except PlaywrightError:
        return False

    log.info("检测到随堂测验")
    await asyncio.sleep(1.5)

    picked: list[int] = []
    try:
        title = (await page.locator(SEL_QUIZ_TITLE).first.inner_text()).strip()
        option_nodes = await page.query_selector_all(SEL_QUIZ_OPTIONS)
        options = [(await node.inner_text()).strip() for node in option_nodes]
        log.info("题目: %s", title)
        log.info("选项: %s", " | ".join(options))

        if use_llm and config.api_key:
            try:
                picked = await llm.ask_question(config, title, options)
            except llm.LLMError as exc:
                log.error("调用大模型失败: %s", exc)
                log.error("注意：本题将回退为默认选项，答案可能不正确")
                picked = []
        elif use_llm:
            log.warning("未配置 API Key，无法使用 AI 答题")
    except PlaywrightError as exc:
        log.warning("读取题目失败: %s", exc)

    clicked = False
    for index in picked:
        try:
            if 0 <= index < len(option_nodes):
                await option_nodes[index].click()
                log.info("已选择第 %d 项", index + 1)
                clicked = True
                await asyncio.sleep(0.4)
        except PlaywrightError:
            continue

    if not clicked:
        log.warning("没有可靠的答案，默认选择第一项")
        await _safe_click(page, f"{SEL_QUIZ_DIALOG} {SEL_QUIZ_OPTIONS}:first-child", force=True)

    await asyncio.sleep(0.5)
    # 关闭答题弹窗（尝试多个候选按钮）
    for selector in ('div#playTopic-dialog .close', 'div#playTopic-dialog i[class*="close"]', 'div:text("关闭")'):
        if await _safe_click(page, selector, timeout=3000, force=True):
            break
    return True


async def _play_video(page, config, use_llm: bool) -> bool:
    """点击播放区域并设置参数；返回是否成功开始。"""
    if not await _safe_click(page, SEL_VIDEO_AREA, timeout=10000, force=True):
        log.warning("找不到视频区域，跳过")
        return False

    await asyncio.sleep(1)
    await _set_playback(page)

    state = await _video_state(page)
    if state.get("error"):
        log.error(
            "视频解码失败 (code=%s)。通常是浏览器缺少 H.264 支持；"
            "请安装 Google Chrome 或把 BROWSER_CHANNEL 设为 msedge。",
            state["error"].get("code"),
        )
        return False
    log.info("已开始播放，当前进度 %.0fs", state.get("current") or 0)
    return True


async def run(config) -> None:
    """主流程。"""
    from playwright.async_api import async_playwright

    from .browser import launch_browser

    use_llm = config.llm_ready
    if use_llm:
        log.info("AI 答题已启用，模型: %s", config.answer_model)
    else:
        log.warning("AI 答题未启用（缺少 API Key 或已被关闭），测验将默认选择第一项")

    async with async_playwright() as pw:
        browser, context, page, channel = await launch_browser(pw, config)
        try:
            await login(page, config)
            await enter_course(page, config.course_name)

            played = 0
            while played < MAX_VIDEOS_PER_RUN:
                await _ensure_alive(page)

                catalog = await _collect_catalog(page)
                if not catalog:
                    log.warning("目录为空，等待后重试")
                    await asyncio.sleep(5)
                    continue

                pending = [(item, title) for item, title, done in catalog if not done]
                if not pending:
                    log.info("所有视频均已完成")
                    print("\n【执行结束】该课程没有更多未完成视频。")
                    break

                item, title = pending[0]
                log.info("下一个待学视频: %s", title or "(无标题)")

                title_el = await item.query_selector(SEL_ITEM_TITLE)
                if title_el is None:
                    log.warning("该条目没有标题元素，跳过")
                    # 标记为已处理，避免死循环
                    await item.evaluate("el => el.dataset.zhsSkip = '1'")
                    continue
                await title_el.click()

                await asyncio.sleep(3)
                await _handle_captcha(page)
                await _answer_quiz(page, config, use_llm)

                await page.wait_for_selector(SEL_VIDEO_AREA, timeout=20000)
                if not await _play_video(page, config, use_llm):
                    log.warning("视频未能开始播放，等待 30 秒后重试其他视频")
                    await asyncio.sleep(30)
                    continue

                played += 1
                await _wait_until_finished(page)
            else:
                log.warning("已达到单次运行上限 %d 个视频，停止", MAX_VIDEOS_PER_RUN)

        except BrowserClosedError:
            print("\n【已退出】浏览器窗口被关闭，脚本停止运行。")
        finally:
            try:
                await context.close()
            except Exception:
                pass
            try:
                await browser.close()
            except Exception:
                pass


async def _wait_until_finished(page, timeout_seconds: int = 7200) -> None:
    """轮询等待当前视频播放完成。"""
    waited = 0.0
    while waited < timeout_seconds:
        await _ensure_alive(page)
        await asyncio.sleep(POLL_INTERVAL)
        waited += POLL_INTERVAL

        # 测验中途弹出
        try:
            dialog = page.locator(SEL_QUIZ_DIALOG).first
            if await dialog.count() and await dialog.is_visible():
                return
        except PlaywrightError:
            pass

        try:
            current = page.locator(SEL_CURRENT_VIDEO).first
            if await current.count() == 0:
                continue
            if await _is_finished(current):
                log.info("当前视频已完成")
                return
        except PlaywrightError:
            continue

    log.warning("等待视频完成超时")
