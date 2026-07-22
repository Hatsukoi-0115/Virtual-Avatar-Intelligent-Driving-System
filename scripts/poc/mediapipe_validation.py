"""MediaPipe 1.4 验证脚本。

用途：
- 验证摄像头输入是否稳定
- 验证 MediaPipe 在目标机器上的实时性能
- 验证脸部关键点输出是否稳定可用

操作：
- 按 q 退出
- 窗口左上角会显示当前 FPS、检测状态和关键点数量
"""

from __future__ import annotations

import contextlib
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Final
from urllib.request import urlopen

import cv2
import mediapipe as mp
from mediapipe.tasks.python.core.base_options import BaseOptions
from mediapipe.tasks.python import vision
from mediapipe.tasks.python.vision import face_landmarker

LOGGER = logging.getLogger(__name__)
SCRIPT_NAME: Final[str] = "MediaPipe 1.4 验证"
CAMERA_INDEX: Final[int] = 0
FRAME_WIDTH: Final[int] = 1280
FRAME_HEIGHT: Final[int] = 720
TARGET_FPS: Final[int] = 30
PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
MODEL_ASSET_PATH: Final[Path] = PROJECT_ROOT / "scripts" / "poc" / "assets" / "face_landmarker.task"
MODEL_DOWNLOAD_URL: Final[str] = (
    "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
    "face_landmarker/float16/1/face_landmarker.task"
)

FACE_CONNECTION_GROUPS: Final[tuple[tuple[str, tuple[face_landmarker.FaceLandmarksConnections.Connection, ...], tuple[int, int, int]], ...]] = (
    ("tesselation", tuple(face_landmarker.FaceLandmarksConnections.FACE_LANDMARKS_TESSELATION), (80, 220, 120)),
    ("contours", tuple(face_landmarker.FaceLandmarksConnections.FACE_LANDMARKS_CONTOURS), (0, 255, 255)),
    ("left_eye", tuple(face_landmarker.FaceLandmarksConnections.FACE_LANDMARKS_LEFT_EYE), (255, 120, 0)),
    ("right_eye", tuple(face_landmarker.FaceLandmarksConnections.FACE_LANDMARKS_RIGHT_EYE), (255, 120, 0)),
    ("lips", tuple(face_landmarker.FaceLandmarksConnections.FACE_LANDMARKS_LIPS), (255, 0, 120)),
)


@dataclass(slots=True)
class RuntimeStats:
    """运行时统计信息。"""

    frame_count: int = 0
    start_time: float = 0.0
    last_report_time: float = 0.0
    smoothed_fps: float = 0.0
    last_face_landmarks_count: int = 0
    consecutive_failures: int = 0


