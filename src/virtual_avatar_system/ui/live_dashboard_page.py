"""直播运行状态页模块。

职责：
- 在直播期间展示摄像头、麦克风、ASR、语义、情绪和动作状态
- 只负责 UI 展示，不直接启动或停止后端链路
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from virtual_avatar_system.business.comment_advisor import analyze_audience_comment
from virtual_avatar_system.comments.bilibili_comment_source import BilibiliComment, BilibiliCommentSource
from virtual_avatar_system.ui.log_panel import LogPanel

ASSETS_DIR = Path(__file__).resolve().parent / "assets"
DASHBOARD_CONTENT_MAX_WIDTH = 620


class LiveDashboardSignal(QObject):
    """跨线程安全的状态更新信号。"""

    update = Signal(str, str)
    bilibili_comment = Signal(str, str)
    bilibili_running = Signal(bool)


class LiveDashboardPage(QWidget):
    """直播期间的实时状态面板。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._bilibili_source = BilibiliCommentSource()
        self._bilibili_source.on_comment(self._emit_bilibili_comment)
        self._bilibili_source.on_status(self.update_bilibili_comment_status)
        self._bilibili_source.on_debug(self.append_backend_log)
        self._bilibili_source.on_running_changed(self._signal_bilibili_running)
        self._signal = LiveDashboardSignal()
        self._signal.update.connect(self._apply_update, Qt.ConnectionType.QueuedConnection)
        self._signal.bilibili_comment.connect(self._on_bilibili_comment_received, Qt.ConnectionType.QueuedConnection)
        self._signal.bilibili_running.connect(self._apply_bilibili_running, Qt.ConnectionType.QueuedConnection)
        self._on_audience_comment_callbacks: list[Callable[[str, str, str], None]] = []
        self._animation_index = 0
        self._dynamic_dot_labels: list[QLabel] = []
        self._wave_bars: list[QFrame] = []
        self._setup_ui()
        self._setup_live_animations()
        self.reset()

    def on_audience_comment(self, callback: Callable[[str, str, str], None]) -> None:
        """注册观众评论分析结果回调。"""
        self._on_audience_comment_callbacks.append(callback)

    def reset(self) -> None:
        """重置直播状态为等待启动。"""
        self.update_camera_connection_status("等待启动")
        self.update_face_detection_status("等待检测")
        self.update_microphone_connection_status("等待启动")
        self.update_microphone_listening_status("等待监听")
        self.update_asr_text("等待输入")
        self.update_semantic_label("待识别")
        self.update_emotion_result("中性")
        self.update_current_action("Idle")
        self.update_recommended_reply("等待观众评论")
        self.update_explanation_focus("等待评论输入")
        self.update_bilibili_comment_status("未接入")
        self._bilibili_source.stop()
        self._bilibili_room_input.clear()
        self._audience_comment_input.clear()
        self.clear_backend_log()

    def append_backend_log(self, text: str) -> None:
        """向后端输出面板追加一行日志。"""
        self._log_panel.append_log(text)

    def clear_backend_log(self) -> None:
        """清空后端输出日志。"""
        self._log_panel.clear()

    def update_camera_connection_status(self, text: str) -> None:
        """更新摄像头连接状态。"""
        self._signal.update.emit("camera_connection", text)

    def update_startup_stage(self, text: str) -> None:
        """兼容旧接口：运行页不再展示启动阶段。"""

    def update_camera_status(self, text: str) -> None:
        """兼容旧接口：按人脸检测状态展示。"""
        self.update_face_detection_status(text)

    def update_face_detection_status(self, text: str) -> None:
        """更新摄像头人脸检测状态。"""
        self._signal.update.emit("face_detection", text)

    def update_microphone_connection_status(self, text: str) -> None:
        """更新麦克风连接状态。"""
        self._signal.update.emit("microphone_connection", text)

    def update_microphone_status(self, text: str) -> None:
        """兼容旧接口：按监听状态展示。"""
        self.update_microphone_listening_status(text)

    def update_microphone_listening_status(self, text: str) -> None:
        """更新麦克风监听状态。"""
        self._signal.update.emit("microphone_listening", text)

    def update_asr_text(self, text: str) -> None:
        """更新 ASR 文本。"""
        self._signal.update.emit("asr", text or "等待输入")

    def update_semantic_label(self, text: str) -> None:
        """更新语义标签。"""
        self._signal.update.emit("semantic", text or "待识别")

    def update_emotion_result(self, text: str) -> None:
        """更新情绪结果。"""
        self._signal.update.emit("emotion", text or "中性")

    def update_current_action(self, text: str) -> None:
        """更新当前动作。"""
        self._signal.update.emit("motion", text or "Idle")

    def update_recommended_reply(self, text: str) -> None:
        """更新当前推荐回复。"""
        self._signal.update.emit("recommended_reply", text or "等待观众评论")

    def update_explanation_focus(self, text: str) -> None:
        """更新推荐讲解重点。"""
        self._signal.update.emit("explanation_focus", text or "等待评论输入")

    def update_bilibili_comment_status(self, text: str) -> None:
        """更新 B站评论接入状态。"""
        self._signal.update.emit("bilibili_status", text or "未接入")

    def _apply_update(self, field: str, text: str) -> None:
        """在 UI 线程中应用状态更新。"""
        label_map = {
            "camera_connection": self._camera_connection_value,
            "face_detection": self._face_detection_value,
            "microphone_connection": self._microphone_connection_value,
            "microphone_listening": self._microphone_listening_value,
            "asr": self._asr_value,
            "semantic": self._semantic_value,
            "emotion": self._emotion_value,
            "motion": self._motion_value,
            "recommended_reply": self._recommended_reply_value,
            "explanation_focus": self._explanation_focus_value,
            "bilibili_status": self._bilibili_status_value,
        }
        target = label_map.get(field)
        if target is not None:
            target.setText(text)
            if field == "explanation_focus":
                self._update_focus_tags(text)
            elif field == "semantic":
                self._update_semantic_tags(text)
            self._update_tile_indicator(field, text)

    def _on_prepare_bilibili_comment(self) -> None:
        """连接或断开 B站直播评论。"""
        if self._bilibili_source.is_running:
            self._bilibili_source.stop()
            return

        room_id = self._bilibili_room_input.text().strip()
        if not room_id:
            self.update_bilibili_comment_status("请先输入直播间号")
            return
        if not room_id.isdigit():
            self.update_bilibili_comment_status("直播间号应为数字")
            return
        self.update_bilibili_comment_status("正在连接 B站评论")
        self.append_backend_log(f"[Bilibili] 开始连接直播间：{room_id}")
        self._bilibili_source.start(int(room_id))

    def _emit_bilibili_comment(self, comment: BilibiliComment) -> None:
        """从后台线程把 B站评论投递到 UI 线程。"""
        self._signal.bilibili_comment.emit(comment.user_name, comment.text)

    def _signal_bilibili_running(self, running: bool) -> None:
        """从后台线程把连接状态投递到 UI 线程。"""
        self._signal.bilibili_running.emit(running)

    def _apply_bilibili_running(self, running: bool) -> None:
        """同步 B站连接按钮状态。"""
        self._bilibili_connect_button.setText("断开连接" if running else "连接 B站")
        self._bilibili_room_input.setEnabled(not running)
        room_text = self._bilibili_room_input.text().strip() if running else "等待连接"
        self._bilibili_room_label.setText(f"房间号：{room_text}")
        self._bilibili_status_badge.setProperty("connected", running)
        self._bilibili_status_badge.style().unpolish(self._bilibili_status_badge)
        self._bilibili_status_badge.style().polish(self._bilibili_status_badge)

    def _on_bilibili_comment_received(self, user_name: str, text: str) -> None:
        """收到 B站评论后自动刷新话术建议。"""
        display_text = f"{user_name}：{text}"
        self._latest_comment_value.setText(display_text)
        self._apply_comment_advice(text, log_manual=False, update_latest_comment=False)
        self.append_backend_log(f"[Bilibili] {display_text}")

    def _on_analyze_comment(self) -> None:
        """分析观众评论并刷新话术建议面板。"""
        comment = self._audience_comment_input.text()
        self._apply_comment_advice(comment)

    def _apply_comment_advice(
        self,
        comment: str,
        log_manual: bool = True,
        update_latest_comment: bool = True,
    ) -> None:
        """根据评论内容刷新语义标签和话术建议。"""
        advice = analyze_audience_comment(comment)
        # 当前最小版用规则模拟 LLM 语义理解，后续可替换为真实平台评论 + LLM 服务。
        self.update_semantic_label(advice.semantic_label)
        self.update_recommended_reply(advice.recommended_reply)
        self.update_explanation_focus(advice.explanation_focus)
        self._update_focus_tags(advice.explanation_focus)
        self._update_semantic_tags(advice.semantic_label)
        if update_latest_comment:
            self._latest_comment_value.setText(advice.audience_comment or "等待观众评论")
        if log_manual and advice.audience_comment:
            self.append_backend_log(f"[Comment] 观众评论={advice.audience_comment} 语义={advice.semantic_label}")
        if advice.audience_comment:
            for callback in self._on_audience_comment_callbacks:
                callback(advice.audience_comment, advice.semantic_label, advice.recommended_reply)

    def _setup_ui(self) -> None:
        """构建运行状态页布局。"""
        outer_layout = QHBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(14)

        outer_layout.addWidget(self._build_sidebar())

        self._dashboard_stack = QStackedWidget(self)
        self._dashboard_stack.setObjectName("dashboardContentStack")
        self._dashboard_stack.setMaximumWidth(DASHBOARD_CONTENT_MAX_WIDTH)
        self._dashboard_stack.addWidget(self._build_status_page())
        self._dashboard_stack.addWidget(self._build_comment_advice_page())
        self._dashboard_stack.addWidget(self._build_backend_log_page())
        outer_layout.addWidget(self._dashboard_stack, stretch=1)
        outer_layout.addStretch()
        self._apply_styles()
        self._set_active_panel(0)

    def _setup_live_animations(self) -> None:
        """启动直播页轻量动画，用于状态提示的动态反馈。"""
        self._animation_timer = QTimer(self)
        self._animation_timer.setInterval(220)
        self._animation_timer.timeout.connect(self._advance_live_animations)
        self._animation_timer.start()

    def _build_sidebar(self) -> QFrame:
        """创建左侧功能切换栏。"""
        sidebar = QFrame(self)
        sidebar.setObjectName("dashboardSidebar")
        sidebar.setFixedWidth(150)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(8, 8, 8, 10)
        layout.setSpacing(8)

        self._panel_buttons: list[QPushButton] = []
        nav_items = (
            ("activity.svg", "实时状态"),
            ("message.svg", "话术建议"),
            ("terminal.svg", "后台输出"),
        )
        for index, (icon_name, text) in enumerate(nav_items):
            button = QPushButton(text, self)
            button.setObjectName("dashboardNavButton")
            button.setCheckable(True)
            button.setIcon(self._asset_icon(icon_name))
            button.setIconSize(QSize(18, 18))
            button.setMinimumHeight(52)
            button.clicked.connect(lambda _checked=False, page_index=index: self._set_active_panel(page_index))
            layout.addWidget(button)
            self._panel_buttons.append(button)

        layout.addStretch()
        return sidebar

    def _build_status_page(self) -> QWidget:
        """创建右侧实时状态内容页。"""
        page = QWidget(self)
        page.setObjectName("dashboardPanelPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        status_card = QFrame(page)
        status_card.setObjectName("dashboardCard")
        self._apply_soft_shadow(status_card, blur=16, y_offset=4, alpha=18)
        status_layout = QGridLayout(status_card)
        status_layout.setContentsMargins(20, 18, 20, 18)
        status_layout.setHorizontalSpacing(10)
        status_layout.setVerticalSpacing(10)
        status_layout.setRowMinimumHeight(0, 28)
        status_layout.setRowMinimumHeight(1, 68)
        status_layout.setRowMinimumHeight(2, 68)
        status_layout.setRowMinimumHeight(3, 74)
        status_layout.setRowMinimumHeight(4, 74)
        status_layout.setRowMinimumHeight(5, 68)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(8)
        title_icon = QLabel(self)
        title_icon.setObjectName("dashboardTitleIcon")
        title_icon.setPixmap(self._asset_icon("activity.svg").pixmap(QSize(20, 20)))
        title_icon.setFixedSize(22, 22)
        title_row.addWidget(title_icon)

        title = QLabel("实时状态", self)
        title.setObjectName("dashboardTitle")
        title_row.addWidget(title)
        title_row.addStretch()
        status_layout.addLayout(title_row, 0, 0, 1, 2)

        self._camera_connection_value = self._create_value_label()
        self._face_detection_value = self._create_value_label()
        self._microphone_connection_value = self._create_value_label()
        self._microphone_listening_value = self._create_value_label()
        self._asr_value = self._create_value_label()
        self._semantic_value = self._create_value_label()
        self._emotion_value = self._create_value_label()
        self._motion_value = self._create_value_label()
        self._status_indicator_labels: dict[str, QLabel] = {}

        status_layout.addWidget(
            self._create_status_tile("摄像头连接", self._camera_connection_value, "camera.svg", "blue", "camera_connection"),
            1,
            0,
        )
        status_layout.addWidget(
            self._create_status_tile("人脸检测", self._face_detection_value, "face.svg", "purple", "face_detection"),
            1,
            1,
        )
        status_layout.addWidget(
            self._create_status_tile("麦克风连接", self._microphone_connection_value, "microphone.svg", "green", "microphone_connection"),
            2,
            0,
        )
        status_layout.addWidget(
            self._create_status_tile("监听状态", self._microphone_listening_value, "microphone.svg", "orange", trailing_kind="wave"),
            2,
            1,
        )
        status_layout.addWidget(
            self._create_status_tile("FunASR文本识别", self._asr_value, "text.svg", "blue", wide=True, trailing_kind="dots"),
            3,
            0,
            1,
            2,
        )
        status_layout.addWidget(
            self._create_status_tile("LLM语义标签", self._semantic_value, "robot.svg", "purple", wide=True, trailing_kind="dots"),
            4,
            0,
            1,
            2,
        )
        status_layout.addWidget(self._create_status_tile("情绪结果", self._emotion_value, "smile.svg", "red"), 5, 0)
        status_layout.addWidget(self._create_status_tile("当前动作", self._motion_value, "chip.svg", "cyan"), 5, 1)

        layout.addWidget(status_card)
        layout.addStretch()
        return page

    def _build_comment_advice_page(self) -> QWidget:
        """创建右侧话术建议内容页。"""
        page = QWidget(self)
        page.setObjectName("dashboardPanelPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_comment_advice_card())
        layout.addStretch()
        return page

    def _build_backend_log_page(self) -> QWidget:
        """创建右侧后台输出内容页。"""
        page = QWidget(self)
        page.setObjectName("dashboardPanelPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        card = QFrame(page)
        card.setObjectName("backendLogCard")
        self._apply_soft_shadow(card, blur=16, y_offset=4, alpha=18)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(20, 18, 20, 20)
        card_layout.setSpacing(12)

        self._log_panel = LogPanel(card)
        card_layout.addWidget(self._log_panel, stretch=1)
        layout.addWidget(card, stretch=1)
        return page

    def _set_active_panel(self, index: int) -> None:
        """切换右侧内容页并同步左侧导航状态。"""
        self._dashboard_stack.setCurrentIndex(index)
        for button_index, button in enumerate(self._panel_buttons):
            button.setChecked(button_index == index)
            button.setProperty("active", button_index == index)
            button.style().unpolish(button)
            button.style().polish(button)

    def _build_comment_advice_card(self) -> QFrame:
        """创建观众评论和话术建议面板。"""
        card = QFrame(self)
        card.setObjectName("adviceCard")
        self._apply_soft_shadow(card, blur=16, y_offset=4, alpha=18)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(9)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(10)

        title = QLabel("话术建议面板", self)
        title.setObjectName("dashboardTitle")
        header_row.addWidget(title)
        header_row.addStretch()

        self._advice_mode_buttons: list[QPushButton] = []
        for index, text in enumerate(("手动输入", "自动输入")):
            button = QPushButton(text, self)
            button.setObjectName("adviceModeButton")
            button.setCheckable(True)
            button.setFixedSize(88, 32)
            button.clicked.connect(lambda _checked=False, page_index=index: self._set_advice_input_mode(page_index))
            header_row.addWidget(button)
            self._advice_mode_buttons.append(button)
        layout.addLayout(header_row)

        self._advice_input_stack = QStackedWidget(self)
        self._advice_input_stack.setObjectName("adviceInputStack")
        self._advice_input_stack.addWidget(self._build_manual_comment_input_panel())
        self._advice_input_stack.addWidget(self._build_auto_comment_input_panel())
        layout.addWidget(self._advice_input_stack)
        self._set_advice_input_mode(0)

        self._latest_comment_value = self._create_value_label()
        self._latest_comment_value.setText("等待观众评论")
        layout.addWidget(self._create_auto_comment_tile())

        self._explanation_focus_value = self._create_value_label()
        self._explanation_focus_value.hide()
        layout.addWidget(self._create_focus_tile())

        self._recommended_reply_value = self._create_value_label()
        layout.addWidget(self._create_recommended_reply_card())
        layout.addStretch()
        return card

    def _build_auto_comment_input_panel(self) -> QWidget:
        """创建自动输入面板，负责接入 B站评论。"""
        panel = QWidget(self)
        panel.setObjectName("adviceInputPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        bilibili_row = QHBoxLayout()
        bilibili_row.setContentsMargins(0, 0, 0, 0)
        bilibili_row.setSpacing(10)
        self._bilibili_room_input = QLineEdit(self)
        self._bilibili_room_input.setObjectName("bilibiliRoomInput")
        self._bilibili_room_input.setPlaceholderText("输入 B站直播间号")
        self._bilibili_room_input.returnPressed.connect(self._on_prepare_bilibili_comment)
        bilibili_row.addWidget(self._bilibili_room_input, stretch=1)

        self._bilibili_connect_button = QPushButton("连接B站", self)
        self._bilibili_connect_button.setObjectName("prepareBilibiliButton")
        self._bilibili_connect_button.setFixedSize(98, 36)
        self._bilibili_connect_button.clicked.connect(self._on_prepare_bilibili_comment)
        bilibili_row.addWidget(self._bilibili_connect_button)
        layout.addLayout(bilibili_row)

        self._bilibili_status_value = self._create_value_label()
        self._bilibili_status_value.setText("未接入")
        layout.addWidget(self._create_bilibili_status_bar())
        return panel

    def _create_bilibili_status_bar(self) -> QFrame:
        """创建自动输入模式下的 B站连接状态条。"""
        bar = QFrame(self)
        bar.setObjectName("bilibiliStatusBar")
        bar.setMinimumHeight(44)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(16)

        logo = QLabel("bilibili", self)
        logo.setObjectName("bilibiliLogo")
        layout.addWidget(logo)

        self._bilibili_status_badge = QLabel("●", self)
        self._bilibili_status_badge.setObjectName("bilibiliStatusDot")
        self._bilibili_status_badge.setProperty("connected", False)
        layout.addWidget(self._bilibili_status_badge)

        layout.addWidget(self._bilibili_status_value)
        self._bilibili_room_label = QLabel("房间号：等待连接", self)
        self._bilibili_room_label.setObjectName("bilibiliMetaText")
        layout.addWidget(self._bilibili_room_label)
        layout.addStretch()

        refresh_icon = QLabel(self)
        refresh_icon.setObjectName("bilibiliRefreshIcon")
        refresh_icon.setPixmap(self._asset_icon("refresh.svg").pixmap(QSize(18, 18)))
        layout.addWidget(refresh_icon)
        return bar

    def _create_auto_comment_tile(self) -> QFrame:
        """创建当前观众评论展示卡片。"""
        tile = QFrame(self)
        tile.setObjectName("autoCommentTile")
        tile.setMinimumHeight(66)
        layout = QHBoxLayout(tile)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(12)
        layout.addWidget(self._create_icon_badge("comments.svg", "blue"), alignment=Qt.AlignmentFlag.AlignTop)

        text_group = QVBoxLayout()
        text_group.setContentsMargins(0, 0, 0, 0)
        text_group.setSpacing(4)
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(8)
        title = QLabel("当前观众评论", self)
        title.setObjectName("autoTileTitle")
        title_row.addWidget(title)
        realtime = QLabel("实时", self)
        realtime.setObjectName("realtimeBadge")
        title_row.addWidget(realtime)
        title_row.addStretch()
        text_group.addLayout(title_row)
        self._latest_comment_value.setObjectName("autoCommentValue")
        text_group.addWidget(self._latest_comment_value)
        layout.addLayout(text_group, stretch=1)
        return tile

    def _create_focus_tile(self) -> QFrame:
        """创建推荐讲解重点标签卡片。"""
        tile = QFrame(self)
        tile.setObjectName("focusTile")
        tile.setMinimumHeight(66)
        layout = QHBoxLayout(tile)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(12)
        layout.addWidget(self._create_icon_badge("lightbulb.svg", "blue"), alignment=Qt.AlignmentFlag.AlignTop)

        text_group = QVBoxLayout()
        text_group.setContentsMargins(0, 0, 0, 0)
        text_group.setSpacing(6)
        title = QLabel("推荐讲解重点", self)
        title.setObjectName("autoTileTitle")
        text_group.addWidget(title)

        self._focus_tags_layout = QHBoxLayout()
        self._focus_tags_layout.setContentsMargins(0, 0, 0, 0)
        self._focus_tags_layout.setSpacing(8)
        self._focus_tags_layout.addStretch()
        text_group.addLayout(self._focus_tags_layout)
        layout.addLayout(text_group, stretch=1)
        return tile

    def _create_recommended_reply_card(self) -> QFrame:
        """创建更醒目的当前推荐回复卡片。"""
        card = QFrame(self)
        card.setObjectName("recommendedReplyCard")
        card.setMinimumHeight(126)
        layout = QHBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(14)
        layout.addWidget(self._create_icon_badge("message-white.svg", "blueStrong"), alignment=Qt.AlignmentFlag.AlignTop)

        text_group = QVBoxLayout()
        text_group.setContentsMargins(0, 0, 0, 0)
        text_group.setSpacing(8)
        title = QLabel("当前推荐回复", self)
        title.setObjectName("recommendedReplyTitle")
        text_group.addWidget(title)
        self._recommended_reply_value.setObjectName("recommendedReplyValue")
        self._recommended_reply_value.setWordWrap(True)
        text_group.addWidget(self._recommended_reply_value)

        semantic_row = QHBoxLayout()
        semantic_row.setContentsMargins(0, 0, 0, 0)
        semantic_row.setSpacing(8)
        semantic_label = QLabel("语义标签：", self)
        semantic_label.setObjectName("semanticPrefix")
        semantic_row.addWidget(semantic_label)
        self._semantic_tags_layout = QHBoxLayout()
        self._semantic_tags_layout.setContentsMargins(0, 0, 0, 0)
        self._semantic_tags_layout.setSpacing(8)
        semantic_row.addLayout(self._semantic_tags_layout)
        semantic_row.addStretch()
        text_group.addLayout(semantic_row)
        layout.addLayout(text_group, stretch=1)
        return card

    def _create_icon_badge(self, icon_name: str, tone: str) -> QFrame:
        """创建话术建议页图标底座。"""
        badge = QFrame(self)
        badge.setObjectName("adviceIconBadge")
        badge.setProperty("tone", tone)
        badge.setFixedSize(44, 44)
        icon_layout = QVBoxLayout(badge)
        icon_layout.setContentsMargins(0, 0, 0, 0)
        icon = QLabel(self)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setPixmap(self._asset_icon(icon_name).pixmap(QSize(22, 22)))
        icon_layout.addWidget(icon)
        return badge

    def _update_focus_tags(self, text: str) -> None:
        """把讲解重点拆成标签展示。"""
        self._replace_tags(self._focus_tags_layout, [part.strip() for part in text.replace("、", "，").split("，") if part.strip()][:3])

    def _update_semantic_tags(self, text: str) -> None:
        """把语义标签拆成标签展示。"""
        self._replace_tags(self._semantic_tags_layout, [part.strip() for part in text.replace("/", "，").split("，") if part.strip()][:2])

    def _replace_tags(self, layout: QHBoxLayout, tags: list[str]) -> None:
        """清理旧标签并添加新的胶囊标签。"""
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
            # QSpacerItem 没有 widget，takeAt 后会被 Python 释放，避免旧 stretch 残留挤压标签。
        for tag in tags or ["等待输入"]:
            label = QLabel(tag, self)
            label.setObjectName("adviceTag")
            layout.addWidget(label)
        layout.addStretch()

    def _build_manual_comment_input_panel(self) -> QWidget:
        """创建手动输入面板，负责人工输入评论并触发分析。"""
        panel = QWidget(self)
        panel.setObjectName("adviceInputPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        input_row = QHBoxLayout()
        input_row.setContentsMargins(0, 0, 0, 0)
        input_row.setSpacing(10)

        self._audience_comment_input = QLineEdit(self)
        self._audience_comment_input.setObjectName("audienceCommentInput")
        self._audience_comment_input.setPlaceholderText("输入观众评论，例如：这个适合学生用吗？")
        self._audience_comment_input.returnPressed.connect(self._on_analyze_comment)
        input_row.addWidget(self._audience_comment_input, stretch=1)

        analyze_button = QPushButton("分析评论", self)
        analyze_button.setObjectName("analyzeCommentButton")
        analyze_button.setFixedSize(90, 34)
        analyze_button.clicked.connect(self._on_analyze_comment)
        input_row.addWidget(analyze_button)
        layout.addLayout(input_row)
        return panel

    def _set_advice_input_mode(self, index: int) -> None:
        """切换话术建议的评论输入来源。"""
        self._advice_input_stack.setCurrentIndex(index)
        for button_index, button in enumerate(self._advice_mode_buttons):
            active = button_index == index
            button.setChecked(active)
            button.setProperty("active", active)
            button.style().unpolish(button)
            button.style().polish(button)

    def _create_status_tile(
        self,
        label_text: str,
        value_label: QLabel,
        icon_name: str = "activity.svg",
        tone: str = "blue",
        indicator_key: str | None = None,
        wide: bool = False,
        trailing_text: str = "",
        trailing_kind: str = "",
    ) -> QFrame:
        """创建一块状态信息区域。"""
        tile = QFrame(self)
        tile.setObjectName("dashboardWideTile" if wide else "dashboardTile")
        tile.setMinimumHeight(74 if wide else 68)
        self._apply_soft_shadow(tile, blur=12, y_offset=3, alpha=12)

        layout = QHBoxLayout(tile)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(12)

        icon_badge = self._create_status_icon_badge(icon_name, tone)
        layout.addWidget(icon_badge, alignment=Qt.AlignmentFlag.AlignVCenter)

        text_group = QVBoxLayout()
        text_group.setContentsMargins(0, 0, 0, 0)
        text_group.setSpacing(3)

        label = QLabel(label_text, self)
        label.setObjectName("dashboardLabel")
        label.setMinimumHeight(20)
        text_group.addWidget(label)
        text_group.addWidget(value_label)
        layout.addLayout(text_group, stretch=1)

        if indicator_key is not None:
            indicator = QLabel(self)
            indicator.setObjectName("statusCheckIcon")
            indicator.setPixmap(self._asset_icon("x-circle.svg").pixmap(QSize(18, 18)))
            indicator.setFixedSize(20, 20)
            indicator.setVisible(True)
            self._status_indicator_labels[indicator_key] = indicator
            layout.addWidget(indicator, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        elif trailing_kind == "wave":
            trailing = QFrame(self)
            trailing.setObjectName("statusTrailingWave")
            trailing.setFixedWidth(38)
            trailing.setFixedHeight(26)
            wave_layout = QHBoxLayout(trailing)
            wave_layout.setContentsMargins(0, 0, 0, 0)
            wave_layout.setSpacing(3)
            wave_layout.setAlignment(Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter)
            self._wave_bars = []
            for height in (8, 16, 22, 12):
                bar = QFrame(self)
                bar.setObjectName("statusWaveBar")
                bar.setFixedSize(4, height)
                wave_layout.addWidget(bar, alignment=Qt.AlignmentFlag.AlignBottom)
                self._wave_bars.append(bar)
            layout.addWidget(trailing, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        elif trailing_kind == "dots" or trailing_text:
            trailing = QLabel(trailing_text or "•", self)
            trailing.setObjectName("statusTrailingDots")
            trailing.setProperty("tone", tone)
            trailing.setFixedWidth(28)
            trailing.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._dynamic_dot_labels.append(trailing)
            layout.addWidget(trailing, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return tile

    def _create_value_label(self) -> QLabel:
        """创建状态值标签。"""
        label = QLabel(self)
        label.setObjectName("dashboardValue")
        label.setWordWrap(True)
        label.setMinimumHeight(28)
        label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        return label

    def _asset_icon(self, icon_name: str) -> QIcon:
        """读取本地 SVG 图标资源。"""
        return QIcon(str(ASSETS_DIR / icon_name))

    def _create_status_icon_badge(self, icon_name: str, tone: str) -> QFrame:
        """创建状态卡片左侧彩色图标底座。"""
        badge = QFrame(self)
        badge.setObjectName("statusIconBadge")
        badge.setProperty("tone", tone)
        badge.setFixedSize(42, 42)

        layout = QVBoxLayout(badge)
        layout.setContentsMargins(0, 0, 0, 0)
        icon_label = QLabel(self)
        icon_label.setObjectName("statusIcon")
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setPixmap(self._asset_icon(icon_name).pixmap(QSize(22, 22)))
        layout.addWidget(icon_label)
        return badge

    def _apply_soft_shadow(self, widget: QWidget, blur: int, y_offset: int, alpha: int) -> None:
        """给主要卡片添加克制阴影，提升层级但不过度装饰。"""
        shadow = QGraphicsDropShadowEffect(widget)
        shadow.setBlurRadius(blur)
        shadow.setOffset(0, y_offset)
        shadow.setColor(QColor(15, 23, 42, alpha))
        widget.setGraphicsEffect(shadow)

    def _update_tile_indicator(self, field: str, text: str) -> None:
        """根据实时状态文本刷新右侧通过/异常标记。"""
        indicator = getattr(self, "_status_indicator_labels", {}).get(field)
        if indicator is None:
            return
        success = False
        if field in {"camera_connection", "microphone_connection"}:
            success = "已连接" in text or "连接正常" in text
        elif field == "face_detection":
            success = "检测到人脸" in text and "未检测" not in text
        elif field == "microphone_listening":
            success = "正在监听" in text
        icon_name = "check-circle.svg" if success else "x-circle.svg"
        indicator.setPixmap(self._asset_icon(icon_name).pixmap(QSize(18, 18)))
        indicator.setVisible(True)

    def _advance_live_animations(self) -> None:
        """推进声波和省略点动画。"""
        self._animation_index += 1

        dot_frames = ("•", "••", "•••")
        dot_text = dot_frames[self._animation_index % len(dot_frames)]
        for label in self._dynamic_dot_labels:
            label.setText(dot_text)

        if self._wave_bars:
            wave_frames = (
                (8, 16, 22, 12),
                (12, 22, 16, 8),
                (16, 8, 12, 22),
                (22, 12, 8, 16),
            )
            heights = wave_frames[self._animation_index % len(wave_frames)]
            for bar, height in zip(self._wave_bars, heights):
                bar.setFixedHeight(height)

    def _apply_styles(self) -> None:
        """设置运行状态页样式。"""
        self.setStyleSheet(
            """
            QFrame#dashboardCard {
                background: #FFFFFF;
                border: 1px solid #E5EAF2;
                border-radius: 12px;
            }
            QFrame#dashboardSidebar {
                background: rgba(255, 255, 255, 248);
                border: 1px solid #E2E8F0;
                border-radius: 12px;
            }
            QStackedWidget#dashboardContentStack,
            QStackedWidget#adviceInputStack,
            QWidget#adviceInputPanel,
            QWidget#dashboardPanelPage {
                background: transparent;
                border: 0;
            }
            QFrame#adviceCard {
                background: #FFFFFF;
                border: 1px solid #E5EAF2;
                border-radius: 12px;
            }
            QFrame#backendLogCard {
                background: #FFFFFF;
                border: 1px solid #E5EAF2;
                border-radius: 12px;
            }
            QFrame#dashboardTile,
            QFrame#dashboardWideTile {
                background: #FFFFFF;
                border: 1px solid #E6EEF8;
                border-radius: 10px;
            }
            QFrame#statusIconBadge {
                border: 0;
                border-radius: 10px;
            }
            QFrame#statusIconBadge[tone="blue"] {
                background: #EAF5FF;
            }
            QFrame#statusIconBadge[tone="purple"] {
                background: #F3E8FF;
            }
            QFrame#statusIconBadge[tone="green"] {
                background: #DCFCE7;
            }
            QFrame#statusIconBadge[tone="orange"] {
                background: #FFEDD5;
            }
            QFrame#statusIconBadge[tone="red"] {
                background: #FEE2E2;
            }
            QFrame#statusIconBadge[tone="cyan"] {
                background: #CCFBF1;
            }
            QLabel#statusIcon {
                background: transparent;
                border: 0;
            }
            QLabel#statusCheckIcon {
                background: transparent;
                border: 0;
            }
            QLabel#statusTrailingDots {
                background: transparent;
                border: 0;
                color: #1677FF;
                font-size: 13px;
                font-weight: 800;
                letter-spacing: 0px;
            }
            QLabel#statusTrailingDots[tone="purple"] {
                color: #7C3AED;
            }
            QFrame#statusTrailingWave {
                background: transparent;
                border: 0;
            }
            QFrame#statusWaveBar {
                background: #60A5FA;
                border: 0;
                border-radius: 2px;
            }
            QLabel#dashboardTitle {
                color: #0F172A;
                font-size: 18px;
                font-weight: 800;
            }
            QLabel#dashboardTitleIcon {
                background: transparent;
                border: 0;
            }
            QLabel#dashboardLabel {
                color: #64748B;
                font-size: 12px;
                font-weight: 600;
            }
            QLabel#dashboardValue {
                color: #0F172A;
                font-size: 15px;
                font-weight: 700;
            }
            QPushButton#dashboardNavButton {
                background: transparent;
                border: 0;
                border-radius: 8px;
                color: #0F172A;
                font-size: 15px;
                font-weight: 800;
                padding: 0 14px;
                text-align: left;
            }
            QPushButton#dashboardNavButton:hover {
                background: #F6FAFF;
                color: #0F172A;
            }
            QPushButton#dashboardNavButton[active="true"] {
                background: #EAF5FF;
                color: #1677FF;
                border-left: 3px solid #1677FF;
            }
            QPushButton#adviceModeButton {
                background: #F8FAFC;
                border: 1px solid #E2E8F0;
                border-radius: 7px;
                color: #475569;
                font-size: 12px;
                font-weight: 700;
                padding: 0 16px;
            }
            QPushButton#adviceModeButton:hover {
                background: #F1F5F9;
                color: #0F172A;
            }
            QPushButton#adviceModeButton[active="true"] {
                background: #EAF5FF;
                border: 1px solid #BFDBFE;
                color: #1677FF;
            }
            QLineEdit#audienceCommentInput {
                background: #FFFFFF;
                border: 1px solid #DDE3EA;
                border-radius: 7px;
                color: #0F172A;
                font-size: 13px;
                min-height: 32px;
                padding: 0 12px;
            }
            QLineEdit#audienceCommentInput:focus {
                border: 1px solid #2563EB;
            }
            QLineEdit#bilibiliRoomInput {
                background: #FFFFFF;
                border: 1px solid #DDE3EA;
                border-radius: 7px;
                color: #0F172A;
                font-size: 13px;
                min-height: 32px;
                padding: 0 12px;
            }
            QLineEdit#bilibiliRoomInput:focus {
                border: 1px solid #2563EB;
            }
            QPushButton#prepareBilibiliButton {
                background: #1677FF;
                border: 0;
                border-radius: 7px;
                color: #FFFFFF;
                font-size: 13px;
                font-weight: 700;
            }
            QPushButton#prepareBilibiliButton:hover {
                background: #0958D9;
            }
            QFrame#bilibiliStatusBar {
                background: #FFFFFF;
                border: 1px solid #E2E8F0;
                border-radius: 9px;
            }
            QLabel#bilibiliLogo {
                color: #EC5A8F;
                font-size: 20px;
                font-weight: 900;
                font-style: italic;
            }
            QLabel#bilibiliStatusDot {
                color: #94A3B8;
                font-size: 15px;
                font-weight: 900;
            }
            QLabel#bilibiliStatusDot[connected="true"] {
                color: #52C41A;
            }
            QLabel#bilibiliMetaText {
                color: #475569;
                font-size: 13px;
                font-weight: 700;
            }
            QLabel#bilibiliRefreshIcon {
                background: transparent;
                border: 0;
            }
            QFrame#autoCommentTile,
            QFrame#focusTile {
                background: #FFFFFF;
                border: 1px solid #E2E8F0;
                border-radius: 9px;
            }
            QFrame#adviceIconBadge {
                background: #EAF2FF;
                border: 0;
                border-radius: 9px;
            }
            QFrame#adviceIconBadge[tone="blueStrong"] {
                background: #1677FF;
            }
            QLabel#autoTileTitle {
                color: #334155;
                font-size: 13px;
                font-weight: 700;
            }
            QLabel#realtimeBadge {
                background: #DCFCE7;
                border: 1px solid #BBF7D0;
                border-radius: 5px;
                color: #10B981;
                font-size: 12px;
                font-weight: 800;
                padding: 2px 8px;
            }
            QLabel#autoCommentValue {
                color: #0F172A;
                font-size: 14px;
                font-weight: 650;
            }
            QLabel#adviceTag {
                background: #F8FAFC;
                border: 1px solid #CBD5E1;
                border-radius: 6px;
                color: #334155;
                font-size: 12px;
                font-weight: 650;
                padding: 3px 10px;
            }
            QFrame#recommendedReplyCard {
                background: #FFFFFF;
                border: 1px solid #E2E8F0;
                border-radius: 10px;
            }
            QLabel#recommendedReplyTitle {
                color: #0F172A;
                font-size: 16px;
                font-weight: 800;
            }
            QLabel#recommendedReplyValue {
                color: #1E293B;
                font-size: 14px;
                font-weight: 650;
                line-height: 1.45;
            }
            QLabel#semanticPrefix {
                color: #475569;
                font-size: 12px;
                font-weight: 650;
            }
            QPushButton#analyzeCommentButton {
                background: #1677FF;
                border: 0;
                border-radius: 7px;
                color: #FFFFFF;
                font-size: 13px;
                font-weight: 700;
            }
            QPushButton#analyzeCommentButton:hover {
                background: #0958D9;
            }
            """
        )
