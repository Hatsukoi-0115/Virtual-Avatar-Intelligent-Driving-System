"""主窗口模块。

职责：
- 托管设置页、顶部状态徽章和底部主操作按钮
- 通过 LiveStateMachine 控制直播状态
- 与 SystemTray 联动
- 只负责 UI 交互，不包含业务逻辑
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase
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
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from virtual_avatar_system.config.app_config import AppConfig, save_config, save_llm_env
from virtual_avatar_system.ui.live_dashboard_page import LiveDashboardPage
from virtual_avatar_system.ui.live_state_machine import LiveState, LiveStateMachine
from virtual_avatar_system.ui.settings_page import SettingsPage
from virtual_avatar_system.ui.system_tray import AppSystemTray

LOGGER = logging.getLogger(__name__)
CONFIG_WINDOW_SIZE: tuple[int, int] = (680, 660)
CONFIG_MIN_SIZE: tuple[int, int] = (620, 620)
CONFIG_MAX_WIDTH = 720
LOADING_WINDOW_SIZE: tuple[int, int] = (440, 300)
LOADING_MIN_SIZE: tuple[int, int] = (400, 260)
LOADING_MAX_WIDTH = 520


class MainWindow(QMainWindow):
    """应用主窗口。"""

    def __init__(self, config: AppConfig) -> None:
        super().__init__()
        self._config = config
        self._state_machine = LiveStateMachine()
        self._system_tray: AppSystemTray | None = None

        self._on_start_callbacks: list[Callable[[], None]] = []
        self._on_stop_callbacks: list[Callable[[], None]] = []

        self._configure_ui_font()
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

    def append_backend_log(self, text: str) -> None:
        """向后端输出面板追加一行日志。"""
        self._live_dashboard.append_backend_log(text)

    def reset_live_dashboard(self) -> None:
        """重置直播运行状态页。"""
        self._live_dashboard.reset()

    def update_camera_status(self, text: str) -> None:
        """更新直播页摄像头状态。"""
        self._live_dashboard.update_camera_status(text)

    def update_startup_stage(self, text: str) -> None:
        """更新直播页启动阶段。"""
        self._live_dashboard.update_startup_stage(text)
        self._loading_stage_label.setText(text or "准备启动")

    def update_microphone_status(self, text: str) -> None:
        """更新直播页麦克风状态。"""
        self._live_dashboard.update_microphone_status(text)

    def update_asr_text(self, text: str) -> None:
        """更新直播页 ASR 文本。"""
        self._live_dashboard.update_asr_text(text)

    def update_semantic_label(self, text: str) -> None:
        """更新直播页语义标签。"""
        self._live_dashboard.update_semantic_label(text)

    def update_emotion_result(self, text: str) -> None:
        """更新直播页情绪结果。"""
        self._live_dashboard.update_emotion_result(text)

    def update_current_action(self, text: str) -> None:
        """更新直播页当前动作。"""
        self._live_dashboard.update_current_action(text)

    # ---- UI 构建 ----

    def _setup_window(self) -> None:
        """设置主窗口属性。"""
        self.setWindowTitle("虚拟形象智能驱动系统")
        self.resize(*CONFIG_WINDOW_SIZE)
        self.setMinimumSize(*CONFIG_MIN_SIZE)
        self.setMaximumWidth(CONFIG_MAX_WIDTH)

    def _configure_ui_font(self) -> None:
        """主动加载中文字体，避免部分 Qt 环境回退到缺字形字体。"""
        fonts_dir = Path("C:/Windows/Fonts")
        font_files = (
            fonts_dir / "NotoSansSC-VF.ttf",
            fonts_dir / "msyh.ttc",
            fonts_dir / "simhei.ttf",
            fonts_dir / "simsun.ttc",
        )
        loaded_families: list[str] = []
        for font_file in font_files:
            if not font_file.exists():
                continue
            font_id = QFontDatabase.addApplicationFont(str(font_file))
            if font_id >= 0:
                loaded_families.extend(QFontDatabase.applicationFontFamilies(font_id))

        app = QApplication.instance()
        if app is not None and loaded_families:
            preferred = next(
                (family for family in ("Noto Sans SC", "Microsoft YaHei UI", "Microsoft YaHei", "SimHei") if family in loaded_families),
                loaded_families[0],
            )
            app.setFont(QFont(preferred, 9))

    def _setup_ui(self) -> None:
        """构建主窗口内容。"""
        central = QWidget(self)
        central.setObjectName("root")
        self.setCentralWidget(central)

        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(24, 24, 24, 20)
        main_layout.setSpacing(16)

        main_layout.addWidget(self._build_header())

        self._settings_page = SettingsPage(self._config, self)
        self._settings_page.on_config_changed(self._on_config_changed)
        self._settings_page.config_validity_changed.connect(self._on_config_validity_changed)

        self._loading_page = self._build_loading_page()
        self._live_dashboard = LiveDashboardPage(self)
        self._content_stack = QStackedWidget(self)
        self._content_stack.addWidget(self._settings_page)
        self._content_stack.addWidget(self._loading_page)
        self._content_stack.addWidget(self._live_dashboard)
        main_layout.addWidget(self._content_stack, stretch=1)

        footer = QFrame(self)
        footer.setObjectName("footer")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(0, 14, 0, 0)
        footer_layout.addStretch()

        self._action_button = QPushButton("▶  开始直播", self)
        self._action_button.setObjectName("primaryActionButton")
        self._action_button.setMinimumSize(196, 46)
        self._action_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._action_button.clicked.connect(self._on_action_pressed)

        button_shadow = QGraphicsDropShadowEffect(self._action_button)
        button_shadow.setBlurRadius(16)
        button_shadow.setOffset(0, 4)
        button_shadow.setColor(QColor(2, 132, 199, 64))
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

        brand_mark = QLabel("VA", self)
        brand_mark.setObjectName("brandMark")
        brand_mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        brand_mark.setFixedSize(28, 28)
        layout.addWidget(brand_mark)

        title_label = QLabel("虚拟形象智能驱动系统", self)
        title_label.setObjectName("titleLabel")
        layout.addWidget(title_label)
        layout.addStretch()

        self._status_badge = QFrame(self)
        self._status_badge.setObjectName("statusBadge")
        self._status_badge.setProperty("status", "idle")
        status_layout = QHBoxLayout(self._status_badge)
        status_layout.setContentsMargins(14, 0, 16, 0)
        status_layout.setSpacing(8)

        self._status_dot = QLabel(self)
        self._status_dot.setObjectName("statusDotIdle")
        self._status_dot.setFixedSize(8, 8)
        status_layout.addWidget(self._status_dot)

        self._status_label = QLabel("未准备", self)
        self._status_label.setObjectName("statusText")
        status_layout.addWidget(self._status_label)
        layout.addWidget(self._status_badge)

        return header

    def _build_loading_page(self) -> QWidget:
        """创建开播准备阶段的紧凑加载页。"""
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.setSpacing(16)
        layout.addStretch()

        card = QFrame(self)
        card.setObjectName("loadingCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(22, 20, 22, 20)
        card_layout.setSpacing(10)

        self._loading_title_label = QLabel("正在启动直播", self)
        self._loading_title_label.setObjectName("loadingTitle")
        self._loading_title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(self._loading_title_label)

        self._loading_stage_label = QLabel("准备启动", self)
        self._loading_stage_label.setObjectName("loadingStage")
        self._loading_stage_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._loading_stage_label.setWordWrap(True)
        card_layout.addWidget(self._loading_stage_label)

        layout.addWidget(card)
        layout.addStretch()
        return page

    def _apply_styles(self) -> None:
        """集中设置主窗口视觉样式。"""
        self.setStyleSheet(
            """
            QWidget#root {
                background: #F8FAFC;
                color: #0F172A;
                font-family: "Noto Sans SC", "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", sans-serif;
                font-size: 13px;
            }
            QLabel#brandMark {
                background: #E0F2FE;
                border: 1px solid #BAE6FD;
                border-radius: 8px;
                color: #0284C7;
                font-size: 11px;
                font-weight: 800;
            }
            QLabel#titleLabel {
                color: #0F172A;
                font-size: 16px;
                font-weight: 700;
            }
            QFrame#statusBadge {
                background: #FEF2F2;
                border: 1px solid #FECACA;
                border-radius: 12px;
                min-height: 28px;
            }
            QFrame#statusBadge[status="ready"],
            QFrame#statusBadge[status="running"] {
                background: #ECFDF5;
                border: 1px solid #A7F3D0;
            }
            QFrame#statusBadge[status="preparing"],
            QFrame#statusBadge[status="stopping"] {
                background: #FFFBEB;
                border: 1px solid #FDE68A;
            }
            QFrame#statusBadge[status="error"] {
                background: #FEF2F2;
                border: 1px solid #FCA5A5;
            }
            QLabel#statusText {
                color: #EF4444;
                font-size: 13px;
                font-weight: 600;
            }
            QFrame#statusBadge[status="ready"] QLabel#statusText,
            QFrame#statusBadge[status="running"] QLabel#statusText {
                color: #10B981;
            }
            QFrame#statusBadge[status="preparing"] QLabel#statusText,
            QFrame#statusBadge[status="stopping"] QLabel#statusText {
                color: #D97706;
            }
            QLabel#statusDotIdle {
                background: #EF4444;
                border-radius: 4px;
            }
            QLabel#statusDotReady {
                background: #10B981;
                border-radius: 4px;
            }
            QLabel#statusDotPreparing {
                background: #D97706;
                border-radius: 4px;
            }
            QLabel#statusDotRunning {
                background: #10B981;
                border-radius: 4px;
            }
            QLabel#statusDotError {
                background: #EF4444;
                border-radius: 4px;
            }
            QPushButton#primaryActionButton {
                background: #0284C7;
                border: 0;
                border-radius: 8px;
                color: white;
                font-size: 15px;
                font-weight: 700;
                padding: 0 24px;
            }
            QPushButton#primaryActionButton:hover {
                background: #0369A1;
            }
            QPushButton#primaryActionButton:pressed {
                background: #075985;
            }
            QPushButton#primaryActionButton:disabled {
                background: #E2E8F0;
                color: #64748b;
            }
            QPushButton#primaryActionButton[mode="stop"] {
                background: #DC2626;
            }
            QPushButton#primaryActionButton[mode="stop"]:hover {
                background: #B91C1C;
            }
            QFrame#loadingCard {
                background: #FFFFFF;
                border: 1px solid #E2E8F0;
                border-radius: 12px;
            }
            QLabel#loadingTitle {
                color: #0F172A;
                font-size: 17px;
                font-weight: 700;
            }
            QLabel#loadingStage {
                color: #2563EB;
                font-size: 14px;
                font-weight: 600;
            }
            """
        )

    # ---- 状态机联动 ----

    def _apply_config_window_size(self) -> None:
        """恢复配置页和运行页使用的主窗口尺寸。"""
        self.setMinimumSize(*CONFIG_MIN_SIZE)
        self.setMaximumWidth(CONFIG_MAX_WIDTH)
        self.resize(*CONFIG_WINDOW_SIZE)

    def _apply_loading_window_size(self) -> None:
        """切换到开播准备阶段使用的紧凑窗口尺寸。"""
        self.setMinimumSize(*LOADING_MIN_SIZE)
        self.setMaximumWidth(LOADING_MAX_WIDTH)
        self.resize(*LOADING_WINDOW_SIZE)

    def _connect_state_machine(self) -> None:
        """绑定状态机变化到 UI。"""
        self._state_machine.on_state_changed(self._on_state_changed)

    def _on_state_changed(self, old: LiveState, new: LiveState) -> None:
        """状态变更时更新顶部徽章和主按钮。"""
        is_config_valid = self._settings_page.is_config_valid()
        state_text_map = {
            LiveState.IDLE: "已就绪" if is_config_valid else "未准备",
            LiveState.PREPARING: "准备中",
            LiveState.RUNNING: "运行中",
            LiveState.STOPPING: "停止中",
            LiveState.ERROR: f"错误：{self._state_machine.error_message}",
        }
        dot_style_map = {
            LiveState.IDLE: "statusDotReady" if is_config_valid else "statusDotIdle",
            LiveState.PREPARING: "statusDotPreparing",
            LiveState.RUNNING: "statusDotRunning",
            LiveState.STOPPING: "statusDotPreparing",
            LiveState.ERROR: "statusDotError",
        }
        badge_status_map = {
            LiveState.IDLE: "ready" if is_config_valid else "idle",
            LiveState.PREPARING: "preparing",
            LiveState.RUNNING: "running",
            LiveState.STOPPING: "stopping",
            LiveState.ERROR: "error",
        }
        # 准备和停止阶段都使用轻量加载页，避免重资源加载/释放期间给用户卡住的错觉。
        if new == LiveState.PREPARING:
            self._loading_title_label.setText("正在启动直播")
            self._apply_loading_window_size()
            self._content_stack.setCurrentWidget(self._loading_page)
        elif new == LiveState.STOPPING:
            self._loading_title_label.setText("正在停止直播")
            self._apply_loading_window_size()
            self._content_stack.setCurrentWidget(self._loading_page)
        elif new == LiveState.RUNNING:
            self._apply_config_window_size()
            self._content_stack.setCurrentWidget(self._live_dashboard)
        else:
            self._apply_config_window_size()
            self._content_stack.setCurrentWidget(self._settings_page)

        self._status_label.setText(state_text_map.get(new, "未知"))
        self._status_badge.setProperty("status", badge_status_map.get(new, "idle"))
        self._status_dot.setObjectName(dot_style_map.get(new, "statusDotIdle"))
        self._status_badge.style().unpolish(self._status_badge)
        self._status_badge.style().polish(self._status_badge)
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
            if is_config_valid:
                self._set_action_button("▶  开始直播", self._state_machine.can_start, "start")
            else:
                self._set_action_button("请先配置参数", False, "start")

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
        if not self._settings_page.is_config_valid():
            return
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
        save_llm_env(config)
        if self._state_machine.current_state == LiveState.IDLE:
            self._on_state_changed(LiveState.IDLE, LiveState.IDLE)

    def _on_config_validity_changed(self, _valid: bool) -> None:
        """配置有效性变化时同步启动按钮和顶部状态。"""
        if self._state_machine.current_state == LiveState.IDLE:
            self._on_state_changed(LiveState.IDLE, LiveState.IDLE)

    # ---- 窗口关闭 ----

    def closeEvent(self, event) -> None:
        """关闭主窗口时直接退出应用。"""
        QApplication.quit()
        event.accept()
