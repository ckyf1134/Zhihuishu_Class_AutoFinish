# 智慧树课程自动学习工具

基于 Playwright 与 DeepSeek 大模型的智慧树（zhihuishu.com）课程自动学习工具：自动登录、1.5 倍速播放、AI 随堂测验答题、自动连播未完成视频。

> **免责声明**：本项目仅供学习与技术交流。使用自动化工具可能违反平台协议，由此产生的一切后果由使用者自行承担。AI 作答可能出错，成绩风险自负。

---

## 特性

- **自动挑浏览器**：依次尝试 Google Chrome → Microsoft Edge → Playwright 内置 Chromium，并探测 H.264 解码能力，避免“视频无法播放”
- 自动登录，自动勾选用户协议，滑块验证码出现时暂停等你手动完成
- 静音 + 1.5 倍速 + 流畅清晰度
- 随堂测验调用 DeepSeek（任何 OpenAI 兼容接口均可）自动作答，支持单选与多选
- 自动识别目录中未完成的视频并连播，轮询检测降低 CPU 占用
- 浏览器被手动关闭时立即优雅退出，不再空转
- 全流程中文日志，同时写入 `logs/run.log`

---

## 环境要求

- Python 3.10+
- Windows / macOS / Linux
- 建议安装 **Google Chrome** 或 **Microsoft Edge**（见下方“为什么必须用真正的 Chrome/Edge”）

---

## 快速开始

```bash
# 1. 安装依赖
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux
pip install -r requirements.txt
python -m playwright install chromium

# 2. 配置
copy .env.example .env          # Windows
# cp .env.example .env          # macOS / Linux
# 编辑 .env，填入账号、密码、课程名与 API Key

# 3. 运行
python run.py
```

---

## 配置项（.env）

| 变量 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `ZHIHUISHU_USERNAME` | 是 | — | 智慧树登录手机号 |
| `ZHIHUISHU_PASSWORD` | 是 | — | 智慧树登录密码 |
| `COURSE_NAME` | 是 | — | 要学习的课程完整名称 |
| `DEEPSEEK_API_KEY` | 否* | — | API 密钥；兼容 `DASHSCOPE_API_KEY` / `QWEN_API_KEY` |
| `DEEPSEEK_BASE_URL` | 否 | `https://api.deepseek.com/v1` | OpenAI 兼容端点 |
| `ANSWER_MODEL` | 否 | `deepseek-flash` | 答题模型名 |
| `ENABLE_LLM_ANSWER` | 否 | `true` | 是否启用 AI 答题；关闭则测验默认选第一项 |
| `ENABLE_REASONING` | 否 | `false` | 是否开启思考模式 |
| `BROWSER_CHANNEL` | 否 | `auto` | `auto` / `chrome` / `msedge` / `chromium` |
| `WINDOW_WIDTH` / `WINDOW_HEIGHT` | 否 | `1600` / `860` | 浏览器窗口尺寸 |
| `HEADLESS` | 否 | `false` | 无头模式（滑块验证码需手动完成，不建议开启） |

\* 不填 API Key 仍可运行，但随堂测验只能默认选第一项。

### 换用其他大模型

任何 OpenAI 兼容服务都可以，改这三项即可：

```env
DEEPSEEK_API_KEY="sk-your-key"
DEEPSEEK_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"   # 例：阿里云百炼
ANSWER_MODEL="qwen-plus"
```

---

## 项目结构

```
run.py                     入口
zhs_core/
  config.py                配置加载与校验
  logger.py                日志
  browser.py               浏览器选择 / 编解码探测 / 存活检测
  llm.py                   大模型调用与答案解析
  study.py                 主流程：登录、进课程、播放、答题
selftest_llm.py            不打开浏览器的快速自检
smoke_e2e.py               端到端冒烟测试
```

---

## 排错指南（这些都是实测踩过的坑）

### 1. 提示“视频无法播放，请尝试切换其他线路”

**原因**：智慧树课程视频是 H.264/AAC 编码的 `.mp4`，而 Playwright 自带的开源 Chromium **不包含这些专有编解码器**，`<video>` 会直接报 `error.code = 4`（`MEDIA_ERR_SRC_NOT_SUPPORTED`）。

**解决**：安装 Google Chrome，或让脚本使用 Edge：

```env
BROWSER_CHANNEL=msedge
```

脚本启动时会打印编解码探测结果，`H.264 支持: 'probably'` 才说明能正常播放。

### 2. AI 答题全部选第一项 / 日志出现 CERTIFICATE_VERIFY_FAILED

**原因**：`httpx` 默认读取 Windows 系统代理。若本机装有 Steam++（Watt Toolkit）一类带 TLS 中间人的加速器，系统代理开启时 HTTP 客户端会因代理证书不被信任而报错，旧实现会“回退选第一项”，导致**每道题都答错却不报错**。

**解决**：本项目的 HTTP 客户端已显式 `trust_env=False`（直连，不走系统代理）。若你确实需要走代理，请在代理软件中把 `api.deepseek.com` 加入直连/白名单，或导入其根证书。

### 3. 页面显示不全 / 按钮点不到

智慧树登录页按固定 1620×810 设计尺寸绝对定位。视口小于该尺寸时，登录按钮会被挤出可视区，Playwright 的可见性与命中检测会一直等到超时。

本项目的默认窗口 1600×860 已避开此问题。**不要全屏最大化**——页面会因 zoom 导致坐标错位。

### 4. 缺少依赖 / 浏览器

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

---

## 开源许可

本项目基于 MIT 许可证发布，详见 [LICENSE](LICENSE)。

项目起步时参考了 **linfish330/zhihuishu_course_automation**（MIT License, Copyright (c) 2026 LIN）的流程思路，并在其基础上重构了代码结构、修复了上述编解码、代理证书、视口与弹窗等一系列问题。原作者的版权声明依 MIT 条款保留于 LICENSE 文件中。
