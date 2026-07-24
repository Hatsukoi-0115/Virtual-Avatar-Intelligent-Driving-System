"""语音、情绪和语义联动管线。"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from virtual_avatar_system.audio.funasr_streaming import FunAsrStreamingRecognizer
from virtual_avatar_system.audio.types import AsrResult, AudioChunk
from virtual_avatar_system.emotion.classifier import EmotionClassifier
from virtual_avatar_system.emotion.types import EmotionResult
from virtual_avatar_system.llm.semantic import SemanticInterpreter, SemanticResult

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class SpeechUnderstandingResult:
    """C 模块统一输出，供 Avatar Controller 消费。"""

    asr: AsrResult
    emotion: EmotionResult | None
    semantic: SemanticResult | None
    timestamp: float


class SpeechUnderstandingPipeline:
    """串联 ASR、情绪分类和低频语义理解。"""

    def __init__(
        self,
        recognizer: FunAsrStreamingRecognizer,
        emotion_classifier: EmotionClassifier,
        semantic_interpreter: SemanticInterpreter | None = None,
    ) -> None:
        self.recognizer = recognizer
        self.emotion_classifier = emotion_classifier
        self.semantic_interpreter = semantic_interpreter

    def process(self, chunk: AudioChunk, is_final: bool = False) -> SpeechUnderstandingResult:
        """处理单个音频块，尽可能输出结构化语音理解结果。"""
        asr_result = self.recognizer.transcribe(chunk, is_final=is_final)
        emotion_result: EmotionResult | None = None
        semantic_result: SemanticResult | None = None

        if asr_result.error:
            return SpeechUnderstandingResult(asr=asr_result, emotion=None, semantic=None, timestamp=time.time())

        # 只有稳定文本才进入情绪和语义层，避免碎片化 ASR 结果造成表情抖动。
        if asr_result.stable_text:
            emotion_result = self.emotion_classifier.classify(asr_result.stable_text)
            if self.semantic_interpreter is not None:
                semantic_result = self.semantic_interpreter.interpret(
                    asr_result.stable_text,
                    context={
                        "emotion": emotion_result.label,
                        "emotion_confidence": emotion_result.confidence,
                    },
                )

        return SpeechUnderstandingResult(
            asr=asr_result,
            emotion=emotion_result,
            semantic=semantic_result,
            timestamp=time.time(),
        )
