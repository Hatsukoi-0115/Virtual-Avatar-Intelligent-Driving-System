"""轻量实时变声器服务。

职责：
- 接收麦克风音频块
- 执行低延迟 DSP 变声处理
- 将处理后的音频输出到观众侧虚拟声卡，或在演示模式下输出到本机监听设备
"""

from __future__ import annotations

import contextlib
import logging
import queue
import threading
from collections import deque
from dataclasses import dataclass
from typing import Any

import numpy as np

from virtual_avatar_system.audio.types import AudioChunk

LOGGER = logging.getLogger(__name__)


def list_available_audio_output_devices() -> list[tuple[int, str]]:
    """扫描本机可用的音频输出设备。"""
    import sounddevice as sd

    devices: list[tuple[int, str]] = []
    for index, device in enumerate(sd.query_devices()):
        if int(device.get("max_output_channels", 0)) <= 0:
            continue
        name = str(device.get("name", f"输出设备 {index}")).strip() or f"输出设备 {index}"
        devices.append((index, name))
    return devices


@dataclass(slots=True)
class VoiceChangerConfig:
    """变声器运行配置。"""

    enabled: bool = False
    demo_monitor_enabled: bool = False
    output_device_index: int | None = None
    output_sample_rate: int = 48000
    block_size: int = 1600
    pitch_semitones: int = 0
    reverb_mix: float = 0.08
    wet_mix: float = 1.0
    output_gain: float = 0.8
    queue_size: int = 80


class LightweightVoiceProcessor:
    """低延迟轻量变声处理器。"""

    def __init__(self, config: VoiceChangerConfig) -> None:
        self.config = config
        self._delay_sample_rate = config.output_sample_rate
        self._delay_buffer = np.zeros(max(1, int(config.output_sample_rate * 0.09)), dtype=np.float32)
        self._delay_index = 0

    def update_config(self, config: VoiceChangerConfig) -> None:
        """更新处理参数，保留已有混响缓存以减少运行中调参的断裂感。"""
        old_sample_rate = self.config.output_sample_rate
        self.config = config
        if config.output_sample_rate != old_sample_rate:
            self._delay_sample_rate = config.output_sample_rate
            self._delay_buffer = np.zeros(max(1, int(config.output_sample_rate * 0.09)), dtype=np.float32)
            self._delay_index = 0

    def process(self, chunk: AudioChunk) -> np.ndarray:
        """处理单个音频块，返回单声道 float32 音频。"""
        samples = np.asarray(chunk.samples, dtype=np.float32)
        if samples.size == 0:
            return samples

        self._ensure_delay_buffer(chunk.sample_rate)
        # 先清理异常采样，避免后续音频设备收到 NaN 或无穷值后爆音。
        cleaned = np.nan_to_num(samples, nan=0.0, posinf=0.0, neginf=0.0)
        pitched = self._pitch_shift(cleaned, self.config.pitch_semitones)
        reverbed = self._apply_reverb(pitched, self.config.reverb_mix)
        mixed = cleaned * (1.0 - self.config.wet_mix) + reverbed * self.config.wet_mix
        gained = mixed * self.config.output_gain

        # 轻量软限幅，控制音量峰值，避免变声后输出破音。
        limited = np.tanh(gained * 1.2) / 1.2
        return np.asarray(limited, dtype=np.float32)

    def _ensure_delay_buffer(self, sample_rate: int) -> None:
        """根据输入采样率调整混响延迟缓存。"""
        if sample_rate == self._delay_sample_rate:
            return
        self._delay_sample_rate = sample_rate
        self._delay_buffer = np.zeros(max(1, int(sample_rate * 0.09)), dtype=np.float32)
        self._delay_index = 0

    def _pitch_shift(self, samples: np.ndarray, semitones: int) -> np.ndarray:
        """使用插值重采样做轻量音高变化。"""
        if semitones == 0 or samples.size < 4:
            return samples.copy()

        factor = 2 ** (semitones / 12)
        source_positions = np.arange(samples.size, dtype=np.float32) * factor
        source_positions %= max(1, samples.size - 1)
        base_positions = np.arange(samples.size, dtype=np.float32)
        shifted = np.interp(source_positions, base_positions, samples)
        return np.asarray(shifted, dtype=np.float32)

    def _apply_reverb(self, samples: np.ndarray, mix: float) -> np.ndarray:
        """加入一个短延迟反馈，形成最小可用的空间感。"""
        if mix <= 0 or samples.size == 0:
            return samples.copy()

        output = samples.copy()
        feedback = 0.35
        for index, sample in enumerate(samples):
            delayed = self._delay_buffer[self._delay_index]
            output[index] = sample * (1.0 - mix) + delayed * mix
            self._delay_buffer[self._delay_index] = sample + delayed * feedback
            self._delay_index = (self._delay_index + 1) % self._delay_buffer.size
        return output


