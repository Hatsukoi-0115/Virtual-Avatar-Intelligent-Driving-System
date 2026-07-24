"""中文流式分词工具。"""

from __future__ import annotations

import re
from dataclasses import dataclass

_PUNCTUATION_RE = re.compile(r"^[，。！？、,.!?；;：:\s]+$")


@dataclass(slots=True)
class ChineseTokenStream:
    """把持续增长的 ASR 文本切成新增词。"""

    _last_text: str = ""

    def reset(self) -> None:
        """重置当前自然句的分词位置。"""
        self._last_text = ""

    def consume(self, text: str) -> list[str]:
        """返回相对上次调用新增的词。"""
        normalized = text.strip()
        if not normalized:
            return []

        if normalized.startswith(self._last_text):
            delta = normalized[len(self._last_text):]
        else:
            # ASR 有时会重写整段文本；无法确定差异时只消费当前完整文本。
            delta = normalized

        self._last_text = normalized
        return [token for token in segment_chinese(delta) if token and not _PUNCTUATION_RE.match(token)]


def segment_chinese(text: str) -> list[str]:
    """中文分词，优先使用 jieba，缺失时回退到轻量规则切分。"""
    cleaned = text.strip()
    if not cleaned:
        return []

    try:
        import jieba

        return [token.strip() for token in jieba.cut(cleaned) if token.strip()]
    except Exception:  # noqa: BLE001
        return _fallback_segment(cleaned)


def _fallback_segment(text: str) -> list[str]:
    """无 jieba 时的保守切分，保证模块仍可独立运行。"""
    tokens: list[str] = []
    buffer = ""
    for char in text:
        if _PUNCTUATION_RE.match(char):
            if buffer:
                tokens.append(buffer)
                buffer = ""
            tokens.append(char)
        elif "\u4e00" <= char <= "\u9fff":
            if buffer:
                tokens.append(buffer)
                buffer = ""
            tokens.append(char)
        else:
            buffer += char
    if buffer:
        tokens.append(buffer)
    return tokens
