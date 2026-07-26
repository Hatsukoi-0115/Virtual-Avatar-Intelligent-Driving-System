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
CALIBRATION_FRAMES: Final[int] = 30
HEAD_SMOOTHING_ALPHA: Final[float] = 0.35
EYE_CLOSE_SMOOTHING_ALPHA: Final[float] = 0.90
EYE_OPEN_SMOOTHING_ALPHA: Final[float] = 0.70
HEAD_DEADZONE: Final[float] = 0.025


def _clamp(value: float, minimum: float, maximum: float) -> float:
    """Clamp a numeric value into a fixed range."""
    return max(minimum, min(maximum, value))


def _apply_deadzone(value: float, threshold: float = HEAD_DEADZONE) -> float:
    """Suppress tiny head movements around the calibrated neutral pose."""
    return 0.0 if abs(value) < threshold else value


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
        self._calibration_samples = 0
        self._baseline_yaw = 0.0
        self._baseline_pitch = 0.0
        self._baseline_roll = 0.0
        self._baseline_eye_left = 0.0
        self._baseline_eye_right = 0.0
        self._smoothed_head_yaw = 0.0
        self._smoothed_head_pitch = 0.0
        self._smoothed_head_roll = 0.0
        self._smoothed_eye_left = 1.0
        self._smoothed_eye_right = 1.0

    # ---- 生命周期 ----

    def start(self) -> None:
        """启动推理线程。"""
        if self._running:
            return

        self._ensure_model_asset()
        self._build_landmarker()

        self._running = True
        self._start_time = time.perf_counter()
        self._reset_tracking_state()
        self._thread = threading.Thread(target=self._run_loop, name="face-inference", daemon=True)
        self._thread.start()
        LOGGER.info("MediaPipe 推理器已启动，正在进行视觉中立校准：请正对摄像头、自然睁眼并保持头部水平约 1 秒")

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

    @property
    def calibration_complete(self) -> bool:
        """视觉中立校准是否已完成。"""
        return self._calibration_samples >= CALIBRATION_FRAMES

    # ---- 输入 ----

    def _reset_tracking_state(self) -> None:
        """Reset per-run calibration and smoothing state."""
        self._calibration_samples = 0
        self._baseline_yaw = 0.0
        self._baseline_pitch = 0.0
        self._baseline_roll = 0.0
        self._baseline_eye_left = 0.0
        self._baseline_eye_right = 0.0
        self._smoothed_head_yaw = 0.0
        self._smoothed_head_pitch = 0.0
        self._smoothed_head_roll = 0.0
        self._smoothed_eye_left = 1.0
        self._smoothed_eye_right = 1.0

    def _update_calibration(
        self,
        raw_yaw: float,
        raw_pitch: float,
        raw_roll: float,
        raw_eye_left: float,
        raw_eye_right: float,
    ) -> bool:
        """Accumulate the first stable face frames as the neutral pose."""
        if self._calibration_samples >= CALIBRATION_FRAMES:
            return True

        self._calibration_samples += 1
        weight = 1.0 / self._calibration_samples
        self._baseline_yaw += (raw_yaw - self._baseline_yaw) * weight
        self._baseline_pitch += (raw_pitch - self._baseline_pitch) * weight
        self._baseline_roll += (raw_roll - self._baseline_roll) * weight
        self._baseline_eye_left += (raw_eye_left - self._baseline_eye_left) * weight
        self._baseline_eye_right += (raw_eye_right - self._baseline_eye_right) * weight

        if self._calibration_samples == CALIBRATION_FRAMES:
            LOGGER.info(
                "视觉中立校准完成：yaw=%.3f pitch=%.3f roll=%.3f eye_l=%.3f eye_r=%.3f",
                self._baseline_yaw,
                self._baseline_pitch,
                self._baseline_roll,
                self._baseline_eye_left,
                self._baseline_eye_right,
            )
            return True
        return False

    @staticmethod
    def _normalize_eye_open(raw_ratio: float, baseline_ratio: float) -> float:
        """Map each user's normal open eye ratio close to 1.0."""
        if baseline_ratio <= 1e-6:
            normalized = raw_ratio * 3.6
        else:
            closed_ratio = baseline_ratio * 0.30
            open_ratio = baseline_ratio * 0.82
            normalized = (raw_ratio - closed_ratio) / max(open_ratio - closed_ratio, 1e-6)

        normalized = _clamp(normalized, 0.0, 1.0)
        if normalized >= 0.78:
            return 1.0
        if normalized <= 0.18:
            return 0.0
        return normalized

    @staticmethod
    def _smooth(previous: float, current: float, alpha: float) -> float:
        """Single-pole smoothing to reduce jitter without adding much latency."""
        return previous + (current - previous) * alpha

    def _smooth_eye_open(self, previous: float, current: float) -> float:
        """Blink quickly while keeping ordinary open-eye frames stable."""
        alpha = EYE_CLOSE_SMOOTHING_ALPHA if current < previous else EYE_OPEN_SMOOTHING_ALPHA
        return self._smooth(previous, current, alpha)

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

                left_eye_gap = abs(landmarks[159].y - landmarks[145].y)
                right_eye_gap = abs(landmarks[386].y - landmarks[374].y)
                raw_eye_left = left_eye_gap / max(left_eye_width, 1e-6)
                raw_eye_right = right_eye_gap / max(right_eye_width, 1e-6)

                nose = landmarks[1]
                eye_center_x = ((landmarks[33].x + landmarks[133].x) + (landmarks[362].x + landmarks[263].x)) / 4.0
                eye_center_y = ((landmarks[159].y + landmarks[145].y) + (landmarks[386].y + landmarks[374].y)) / 4.0
                raw_yaw = (nose.x - eye_center_x) / 0.12
                raw_pitch = (eye_center_y - nose.y) / 0.12
                raw_roll = (
                    math.degrees(
                        math.atan2(
                            landmarks[263].y - landmarks[33].y,
                            landmarks[263].x - landmarks[33].x,
                        )
                    )
                    / 20.0
                )

                calibrated = self._update_calibration(
                    raw_yaw,
                    raw_pitch,
                    raw_roll,
                    raw_eye_left,
                    raw_eye_right,
                )

                if calibrated:
                    target_yaw = _apply_deadzone(_clamp((raw_yaw - self._baseline_yaw) * 1.15, -1.0, 1.0))
                    target_pitch = _apply_deadzone(_clamp((raw_pitch - self._baseline_pitch) * 1.15, -1.0, 1.0))
                    target_roll = _apply_deadzone(_clamp((raw_roll - self._baseline_roll) * 1.10, -1.0, 1.0))
                    target_eye_left = self._normalize_eye_open(raw_eye_left, self._baseline_eye_left)
                    target_eye_right = self._normalize_eye_open(raw_eye_right, self._baseline_eye_right)
                else:
                    target_yaw = 0.0
                    target_pitch = 0.0
                    target_roll = 0.0
                    target_eye_left = 1.0
                    target_eye_right = 1.0

                self._smoothed_head_yaw = self._smooth(self._smoothed_head_yaw, target_yaw, HEAD_SMOOTHING_ALPHA)
                self._smoothed_head_pitch = self._smooth(
                    self._smoothed_head_pitch,
                    target_pitch,
                    HEAD_SMOOTHING_ALPHA,
                )
                self._smoothed_head_roll = self._smooth(self._smoothed_head_roll, target_roll, HEAD_SMOOTHING_ALPHA)
                self._smoothed_eye_left = self._smooth_eye_open(self._smoothed_eye_left, target_eye_left)
                self._smoothed_eye_right = self._smooth_eye_open(self._smoothed_eye_right, target_eye_right)

                packet.head_yaw = _clamp(self._smoothed_head_yaw, -1.0, 1.0)
                packet.head_pitch = _clamp(self._smoothed_head_pitch, -1.0, 1.0)
                packet.head_roll = _clamp(self._smoothed_head_roll, -1.0, 1.0)
                packet.eye_open_left = _clamp(self._smoothed_eye_left, 0.0, 1.0)
                packet.eye_open_right = _clamp(self._smoothed_eye_right, 0.0, 1.0)

            # 写入输出队列
            with self._output_lock:
                self._output_queue.append(packet)
                while len(self._output_queue) > self._max_output_size:
                    self._output_queue.pop(0)
