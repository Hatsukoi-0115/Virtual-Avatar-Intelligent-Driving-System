"""情绪链路统一数据结构。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class EmotionResult:
    """情绪分类输出。"""

    label: str
    confidence: float
    source: str
    timestamp: float
    raw_label: str = ""
    metadata: dict[str, str] = field(default_factory=dict)
