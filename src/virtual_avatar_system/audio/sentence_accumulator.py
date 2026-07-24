"""ASR 自然句累积工具。"""

from __future__ import annotations

from dataclasses import dataclass

from virtual_avatar_system.audio.text_stabilizer import TextStabilizer


@dataclass(slots=True)
class SentenceAccumulator:
    """把 ASR 输出合并成一整句自然语句。

    FunASR 流式结果可能有两种形态：
    - 累计式：你是 -> 你是个 -> 你是个傻逼吗
    - 增量式：你是 -> 个傻 -> 逼吗

    LLM 只能消费完整自然句，所以这里统一合并成当前句子的完整文本。
    """

    _text: str = ""
    _last_asr_text: str = ""

    @property
    def text(self) -> str:
        """当前已累积的自然句文本。"""
        return self._text

    def reset(self) -> None:
        """重置当前自然句。"""
        self._text = ""
        self._last_asr_text = ""

    def update(self, asr_text: str) -> str:
        """合并一条 ASR 文本并返回当前完整自然句。"""
        normalized = TextStabilizer.normalize(asr_text)
        if not normalized:
            return self._text

        if not self._text:
            self._text = normalized
        elif normalized == self._last_asr_text or self._text.endswith(normalized):
            # 重复片段不刷新整句，避免停顿检测被同一结果反复推迟。
            pass
        elif normalized.startswith(self._text):
            # ASR 返回完整累计句子，直接用更完整的新文本替换。
            self._text = normalized
        elif self._last_asr_text and normalized.startswith(self._last_asr_text):
            # ASR 返回相对上一条更长的累计文本，只追加新增部分。
            delta = normalized[len(self._last_asr_text):]
            self._text = _append_with_overlap(self._text, delta)
        elif _should_replace_with_correction(self._text, normalized):
            # ASR 对前文做了明显改写，优先相信更长的新句子。
            self._text = normalized
        else:
            # ASR 返回增量片段，按最大重叠合并到当前句末。
            self._text = _append_with_overlap(self._text, normalized)

        self._last_asr_text = normalized
        return self._text


def _append_with_overlap(base: str, addition: str) -> str:
    """把片段追加到句末，并去掉首尾重叠部分。"""
    if not addition:
        return base
    if not base:
        return addition

    max_overlap = min(len(base), len(addition))
    for size in range(max_overlap, 0, -1):
        if base.endswith(addition[:size]):
            return base + addition[size:]
    return base + addition


def _should_replace_with_correction(current: str, candidate: str) -> bool:
    """判断 candidate 是否像 ASR 对当前句子的完整修正。"""
    if len(candidate) <= len(current):
        return False

    common_prefix = 0
    for left, right in zip(current, candidate, strict=False):
        if left != right:
            break
        common_prefix += 1

    # 至少共享两个开头字符，通常说明新结果是完整句改写，而不是一个独立增量片段。
    return common_prefix >= 2
