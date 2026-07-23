"""MediaPipe 人脸特征推理模块。

职责：
- 消费 CameraFramePacket
- 进行 MediaPipe Face Landmarker 推理
- 输出 VisualFeaturePacket
- 不负责采集和渲染
"""

from __future__ import annotations

import contextlib
import math
import logging
import threading
import time
from pathlib import Path
from typing import Final
from urllib.request import urlopen

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks.python import vision
from mediapipe.tasks.python.core.base_options import BaseOptions
from mediapipe.tasks.python.vision import face_landmarker

from virtual_avatar_system.vision.feature_packet import VisualFeaturePacket

LOGGER = logging.getLogger(__name__)
PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
MODEL_ASSET_PATH: Final[Path] = PROJECT_ROOT / "scripts" / "poc" / "assets" / "face_landmarker.task"
MODEL_DOWNLOAD_URL: Final[str] = (
    "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
    "face_landmarker/float16/1/face_landmarker.task"
)


class FaceLandmarkInferencer:
    """MediaPipe Face Landmarker 推理器。

    在独立线程中运行，消费帧包，产出视觉特征包。
    """

    def __init__(self) -> None:
        self._landmarker: face_landmarker.FaceLandmarker | None = None
        self._thread: threading.Thread | None = None
        self._running = False

        # 输入帧队列，每项为 (bgr_bytes, width, height)
        self._input_queue: list[tuple[bytes, int, int]] = []
        self._input_condition = threading.Condition()

        # 输出特征队列
        self._output_queue: list[VisualFeaturePacket] = []
        self._output_lock = threading.Lock()
        self._max_output_size = 16

        self._start_time = 0.0
        self._frame_index = 0

    # ---- 生命周期 ----

    def start(self) -> None:
        """启动推理线程。"""
        if self._running:
            return

        self._ensure_model_asset()
        self._build_landmarker()

        self._running = True
        self._start_time = time.perf_counter()
        self._thread = threading.Thread(target=self._run_loop, name="face-inference", daemon=True)
        self._thread.start()
        LOGGER.info("MediaPipe 推理器已启动")

    def stop(self) -> None:
        """停止推理并释放模型。"""
        self._running = False

        with self._input_condition:
            self._input_condition.notify_all()

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)

        if self._landmarker:
            self._landmarker.close()

        LOGGER.info("MediaPipe 推理器已释放")

    # ---- 输入 ----

    def feed_frame(self, bgr_bytes: bytes, width: int, height: int) -> None:
        """向推理器投喂一帧 BGR 数据。"""
        with self._input_condition:
            self._input_queue.append((bgr_bytes, width, height))
            # 限制输入队列长度，避免积压
            while len(self._input_queue) > 4:
                self._input_queue.pop(0)
            self._input_condition.notify()

    # ---- 输出消费 ----

    def pop_features(self) -> list[VisualFeaturePacket]:
        """取出当前所有视觉特征包（线程安全）。"""
        with self._output_lock:
            result = list(self._output_queue)
            self._output_queue.clear()
        return result

    # ---- 内部 ----

    def _ensure_model_asset(self) -> None:
        """确保 MediaPipe 模型文件可用。"""
        if MODEL_ASSET_PATH.exists():
            return
        MODEL_ASSET_PATH.parent.mkdir(parents=True, exist_ok=True)
        LOGGER.info("下载 MediaPipe 模型文件…")
        with contextlib.closing(urlopen(MODEL_DOWNLOAD_URL, timeout=60)) as resp, MODEL_ASSET_PATH.open("wb") as f:
            while True:
                chunk = resp.read(1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)

    def _build_landmarker(self) -> None:
        """构建 MediaPipe Face Landmarker 实例。"""
        options = face_landmarker.FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(MODEL_ASSET_PATH)),
            running_mode=vision.RunningMode.VIDEO,
            num_faces=1,
            # 适当降低阈值，提升半遮挡、侧脸、画面边缘等情况下的人脸保持能力。
            min_face_detection_confidence=0.3,
            min_face_presence_confidence=0.3,
            min_tracking_confidence=0.3,
            output_face_blendshapes=False,
            output_facial_transformation_matrixes=False,
        )
        self._landmarker = face_landmarker.FaceLandmarker.create_from_options(options)

    def _run_loop(self) -> None:
        """推理主循环，使用归一化比例生成视觉特征包。"""
        while self._running:
            # 等待输入帧，避免空转占用 CPU
            with self._input_condition:
                if not self._input_queue:
                    self._input_condition.wait(timeout=0.1)
                    continue
                bgr_bytes, f_width, f_height = self._input_queue.pop(0)

            self._frame_index += 1
            inference_start = time.perf_counter()

            # 还原为 numpy 图像并转换到 RGB
            frame = np.frombuffer(bgr_bytes, dtype=np.uint8).reshape((f_height, f_width, 3))
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

            image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            timestamp_ms = int((time.perf_counter() - self._start_time) * 1000)
            results = self._landmarker.detect_for_video(image, timestamp_ms)
            inference_ms = (time.perf_counter() - inference_start) * 1000

            # 构建特征包
            packet = VisualFeaturePacket(
                timestamp=time.perf_counter(),
                frame_index=self._frame_index,
                inference_ms=inference_ms,
            )

            if results.face_landmarks:
                landmarks = results.face_landmarks[0]
                packet.face_detected = True

                # 用脸部局部比例做归一化，减少分辨率变化带来的数值漂移
                left_eye_width = abs(landmarks[133].x - landmarks[33].x)
                right_eye_width = abs(landmarks[362].x - landmarks[263].x)
                mouth_width = abs(landmarks[291].x - landmarks[61].x)

                # 嘴部张开：上下唇间距 / 嘴宽
                mouth_gap = abs(landmarks[13].y - landmarks[14].y)
                packet.mouth_open = min(1.0, max(0.0, mouth_gap / max(mouth_width, 1e-6) * 2.5))

                # 左右眼开合：上下眼睑间距 / 眼宽
                left_eye_gap = abs(landmarks[159].y - landmarks[145].y)
                right_eye_gap = abs(landmarks[386].y - landmarks[374].y)
                packet.eye_open_left = min(1.0, max(0.0, left_eye_gap / max(left_eye_width, 1e-6) * 2.2))
                packet.eye_open_right = min(1.0, max(0.0, right_eye_gap / max(right_eye_width, 1e-6) * 2.2))

                # 头部偏航/俯仰：鼻尖相对眼部中心的位置
                nose = landmarks[1]
                eye_center_x = ((landmarks[33].x + landmarks[133].x) + (landmarks[362].x + landmarks[263].x)) / 4.0
                eye_center_y = ((landmarks[159].y + landmarks[145].y) + (landmarks[386].y + landmarks[374].y)) / 4.0
                # 提高偏移灵敏度：在脸部只露出一部分时，也更容易把数值推到饱和区间。
                packet.head_yaw = max(-1.0, min(1.0, (nose.x - eye_center_x) / 0.12))
                packet.head_pitch = max(-1.0, min(1.0, (eye_center_y - nose.y) / 0.12))

                # 头部滚转：双眼连线斜率 → 角度，再归一化到 [-1, 1]
                packet.head_roll = max(
                    -1.0,
                    min(
                        1.0,
                        math.degrees(
                            math.atan2(
                                landmarks[263].y - landmarks[33].y,
                                landmarks[263].x - landmarks[33].x,
                            )
                        )
                        / 20.0,
                    ),
                )

            # 写入输出队列
            with self._output_lock:
                self._output_queue.append(packet)
                while len(self._output_queue) > self._max_output_size:
                    self._output_queue.pop(0)
