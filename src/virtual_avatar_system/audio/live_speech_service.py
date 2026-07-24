"""主程序使用的直播语音、情绪和语义服务。"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable

from virtual_avatar_system.audio.funasr_streaming import FunAsrConfig, FunAsrStreamingRecognizer
from virtual_avatar_system.audio.sentence_accumulator import SentenceAccumulator
from virtual_avatar_system.audio.source import AudioStreamConfig, AudioStreamSource
from virtual_avatar_system.config.app_config import AppConfig, resolve_project_path
from virtual_avatar_system.emotion.classifier import EmotionClassifier, EmotionClassifierConfig, emotion_to_expression
from virtual_avatar_system.llm.semantic import SemanticInterpreter, SemanticInterpreterConfig

LOGGER = logging.getLogger(__name__)

# 情绪分类去抖参数
_EMOTION_MIN_CHARS = 4
_EMOTION_MIN_NEW_CHARS = 3
_EMOTION_MIN_INTERVAL_MS = 500
_EMOTION_CONFIDENCE_THRESHOLD = 0.5


@dataclass(slots=True)
class LiveSpeechServiceConfig:
    """直播语音服务配置。"""

    audio: AudioStreamConfig
    asr: FunAsrConfig
    emotion: EmotionClassifierConfig
    llm: SemanticInterpreterConfig
    # 调试重置点：自然语句结束停顿阈值。调小会更快触发换行和 LLM，调大会等待更完整的句子。
    pause_threshold_ms: int = 1200
    debug_print_asr_text: bool = False
    # 情绪分类置信度阈值，低于此值的结果被舍弃，不输出
    emotion_confidence_threshold: float = _EMOTION_CONFIDENCE_THRESHOLD

    @classmethod
    def from_app_config(cls, app_config: AppConfig) -> "LiveSpeechServiceConfig":
        """从全局应用配置转换出 C 模块运行配置。"""
        return cls(
            audio=AudioStreamConfig(
                device_index=app_config.microphone_index,
                sample_rate=app_config.mic_sample_rate,
                block_size=app_config.mic_block_size,
            ),
            asr=FunAsrConfig(model=app_config.asr_model, disable_pbar=True),
            emotion=EmotionClassifierConfig(model_path=str(resolve_project_path(app_config.emotion_model_path))),
            llm=SemanticInterpreterConfig.from_sources(
                base_url=app_config.llm_base_url,
                api_key=app_config.llm_api_key,
                model=app_config.llm_model,
                min_interval_ms=app_config.llm_min_interval_ms,
            ),
            pause_threshold_ms=app_config.speech_pause_threshold_ms,
            debug_print_asr_text=app_config.debug_print_asr_text,
        )


class LiveSpeechUnderstandingService:
    """在后台线程中运行麦克风风、FunASR、情绪分类和 LLM 语义理解。"""

    def __init__(self, config: LiveSpeechServiceConfig) -> None:
        self.config = config
        self.audio_source = AudioStreamSource(config.audio)
        self.recognizer = FunAsrStreamingRecognizer(config.asr)
        self.emotion_classifier = EmotionClassifier(config.emotion)
        self.semantic_interpreter = SemanticInterpreter(config.llm)
        self._sentence_accumulator = SentenceAccumulator()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_text_at = 0.0
        self._sentence_text = ""
        self._sentence_closed = True
        # 情绪分类去抖状态
        self._last_emotion_chars = 0
        self._last_emotion_at = 0.0
        self._emotion_threshold = config.emotion_confidence_threshold
        # 情绪→表情回调，主线程注册后在此触发
        self._on_emotion: Callable[[str, float], None] | None = None

    def on_emotion(self, callback: Callable[[str, float], None]) -> None:
        """注册情绪→表情回调，参数为 (表情ID, 置信度)。"""
        self._on_emotion = callback

    @property
    def running(self) -> bool:
        """服务是否正在运行。"""
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        """启动后台语音理解链路。"""
        if self.running:
            return

        self._stop_event.clear()
        self._reset_sentence_state()
        self.audio_source.start()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="live-speech-understanding",
            daemon=True,
        )
        self._thread.start()
        print("[C] 语音/情绪/LLM 链路已启动", flush=True)

    def stop(self) -> None:
        """停止后台线程并释放识别模块。"""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        self.audio_source.stop()
        self.audio_source.clear()
        self.recognizer.close()
        self._thread = None
        print("[C] 语音/情绪/LLM 链路已停止", flush=True)

    def _run_loop(self) -> None:
        """持续读取音频块并输出情绪与语义结果。"""
        try:
            self.recognizer.load()
            while not self._stop_event.is_set():
                chunk = self.audio_source.pull(timeout=0.2)
                if chunk is None:
                    self._check_sentence_pause()
                    continue

                asr_result = self.recognizer.transcribe(chunk, is_final=False)
                if asr_result.error:
                    LOGGER.warning("ASR 结果异常：%s", asr_result.error)
                    continue

                if self.config.debug_print_asr_text and asr_result.text:
                    print(f"[ASR] {asr_result.text}", flush=True)

                self._consume_asr_text(asr_result.text)
                self._check_sentence_pause()
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("直播语音理解链路异常：%s", exc)
        finally:
            self.audio_source.stop()

    def _consume_asr_text(self, text: str) -> None:
        """把新增 ASR 文本累积到句子缓冲，满足条件时做整句情绪分类。"""
        normalized = text.strip()
        if not normalized:
            return

        previous_sentence = self._sentence_accumulator.text
        current_sentence = self._sentence_accumulator.update(normalized)
        if not current_sentence or current_sentence == previous_sentence:
            return

        self._last_text_at = time.monotonic()
        self._sentence_text = current_sentence
        self._sentence_closed = False

        if self.config.debug_print_asr_text:
            print(f"[ASR_FULL] {current_sentence}", flush=True)

        # 整句情绪分类（带去抖），不再逐词分类
        self._maybe_classify_emotion(current_sentence)

    def _check_sentence_pause(self) -> None:
        """检测自然句停顿，达到阈值后触发最终情绪分类和 LLM。"""
        if self._sentence_closed or not self._sentence_text or self._last_text_at <= 0:
            return

        elapsed_ms = (time.monotonic() - self._last_text_at) * 1000
        if elapsed_ms < self.config.pause_threshold_ms:
            return

        sentence = self._sentence_accumulator.text.strip()
        self._sentence_closed = True
        self.recognizer.reset()

        if sentence:
            # 句子结束时用完整文本做最终情绪分类
            self._do_classify_emotion(sentence, tag="final")

            # 自然句结束后把完整句子交给 LLM；强制绕过低频缓存
            semantic = self.semantic_interpreter.interpret(sentence, force=True)
            if semantic.error:
                print(f"\n[LLM] 句子={sentence} 标签=neutral 错误={semantic.error}\n", flush=True)
            else:
                print(
                    f"\n[LLM] 句子={sentence} 标签={semantic.label} "
                    f"置信度={semantic.confidence:.2f} 摘要={semantic.summary}\n",
                    flush=True,
                )
        self._reset_sentence_state()

    def _maybe_classify_emotion(self, sentence: str) -> None:
        """对累积中的句子做去抖情绪分类。

        策略：
        - 句子不足 _EMOTION_MIN_CHARS 字时跳过，避免短片段低置信度干扰
        - 距上次分类新增不足 _EMOTION_MIN_NEW_CHARS 字时跳过，减少模型调用频率
        - 距上次分类不足 _EMOTION_MIN_INTERVAL_MS 时跳过，防止高频触发
        """
        if len(sentence) < _EMOTION_MIN_CHARS:
            return

        new_chars = len(sentence) - self._last_emotion_chars
        if new_chars < _EMOTION_MIN_NEW_CHARS:
            return

        now = time.monotonic()
        if (now - self._last_emotion_at) * 1000 < _EMOTION_MIN_INTERVAL_MS:
            return

        self._do_classify_emotion(sentence, tag="stream")

    def _do_classify_emotion(self, sentence: str, tag: str = "") -> None:
        """执行情绪分类并输出结果，更新去抖状态。"""
        emotion = self.emotion_classifier.classify(sentence)

        # 置信度低于阈值时舍弃，不输出低质量分类结果
        if emotion.confidence < self._emotion_threshold:
            LOGGER.debug(
                "情绪分类置信度 %.2f 低于阈值 %.2f，已舍弃：句子=%s",
                emotion.confidence,
                self._emotion_threshold,
                sentence,
            )
            self._last_emotion_chars = len(sentence)
            self._last_emotion_at = time.monotonic()
            return

        prefix = f"[Emotion/{tag}]" if tag else "[Emotion]"
        print(
            f'{prefix} 句子="{sentence}" 标签={emotion.label} '
            f"置信度={emotion.confidence:.2f} 来源={emotion.source}",
            flush=True,
        )
        self._last_emotion_chars = len(sentence)
        self._last_emotion_at = time.monotonic()

        # 通过回调把情绪标签映射为 Live2D 表情 ID，通知主线程
        expression_id = emotion_to_expression(emotion.label)
        if self._on_emotion is not None:
            try:
                self._on_emotion(expression_id, emotion.confidence)
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("情绪回调异常：%s", exc)

    def _reset_sentence_state(self) -> None:
        """重置自然句缓存和情绪去抖状态。"""
        self._last_text_at = 0.0
        self._sentence_text = ""
        self._sentence_closed = True
        self._sentence_accumulator.reset()
        self._last_emotion_chars = 0
        self._last_emotion_at = 0.0


def main() -> None:
    """允许 C 链路独立运行，方便调试麦克风风、FunASR、情绪和 LLM。"""
    import argparse

    from virtual_avatar_system.config.app_config import load_config

    parser = argparse.ArgumentParser(description="直播语音理解链路调试")
    parser.add_argument("--duration", type=float, default=0.0, help="运行秒数，0 表示一直运行到 Ctrl+C")
    parser.add_argument("--debug-asr", action="store_true", help="同时打印 ASR 原文，默认关闭")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    app_config = load_config()
    service_config = LiveSpeechServiceConfig.from_app_config(app_config)
    service_config.debug_print_asr_text = args.debug_asr
    service = LiveSpeechUnderstandingService(service_config)

    service.start()
    started_at = time.monotonic()
    try:
        while args.duration <= 0 or time.monotonic() - started_at < args.duration:
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    finally:
        service.stop()


if __name__ == "__main__":
    main()
