"""FunASR 流式识别封装。"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Final

from virtual_avatar_system.audio.text_stabilizer import TextStabilizer
from virtual_avatar_system.audio.types import AsrResult, AudioChunk

LOGGER = logging.getLogger(__name__)

DEFAULT_STREAM_CONFIG: Final[dict[str, int | list[int]]] = {
    "chunk_size": [0, 10, 5],
    "encoder_chunk_look_back": 4,
    "decoder_chunk_look_back": 1,
}


@dataclass(slots=True)
class FunAsrConfig:
    """FunASR 流式模型配置。"""

    model: str = "paraformer-zh-streaming"
    stream_config: dict[str, int | list[int]] = field(default_factory=lambda: dict(DEFAULT_STREAM_CONFIG))
    disable_update: bool = True
    disable_pbar: bool = True


class FunAsrStreamingRecognizer:
    """把音频块转换成增量 ASR 文本。"""

    def __init__(self, config: FunAsrConfig | None = None, stabilizer: TextStabilizer | None = None) -> None:
        self.config = config or FunAsrConfig()
        self.stabilizer = stabilizer or TextStabilizer()
        self._model: Any | None = None
        self._cache: dict[str, Any] = {}

    def load(self) -> None:
        """加载 FunASR 模型。"""
        if self._model is not None:
            return

        # FunASR 模型加载较重，延迟到运行期，避免 UI 启动和测试导入被拖慢。
        from funasr import AutoModel

        LOGGER.info("加载 FunASR 流式模型：%s", self.config.model)
        self._model = AutoModel(
            model=self.config.model,
            disable_update=self.config.disable_update,
            disable_pbar=self.config.disable_pbar,
        )

    def reset(self) -> None:
        """重置流式缓存，用于重新开始一段识别。"""
        self._cache.clear()
        self.stabilizer = TextStabilizer(
            min_stable_chars=self.stabilizer.min_stable_chars,
            stable_hold_ms=self.stabilizer.stable_hold_ms,
        )

    def close(self) -> None:
        """释放识别器持有的模型引用和流式缓存。"""
        self._model = None
        self._cache.clear()

    def transcribe(self, chunk: AudioChunk, is_final: bool = False) -> AsrResult:
        """识别单个音频块。"""
        if self._model is None:
            self.load()

        assert self._model is not None
        started_at = time.perf_counter()
        timestamp = time.time()

        try:
            result = self._model.generate(
                chunk.samples,
                cache=self._cache,
                is_final=is_final,
                **self.config.stream_config,
            )
            latency_ms = (time.perf_counter() - started_at) * 1000
            text = self._extract_text(result)
            stable_text = self.stabilizer.update(text, is_final=is_final)
            return AsrResult(
                text=text,
                stable_text=stable_text,
                is_final=is_final,
                timestamp=timestamp,
                latency_ms=latency_ms,
            )
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("FunASR 识别失败")
            return AsrResult(
                text="",
                stable_text="",
                is_final=is_final,
                timestamp=timestamp,
                latency_ms=(time.perf_counter() - started_at) * 1000,
                error=f"{type(exc).__name__}: {exc}",
            )

    @staticmethod
    def _extract_text(result: object) -> str:
        """从 FunASR 返回结构里提取文本。"""
        if not result:
            return ""
        if isinstance(result, list) and result:
            first = result[0]
            if isinstance(first, dict):
                return str(first.get("text", "")).strip()
        if isinstance(result, dict):
            return str(result.get("text", "")).strip()
        return str(result).strip()
