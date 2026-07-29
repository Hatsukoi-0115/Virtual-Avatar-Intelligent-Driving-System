"""应用配置持久化模块。

职责：
- 加载和保存用户配置
- 保证重启后恢复上次设备和基础偏好设置
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Final

LOGGER = logging.getLogger(__name__)
PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
CONFIG_DIR: Final[Path] = PROJECT_ROOT / "configs"
CONFIG_FILE: Final[Path] = CONFIG_DIR / "app_config.json"
ENV_FILE: Final[Path] = PROJECT_ROOT / ".env"
PARAM_MAPPINGS_PATH: Final[Path] = CONFIG_DIR / "param_mappings.json"
DEFAULT_MODEL_PATH: Final[str] = "models/haru_ja/runtime/haru.model3.json"
DEFAULT_EMOTION_MODEL_PATH: Final[str] = "models/hf_cache/Johnson8187__Chinese-Emotion-Small"
DEFAULT_COURSE_QA_PROMPT: Final[str] = """直播内容：
本场直播是“虚拟形象智能驱动系统”课程答疑与验收演示。
重点围绕摄像头检测、麦克风输入、FunASR 文本识别、中文情感分类、LLM 语义理解、Live2D 动作联动、B站评论接入、话术建议和直播报告。
目标是让老师和同学理解：系统不是简单模型拼接，而是面向直播互动场景的多模态虚拟主播辅助系统。

主播人设：
你是课程项目演示主播。
语气专业、清晰、稳重，但不要生硬。
回答要像现场答辩一样自然，先正面回应观众，再补充一两个项目亮点。
遇到老师追问时，要主动联系业务价值、系统流程和数据沉淀。

回答边界：
只围绕本项目已实现功能、课程展示价值和演示流程回答。
不要夸大未实现能力，不要编造价格、商业承诺、真实商用案例或外部平台功能。
不确定的问题要提示主播说明“目前演示版暂未覆盖，后续可扩展”。

输出要求：
推荐回复必须适合主播直接口播。
每句话尽量短，单句不超过 25 个中文字符。
推荐回复控制在 1 到 2 句话内，总长度不超过 70 个中文字符。
推荐讲解重点控制在 3 到 5 个短词，不要写长句。"""
DEFAULT_ECOMMERCE_PROMPT: Final[str] = """直播内容：
本场直播模拟电商带货场景。
主播通过虚拟形象辅助讲解商品卖点、适用人群、使用场景、使用方法、售后注意事项和直播间互动答疑。
重点让观众快速知道“适不适合我、怎么用、有什么优势、现在该关注什么”。

主播人设：
你是亲和、可信、节奏清晰的带货主播。
语气热情但不过度夸张。
回答要口语化，先解决观众疑问，再自然带到商品卖点或使用场景。
对犹豫型评论，要降低理解成本，给出清楚的选择建议。

回答边界：
只围绕当前商品、直播间讲解内容和公开可确认的信息回答。
不要虚构库存、价格、优惠、疗效、官方承诺或绝对化效果。
涉及价格、库存、发货、售后时，提醒主播以直播间页面或客服说明为准。

