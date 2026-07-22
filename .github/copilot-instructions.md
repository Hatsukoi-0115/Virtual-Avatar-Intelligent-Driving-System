# Copilot Instructions

## 项目概述

本项目为基于 Python 的 Live2D 多模态虚拟形象驱动系统，目标是在 Windows 平台实现摄像头、麦克风、实时语音识别、情绪理解、LLM 语义理解与 Live2D 虚拟形象的统一驱动。

开发过程中应遵循模块化、低耦合、高可维护性的原则。

---

# Python 环境

## 使用 uv 管理项目

本项目统一使用 **uv** 进行 Python 版本及依赖管理。

### Python

- 使用 uv 管理 Python 版本。
- 不要假设系统 Python 已安装。
- 不要建议使用 pipenv、poetry、conda 等其他环境管理工具。
- 不要生成 `requirements.txt` 作为主要依赖文件。
- 使用 `pyproject.toml` 管理项目依赖。

### 安装依赖

新增依赖时优先使用：

```bash
uv add package_name
```

开发依赖：

```bash
uv add --dev package_name
```

同步环境：

```bash
uv sync
```

运行程序：

```bash
uv run python main.py
```

运行脚本：

```bash
uv run python script.py
```

运行测试：

```bash
uv run pytest
```

除非用户明确要求，否则不要使用：

- pip install
- python -m pip
- virtualenv
- venv

---

# 注释规范

所有代码注释必须使用**中文**。

包括但不限于：

- 类注释
- 函数注释
- 方法注释
- 模块说明
- 行内注释

不要生成英文注释。

---

# 关键代码说明

生成或修改代码时：

**必须在关键逻辑处添加中文注释。**

例如：

- 算法实现
- 状态切换
- 多线程
- 异步流程
- Live2D 参数更新
- MediaPipe 数据处理
- 音频处理
- LLM 调用
- 配置加载
- 异常处理

避免只有函数说明而没有关键步骤说明。

---

# 代码风格

遵循：

- PEP8
- 类型注解（Type Hint）
- pathlib 替代 os.path
- dataclass 或 Pydantic 用于结构化数据
- 使用 logging，不使用 print 作为正式日志

优先使用：

- pathlib.Path
- Enum
- Pydantic
- typing

---

# Live2D 开发规范

Live2D 渲染层仅负责：

- 模型加载
- 参数更新
- 表情播放
- 动作播放

不要将业务逻辑写入渲染层。

所有状态统一由 Avatar Controller 管理。

---

# 多模态数据流

遵循单向数据流：

```
Camera
Mic
LLM
Emotion
        │
        ▼
Avatar Controller
        │
        ▼
Live2D Renderer
```

不要让多个模块直接修改 Live2D 参数。

所有状态融合必须经过 Avatar Controller。

---

# 性能要求

避免阻塞 UI。

涉及：

- 摄像头
- 麦克风
- MediaPipe
- FunASR
- LLM

应采用异步或独立线程处理。

LLM 不允许进入高频实时循环。

---

# 配置管理

配置项应统一放入配置文件，不要硬编码。

包括：

- API Key
- 模型路径
- 阈值
- 摄像头编号
- 麦克风编号
- 刷新率
- 参数映射

---

# 错误处理

不要忽略异常。

关键模块应：

- 捕获异常
- 输出日志
- 保证程序可恢复

不要使用裸 except。

---

# Git

生成代码时不要包含：

- .venv
- __pycache__
- 临时文件

遵循已有目录结构，不随意移动文件。

---

# 文档要求

新增模块时：

应包含：

- 模块说明
- 类说明
- 函数说明

均使用中文。

---

# 输出原则

优先保证：

1. 可读性
2. 可维护性
3. 模块解耦
4. 清晰注释

不要为了缩短代码而降低可维护性。

优先生成易于理解、适合长期维护的代码。