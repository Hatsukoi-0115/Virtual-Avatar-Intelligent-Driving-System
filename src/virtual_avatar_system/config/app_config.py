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
DEFAULT_MODEL_PATH: Final[Path] = PROJECT_ROOT / "models" / "haru_ja" / "runtime" / "haru.model3.json"


@dataclass(slots=True)
class AppConfig:
    """应用全局配置。

    所有配置项统一存放在此处，不要硬编码到其他模块。
    """

    # ---- 设备选择 ----
    camera_index: int = 0
    microphone_index: int = 0

    # ---- 摄像头参数 ----
    camera_width: int = 1280
    camera_height: int = 720
    camera_fps: int = 30

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
    emotion_model_path: str = str(PROJECT_ROOT / "models" / "hf_cache" / "Johnson8187__Chinese-Emotion-Small")

    # ---- Live2D 模型路径 ----
    model_path: str = str(DEFAULT_MODEL_PATH)

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
        return AppConfig()

    try:
        with CONFIG_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
        config = AppConfig(**data)
        if not config.model_path.strip() or not Path(config.model_path).exists():
            config.model_path = str(DEFAULT_MODEL_PATH)
            LOGGER.warning("配置中的模型路径无效，已回退到默认值：%s", config.model_path)
        LOGGER.info("已加载配置：%s", CONFIG_FILE)
        return config
    except (json.JSONDecodeError, TypeError) as exc:
        LOGGER.warning("配置文件解析失败，使用默认配置：%s", exc)
        return AppConfig()


def save_config(config: AppConfig) -> None:
    """将当前配置持久化到文件。"""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with CONFIG_FILE.open("w", encoding="utf-8") as f:
        json.dump(asdict(config), f, indent=2, ensure_ascii=False)
    LOGGER.info("配置已保存：%s", CONFIG_FILE)
