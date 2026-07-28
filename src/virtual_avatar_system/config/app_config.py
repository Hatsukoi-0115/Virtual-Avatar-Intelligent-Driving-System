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
DEFAULT_MODEL_PATH: Final[str] = "models/haru_ja/runtime/haru.model3.json"
DEFAULT_EMOTION_MODEL_PATH: Final[str] = "models/hf_cache/Johnson8187__Chinese-Emotion-Small"


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

    # ---- 轻量实时变声器 ----
    voice_changer_enabled: bool = False
    voice_output_device_index: int | None = None
    voice_output_sample_rate: int = 48000
    voice_pitch_semitones: int = 4
    voice_reverb_percent: int = 8
    voice_wet_percent: int = 100
    voice_output_gain_percent: int = 80

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
