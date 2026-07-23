"""摄像头视频采集模块。

职责：
- 打开摄像头，持续读取帧
- 输出到队列，供推理线程消费
- 只负责采集，不包含任何推理逻辑
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

import cv2

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class CameraFramePacket:
    """摄像头帧数据包。"""

    frame_index: int = 0
    """帧序号"""

    timestamp: float = 0.0
    """采集时间戳（perf_counter）"""

    bgr_data: bytes | None = None
    """BGR 格式原始帧数据，None 表示采集失败"""

    width: int = 0
    height: int = 0


class CameraFrameSource:
    """摄像头采集器。

    在独立线程中持续拉取摄像头帧，放入内部队列。
    使用者调用 pop_frames() 获取最新帧。
    """

    def __init__(self, camera_index: int = 0, width: int = 1280, height: int = 720, fps: int = 30) -> None:
        self._camera_index = camera_index
        self._width = width
        self._height = height
        self._target_fps = fps

        self._capture: cv2.VideoCapture | None = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._frame_index = 0

        self._queue: list[CameraFramePacket] = []
        self._lock = threading.Lock()
        self._max_queue_size = 8

    # ---- 生命周期 ----

    def start(self) -> None:
        """打开摄像头并启动采集线程。"""
        if self._running:
            LOGGER.warning("摄像头已在采集")
            return

        self._capture = cv2.VideoCapture(self._camera_index, cv2.CAP_DSHOW)
        if not self._capture.isOpened():
            raise RuntimeError(f"无法打开摄像头：{self._camera_index}")

        self._capture.set(cv2.CAP_PROP_FRAME_WIDTH, self._width)
        self._capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self._height)
        self._capture.set(cv2.CAP_PROP_FPS, self._target_fps)
        self._capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        self._running = True
        self._frame_index = 0
        self._thread = threading.Thread(target=self._run_loop, name="camera-source", daemon=True)
        self._thread.start()
        LOGGER.info("摄像头采集已启动：camera=%s %sx%s", self._camera_index, self._width, self._height)

    def stop(self) -> None:
        """停止采集并释放摄像头。"""
        self._running = False

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)

        if self._capture and self._capture.isOpened():
            self._capture.release()

        LOGGER.info("摄像头采集已停止")

    # ---- 输出消费 ----

    def pop_frames(self) -> list[CameraFramePacket]:
        """取出当前队列中所有未消费帧（线程安全）。"""
        with self._lock:
            result = list(self._queue)
            self._queue.clear()
        return result

    # ---- 内部循环 ----

    def _run_loop(self) -> None:
        """采集主循环。"""
        consecutive_failures = 0

        while self._running:
            if self._capture is None:
                break

            success, frame = self._capture.read()
            if not success:
                consecutive_failures += 1
                if consecutive_failures >= 30:
                    LOGGER.error("摄像头连续读帧失败，停止采集")
                    self._running = False
                continue

            consecutive_failures = 0
            self._frame_index += 1

            # 水平翻转，模拟镜子效果
            frame = cv2.flip(frame, 1)

            packet = CameraFramePacket(
                frame_index=self._frame_index,
                timestamp=time.perf_counter(),
                bgr_data=frame.tobytes(),
                width=self._width,
                height=self._height,
            )

            with self._lock:
                self._queue.append(packet)
                while len(self._queue) > self._max_queue_size:
                    self._queue.pop(0)
