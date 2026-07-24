"""麦克风输入采集与缓存。"""

from __future__ import annotations

import contextlib
import logging
import queue
import time
from dataclasses import dataclass
from typing import Any

import numpy as np

from virtual_avatar_system.audio.types import AudioChunk

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class AudioStreamConfig:
    """麦克风采集配置。"""

    device_index: int | None = None
    sample_rate: int = 16000
    channels: int = 1
    block_size: int = 1600
    queue_size: int = 200


class AudioStreamSource:
    """麦克风输入源，负责采集、缓存和丢弃过期音频块。"""

    def __init__(self, config: AudioStreamConfig | None = None) -> None:
        self.config = config or AudioStreamConfig()
        self._queue: queue.Queue[AudioChunk] = queue.Queue(maxsize=self.config.queue_size)
        self._stream: Any | None = None
        self._running = False

    @property
    def running(self) -> bool:
        """当前音频流是否已经启动。"""
        return self._running

    def start(self) -> None:
        """启动麦克风输入流。"""
        if self._running:
            return

        # sounddevice 初始化可能访问硬件，延迟导入方便单元测试和无设备环境加载模块。
        import sounddevice as sd

        self._stream = sd.InputStream(
            samplerate=self.config.sample_rate,
            channels=self.config.channels,
            dtype="float32",
            blocksize=self.config.block_size,
            device=self.config.device_index,
            callback=self._on_audio,
        )
        self._stream.start()
        self._running = True
        LOGGER.info("麦克风采集已启动：device=%s sample_rate=%s", self.config.device_index, self.config.sample_rate)

    def stop(self) -> None:
        """停止麦克风输入流并释放设备。"""
        if self._stream is not None:
            with contextlib.suppress(Exception):
                self._stream.stop()
            with contextlib.suppress(Exception):
                self._stream.close()
        self._stream = None
        self._running = False
        LOGGER.info("麦克风采集已停止")

    def pull(self, timeout: float = 0.2) -> AudioChunk | None:
        """拉取一段音频；超时返回 None。"""
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def clear(self) -> None:
        """清空缓存，通常用于停止或切换设备前。"""
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

    def _on_audio(self, indata, frames: int, time_info, status) -> None:
        """sounddevice 回调：只做轻量复制和入队，避免阻塞音频线程。"""
        if status:
            LOGGER.warning("音频输入状态：%s", status)
        if frames <= 0:
            return

        samples = np.asarray(indata[:, 0], dtype=np.float32).copy()
        chunk = AudioChunk(
            samples=samples,
            sample_rate=self.config.sample_rate,
            timestamp=time.time(),
            duration_ms=frames / self.config.sample_rate * 1000,
            device_index=self.config.device_index,
        )

        # 队列满时丢弃最旧数据，保证 ASR 消费的是接近实时的音频。
        try:
            self._queue.put_nowait(chunk)
        except queue.Full:
            with contextlib.suppress(queue.Empty):
                self._queue.get_nowait()
            with contextlib.suppress(queue.Full):
                self._queue.put_nowait(chunk)
