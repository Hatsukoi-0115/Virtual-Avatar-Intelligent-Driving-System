"""语音链路统一数据结构。"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass(slots=True)
class AudioChunk:
    """一段来自麦克风的音频数据。"""

    samples: np.ndarray
    sample_rate: int
    timestamp: float
    duration_ms: float
    device_index: int | None = None
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class AsrResult:
    """ASR 输出结果，区分增量文本和稳定文本。"""

    text: str
    stable_text: str
    is_final: bool
    timestamp: float
    latency_ms: float = 0.0
    source: str = "funasr"
    error: str = ""
