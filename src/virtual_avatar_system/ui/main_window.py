"""主窗口模块。

职责：
- 托管设置页、顶部状态徽章和底部主操作按钮
- 通过 LiveStateMachine 控制直播状态
- 与 SystemTray 联动
- 只负责 UI 交互，不包含业务逻辑
"""

from __future__ import annotations

import logging
from typing import Callable

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from virtual_avatar_system.config.app_config import AppConfig, save_config
from virtual_avatar_system.ui.live_state_machine import LiveState, LiveStateMachine
from virtual_avatar_system.ui.settings_page import SettingsPage
from virtual_avatar_system.ui.system_tray import AppSystemTray

LOGGER = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """应用主窗口。"""

    def __init__(self, config: AppConfig) -> None:
        super().__init__()
        self._config = config
        self._state_machine = LiveStateMachine()
        self._system_tray: AppSystemTray | None = None

        self._on_start_callbacks: list[Callable[[], None]] = []
        self._on_stop_callbacks: list[Callable[[], None]] = []

        self._setup_window()
        self._setup_ui()
        self._connect_state_machine()
        self._on_state_changed(self._state_machine.current_state, self._state_machine.current_state)

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

    def set_system_tray(self, tray: AppSystemTray) -> None:
        """注入系统托盘实例。"""
        self._system_tray = tray

    # ---- UI 构建 ----

    def _setup_window(self) -> None:
        """设置主窗口属性。"""
        self.setWindowTitle("虚拟形象智能驱动系统")
        self.resize(680, 720)
        self.setMinimumSize(620, 680)
        self.setMaximumWidth(720)

    def _setup_ui(self) -> None:
        """构建主窗口内容。"""
        central = QWidget(self)
        central.setObjectName("root")
        self.setCentralWidget(central)

        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(26, 26, 26, 22)
        main_layout.setSpacing(18)

        main_layout.addWidget(self._build_header())

        self._settings_page = SettingsPage(self._config, self)
        self._settings_page.on_config_changed(self._on_config_changed)
        main_layout.addWidget(self._settings_page, stretch=1)

        footer = QFrame(self)
        footer.setObjectName("footer")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(0, 28, 0, 0)
        footer_layout.addStretch()

        self._action_button = QPushButton("▶  开始直播", self)
        self._action_button.setObjectName("primaryActionButton")
        self._action_button.setMinimumSize(210, 52)
        self._action_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._action_button.clicked.connect(self._on_action_pressed)

        button_shadow = QGraphicsDropShadowEffect(self._action_button)
        button_shadow.setBlurRadius(20)
        button_shadow.setOffset(0, 5)
        button_shadow.setColor(QColor(15, 79, 145, 90))
        self._action_button.setGraphicsEffect(button_shadow)

        footer_layout.addWidget(self._action_button)
        footer_layout.addStretch()

        main_layout.addWidget(footer)
        self._apply_styles()

    def _build_header(self) -> QFrame:
        """创建顶部标题栏和状态徽章。"""
        header = QFrame(self)
        header.setObjectName("header")

        layout = QHBoxLayout(header)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        icon_label = QLabel(self)
        icon = QApplication.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
        icon_label.setPixmap(icon.pixmap(28, 28))
        layout.addWidget(icon_label)

        title_label = QLabel("虚拟形象智能驱动系统", self)
        title_label.setObjectName("titleLabel")
        layout.addWidget(title_label)
        layout.addStretch()

        status_badge = QFrame(self)
        status_badge.setObjectName("statusBadge")
        status_layout = QHBoxLayout(status_badge)
        status_layout.setContentsMargins(14, 0, 16, 0)
        status_layout.setSpacing(10)

        self._status_dot = QLabel(self)
        self._status_dot.setObjectName("statusDotIdle")
        self._status_dot.setFixedSize(10, 10)
        status_layout.addWidget(self._status_dot)

        self._status_label = QLabel("未准备", self)
        self._status_label.setObjectName("statusText")
        status_layout.addWidget(self._status_label)
        layout.addWidget(status_badge)

        return header

    def _apply_styles(self) -> None:
        """集中设置主窗口视觉样式。"""
        self.setStyleSheet(
            """
            QWidget#root {
                background: #eef2f6;
                color: #111827;
                font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
                font-size: 14px;
            }
            QLabel#titleLabel {
                color: #111827;
                font-size: 22px;
                font-weight: 800;
            }
            QFrame#statusBadge {
                background: #f8fafc;
                border: 1px solid #d8dee8;
                border-radius: 18px;
                min-height: 36px;
            }
            QLabel#statusText {
                color: #374151;
                font-size: 14px;
                font-weight: 600;
            }
            QLabel#statusDotIdle {
                background: #ef4444;
                border-radius: 5px;
            }
            QLabel#statusDotPreparing {
                background: #d19a1f;
                border-radius: 5px;
            }
            QLabel#statusDotRunning {
                background: #16a34a;
                border-radius: 5px;
            }
            QLabel#statusDotError {
                background: #b91c1c;
                border-radius: 5px;
            }
            QPushButton#primaryActionButton {
                background: #0f4f91;
                border: 0;
                border-radius: 10px;
                color: white;
                font-size: 18px;
                font-weight: 800;
                padding: 0 28px;
            }
            QPushButton#primaryActionButton:hover {
                background: #0b437d;
            }
            QPushButton#primaryActionButton:pressed {
                background: #083766;
            }
            QPushButton#primaryActionButton:disabled {
                background: #c7d2e0;
                color: #64748b;
            }
            QPushButton#primaryActionButton[mode="stop"] {
                background: #dc2626;
            }
            QPushButton#primaryActionButton[mode="stop"]:hover {
                background: #b91c1c;
            }
            """
        )

    # ---- 状态机联动 ----

    def _connect_state_machine(self) -> None:
        """绑定状态机变化到 UI。"""
        self._state_machine.on_state_changed(self._on_state_changed)

    def _on_state_changed(self, old: LiveState, new: LiveState) -> None:
        """状态变更时更新顶部徽章和主按钮。"""
        state_text_map = {
            LiveState.IDLE: "未准备",
            LiveState.PREPARING: "准备中",
            LiveState.RUNNING: "运行中",
            LiveState.STOPPING: "停止中",
            LiveState.ERROR: f"错误：{self._state_machine.error_message}",
        }
        dot_style_map = {
            LiveState.IDLE: "statusDotIdle",
            LiveState.PREPARING: "statusDotPreparing",
            LiveState.RUNNING: "statusDotRunning",
            LiveState.STOPPING: "statusDotPreparing",
            LiveState.ERROR: "statusDotError",
        }
        self._status_label.setText(state_text_map.get(new, "未知"))
        self._status_dot.setObjectName(dot_style_map.get(new, "statusDotIdle"))
        self._status_dot.style().unpolish(self._status_dot)
        self._status_dot.style().polish(self._status_dot)

        if new == LiveState.RUNNING:
            self._set_action_button("■  停止直播", True, "stop")
        elif new == LiveState.PREPARING:
            self._set_action_button("准备中", False, "start")
        elif new == LiveState.STOPPING:
            self._set_action_button("停止中", False, "stop")
        elif new == LiveState.ERROR:
            self._set_action_button("▶  重试启动", True, "start")
        else:
            self._set_action_button("▶  开始直播", self._state_machine.can_start, "start")

        if new == LiveState.ERROR:
            QMessageBox.critical(
                self,
                "错误",
                self._state_machine.error_message or "发生未知错误",
            )

    def _set_action_button(self, text: str, enabled: bool, mode: str) -> None:
        """同步底部主按钮的文案、可用状态和视觉层级。"""
        self._action_button.setText(text)
        self._action_button.setEnabled(enabled)
        self._action_button.setProperty("mode", mode)
        self._action_button.style().unpolish(self._action_button)
        self._action_button.style().polish(self._action_button)

    # ---- 按钮事件 ----

    def _on_action_pressed(self) -> None:
        """根据当前状态执行开始、停止或错误恢复。"""
        state = self._state_machine.current_state
        if state == LiveState.RUNNING:
            self._on_stop_pressed()
            return
        if state == LiveState.ERROR:
            self._state_machine.reset()
        if self._state_machine.can_start:
            self._on_start_pressed()

    def _on_start_pressed(self) -> None:
        """用户点击开始直播。"""
        self._state_machine.start()
        for callback in self._on_start_callbacks:
            try:
                callback()
            except Exception as exc:  # noqa: BLE001
                LOGGER.error("开始回调异常：%s", exc)
                self._state_machine.on_error(str(exc))

    def _on_stop_pressed(self) -> None:
        """用户点击停止直播。"""
        self._state_machine.stop()
        for callback in self._on_stop_callbacks:
            try:
                callback()
            except Exception as exc:  # noqa: BLE001
                LOGGER.error("停止回调异常：%s", exc)

    # ---- 配置变更 ----

    def _on_config_changed(self, config: AppConfig) -> None:
        """设置页配置变更时持久化。"""
        save_config(config)

    # ---- 窗口关闭 ----

    def closeEvent(self, event) -> None:
        """关闭主窗口时直接退出应用。"""
        QApplication.quit()
        event.accept()
