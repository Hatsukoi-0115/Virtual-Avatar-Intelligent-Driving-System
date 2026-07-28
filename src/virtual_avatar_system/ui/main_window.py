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

from PySide6.QtCore import QDateTime, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon
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
from virtual_avatar_system.reporting.live_report_generator import LiveReportSummary
from virtual_avatar_system.ui.live_dashboard_page import LiveDashboardPage
from virtual_avatar_system.ui.live_report_summary_page import LiveReportSummaryPage
from virtual_avatar_system.ui.live_state_machine import LiveState, LiveStateMachine
from virtual_avatar_system.ui.settings_page import SettingsPage
from virtual_avatar_system.ui.system_tray import AppSystemTray

LOGGER = logging.getLogger(__name__)
ASSETS_DIR = Path(__file__).resolve().parent / "assets"
CONFIG_WINDOW_SIZE: tuple[int, int] = (820, 700)
CONFIG_MIN_SIZE: tuple[int, int] = (780, 640)
CONFIG_MAX_WIDTH = 840
LOADING_WINDOW_SIZE: tuple[int, int] = (480, 340)
LOADING_MIN_SIZE: tuple[int, int] = (460, 320)
LOADING_MAX_WIDTH = 540


class MainWindow(QMainWindow):
    """应用主窗口。"""

    def __init__(self, config: AppConfig) -> None:
        super().__init__()
        self._config = config
        self._state_machine = LiveStateMachine()
        self._system_tray: AppSystemTray | None = None
        self._showing_report_summary = False
        self._last_loading_pulse_ms = 0

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

    def on_audience_comment(self, callback: Callable[[str, str, str], None]) -> None:
        """注册观众评论分析结果回调。"""
        self._live_dashboard.on_audience_comment(callback)

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
        """兼容旧接口：更新直播页人脸检测状态。"""
        self.update_face_detection_status(text)

    def update_camera_connection_status(self, text: str) -> None:
        """更新直播页摄像头连接状态。"""
        self._live_dashboard.update_camera_connection_status(text)

    def update_face_detection_status(self, text: str) -> None:
        """更新直播页人脸检测状态。"""
        self._live_dashboard.update_face_detection_status(text)

    def update_startup_stage(self, text: str) -> None:
        """更新启动/停止加载页阶段。"""
        self._loading_stage_label.setText(text or "准备启动")
        self.pulse_loading_animation()

    def pulse_loading_animation(self, frames: int = 1) -> None:
        """在同步启动/停止步骤中主动刷新加载图标。"""
        if not self._loading_spinner_timer.isActive():
            return
        now_ms = QDateTime.currentMSecsSinceEpoch()
        if now_ms - self._last_loading_pulse_ms < 220:
            QApplication.processEvents()
            return
        self._last_loading_pulse_ms = now_ms
        for _ in range(max(1, frames)):
            self._advance_loading_spinner()
        QApplication.processEvents()

    def update_microphone_status(self, text: str) -> None:
        """兼容旧接口：更新直播页监听状态。"""
        self.update_microphone_listening_status(text)

    def update_microphone_connection_status(self, text: str) -> None:
        """更新直播页麦克风连接状态。"""
        self._live_dashboard.update_microphone_connection_status(text)

    def update_microphone_listening_status(self, text: str) -> None:
        """更新直播页麦克风监听状态。"""
        self._live_dashboard.update_microphone_listening_status(text)

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

    def show_live_report_summary(self, summary: LiveReportSummary) -> None:
        """停止直播后展示本次直播报告摘要。"""
        self._showing_report_summary = True
        self._report_summary_page.set_summary(summary)
        self._apply_config_window_size()
        self._show_report_header()
        self._content_stack.setCurrentWidget(self._report_summary_page)
        self._status_label.setText("报告已生成")
        self._status_badge.setProperty("status", "ready")
        self._status_label.setProperty("status", "ready")
        self._status_dot.setObjectName("statusDotReady")
        self._status_badge.style().unpolish(self._status_badge)
        self._status_badge.style().polish(self._status_badge)
        self._status_label.style().unpolish(self._status_label)
        self._status_label.style().polish(self._status_label)
        self._status_dot.style().unpolish(self._status_dot)
        self._status_dot.style().polish(self._status_dot)
        self._set_action_button("←  返回主页", True, "start")

    def return_to_home(self) -> None:
        """从报告摘要页返回开播前配置页。"""
        self._showing_report_summary = False
        self._apply_config_window_size()
        self._show_default_header()
        self._content_stack.setCurrentWidget(self._settings_page)
        self._on_state_changed(self._state_machine.current_state, self._state_machine.current_state)

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
        main_layout.setContentsMargins(22, 18, 22, 20)
        main_layout.setSpacing(14)

        self._header = self._build_header()
        main_layout.addWidget(self._header)

        self._settings_page = SettingsPage(self._config, self)
        self._settings_page.on_config_changed(self._on_config_changed)
        self._settings_page.config_validity_changed.connect(self._on_config_validity_changed)

        self._loading_page = self._build_loading_page()
        self._live_dashboard = LiveDashboardPage(self)
        self._report_summary_page = LiveReportSummaryPage(self)
        self._content_stack = QStackedWidget(self)
        self._content_stack.addWidget(self._settings_page)
        self._content_stack.addWidget(self._loading_page)
        self._content_stack.addWidget(self._live_dashboard)
        self._content_stack.addWidget(self._report_summary_page)
        main_layout.addWidget(self._content_stack, stretch=1)
        self._action_footer = self._build_action_footer()
        main_layout.addWidget(self._action_footer)

        self._apply_styles()

    def _build_header(self) -> QFrame:
        """创建顶部标题栏和状态徽章。"""
        header = QFrame(self)
        header.setObjectName("header")

        layout = QHBoxLayout(header)
        layout.setContentsMargins(4, 0, 6, 0)
        layout.setSpacing(14)

        self._brand_mark = QLabel("VA", self)
        self._brand_mark.setObjectName("brandMark")
        self._brand_mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._brand_mark.setFixedSize(46, 46)
        layout.addWidget(self._brand_mark)

        title_group = QVBoxLayout()
        title_group.setContentsMargins(0, 0, 0, 0)
        title_group.setSpacing(4)

        self._title_label = QLabel("虚拟形象智能驱动系统", self)
        self._title_label.setObjectName("titleLabel")
        title_group.addWidget(self._title_label)

        self._subtitle_label = QLabel("配置驱动参数，开启智能直播", self)
        self._subtitle_label.setObjectName("subtitleLabel")
        title_group.addWidget(self._subtitle_label)
        layout.addLayout(title_group)
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

    def _show_default_header(self) -> None:
        """恢复开播前和直播中的主窗口 Header。"""
        self._brand_mark.clear()
        self._brand_mark.setText("VA")
        self._title_label.setText("虚拟形象智能驱动系统")
        self._subtitle_label.setText("配置驱动参数，开启智能直播")
        self._header.setVisible(True)

    def _show_report_header(self) -> None:
        """把主窗口 Header 切换为直播报告摘要标题。"""
        self._brand_mark.setText("")
        self._brand_mark.setPixmap(QIcon(str(ASSETS_DIR / "report-white.svg")).pixmap(QSize(24, 24)))
        self._title_label.setText("直播报告摘要")
        self._subtitle_label.setText("本次直播已结束，系统已沉淀 ASR、情绪、语义和动作事件记录。")
        self._header.setVisible(True)

    def _build_action_footer(self) -> QFrame:
        """创建底部主操作区。"""
        footer = QFrame(self)
        footer.setObjectName("actionFooter")

        layout = QVBoxLayout(footer)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        self._action_button = QPushButton("▶  开始直播", self)
        self._action_button.setObjectName("primaryActionButton")
        self._action_button.setMinimumSize(280, 50)
        self._action_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._action_button.clicked.connect(self._on_action_pressed)

        button_shadow = QGraphicsDropShadowEffect(self._action_button)
        button_shadow.setBlurRadius(22)
        button_shadow.setOffset(0, 8)
        button_shadow.setColor(QColor(37, 99, 235, 58))
        self._action_button.setGraphicsEffect(button_shadow)
        layout.addWidget(self._action_button, alignment=Qt.AlignmentFlag.AlignHCenter)

        self._action_hint_label = QLabel("点击开始直播，系统将自动启动所有服务", self)
        self._action_hint_label.setObjectName("actionHint")
        self._action_hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._action_hint_label, alignment=Qt.AlignmentFlag.AlignHCenter)

        return footer

    def _build_loading_page(self) -> QWidget:
        """创建开播准备阶段的紧凑加载页。"""
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addStretch()

        card = QFrame(self)
        card.setObjectName("loadingCard")
        card.setMinimumHeight(170)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(22, 20, 22, 20)
        card_layout.setSpacing(10)

        self._loading_indicator = QFrame(self)
        self._loading_indicator.setObjectName("loadingIndicator")
        self._loading_indicator.setFixedSize(46, 46)
        indicator_layout = QHBoxLayout(self._loading_indicator)
        indicator_layout.setContentsMargins(11, 10, 11, 10)
        indicator_layout.setSpacing(3)
        indicator_layout.setAlignment(Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter)

        self._loading_spinner_bars: list[QFrame] = []
        for height in (8, 16, 22, 12):
            bar = QFrame(self)
            bar.setObjectName("loadingSpinnerBar")
            bar.setProperty("mode", "starting")
            bar.setFixedSize(4, height)
            indicator_layout.addWidget(bar, alignment=Qt.AlignmentFlag.AlignBottom)
            self._loading_spinner_bars.append(bar)
        card_layout.addWidget(self._loading_indicator, alignment=Qt.AlignmentFlag.AlignHCenter)

        self._loading_title_label = QLabel("正在启动直播", self)
        self._loading_title_label.setObjectName("loadingTitle")
        self._loading_title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._loading_title_label.setMinimumHeight(32)
        card_layout.addWidget(self._loading_title_label)

        self._loading_stage_label = QLabel("准备启动", self)
        self._loading_stage_label.setObjectName("loadingStage")
        self._loading_stage_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._loading_stage_label.setWordWrap(True)
        self._loading_stage_label.setMinimumHeight(30)
        card_layout.addWidget(self._loading_stage_label)

        loading_hint = QLabel("请稍候", self)
        loading_hint.setObjectName("loadingHint")
        loading_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        loading_hint.setMinimumHeight(24)
        card_layout.addWidget(loading_hint)

        layout.addWidget(card)
        layout.addStretch()

        self._loading_spinner_frames = (
            (8, 16, 22, 12),
            (12, 22, 16, 8),
            (16, 8, 12, 22),
            (22, 12, 8, 16),
        )
        self._loading_spinner_index = 0
        self._loading_spinner_timer = QTimer(self)
        self._loading_spinner_timer.setInterval(220)
        self._loading_spinner_timer.timeout.connect(self._advance_loading_spinner)
        return page

    def _apply_styles(self) -> None:
        """集中设置主窗口视觉样式。"""
        self.setStyleSheet(
            """
            QWidget#root {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #F8FBFF, stop:0.58 #F4F8FC, stop:1 #EEF6FF);
                color: #0F172A;
                font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei UI", "Microsoft YaHei", sans-serif;
                font-size: 13px;
            }
            QLabel#brandMark {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #3B82F6, stop:1 #1D4ED8);
                border: 0;
                border-radius: 12px;
                color: #FFFFFF;
                font-size: 19px;
                font-weight: 800;
            }
            QLabel#titleLabel {
                color: #0F172A;
                font-size: 24px;
                font-weight: 800;
            }
            QLabel#subtitleLabel {
                color: #64748B;
                font-size: 14px;
                font-weight: 500;
            }
            QFrame#statusBadge {
                background: #FEF2F2;
                border: 1px solid #FECACA;
                border-radius: 16px;
                min-height: 44px;
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
                font-size: 16px;
                font-weight: 800;
            }
            QLabel#statusText[status="ready"],
            QLabel#statusText[status="running"] {
                color: #10B981;
            }
            QLabel#statusText[status="preparing"],
            QLabel#statusText[status="stopping"] {
                color: #D97706;
            }
            QLabel#statusText[status="idle"],
            QLabel#statusText[status="error"] {
                color: #EF4444;
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
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #2563EB, stop:1 #1D4ED8);
                border: 0;
                border-radius: 10px;
                color: white;
                font-size: 20px;
                font-weight: 700;
                padding: 0 22px;
            }
            QPushButton#primaryActionButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #1D4ED8, stop:1 #1E40AF);
            }
            QPushButton#primaryActionButton:pressed {
                background: #1E40AF;
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
            QLabel#actionHint {
                color: #64748B;
                font-size: 13px;
                font-weight: 500;
            }
            QFrame#actionFooter {
                background: transparent;
                border: 0;
            }
            QFrame#loadingCard {
                background: #FFFFFF;
                border: 1px solid #E2E8F0;
                border-radius: 10px;
            }
            QFrame#loadingIndicator {
                background: #EFF6FF;
                border: 1px solid #BFDBFE;
                border-radius: 23px;
            }
            QFrame#loadingIndicator[mode="stopping"] {
                background: #FEF2F2;
                border: 1px solid #FECACA;
            }
            QFrame#loadingSpinnerBar {
                background: #60A5FA;
                border: 0;
                border-radius: 2px;
            }
            QFrame#loadingSpinnerBar[mode="stopping"] {
                background: #F87171;
            }
            QLabel#loadingTitle {
                color: #0F172A;
                font-size: 17px;
                font-weight: 700;
            }
            QLabel#loadingStage {
                color: #2563EB;
                font-size: 13px;
                font-weight: 600;
            }
            QLabel#loadingHint {
                color: #64748B;
                font-size: 12px;
                font-weight: 500;
            }
            """
        )

    def _set_loading_animation_active(self, active: bool, mode: str = "starting") -> None:
        """控制加载页动态图标，避免离开加载页后继续刷新。"""
        self._loading_indicator.setProperty("mode", mode)
        self._last_loading_pulse_ms = 0
        for bar in self._loading_spinner_bars:
            bar.setProperty("mode", mode)
        for widget in (self._loading_indicator, *self._loading_spinner_bars):
            widget.style().unpolish(widget)
            widget.style().polish(widget)

        if active and not self._loading_spinner_timer.isActive():
            self._loading_spinner_timer.start()
            return
        if not active and self._loading_spinner_timer.isActive():
            self._loading_spinner_timer.stop()

    def _advance_loading_spinner(self) -> None:
        """推进加载图标帧，给重资源启动/停止阶段提供动态反馈。"""
        self._loading_spinner_index = (self._loading_spinner_index + 1) % len(self._loading_spinner_frames)
        heights = self._loading_spinner_frames[self._loading_spinner_index]
        for bar, height in zip(self._loading_spinner_bars, heights):
            bar.setFixedHeight(height)

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
            self._set_loading_animation_active(True, "starting")
            self._apply_loading_window_size()
            self._show_default_header()
            self._content_stack.setCurrentWidget(self._loading_page)
        elif new == LiveState.STOPPING:
            self._loading_title_label.setText("正在停止直播")
            self._set_loading_animation_active(True, "stopping")
            self._apply_loading_window_size()
            self._show_default_header()
            self._content_stack.setCurrentWidget(self._loading_page)
        elif new == LiveState.RUNNING:
            self._set_loading_animation_active(False)
            self._apply_config_window_size()
            self._show_default_header()
            self._content_stack.setCurrentWidget(self._live_dashboard)
        elif self._showing_report_summary:
            # 停播后保持报告摘要页，避免状态回到 IDLE 时立刻跳回配置页。
            self._set_loading_animation_active(False)
            self._apply_config_window_size()
            self._show_report_header()
            self._content_stack.setCurrentWidget(self._report_summary_page)
        else:
            self._set_loading_animation_active(False)
            self._apply_config_window_size()
            self._show_default_header()
            self._content_stack.setCurrentWidget(self._settings_page)

        if self._showing_report_summary:
            status_text = "报告已生成"
            status_name = "ready"
            dot_name = "statusDotReady"
        else:
            status_text = state_text_map.get(new, "未知")
            status_name = badge_status_map.get(new, "idle")
            dot_name = dot_style_map.get(new, "statusDotIdle")

        self._status_label.setText(status_text)
        self._status_badge.setProperty("status", status_name)
        self._status_label.setProperty("status", status_name)
        self._status_dot.setObjectName(dot_name)
        self._status_badge.style().unpolish(self._status_badge)
        self._status_badge.style().polish(self._status_badge)
        self._status_label.style().unpolish(self._status_label)
        self._status_label.style().polish(self._status_label)
        self._status_dot.style().unpolish(self._status_dot)
        self._status_dot.style().polish(self._status_dot)

        if new == LiveState.RUNNING:
            self._set_action_button("■  停止直播", True, "stop")
            self._action_footer.setVisible(True)
        elif new == LiveState.PREPARING:
            self._set_action_button("准备中", False, "start")
            self._action_footer.setVisible(False)
        elif new == LiveState.STOPPING:
            self._set_action_button("停止中", False, "stop")
            self._action_footer.setVisible(False)
        elif new == LiveState.ERROR:
            self._set_action_button("▶  重试启动", True, "start")
            self._action_footer.setVisible(True)
        elif self._showing_report_summary:
            self._set_action_button("←  返回主页", True, "start")
            self._action_footer.setVisible(True)
        else:
            self._action_footer.setVisible(True)
            if is_config_valid:
                self._set_action_button("▶  开始直播", self._state_machine.can_start, "start")
            else:
                self._set_action_button("请先完成测试", False, "start")

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
        self._action_button.setMinimumWidth(340 if "返回主页" in text else 280)
        self._action_button.setProperty("mode", mode)
        self._action_button.style().unpolish(self._action_button)
        self._action_button.style().polish(self._action_button)
        if mode == "stop":
            self._action_hint_label.setText("停止直播后，系统将生成本次直播报告")
        elif "返回主页" in text:
            self._action_hint_label.setText("查看完报告后，可返回配置主页")
        elif enabled:
            self._action_hint_label.setText("点击开始直播，系统将自动启动所有服务")
        else:
            self._action_hint_label.setText("请先完成摄像头、麦克风、人物模型和 LLM 连接测试")

    # ---- 按钮事件 ----

    def _on_action_pressed(self) -> None:
        """根据当前状态执行开始、停止或错误恢复。"""
        if self._showing_report_summary:
            self.return_to_home()
            return
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
        self._showing_report_summary = False
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