def _configure_logging() -> None:
    """配置日志，便于观察摄像头和 MediaPipe 初始化问题。"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


def _ensure_model_asset() -> Path:
    """确保 Face Landmarker 模型文件可用。

    这个 1.4 验证脚本使用 MediaPipe Tasks API，因此需要单独的 .task 模型文件。
    """
    if MODEL_ASSET_PATH.exists():
        return MODEL_ASSET_PATH

    MODEL_ASSET_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOGGER.info("未找到模型文件，开始下载：%s", MODEL_ASSET_PATH)

    try:
        with contextlib.closing(urlopen(MODEL_DOWNLOAD_URL, timeout=30)) as response, MODEL_ASSET_PATH.open("wb") as file_handle:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                file_handle.write(chunk)
    except Exception as exc:  # noqa: BLE001
        with contextlib.suppress(FileNotFoundError):
            MODEL_ASSET_PATH.unlink()
        raise RuntimeError(
            "无法下载 MediaPipe Face Landmarker 模型文件，请检查网络后重试"
        ) from exc

    return MODEL_ASSET_PATH


def _open_camera(index: int) -> cv2.VideoCapture:
    """打开摄像头并设置基础参数。"""
    capture = cv2.VideoCapture(index, cv2.CAP_DSHOW)
    if not capture.isOpened():
        raise RuntimeError(f"无法打开摄像头：{index}")

    capture.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
    capture.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)
    capture.set(cv2.CAP_PROP_FPS, TARGET_FPS)
    capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return capture


def _build_face_landmarker() -> face_landmarker.FaceLandmarker:
    """构建用于实时验证的 Face Landmarker 实例。"""
    model_asset = _ensure_model_asset()
    options = face_landmarker.FaceLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=str(model_asset)),
        running_mode=vision.RunningMode.VIDEO,
        num_faces=1,
        min_face_detection_confidence=0.5,
        min_face_presence_confidence=0.5,
        min_tracking_confidence=0.5,
        output_face_blendshapes=False,
        output_facial_transformation_matrixes=False,
    )
    return face_landmarker.FaceLandmarker.create_from_options(options)


def _draw_overlay(frame, fps: float, status: str, landmarks_count: int) -> None:
    """在画面左上角显示运行信息。"""
    lines = [
        f"FPS: {fps:.1f}",
        f"Status: {status}",
        f"Landmarks: {landmarks_count}",
        "Press Q to quit",
    ]

    x = 16
    y = 32
    for line in lines:
        cv2.putText(
            frame,
            line,
            (x, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.75,
            (0, 255, 0),
            2,
            cv2.LINE_AA,
        )
        y += 32


def _draw_connections(frame, landmarks, connections, color: tuple[int, int, int], thickness: int = 1) -> None:
    """把任务式关键点连接画到画面上。"""
    height, width = frame.shape[:2]
    for connection in connections:
        start = landmarks[connection.start]
        end = landmarks[connection.end]
        start_point = (int(start.x * width), int(start.y * height))
        end_point = (int(end.x * width), int(end.y * height))
        cv2.line(frame, start_point, end_point, color, thickness, cv2.LINE_AA)


def _draw_landmarks(frame, landmarks) -> None:
    """绘制面部关键点和主要轮廓，方便观察检测稳定性。"""
    height, width = frame.shape[:2]

    for _, connections, color in FACE_CONNECTION_GROUPS:
        _draw_connections(frame, landmarks, connections, color, 1)

    for landmark in landmarks:
        point = (int(landmark.x * width), int(landmark.y * height))
        cv2.circle(frame, point, 1, (0, 255, 0), -1, cv2.LINE_AA)


def main() -> None:
    """执行 1.4 验证流程。"""
    _configure_logging()
    LOGGER.info("启动 %s", SCRIPT_NAME)

    capture = _open_camera(CAMERA_INDEX)
    stats = RuntimeStats(start_time=time.perf_counter(), last_report_time=time.perf_counter())

    with _build_face_landmarker() as face_landmarker_instance:
        try:
            while True:
                success, frame = capture.read()
                if not success:
                    stats.consecutive_failures += 1
                    LOGGER.warning("摄像头读帧失败，连续失败次数：%s", stats.consecutive_failures)
                    if stats.consecutive_failures >= 30:
                        raise RuntimeError("摄像头连续读帧失败，停止验证")
                    continue

                stats.consecutive_failures = 0
                stats.frame_count += 1

                frame = cv2.flip(frame, 1)
                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
                timestamp_ms = int((time.perf_counter() - stats.start_time) * 1000)
                results = face_landmarker_instance.detect_for_video(image, timestamp_ms)

                face_landmarks_count = 0
                status = "No face"
                if results.face_landmarks:
                    face_landmarks_count = len(results.face_landmarks[0])
                    status = "Face detected"
                    _draw_landmarks(frame, results.face_landmarks[0])

                stats.last_face_landmarks_count = face_landmarks_count

                elapsed = time.perf_counter() - stats.start_time
                fps = stats.frame_count / elapsed if elapsed > 0 else 0.0
                stats.smoothed_fps = fps if stats.smoothed_fps == 0.0 else stats.smoothed_fps * 0.9 + fps * 0.1

                _draw_overlay(frame, stats.smoothed_fps, status, face_landmarks_count)
                cv2.imshow(SCRIPT_NAME, frame)

                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break

                now = time.perf_counter()
                if now - stats.last_report_time >= 5.0:
                    LOGGER.info(
                        "运行中：平均FPS=%.2f，当前关键点数=%s，检测状态=%s",
                        stats.smoothed_fps,
                        stats.last_face_landmarks_count,
                        status,
                    )
                    stats.last_report_time = now
        finally:
            capture.release()
            cv2.destroyAllWindows()

    LOGGER.info("验证结束")


if __name__ == "__main__":
    main()
