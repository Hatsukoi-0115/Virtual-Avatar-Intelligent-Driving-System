"""FunASR 1.5 终端流式验证脚本。

用途：
- 本机采集麦克风音频
- 通过 FunASR 流式模型做在线识别
- 在终端持续打印增量识别结果

运行方式：
- uv run python scripts/poc/funasr_streaming_validation.py
- 可选：--device 选择输入设备
- 可选：--duration 指定运行秒数
"""

from __future__ import annotations

import argparse
import contextlib
import logging
import queue
import threading
import time
from dataclasses import dataclass
from typing import Final

import numpy as np
import sounddevice as sd
from funasr import AutoModel

LOGGER = logging.getLogger(__name__)
MODEL_NAME: Final[str] = "paraformer-zh-streaming"
SAMPLE_RATE: Final[int] = 16000
CHANNELS: Final[int] = 1
BLOCK_MS: Final[int] = 100
BLOCK_FRAMES: Final[int] = int(SAMPLE_RATE * BLOCK_MS / 1000)
QUEUE_MAXSIZE: Final[int] = 200
STREAM_CFG: Final[dict[str, int | list[int]]] = {
    "chunk_size": [0, 10, 5],
    "encoder_chunk_look_back": 4,
    "decoder_chunk_look_back": 1,
}


@dataclass(slots=True)
class StreamStats:
    """流式识别统计信息。"""

    chunks: int = 0
    inference_time: float = 0.0
    last_printed_text: str = ""
    last_partial_text: str = ""


def _configure_logging() -> None:
    """配置日志输出。"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


def _build_parser() -> argparse.ArgumentParser:
    """构建命令行参数。"""
    parser = argparse.ArgumentParser(description="FunASR 终端流式验证脚本")
    parser.add_argument("--device", type=int, default=None, help="输入设备编号，默认使用系统默认输入设备")
    parser.add_argument("--duration", type=float, default=0.0, help="运行时长（秒），0 表示一直运行到 Ctrl+C")
    parser.add_argument("--model", type=str, default=MODEL_NAME, help="FunASR 模型名或本地路径")
    return parser


def _build_model(model_name: str) -> AutoModel:
    """构建流式 ASR 模型。"""
    LOGGER.info("加载 FunASR 模型：%s", model_name)
    return AutoModel(model=model_name, disable_update=True)


def _pick_input_device(device_index: int | None) -> int | None:
    """选择输入设备并打印信息。"""
    if device_index is None:
        LOGGER.info("使用系统默认输入设备")
        return None

    device_info = sd.query_devices(device_index, kind="input")
    LOGGER.info("使用输入设备 #%s：%s", device_index, device_info["name"])
    return device_index


def _drain_audio_queue(
    audio_queue: queue.Queue[np.ndarray], stop_event: threading.Event
) -> np.ndarray | None:
    """从队列中取出一帧音频，若当前没有数据则返回 None。"""
    try:
        return audio_queue.get(timeout=0.2)
    except queue.Empty:
        if stop_event.is_set():
            return None
        return np.array([], dtype=np.float32)


def _audio_callback(indata, frames, time_info, status, audio_queue: queue.Queue[np.ndarray]) -> None:
    """把麦克风输入放入队列，避免在回调里做重推理。"""
    if status:
        LOGGER.warning("音频回调状态：%s", status)

    if not frames:
        return

    chunk = np.asarray(indata[:, 0], dtype=np.float32).copy()
    if not len(chunk):
        return

    try:
        audio_queue.put_nowait(chunk)
    except queue.Full:
        with contextlib.suppress(queue.Empty):
            audio_queue.get_nowait()
        with contextlib.suppress(queue.Full):
            audio_queue.put_nowait(chunk)


def _extract_text(result_list: list[dict]) -> str:
    """从 FunASR 返回结果中提取文本。"""
    if not result_list:
        return ""

    first_result = result_list[0]
    return str(first_result.get("text", "")).strip()


def _print_text_line(label: str, text: str, elapsed: float) -> None:
    """打印一行终端流式结果。"""
    print(f"[{elapsed:7.2f}s] {label}: {text}", flush=True)


def main() -> None:
    """执行 FunASR 终端流式验证。"""
    _configure_logging()
    parser = _build_parser()
    args = parser.parse_args()

    device_index = _pick_input_device(args.device)
    model = _build_model(args.model)
    audio_queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=QUEUE_MAXSIZE)
    stop_event = threading.Event()
    stats = StreamStats()
    stream_start = time.perf_counter()
    cache: dict = {}

    LOGGER.info("采样率：%s Hz，块大小：%s 帧，按 Ctrl+C 退出", SAMPLE_RATE, BLOCK_FRAMES)
    _print_text_line("INFO", "开始监听麦克风并输出增量识别结果", 0.0)

    try:
        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype="float32",
            blocksize=BLOCK_FRAMES,
            device=device_index,
            callback=lambda indata, frames, time_info, status: _audio_callback(
                indata, frames, time_info, status, audio_queue
            ),
        ):
            while True:
                if args.duration and (time.perf_counter() - stream_start) >= args.duration:
                    LOGGER.info("达到指定运行时长，准备结束")
                    break

                chunk = _drain_audio_queue(audio_queue, stop_event)
                if chunk is None:
                    break
                if chunk.size == 0:
                    continue

                infer_start = time.perf_counter()
                result = model.generate(
                    chunk,
                    cache=cache,
                    is_final=False,
                    disable_pbar=True,
                    **STREAM_CFG,
                )
                infer_elapsed = time.perf_counter() - infer_start
                stats.chunks += 1
                stats.inference_time += infer_elapsed

                text = _extract_text(result)
                if text and text != stats.last_partial_text:
                    stats.last_partial_text = text
                    elapsed = time.perf_counter() - stream_start
                    _print_text_line("PARTIAL", text, elapsed)

    except KeyboardInterrupt:
        LOGGER.info("收到 Ctrl+C，准备刷新最终结果")
    finally:
        stop_event.set()
        remaining_chunks: list[np.ndarray] = []
        while True:
            try:
                remaining_chunks.append(audio_queue.get_nowait())
            except queue.Empty:
                break

        if remaining_chunks:
            tail_audio = np.concatenate(remaining_chunks).astype(np.float32, copy=False)
            final_result = model.generate(
                tail_audio,
                cache=cache,
                is_final=True,
                disable_pbar=True,
                **STREAM_CFG,
            )
            final_text = _extract_text(final_result)
            if final_text and final_text != stats.last_partial_text:
                elapsed = time.perf_counter() - stream_start
                _print_text_line("FINAL", final_text, elapsed)

        total_elapsed = time.perf_counter() - stream_start
        avg_rtf = stats.inference_time / total_elapsed if total_elapsed > 0 else 0.0
        LOGGER.info(
            "结束：chunks=%s, total=%.2fs, avg_rtf=%.2f",
            stats.chunks,
            total_elapsed,
            avg_rtf,
        )


if __name__ == "__main__":
    main()
