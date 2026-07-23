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

    # ---- 开始 / 停止事件（预留接入 Avatar Controller） ----
    def on_start() -> None:
        """开始直播时的回调。

        后续在这里：
        - 启动摄像头采集线程
        - 启动麦克风采集线程
        - 启动 Avatar Controller
        - 调用 state_machine.on_ready()
        """
        logger.info("开始直播（骨架阶段，尚未接入感知模块）")
        # 模拟所有模块就绪
        main_window.state_machine.on_ready()

    def on_stop() -> None:
        """停止直播时的回调。

        后续在这里：
        - 停止所有采集线程
        - 释放 Avatar Controller
        - 调用 state_machine.on_stopped()
        """
        logger.info("停止直播（骨架阶段，尚未接入感知模块）")
        # 模拟资源释放完成
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
