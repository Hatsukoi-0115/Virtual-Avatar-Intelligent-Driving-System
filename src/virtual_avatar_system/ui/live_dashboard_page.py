"""直播运行状态页模块。

职责：
- 在直播期间展示摄像头、麦克风、ASR、语义、情绪和动作状态
- 只负责 UI 展示，不直接启动或停止后端链路
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from virtual_avatar_system.ui.log_panel import LogPanel


class LiveDashboardSignal(QObject):
    """跨线程安全的状态更新信号。"""

    update = Signal(str, str)


class LiveDashboardPage(QWidget):
    """直播期间的实时状态面板。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._signal = LiveDashboardSignal()
        self._signal.update.connect(self._apply_update, Qt.ConnectionType.QueuedConnection)
        self._setup_ui()
        self.reset()

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
        }
        target = label_map.get(field)
        if target is not None:
            target.setText(text)

    def _setup_ui(self) -> None:
        """构建运行状态页布局。"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        status_card = QFrame(self)
        status_card.setObjectName("dashboardCard")
        status_card.setMinimumHeight(430)
        status_layout = QGridLayout(status_card)
        status_layout.setContentsMargins(18, 16, 18, 18)
        status_layout.setHorizontalSpacing(12)
        status_layout.setVerticalSpacing(10)
        status_layout.setRowMinimumHeight(0, 30)
        status_layout.setRowMinimumHeight(1, 78)
        status_layout.setRowMinimumHeight(2, 78)
        status_layout.setRowMinimumHeight(3, 78)
        status_layout.setRowMinimumHeight(4, 82)
        status_layout.setRowMinimumHeight(5, 82)

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
        self._log_panel = LogPanel(self)
        layout.addWidget(self._log_panel, stretch=1)
        layout.addStretch()
        self._apply_styles()

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
            """
        )
