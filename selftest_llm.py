"""快速自检：不打开浏览器，验证模块导入、配置加载、答案解析、提示词构造。"""
import asyncio
import io
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

FAILED = []


def check(label, actual, expected):
    ok = actual == expected
    if not ok:
        FAILED.append(f"{label}: 期望 {expected!r}，实际 {actual!r}")
    print(f"{'PASS' if ok else 'FAIL'}  {label}: {actual!r}")


print("=== 1. 模块导入 ===")
from zhs_core import browser, config as cfg_mod, llm, study  # noqa: E402
print("PASS  导入 browser/config/llm/study")

print("\n=== 2. 配置加载 ===")
cfg = cfg_mod.load_config()
print(f"PASS  课程={cfg.course_name} 账号={cfg.username} 模型={cfg.answer_model}")
print(f"PASS  base_url={cfg.base_url} llm_ready={cfg.llm_ready}")
print(f"PASS  窗口={cfg.window_width}x{cfg.window_height} channel={cfg.browser_channel}")
check("api_key 非空", bool(cfg.api_key), True)
check("enable_llm_answer", cfg.enable_llm_answer, True)

print("\n=== 3. 答案解析 ===")
check("单选 2", llm.parse_choice_indices("2", 4), [1])
check("多选 1;3;4", llm.parse_choice_indices("1;3;4", 4), [0, 2, 3])
check("顿号 1、3", llm.parse_choice_indices("1、3", 4), [0, 2])
check("字母 B", llm.parse_choice_indices("B", 4), [1])
check("答案是C", llm.parse_choice_indices("答案是C", 4), [2])
check("多字母 AC", llm.parse_choice_indices("AC", 4), [0, 2])
check("越界数字 9", llm.parse_choice_indices("9", 4), [])
check("带思考标签", llm.parse_choice_indices("<think>想想</think>3", 4), [2])
check("去重 2;2", llm.parse_choice_indices("2;2", 4), [1])
check("空", llm.parse_choice_indices("", 4), [])

print("\n=== 4. 响应提取 ===")
check(
    "chat completions",
    llm.extract_content({"choices": [{"message": {"content": " 3 "}}]}),
    "3",
)
check(
    "output_text 兜底",
    llm.extract_content({"output_text": "1;2"}),
    "1;2",
)

print("\n=== 5. 真实调用大模型（1 题） ===")


async def live():
    try:
        picks = await llm.ask_question(
            cfg,
            "马克思主义中国化时代化的第一次历史性飞跃的理论成果是？",
            ["邓小平理论", "毛泽东思想", "三个代表重要思想", "科学发展观"],
        )
        print(f"PASS  模型返回索引 {picks} -> 选项 {[p + 1 for p in picks]}")
        check("客观答案应为 2", [p + 1 for p in picks], [2])
    except Exception as exc:
        FAILED.append(f"真实调用失败: {exc}")
        print(f"FAIL  真实调用失败: {exc}")


asyncio.run(live())

print("\n=== 结果 ===")
if FAILED:
    print(f"{len(FAILED)} 项失败:")
    for item in FAILED:
        print("  -", item)
    sys.exit(1)
print("全部通过")
