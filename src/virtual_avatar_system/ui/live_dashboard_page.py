"""直播运行状态页模块。

职责：
- 在直播期间展示摄像头、麦克风、ASR、语义、情绪和动作状态
- 只负责 UI 展示，不直接启动或停止后端链路
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
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
        self._setup_ui()
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
        self._bilibili_connect_button.setText("断开" if running else "连接B站")
        self._bilibili_room_input.setEnabled(not running)

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
        self._dashboard_stack.addWidget(self._build_status_page())
        self._dashboard_stack.addWidget(self._build_comment_advice_page())
        self._dashboard_stack.addWidget(self._build_backend_log_page())
        outer_layout.addWidget(self._dashboard_stack, stretch=1)
        self._apply_styles()
        self._set_active_panel(0)

    def _build_sidebar(self) -> QFrame:
        """创建左侧功能切换栏。"""
        sidebar = QFrame(self)
        sidebar.setObjectName("dashboardSidebar")
        sidebar.setFixedWidth(132)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(10, 12, 10, 12)
        layout.setSpacing(8)

        self._panel_buttons: list[QPushButton] = []
        for index, text in enumerate(("实时状态", "话术建议", "后台输出")):
            button = QPushButton(text, self)
            button.setObjectName("dashboardNavButton")
            button.setCheckable(True)
            button.setMinimumHeight(38)
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
        status_layout = QGridLayout(status_card)
        status_layout.setContentsMargins(18, 16, 18, 18)
        status_layout.setHorizontalSpacing(12)
        status_layout.setVerticalSpacing(10)
        status_layout.setRowMinimumHeight(0, 30)
        status_layout.setRowMinimumHeight(1, 78)
        status_layout.setRowMinimumHeight(2, 78)
        status_layout.setRowMinimumHeight(3, 82)
        status_layout.setRowMinimumHeight(4, 82)
        status_layout.setRowMinimumHeight(5, 78)

        title = QLabel("实时状态", self)
        title.setObjectName("dashboardTitle")
        status_layout.addWidget(title, 0, 0, 1, 2)

        self._camera_connection_value = self._create_value_label()
        self._face_detection_value = self._create_value_label()
        self._microphone_connection_value = self._create_value_label()
        self._microphone_listening_value = self._create_value_label()
        self._asr_value = self._create_value_label()
        self._semantic_value = self._create_value_label()
        self._emotion_value = self._create_value_label()
        self._motion_value = self._create_value_label()

        status_layout.addWidget(self._create_status_tile("摄像头连接", self._camera_connection_value), 1, 0)
        status_layout.addWidget(self._create_status_tile("人脸检测", self._face_detection_value), 1, 1)
        status_layout.addWidget(self._create_status_tile("麦克风连接", self._microphone_connection_value), 2, 0)
        status_layout.addWidget(self._create_status_tile("监听状态", self._microphone_listening_value), 2, 1)
        status_layout.addWidget(self._create_status_tile("FunASR文本识别", self._asr_value, wide=True), 3, 0, 1, 2)
        status_layout.addWidget(self._create_status_tile("LLM语义标签", self._semantic_value, wide=True), 4, 0, 1, 2)
        status_layout.addWidget(self._create_status_tile("情绪结果", self._emotion_value), 5, 0)
        status_layout.addWidget(self._create_status_tile("当前动作", self._motion_value), 5, 1)

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
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(18, 16, 18, 18)
        card_layout.setSpacing(10)

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
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 18)
        layout.setSpacing(12)

        title = QLabel("话术建议面板", self)
        title.setObjectName("dashboardTitle")
        layout.addWidget(title)

        mode_row = QHBoxLayout()
        mode_row.setContentsMargins(0, 0, 0, 0)
        mode_row.setSpacing(8)
        self._advice_mode_buttons: list[QPushButton] = []
        for index, text in enumerate(("手动输入", "自动输入")):
            button = QPushButton(text, self)
            button.setObjectName("adviceModeButton")
            button.setCheckable(True)
            button.setFixedHeight(34)
            button.clicked.connect(lambda _checked=False, page_index=index: self._set_advice_input_mode(page_index))
            mode_row.addWidget(button)
            self._advice_mode_buttons.append(button)
        mode_row.addStretch()
        layout.addLayout(mode_row)

        self._advice_input_stack = QStackedWidget(self)
        self._advice_input_stack.setObjectName("adviceInputStack")
        self._advice_input_stack.addWidget(self._build_manual_comment_input_panel())
        self._advice_input_stack.addWidget(self._build_auto_comment_input_panel())
        layout.addWidget(self._advice_input_stack)
        self._set_advice_input_mode(0)

        self._latest_comment_value = self._create_value_label()
        self._latest_comment_value.setText("等待观众评论")
        layout.addWidget(self._create_status_tile("当前观众评论", self._latest_comment_value, wide=True))

        advice_grid = QGridLayout()
        advice_grid.setContentsMargins(0, 0, 0, 0)
        advice_grid.setHorizontalSpacing(12)
        advice_grid.setVerticalSpacing(8)
        self._recommended_reply_value = self._create_value_label()
        self._explanation_focus_value = self._create_value_label()
        advice_grid.addWidget(self._create_status_tile("当前推荐回复", self._recommended_reply_value, wide=True), 0, 0)
        advice_grid.addWidget(self._create_status_tile("推荐讲解重点", self._explanation_focus_value, wide=True), 1, 0)
        layout.addLayout(advice_grid)
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
        self._bilibili_connect_button.setFixedSize(96, 36)
        self._bilibili_connect_button.clicked.connect(self._on_prepare_bilibili_comment)
        bilibili_row.addWidget(self._bilibili_connect_button)
        layout.addLayout(bilibili_row)

        self._bilibili_status_value = self._create_value_label()
        self._bilibili_status_value.setText("未接入")
        layout.addWidget(self._create_status_tile("B站评论接入状态", self._bilibili_status_value, wide=True))
        return panel

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
        analyze_button.setFixedSize(96, 36)
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

    def _create_status_tile(self, label_text: str, value_label: QLabel, wide: bool = False) -> QFrame:
        """创建一块状态信息区域。"""
        tile = QFrame(self)
        tile.setObjectName("dashboardWideTile" if wide else "dashboardTile")
        tile.setMinimumHeight(82 if wide else 78)
        layout = QVBoxLayout(tile)
        layout.setContentsMargins(12, 9, 12, 10)
        layout.setSpacing(4)

        label = QLabel(label_text, self)
        label.setObjectName("dashboardLabel")
        label.setMinimumHeight(20)
        layout.addWidget(label)
        layout.addWidget(value_label)
        return tile

    def _create_value_label(self) -> QLabel:
        """创建状态值标签。"""
        label = QLabel(self)
        label.setObjectName("dashboardValue")
        label.setWordWrap(True)
        label.setMinimumHeight(34)
        label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        return label

    def _apply_styles(self) -> None:
        """设置运行状态页样式。"""
        self.setStyleSheet(
            """
            QFrame#dashboardCard {
                background: #FFFFFF;
                border: 1px solid #E5E7EB;
                border-radius: 8px;
            }
            QFrame#dashboardSidebar {
                background: #FFFFFF;
                border: 1px solid #E5E7EB;
                border-radius: 8px;
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
                border: 1px solid #DDE7F3;
                border-radius: 8px;
            }
            QFrame#backendLogCard {
                background: #FFFFFF;
                border: 1px solid #DDE7F3;
                border-radius: 8px;
            }
            QFrame#dashboardTile,
            QFrame#dashboardWideTile {
                background: #F8FAFC;
                border: 1px solid #E2E8F0;
                border-radius: 8px;
            }
            QLabel#dashboardTitle {
                color: #0F172A;
                font-size: 15px;
                font-weight: 700;
            }
            QLabel#dashboardLabel {
                color: #64748B;
                font-size: 12px;
                font-weight: 600;
            }
            QLabel#dashboardValue {
                color: #0F172A;
                font-size: 14px;
                font-weight: 600;
            }
            QPushButton#dashboardNavButton {
                background: transparent;
                border: 0;
                border-radius: 8px;
                color: #475569;
                font-size: 13px;
                font-weight: 700;
                padding: 0 12px;
                text-align: left;
            }
            QPushButton#dashboardNavButton:hover {
                background: #F1F5F9;
                color: #0F172A;
            }
            QPushButton#dashboardNavButton[active="true"] {
                background: #EFF6FF;
                color: #2563EB;
            }
            QPushButton#adviceModeButton {
                background: #F8FAFC;
                border: 1px solid #E2E8F0;
                border-radius: 8px;
                color: #475569;
                font-size: 13px;
                font-weight: 700;
                padding: 0 18px;
            }
            QPushButton#adviceModeButton:hover {
                background: #F1F5F9;
                color: #0F172A;
            }
            QPushButton#adviceModeButton[active="true"] {
                background: #EFF6FF;
                border: 1px solid #BFDBFE;
                color: #2563EB;
            }
            QLineEdit#audienceCommentInput {
                background: #FFFFFF;
                border: 1px solid #CBD5E1;
                border-radius: 8px;
                color: #0F172A;
                font-size: 13px;
                min-height: 34px;
                padding: 0 12px;
            }
            QLineEdit#audienceCommentInput:focus {
                border: 1px solid #2563EB;
            }
            QLineEdit#bilibiliRoomInput {
                background: #FFFFFF;
                border: 1px solid #CBD5E1;
                border-radius: 8px;
                color: #0F172A;
                font-size: 13px;
                min-height: 34px;
                padding: 0 12px;
            }
            QLineEdit#bilibiliRoomInput:focus {
                border: 1px solid #2563EB;
            }
            QPushButton#prepareBilibiliButton {
                background: #0EA5E9;
                border: 0;
                border-radius: 8px;
                color: #FFFFFF;
                font-size: 13px;
                font-weight: 700;
            }
            QPushButton#prepareBilibiliButton:hover {
                background: #0284C7;
            }
            QPushButton#analyzeCommentButton {
                background: #2563EB;
                border: 0;
                border-radius: 8px;
                color: #FFFFFF;
                font-size: 13px;
                font-weight: 700;
            }
            QPushButton#analyzeCommentButton:hover {
                background: #1D4ED8;
            }
            """
        )