class RealtimeVoiceChangerService:
    """实时变声输出服务。"""

    def __init__(self, config: VoiceChangerConfig) -> None:
        self.config = config
        self.processor = LightweightVoiceProcessor(config)
        self._input_queue: queue.Queue[AudioChunk] = queue.Queue(maxsize=config.queue_size)
        self._buffer: deque[np.ndarray] = deque()
        self._buffer_offset = 0
        self._buffer_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._stream: Any | None = None
        self._running = False
        self._config_lock = threading.Lock()
        self._output_channels = 1

    @property
    def running(self) -> bool:
        """当前变声器是否正在运行。"""
        return self._running

    def update_config(self, config: VoiceChangerConfig) -> None:
        """运行中更新变声器配置。"""
        with self._config_lock:
            old_config = self.config
            was_enabled = self.config.enabled
            self.config = config
            self.processor.update_config(config)

        if self._running and not config.enabled:
            # 运行中关闭变声器时，只释放输出链路，不影响麦克风和 ASR 主链路。
            self.stop()
            return

        if not self._running and config.enabled:
            # 运行中重新启用变声器时，尝试打开输出设备；失败交给上层降级提示。
            self.start()
            return

        if self._running and was_enabled and config.enabled:
            if self._should_restart_output(old_config, config):
                # 输出目标或流格式变化时需要重启 PortAudio 流，否则声音仍会留在旧设备。
                self.stop()
                self.start()
                return
            LOGGER.info(
                "实时变声器参数已更新：pitch=%s reverb=%.2f wet=%.2f gain=%.2f",
                config.pitch_semitones,
                config.reverb_mix,
                config.wet_mix,
                config.output_gain,
            )

    def start(self) -> None:
        """启动变声器输出流。"""
        with self._config_lock:
            config = self.config
        if not config.enabled or self._running:
            return
        output_device_index = self._resolve_effective_output_device(config)
        if output_device_index is None and not config.demo_monitor_enabled:
            raise RuntimeError("未选择观众输出设备，请选择虚拟声卡或开启演示监听")

        import sounddevice as sd

        try:
            self._stop_event.clear()
            self._clear_buffers()
            self._output_channels = self._resolve_output_channels(sd, output_device_index)
            self._stream = sd.OutputStream(
                samplerate=config.output_sample_rate,
                channels=self._output_channels,
                dtype="float32",
                blocksize=config.block_size,
                device=output_device_index,
                callback=self._on_output,
            )
            self._stream.start()
            self._thread = threading.Thread(
                target=self._run_loop,
                name="realtime-voice-changer",
                daemon=True,
            )
            self._thread.start()
            self._running = True
            LOGGER.info(
                "实时变声器已启动：device=%s sample_rate=%s channels=%s pitch=%s",
                output_device_index,
                config.output_sample_rate,
                self._output_channels,
                config.pitch_semitones,
            )
        except Exception:
            # 输出设备初始化失败时释放已经创建的 PortAudio 资源，再交给上层决定是否降级。
            if self._stream is not None:
                with contextlib.suppress(Exception):
                    self._stream.stop()
                with contextlib.suppress(Exception):
                    self._stream.close()
            self._stream = None
            self._running = False
            raise

    def stop(self) -> None:
        """停止变声器并释放输出设备。"""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        if self._stream is not None:
            with contextlib.suppress(Exception):
                self._stream.stop()
            with contextlib.suppress(Exception):
                self._stream.close()

        self._thread = None
        self._stream = None
        self._running = False
        self._clear_buffers()
        LOGGER.info("实时变声器已停止")

    def push(self, chunk: AudioChunk) -> None:
        """把麦克风音频送入变声器，队列满时丢弃旧数据。"""
        with self._config_lock:
            enabled = self.config.enabled
        if not enabled or not self._running:
            return

        try:
            self._input_queue.put_nowait(chunk)
        except queue.Full:
            # 实时监听宁愿丢旧块，也不要累积延迟。
            with contextlib.suppress(queue.Empty):
                self._input_queue.get_nowait()
            with contextlib.suppress(queue.Full):
                self._input_queue.put_nowait(chunk)

    def _run_loop(self) -> None:
        """后台处理输入音频，避免在输出回调里做重计算。"""
        while not self._stop_event.is_set():
            try:
                chunk = self._input_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            processed = self.processor.process(chunk)
            output_samples = self._resample_if_needed(processed, chunk.sample_rate, self.config.output_sample_rate)
            with self._buffer_lock:
                self._buffer.append(output_samples)

    def _on_output(self, outdata, frames: int, time_info, status) -> None:
        """sounddevice 输出回调：从缓冲区取音频，不足时补静音。"""
        if status:
            LOGGER.warning("变声器输出状态：%s", status)

        output = np.zeros(frames, dtype=np.float32)
        filled = 0
        with self._buffer_lock:
            while filled < frames and self._buffer:
                current = self._buffer[0]
                available = current.size - self._buffer_offset
                take = min(frames - filled, available)
                output[filled : filled + take] = current[self._buffer_offset : self._buffer_offset + take]
                filled += take
                self._buffer_offset += take
                if self._buffer_offset >= current.size:
                    self._buffer.popleft()
                    self._buffer_offset = 0

        outdata[:, 0] = output
        if self._output_channels > 1:
            outdata[:, 1:self._output_channels] = output[:, None]

    def _resample_if_needed(self, samples: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
        """在麦克风采样率和输出采样率不一致时做线性重采样。"""
        if source_rate == target_rate or samples.size == 0:
            return samples

        target_size = max(1, int(round(samples.size * target_rate / source_rate)))
        source_positions = np.linspace(0, samples.size - 1, num=samples.size, dtype=np.float32)
        target_positions = np.linspace(0, samples.size - 1, num=target_size, dtype=np.float32)
        resampled = np.interp(target_positions, source_positions, samples)
        return np.asarray(resampled, dtype=np.float32)

    def _clear_buffers(self) -> None:
        """清空输入队列和输出缓冲。"""
        while True:
            try:
                self._input_queue.get_nowait()
            except queue.Empty:
                break
        with self._buffer_lock:
            self._buffer.clear()
            self._buffer_offset = 0

    def _resolve_output_channels(self, sounddevice_module: Any, device_index: int | None) -> int:
        """根据输出设备能力选择声道数，优先使用双声道提升 Windows 设备兼容性。"""
        try:
            device_info = sounddevice_module.query_devices(device_index, "output")
            max_channels = int(device_info.get("max_output_channels", 1))
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("读取输出设备声道数失败，使用单声道输出：%s", exc)
            return 1
        return 2 if max_channels >= 2 else 1

    def _resolve_effective_output_device(self, config: VoiceChangerConfig) -> int | None:
        """根据模式解析实际输出设备。"""
        if config.demo_monitor_enabled:
            # 演示监听明确面向主播本机试听，使用系统默认输出设备。
            return None
        return config.output_device_index

    def _should_restart_output(self, old_config: VoiceChangerConfig, new_config: VoiceChangerConfig) -> bool:
        """判断输出流是否需要重启。"""
        return (
            self._resolve_effective_output_device(old_config) != self._resolve_effective_output_device(new_config)
            or old_config.demo_monitor_enabled != new_config.demo_monitor_enabled
            or old_config.output_sample_rate != new_config.output_sample_rate
            or old_config.block_size != new_config.block_size
        )
