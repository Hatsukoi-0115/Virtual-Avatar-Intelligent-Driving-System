"""主窗口模块。

职责：
- 托管设置页、状态展示区和开始/停止按钮
- 通过 LiveStateMachine 控制直播状态
- 与 SystemTray、PreviewWindow 联动
- 只负责 UI 交互，不包含任何业务逻辑
"""

from __future__ import annotations

import logging
from typing import Callable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QStackedWidget,
    QMessageBox,
    QApplication,
)

from virtual_avatar_system.config.app_config import AppConfig, save_config
from virtual_avatar_system.ui.live_state_machine import LiveStateMachine, LiveState
from virtual_avatar_system.ui.settings_page import SettingsPage
from virtual_avatar_system.ui.preview_window import PreviewWindow
from virtual_avatar_system.ui.system_tray import AppSystemTray

LOGGER = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """应用主窗口。

    结构：
    - 顶部：状态栏
    - 中部：设置页（选项卡式）
    - 底部：开始 / 停止按钮
    """

    def __init__(self, config: AppConfig) -> None:
        super().__init__()
        self._config = config
        self._state_machine = LiveStateMachine()
        self._preview_window: PreviewWindow | None = None
        self._system_tray: AppSystemTray | None = None

        # 事件回调注册表，供外部接入业务逻辑
        self._on_start_callbacks: list[Callable[[], None]] = []
        self._on_stop_callbacks: list[Callable[[], None]] = []

        self._setup_window()
        self._setup_ui()
        self._connect_state_machine()

    # ---- 回调注册 ----

    def on_start(self, callback: Callable[[], None]) -> None:
        """注册开始直播回调。"""
        self._on_start_callbacks.append(callback)

    def on_stop(self, callback: Callable[[], None]) -> None:
        """注册停止直播回调。"""
        self._on_stop_callbacks.append(callback)

    # ---- 公共访问 ----

    @property
    def state_machine(self) -> LiveStateMachine:
        """暴露状态机供外部读取。"""
        return self._state_machine

    @property
    def config(self) -> AppConfig:
        """暴露当前配置。"""
        return self._config

    def set_preview_window(self, preview: PreviewWindow) -> None:
        """注入预览窗口实例。"""
        self._preview_window = preview

    def set_system_tray(self, tray: AppSystemTray) -> None:
        """注入系统托盘实例。"""
        self._system_tray = tray

    # ---- UI 构建 ----

    def _setup_window(self) -> None:
        """设置主窗口属性。"""
        self.setWindowTitle("虚拟形象智能驱动系统")
        self.resize(600, 500)
        self.setMinimumSize(480, 400)

    def _setup_ui(self) -> None:
        """构建主窗口内容。"""
        central = QWidget(self)
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(12, 12, 12, 12)

        # ---- 状态栏 ----
        self._status_label = QLabel("状态：未准备", self)
        self._status_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        main_layout.addWidget(self._status_label)

        # ---- 设置页 ----
        self._settings_page = SettingsPage(self._config, self)
        self._settings_page.on_config_changed(self._on_config_changed)
        main_layout.addWidget(self._settings_page, stretch=1)

        # ---- 底部按钮 ----
        button_layout = QHBoxLayout()

        self._start_button = QPushButton("开始直播", self)
        self._start_button.setMinimumHeight(36)
        self._start_button.clicked.connect(self._on_start_pressed)
        button_layout.addWidget(self._start_button)

        self._stop_button = QPushButton("停止直播", self)
        self._stop_button.setMinimumHeight(36)
        self._stop_button.setEnabled(False)
        self._stop_button.clicked.connect(self._on_stop_pressed)
        button_layout.addWidget(self._stop_button)

        main_layout.addLayout(button_layout)

    # ---- 状态机联动 ----

    def _connect_state_machine(self) -> None:
        """绑定状态机变化到 UI。"""
        self._state_machine.on_state_changed(self._on_state_changed)

    def _on_state_changed(self, old: LiveState, new: LiveState) -> None:
        """状态变更时更新 UI 表达。"""
        state_text_map = {
            LiveState.IDLE: "状态：未准备",
            LiveState.PREPARING: "状态：准备中…",
            LiveState.RUNNING: "状态：运行中",
            LiveState.STOPPING: "状态：停止中…",
            LiveState.ERROR: f"状态：错误 - {self._state_machine.error_message}",
        }
        self._status_label.setText(state_text_map.get(new, "状态：未知"))

        # 更新按钮可用性
        self._start_button.setEnabled(self._state_machine.can_start)
        self._stop_button.setEnabled(self._state_machine.can_stop)

        # 错误状态自动弹出提示
        if new == LiveState.ERROR:
            QMessageBox.critical(
                self,
                "错误",
                self._state_machine.error_message or "发生未知错误",
            )

    # ---- 按钮事件 ----

    def _on_start_pressed(self) -> None:
        """用户点击"开始直播"。"""
        self._state_machine.start()
        for callback in self._on_start_callbacks:
            try:
                callback()
            except Exception as exc:  # noqa: BLE001
                LOGGER.error("开始回调异常：%s", exc)
                self._state_machine.on_error(str(exc))

    def _on_stop_pressed(self) -> None:
        """用户点击"停止直播"。"""
        self._state_machine.stop()
        for callback in self._on_stop_callbacks:
            try:
                callback()
            except Exception as exc:  # noqa: BLE001
                LOGGER.error("停止回调异常：%s", exc)

    # ---- 配置变更 ----

    def _on_config_changed(self, config: AppConfig) -> None:
        """设置页配置变更时持久化并同步预览窗口。"""
        save_config(config)
        if self._preview_window:
            self._preview_window.setVisible(config.preview_visible)

    # ---- 窗口关闭 ----

    def closeEvent(self, event) -> None:
        """关闭主窗口时直接退出应用。"""
        # 关闭预览窗口
        if self._preview_window:
            self._preview_window.close()

        # 触发应用退出，由 main.py 统一保存配置
        QApplication.quit()
        event.accept()
