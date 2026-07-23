"""Live2D 多模态虚拟形象驱动系统 — 应用入口。

职责：
- 初始化 QApplication
- 加载配置
- 创建主窗口、预览窗口、系统托盘
- 连接开始/停止事件（后续接入 Avatar Controller）
- 启动事件循环
"""

from __future__ import annotations

import logging
import signal
import sys
import time
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

# 确保 src 目录在 Python 搜索路径中
PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from virtual_avatar_system.config.app_config import load_config, save_config
from virtual_avatar_system.ui.live_state_machine import LiveState
from virtual_avatar_system.ui.main_window import MainWindow
from virtual_avatar_system.ui.preview_window import PreviewWindow
from virtual_avatar_system.ui.system_tray import AppSystemTray
from virtual_avatar_system.vision.camera_source import CameraFrameSource
from virtual_avatar_system.vision.face_inference import FaceLandmarkInferencer


def _configure_logging() -> None:
    """配置全局日志输出。"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


def main() -> None:
    """启动桌面应用骨架。"""
    _configure_logging()
    logger = logging.getLogger(__name__)

    # ---- Qt 应用初始化 ----
    app = QApplication(sys.argv)
    app.setApplicationName("Virtual Avatar Intelligent Driving System")
    app.setOrganizationName("VAIDS")

    # ---- 加载配置 ----
    config = load_config()

    # ---- 创建窗口 ----
    preview = PreviewWindow()
    if config.preview_visible:
        preview.show()

    main_window = MainWindow(config)
    main_window.set_preview_window(preview)
    main_window.show()

    # ---- 系统托盘 ----
    tray = AppSystemTray(main_window)
    tray.show()

    main_window.set_system_tray(tray)

    # ---- 视觉链路：摄像头采集 + MediaPipe 推理 ----
    camera_source = CameraFrameSource(
        camera_index=config.camera_index,
        width=config.camera_width,
        height=config.camera_height,
        fps=config.camera_fps,
    )
    inferencer = FaceLandmarkInferencer()

    # 桥接定时器：摄像头帧 → 推理器
    feed_timer = QTimer()
    feed_timer.setInterval(16)

    def _feed_frames() -> None:
        for frame_packet in camera_source.pop_frames():
            if frame_packet.bgr_data:
                inferencer.feed_frame(
                    frame_packet.bgr_data,
                    frame_packet.width,
                    frame_packet.height,
                )

    feed_timer.timeout.connect(_feed_frames)

    # 桥接定时器：推理结果 → 日志报告（后续对接 Avatar Controller）
    consume_timer = QTimer()
    consume_timer.setInterval(33)
    last_report_time = 0.0

    def _consume_features() -> None:
        nonlocal last_report_time
        packets = inferencer.pop_features()
        if not packets:
            return
        latest = packets[-1]
        now = time.time()
        if now - last_report_time >= 5.0:
            logger.info(
                "视觉推理中：帧=%s 检测=%s 嘴部=%.2f 推理=%.1fms",
                latest.frame_index,
                "有" if latest.face_detected else "无",
                latest.mouth_open,
                latest.inference_ms,
            )
            last_report_time = now

    consume_timer.timeout.connect(_consume_features)

    # ---- 开始 / 停止事件 ----
    def on_start() -> None:
        logger.info("开始直播")
        try:
            camera_source.start()
            inferencer.start()
            feed_timer.start()
            consume_timer.start()
            main_window.state_machine.on_ready()
        except Exception as exc:  # noqa: BLE001
            logger.exception("启动视觉链路失败")
            main_window.state_machine.on_error(str(exc))

    def on_stop() -> None:
        logger.info("停止直播")
        feed_timer.stop()
        consume_timer.stop()
        inferencer.stop()
        camera_source.stop()
        main_window.state_machine.on_stopped()

    main_window.on_start(on_start)
    main_window.on_stop(on_stop)

    # ---- 统一退出入口 ----
    def _quit_application() -> None:
        """统一退出函数，供关闭按钮、Ctrl+C、托盘菜单复用。"""
        logger.info("开始执行退出流程…")
        save_config(main_window.config)
        preview.close()
        main_window.close()
        app.quit()

    # 托盘退出只执行统一退出流程
    tray.on_quit(_quit_application)

    # ---- 注册 Ctrl+C / SIGTERM 信号处理 ----
    def _handle_sigint(signum, frame) -> None:
        """收到 SIGINT (Ctrl+C) 时安全退出事件循环。"""
        logger.info("收到 Ctrl+C，正在退出…")
        _quit_application()

    signal.signal(signal.SIGINT, _handle_sigint)
    signal.signal(signal.SIGTERM, _handle_sigint)

    # ---- 让 Qt 事件循环周期性处理信号 ----
    sigint_pump = QTimer()
    sigint_pump.setInterval(100)
    sigint_pump.timeout.connect(lambda: None)
    sigint_pump.start()

    # ---- 进入事件循环 ----
    exit_code = app.exec()
    logger.info("应用已退出")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
