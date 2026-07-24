"""ASR 文本断句、去噪和稳定化。"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass


_SPACE_RE = re.compile(r"\s+")
_ENDING_PUNCTUATION = ("。", "！", "？", "!", "?", ".", "\n")


@dataclass(slots=True)
class TextStabilizer:
    """把 FunASR 增量文本整理成上层可消费的稳定文本。"""

    min_stable_chars: int = 4
    stable_hold_ms: int = 600
    _last_text: str = ""
    _last_changed_at: float = 0.0
    _last_stable_text: str = ""

    def update(self, text: str, is_final: bool = False, now: float | None = None) -> str:
        """更新增量文本，返回当前可确认的稳定文本。"""
        current = self.normalize(text)
        if not current:
            return self._last_stable_text

        timestamp = now if now is not None else time.monotonic()
        if current != self._last_text:
            self._last_text = current
            self._last_changed_at = timestamp

        held_long_enough = (timestamp - self._last_changed_at) * 1000 >= self.stable_hold_ms
        has_sentence_boundary = current.endswith(_ENDING_PUNCTUATION)
        long_enough = len(current) >= self.min_stable_chars

        # 最终帧、明显断句或短时间内不再变化，都可以交给情绪和语义层。
        if is_final or (long_enough and (has_sentence_boundary or held_long_enough)):
            self._last_stable_text = current

        return self._last_stable_text

    @staticmethod
    def normalize(text: str) -> str:
        """去掉多余空白和常见占位符。"""
        normalized = _SPACE_RE.sub("", text or "")
        for noise in ("<unk>", "[unk]", "嗯嗯", "呃呃"):
            normalized = normalized.replace(noise, "")
        return normalized.strip()