输出要求：
推荐回复必须适合主播直接口播。
每句话尽量短，单句不超过 25 个中文字符。
推荐回复控制在 1 到 2 句话内，总长度不超过 70 个中文字符。
推荐讲解重点控制在 3 到 5 个短词，不要写长句。"""


@dataclass(slots=True)
class AppConfig:
    """应用全局配置。

    所有配置项统一存放在此处，不要硬编码到其他模块。
    """

    # ---- 设备选择 ----
    camera_index: int = 0
    microphone_index: int = 0

    # ---- 摄像头参数 ----
    camera_width: int = 320
    camera_height: int = 240
    camera_fps: int = 60

    # ---- 麦克风参数 ----
    mic_sample_rate: int = 16000
    mic_block_size: int = 1600

    # ---- 语音识别与自然句切分 ----
    asr_model: str = "paraformer-zh-streaming"
    # 调试重点：自然语句结束停顿阈值。调小会更快换行和触发 LLM，调大会等待更完整的句子。
    speech_pause_threshold_ms: int = 1200
    # 默认不打印 ASR 原文；后续调试语音识别时可改为 true。
    debug_print_asr_text: bool = False

    # ---- 情绪模型 ----
    emotion_model_path: str = DEFAULT_EMOTION_MODEL_PATH

    # ---- Live2D 模型配置 ----
    model_name: str = "haru_ja"
    model_paths: dict[str, str] = field(default_factory=lambda: {"haru_ja": DEFAULT_MODEL_PATH})

    # ---- LLM 配置 ----
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""

    # ---- 观众评论 Prompt 配置 ----
    comment_prompt_mode: str = "course_qa"
    comment_course_prompt: str = DEFAULT_COURSE_QA_PROMPT
    comment_ecommerce_prompt: str = DEFAULT_ECOMMERCE_PROMPT
    comment_custom_prompt: str = ""
    comment_prompt_confirmed_mode: str = ""
    comment_prompt_confirmed_text: str = ""
    # 兼容旧版拆分字段，后续读取旧配置时仍可正常加载。
    comment_live_content: str = "虚拟形象智能驱动系统直播演示，重点展示摄像头、麦克风、FunASR、情绪理解、LLM 语义理解、Live2D 动作联动、B站评论接入和直播报告。"
    comment_host_persona: str = "课程项目演示主播，表达清晰、客观专业，面向老师和同学讲解系统能力。"
    comment_answer_boundary: str = "回答必须围绕本项目功能、演示场景和课程验收，不夸大未实现能力，不编造价格、商业承诺或外部平台功能。"

    # ---- 窗口状态 ----
    preview_visible: bool = False
    preview_width: int = 360
    preview_height: int = 640
    preview_always_on_top: bool = True

    # ---- 性能 ----
    visual_feature_fps: int = 30
    asr_refresh_ms: int = 200
    llm_min_interval_ms: int = 5000


def load_config() -> AppConfig:
    """从配置文件加载配置，文件不存在时返回默认值。"""
    if not CONFIG_FILE.exists():
        LOGGER.info("配置文件不存在，使用默认配置：%s", CONFIG_FILE)
        config = AppConfig()
        _load_llm_env_fallback(config)
        return config

    try:
        with CONFIG_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
        # 兼容旧版单模型路径配置
        if "model_path" in data and "model_paths" not in data:
            data["model_paths"] = {"haru_ja": data.pop("model_path")}
            data.setdefault("model_name", "haru_ja")
        config = AppConfig(**data)
        config.emotion_model_path = project_relative_path(config.emotion_model_path or DEFAULT_EMOTION_MODEL_PATH)
        _load_llm_env_fallback(config)

        # 验证当前选中模型路径是否存在
        current_model_path = get_model_path(config)
        if current_model_path and not resolve_project_path(current_model_path).exists():
            LOGGER.warning("模型路径无效：%s", current_model_path)
        if not resolve_project_path(config.emotion_model_path).exists():
            config.emotion_model_path = DEFAULT_EMOTION_MODEL_PATH
            LOGGER.warning("配置中的情绪模型路径无效，已回退到默认值：%s", config.emotion_model_path)
        LOGGER.info("已加载配置：%s", CONFIG_FILE)
        return config
    except (json.JSONDecodeError, TypeError) as exc:
        LOGGER.warning("配置文件解析失败，使用默认配置：%s", exc)
        return AppConfig()


def save_config(config: AppConfig) -> None:
    """将当前配置持久化到文件。"""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    config.emotion_model_path = project_relative_path(config.emotion_model_path or DEFAULT_EMOTION_MODEL_PATH)
    data = asdict(config)
    # API Key 只写入 .env，避免密钥进入仓库配置文件。
    data["llm_api_key"] = ""
    with CONFIG_FILE.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    LOGGER.info("配置已保存：%s", CONFIG_FILE)


def save_llm_env(config: AppConfig) -> None:
    """将 LLM 配置同步写入项目根目录 .env，不在日志中输出密钥。"""
    should_write = bool(config.llm_base_url or config.llm_api_key or config.llm_model or ENV_FILE.exists())
    if not should_write:
        return

    lines = [
        "# Live2D 虚拟形象智能驱动系统 — LLM 配置",
        "LLM_BASE_URL=" + config.llm_base_url.strip(),
        "LLM_API_KEY=" + config.llm_api_key.strip(),
        "LLM_MODEL=" + config.llm_model.strip(),
        "",
    ]
    ENV_FILE.write_text("\n".join(lines), encoding="utf-8")
    LOGGER.info("LLM 配置已同步到 .env：%s", ENV_FILE)


def normalize_comment_prompt_mode(mode: str) -> str:
    """把旧版 Prompt 模式兼容映射到当前三段切换模式。"""
    if mode in {"no_prompt", "none", "disabled"}:
        return "no_prompt"
    if mode in {"custom"}:
        return "custom"
    if mode in {"ecommerce", "ecommerce_sales"}:
        return "ecommerce"
    return "course_qa"


def get_comment_prompt_text(config: AppConfig) -> str:
    """根据当前 Prompt 模式读取完整提示词。"""
    mode = normalize_comment_prompt_mode(config.comment_prompt_mode)
    if mode == "no_prompt":
        return ""
    if mode == "ecommerce":
        return config.comment_ecommerce_prompt.strip() or DEFAULT_ECOMMERCE_PROMPT
    if mode == "custom":
        return config.comment_custom_prompt.strip()
    return config.comment_course_prompt.strip() or DEFAULT_COURSE_QA_PROMPT


def resolve_project_path(path_value: str | Path) -> Path:
    """把配置中的项目相对路径解析为绝对路径。"""
    path = Path(path_value)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def get_model_path(config: AppConfig) -> str:
    """根据 model_name 从 model_paths 字典中获取当前模型路径。"""
    return config.model_paths.get(config.model_name, DEFAULT_MODEL_PATH)


def project_relative_path(path_value: str | Path) -> str:
    """把路径转成相对于项目根目录的配置值。"""
    path = Path(path_value)
    if not path.is_absolute():
        return path.as_posix()

    try:
        return path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        # 不在项目根目录下的外部路径保留原值，避免误改用户自定义路径。
        return str(path)


def _load_llm_env_fallback(config: AppConfig) -> None:
    """配置文件缺少 LLM 字段时，从 .env 回填到 AppConfig。"""
    if config.llm_base_url and config.llm_api_key and config.llm_model:
        return
    if not ENV_FILE.exists():
        return

    env_values: dict[str, str] = {}
    with ENV_FILE.open("r", encoding="utf-8") as env_file:
        for line in env_file:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, _, value = stripped.partition("=")
            env_values[key.strip()] = value.strip()

    config.llm_base_url = config.llm_base_url or env_values.get("LLM_BASE_URL", "")
    config.llm_api_key = config.llm_api_key or env_values.get("LLM_API_KEY", "")
    config.llm_model = config.llm_model or env_values.get("LLM_MODEL", "")


def load_param_mappings(model_name: str) -> dict[str, str]:
    """加载指定模型的参数 ID 映射表。

    不同 Live2D 模型可能使用不同的参数命名规范（如 haru_ja 的 PARAM_ANGLE_X
    与 Cubism 5.x 标准的 ParamAngleX），通过映射表统一翻译为代码内部使用的 ID。

    返回 {代码内部ID: 模型实际ID} 的映射字典。
    """
    if not PARAM_MAPPINGS_PATH.exists():
        LOGGER.info("参数映射文件不存在，使用默认映射：%s", PARAM_MAPPINGS_PATH)
        return {}

    try:
        with PARAM_MAPPINGS_PATH.open("r", encoding="utf-8") as f:
            all_mappings: dict[str, dict[str, str]] = json.load(f)
        mappings = all_mappings.get(model_name, {})
        if not mappings:
            LOGGER.info("模型 '%s' 未在参数映射中配置，将直接使用代码内部 ID", model_name)
        return mappings
    except (json.JSONDecodeError, TypeError) as exc:
        LOGGER.warning("参数映射文件解析失败：%s", exc)
        return {}
