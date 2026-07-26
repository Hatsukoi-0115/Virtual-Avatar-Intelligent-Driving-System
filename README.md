# Virtual Avatar Intelligent Driving System

Live2D 多模态虚拟形象驱动系统。当前版本用于在 Windows 本地验证摄像头、麦克风、实时语音识别、中文情绪分类、LLM 语义理解和 Live2D 表情驱动链路。

## 当前状态

当前已经打通：

- 摄像头输入
- 麦克风输入
- FunASR 流式识别
- 中文情绪分类
- LLM 语义理解
- Live2D 模型加载与表情切换
- 情绪到表情的映射

当前重点优化项：

- 表情响应速度
- 头部和眼睛跟踪校准
- 运行时延迟控制
- 本地复现与验收文档完善

## 环境要求

- Windows 10 / 11
- Python 3.12
- `uv`
- 摄像头
- 麦克风

## 项目路径

如果项目克隆在桌面，默认路径为：

```powershell
C:\Users\liuzihao\Desktop\Virtual-Avatar-Intelligent-Driving-System
```

后续命令都在项目根目录执行。

```powershell
cd C:\Users\liuzihao\Desktop\Virtual-Avatar-Intelligent-Driving-System
```

## 模型准备

### Live2D 测试模型

测试模型使用 Live2D 官方 Haru 示例模型：

- [Live2D Haru Sample](https://www.live2d.com/en/learn/sample/haru/)

下载 `haru_ja.zip` 后解压，并确保模型文件位于：

```text
models/haru_ja/runtime/haru.model3.json
```

### 中文情绪分类模型

情绪分类模型使用：

- [Johnson8187/Chinese-Emotion-Small](https://huggingface.co/Johnson8187/Chinese-Emotion-Small)

模型文件需要放到：

```text
models/hf_cache/Johnson8187__Chinese-Emotion-Small
```

该目录中应包含 tokenizer、config、权重等 Hugging Face 模型文件。

## 安装依赖

```powershell
uv sync
```

如果网络不稳定，可以先设置镜像源：

```powershell
$env:UV_INDEX_URL="https://mirrors.aliyun.com/pypi/simple/"
uv sync
```

## 启动项目

推荐直接使用项目虚拟环境中的 Python：

```powershell
.\.venv\Scripts\python.exe main.py
```

如果需要先激活虚拟环境：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
.\.venv\Scripts\Activate.ps1
python main.py
```

说明：当前本地环境里，`uv run python main.py` 可能受镜像源或网络影响，优先使用 `.venv` 里的 Python 启动。

## LLM 配置

如果需要启用 LLM 语义理解，需要在 `.env` 或配置中填写兼容 OpenAI 接口的服务信息，例如 DeepSeek：

```env
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_API_KEY=你的_api_key
LLM_MODEL=deepseek-chat
```

如果未配置完整，项目仍可运行，但会提示 LLM 配置不完整，语义理解不会生效。

## 验收方法

### 基础启动验收

启动后应能看到：

- Live2D 窗口正常出现
- 主窗口显示 3 秒视觉校准准备倒计时，此时请正对摄像头、自然睁眼并保持头部水平
- 倒计时结束后进入约 1 秒视觉中立校准，完成后主窗口会提示可以开始测试
- 摄像头驱动头部、眼睛、嘴部
- 麦克风输入后出现语音识别、情绪或 LLM 日志

### 表情映射验收

依次说下面几句话：

```text
太好了
我很难
你太过分了
我的天哪
```

期望映射：

- 开心 -> `Smile`
- 难过 -> `Sad`
- 愤怒 -> `Angry`
- 疑问 / 惊讶 -> `Surprised`
- 平静 -> `Normal`

### 延迟验收

重点观察：

- 说完一句话后，表情应较快出现
- 同一句话内表情不应频繁跳变
- `[Emotion] 句子=...` 应先出现
- `[LLM] 句子=...` 可以稍晚出现，这是正常的

## 常见问题

### 直接输入项目路径报错

在 PowerShell 中，文件夹路径不是命令。进入项目目录应使用：

```powershell
cd C:\Users\liuzihao\Desktop\Virtual-Avatar-Intelligent-Driving-System
```

### `uv run` 拉包失败

优先改用：

```powershell
.\.venv\Scripts\python.exe main.py
```

如果依赖尚未安装完成，再检查网络和镜像源。

### Live2D 模型不显示

检查文件是否存在：

```text
models/haru_ja/runtime/haru.model3.json
```

如果不存在，需要重新解压 `haru_ja.zip`。

### 情绪模型不生效

检查目录是否存在：

```text
models/hf_cache/Johnson8187__Chinese-Emotion-Small
```

如果不存在，需要重新下载 Hugging Face 情绪分类模型。

## 开发计划

详细开发计划见：

- [docs/plan.md](docs/plan.md)
- [docs/four-person-development-plan.md](docs/four-person-development-plan.md)
