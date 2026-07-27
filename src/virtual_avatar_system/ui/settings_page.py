"""设置页模块。

职责：
- 提供摄像头、麦克风、模型路径等配置界面
- 配置变更后同步写入 AppConfig
- 只负责设置项采集，不直接启动业务链路
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QColor, QIntValidator, QPalette
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from virtual_avatar_system.audio.source import list_available_microphone_devices
from virtual_avatar_system.config.app_config import (
    AppConfig,
    project_relative_path,
    resolve_project_path,
)
from virtual_avatar_system.vision.camera_source import list_available_camera_indices

LOGGER = logging.getLogger(__name__)


class NoWheelComboBox(QComboBox):
    """禁止鼠标滚轮在未展开下拉菜单时误切换选项。"""

    def wheelEvent(self, event) -> None:
        """忽略滚轮事件，避免滚动页面时改掉配置。"""
        event.ignore()


class UnitInput(QFrame):
    """带右侧单位徽标的数字输入控件。"""

    valueChanged = Signal(int)

    def __init__(self, unit: str, minimum: int, maximum: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._minimum = minimum
        self._maximum = maximum

        self.setObjectName("unitInput")
        self.setFixedSize(118, 40)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 8, 0)
        layout.setSpacing(6)

        self._line_edit = QLineEdit(self)
        self._line_edit.setObjectName("unitInputEdit")
        self._line_edit.setValidator(QIntValidator(minimum, maximum, self))
        self._line_edit.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._line_edit.textChanged.connect(self._on_text_changed)
        layout.addWidget(self._line_edit, stretch=1)

        unit_label = QLabel(unit, self)
        unit_label.setObjectName("unitBadge")
        unit_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        unit_label.setFixedSize(28, 28)
        layout.addWidget(unit_label)

    def value(self) -> int:
        """读取当前数值，空值时回退到最小值。"""
        text = self._line_edit.text().strip()
        if not text:
            return self._minimum
        return max(self._minimum, min(self._maximum, int(text)))

    def setValue(self, value: int) -> None:
        """设置输入框数值。"""
        self.blockSignals(True)
        self._line_edit.setText(str(value))
        self.blockSignals(False)

    def _on_text_changed(self, text: str) -> None:
        """文本变化时向外发出数值变化信号。"""
        if self.signalsBlocked() or not text:
            return
        self.valueChanged.emit(self.value())


class SettingsPage(QWidget):
    """应用设置页。

    修改后立即写入 AppConfig，不依赖外部保存按钮。
    """

    def __init__(self, config: AppConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._config = config
        self._on_config_changed_callbacks: list[Callable[[AppConfig], None]] = []

        self._setup_ui()
        self._load_from_config()

    # ---- 回调注册 ----

    def on_config_changed(self, callback: Callable[[AppConfig], None]) -> None:
        """注册配置变更回调。"""
        self._on_config_changed_callbacks.append(callback)

    # ---- UI 构建 ----

    def _setup_ui(self) -> None:
        """构建设置页布局。"""
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)

        scroll_area = QScrollArea(self)
        scroll_area.setObjectName("settingsScrollArea")
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.viewport().setObjectName("settingsViewport")

        content = QWidget(scroll_area)
        content.setObjectName("settingsContent")
        main_layout = QVBoxLayout(content)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(14)

        main_layout.addWidget(self._build_camera_card())
        main_layout.addWidget(self._build_microphone_card())
        main_layout.addWidget(self._build_model_card())
        main_layout.addStretch()

        scroll_area.setWidget(content)
        outer_layout.addWidget(scroll_area)
        self._apply_styles()
        self._connect_signals()

    def _build_camera_card(self) -> QFrame:
        """创建摄像头参数卡片。"""
        card = self._create_card("cameraCard")
        layout = self._create_card_layout(card)

        title = QLabel("摄像头参数", self)
        title.setObjectName("cardTitle")
        layout.addWidget(title)

        device_row = QHBoxLayout()
        device_row.setSpacing(10)
        device_row.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        device_row.addWidget(self._create_field_label("摄像头"))

        self._camera_index = NoWheelComboBox(self)
        self._camera_index.setObjectName("cameraSelect")
        self._camera_index.setFixedHeight(40)
        self._configure_combo_width(self._camera_index)
        self._apply_combo_popup_style(self._camera_index)
        device_row.addWidget(self._camera_index, stretch=1)

        self._refresh_cameras_button = QPushButton("刷新", self)
        self._refresh_cameras_button.setObjectName("secondaryButton")
        self._refresh_cameras_button.setFixedHeight(40)
        self._refresh_cameras_button.clicked.connect(self._refresh_camera_options)
        device_row.addWidget(self._refresh_cameras_button)
        layout.addLayout(device_row)

        row = QHBoxLayout()
        row.setSpacing(10)
        row.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self._create_field_label("分辨率"))

        self._camera_width = UnitInput("W", 320, 3840, self)
        row.addWidget(self._camera_width)

        separator = QLabel("x", self)
        separator.setObjectName("resolutionSeparator")
        separator.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(separator)

        self._camera_height = UnitInput("H", 240, 2160, self)
        row.addWidget(self._camera_height)

        row.addSpacing(4)
        row.addWidget(self._create_field_label("帧率"))

        self._camera_fps = NoWheelComboBox(self)
        self._camera_fps.setObjectName("fpsSelect")
        self._camera_fps.setFixedHeight(40)
        self._camera_fps.addItems(["60 fps", "30 fps", "24 fps", "15 fps"])
        self._configure_combo_width(self._camera_fps)
        self._apply_combo_popup_style(self._camera_fps)
        row.addWidget(self._camera_fps, stretch=1)

        layout.addLayout(row)
        return card

    def _build_microphone_card(self) -> QFrame:
        """创建麦克风参数卡片。"""
        card = self._create_card("microphoneCard")
        layout = self._create_card_layout(card)

        title = QLabel("麦克风参数", self)
        title.setObjectName("cardTitle")
        layout.addWidget(title)

        device_row = QHBoxLayout()
        device_row.setSpacing(10)
        device_row.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        device_row.addWidget(self._create_field_label("麦克风"))

        self._microphone_index = NoWheelComboBox(self)
        self._microphone_index.setObjectName("microphoneSelect")
        self._microphone_index.setFixedHeight(40)
        self._configure_combo_width(self._microphone_index)
        self._apply_combo_popup_style(self._microphone_index)
        device_row.addWidget(self._microphone_index, stretch=1)

        self._refresh_microphones_button = QPushButton("刷新", self)
        self._refresh_microphones_button.setObjectName("secondaryButton")
        self._refresh_microphones_button.setFixedHeight(40)
        self._refresh_microphones_button.clicked.connect(self._refresh_microphone_options)
        device_row.addWidget(self._refresh_microphones_button)
        layout.addLayout(device_row)

        row = QHBoxLayout()
        row.setSpacing(10)
        row.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self._create_field_label("采样率"))

        self._mic_sample_rate = NoWheelComboBox(self)
        self._mic_sample_rate.setObjectName("sampleRateSelect")
        self._mic_sample_rate.setFixedHeight(40)
        self._mic_sample_rate.addItems(["16000 Hz", "44100 Hz", "48000 Hz"])
        self._configure_combo_width(self._mic_sample_rate)
        self._apply_combo_popup_style(self._mic_sample_rate)
        self._mic_sample_rate.setFixedWidth(170)
        row.addWidget(self._mic_sample_rate)

        row.addWidget(self._create_field_label("块大小"))
        self._mic_block_size = UnitInput("B", 320, 8192, self)
        row.addWidget(self._mic_block_size)
        row.addStretch()
        layout.addLayout(row)
        return card

    def _build_model_card(self) -> QFrame:
        """创建模型路径卡片。"""
        card = self._create_card("modelCard")
        layout = self._create_card_layout(card)
        layout.setSpacing(12)

        title = QLabel("模型", self)
        title.setObjectName("cardTitle")
        layout.addWidget(title)

        path_label = QLabel("Live2D 模型路径", self)
        path_label.setObjectName("subLabel")
        layout.addWidget(path_label)

        input_group = QFrame(self)
        input_group.setObjectName("inputGroup")
        input_layout = QHBoxLayout(input_group)
        input_layout.setContentsMargins(0, 0, 0, 0)
        input_layout.setSpacing(0)

        self._model_path_edit = QLineEdit(self)
        self._model_path_edit.setObjectName("pathInput")
        self._model_path_edit.setMinimumWidth(0)
        input_layout.addWidget(self._model_path_edit, stretch=1)

        self._browse_button = QPushButton("浏览", self)
        self._browse_button.setObjectName("browseButton")
        self._browse_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon))
        self._browse_button.setFixedHeight(42)
        self._browse_button.clicked.connect(self._browse_model_file)
        input_layout.addWidget(self._browse_button)

        layout.addWidget(input_group)
        return card

    def _create_card(self, object_name: str) -> QFrame:
        """创建统一卡片容器。"""
        card = QFrame(self)
        card.setObjectName(object_name)
        card.setFrameShape(QFrame.Shape.NoFrame)
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        shadow = QGraphicsDropShadowEffect(card)
        shadow.setBlurRadius(18)
        shadow.setOffset(0, 3)
        shadow.setColor(QColor(15, 23, 42, 28))
        card.setGraphicsEffect(shadow)
        return card

    def _create_card_layout(self, card: QFrame) -> QVBoxLayout:
        """创建卡片内部统一布局。"""
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 18, 20, 20)
        layout.setSpacing(18)
        return layout

    def _create_field_label(self, text: str) -> QLabel:
        """创建字段标签。"""
        label = QLabel(text, self)
        label.setObjectName("fieldLabel")
        return label

    def _configure_combo_width(self, combo_box: QComboBox) -> None:
        """避免长设备名把卡片撑破。"""
        combo_box.setMinimumWidth(0)
        combo_box.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        combo_box.setMinimumContentsLength(8)
        combo_box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def _apply_combo_popup_style(self, combo_box: QComboBox) -> None:
        """固定下拉菜单的浅色背景和深色文字。"""
        view = combo_box.view()
        palette = view.palette()
        palette.setColor(QPalette.ColorRole.Text, QColor("#111827"))
        palette.setColor(QPalette.ColorRole.WindowText, QColor("#111827"))
        palette.setColor(QPalette.ColorRole.Base, QColor("#ffffff"))
        palette.setColor(QPalette.ColorRole.Highlight, QColor("#e8f1ff"))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#111827"))
        view.setPalette(palette)
        view.setStyleSheet(
            """
            QListView {
                background: #ffffff;
                border: 1px solid #cbd5e1;
                border-radius: 8px;
                color: #111827;
                font-size: 15px;
                outline: 0;
                padding: 4px;
            }
            QListView::item {
                min-height: 30px;
                padding: 4px 10px;
                color: #111827;
            }
            QListView::item:selected {
                background: #e8f1ff;
                color: #111827;
            }
            """
        )

    def _apply_styles(self) -> None:
        """集中设置设置页视觉样式。"""
        self.setStyleSheet(
            """
            QScrollArea#settingsScrollArea {
                background: transparent;
            }
            QWidget#settingsViewport,
            QWidget#settingsContent {
                background: #eef2f6;
            }
            QFrame#cameraCard,
            QFrame#microphoneCard,
            QFrame#modelCard {
                background: #ffffff;
                border: 1px solid #e2e8f0;
                border-radius: 14px;
            }
            QLabel#cardTitle {
                color: #111827;
                font-size: 18px;
                font-weight: 800;
            }
            QLabel#fieldLabel {
                color: #334155;
                font-size: 14px;
                font-weight: 600;
                min-width: 48px;
            }
            QLabel#subLabel {
                color: #64748b;
                font-size: 13px;
                font-weight: 600;
            }
            QLabel#resolutionSeparator {
                color: #334155;
                font-size: 14px;
                font-weight: 700;
            }
            QFrame#unitInput {
                background: #f8fafc;
                border: 1px solid #d8dee8;
                border-radius: 8px;
            }
            QLineEdit#unitInputEdit {
                background: transparent;
                border: 0;
                color: #111827;
                font-size: 15px;
                padding: 0;
            }
            QLabel#unitBadge {
                background: #eef2f7;
                border-radius: 7px;
                color: #334155;
                font-size: 13px;
                font-weight: 700;
            }
            QComboBox#fpsSelect,
            QComboBox#cameraSelect,
            QComboBox#microphoneSelect,
            QComboBox#sampleRateSelect {
                background: #f8fafc;
                border: 1px solid #d8dee8;
                border-radius: 8px;
                color: #111827;
                font-size: 15px;
                padding-left: 14px;
                padding-right: 14px;
            }
            QComboBox#fpsSelect {
                min-width: 150px;
            }
            QComboBox:focus {
                border: 1px solid #2563eb;
                background: #ffffff;
            }
            QComboBox QAbstractItemView {
                background: #ffffff;
                border: 1px solid #cbd5e1;
                border-radius: 8px;
                color: #111827;
                font-size: 15px;
                outline: 0;
                padding: 4px;
                selection-background-color: #e8f1ff;
                selection-color: #111827;
            }
            QFrame#inputGroup {
                background: #f8fafc;
                border: 1px solid #d8dee8;
                border-radius: 9px;
            }
            QLineEdit#pathInput {
                background: transparent;
                border: 0;
                color: #111827;
                font-size: 15px;
                min-height: 40px;
                padding: 0 14px;
            }
            QPushButton#browseButton {
                background: #f8fafc;
                border: 0;
                border-left: 1px solid #d8dee8;
                border-top-right-radius: 9px;
                border-bottom-right-radius: 9px;
                color: #1f2937;
                font-size: 14px;
                font-weight: 700;
                padding: 0 14px;
            }
            QPushButton#browseButton:hover {
                background: #eef2f7;
            }
            QPushButton#secondaryButton {
                background: #f8fafc;
                border: 1px solid #d8dee8;
                border-radius: 8px;
                color: #1f2937;
                font-size: 14px;
                font-weight: 700;
                padding: 0 14px;
            }
            QPushButton#secondaryButton:hover {
                background: #eef2f7;
            }
            """
        )

    def _connect_signals(self) -> None:
        """将控件变更连接到保存逻辑。"""
        self._camera_index.currentIndexChanged.connect(self._on_setting_changed)
        self._camera_width.valueChanged.connect(self._on_setting_changed)
        self._camera_height.valueChanged.connect(self._on_setting_changed)
        self._camera_fps.currentTextChanged.connect(self._on_setting_changed)
        self._microphone_index.currentIndexChanged.connect(self._on_setting_changed)
        self._mic_sample_rate.currentTextChanged.connect(self._on_setting_changed)
        self._mic_block_size.valueChanged.connect(self._on_setting_changed)
        self._model_path_edit.textChanged.connect(self._on_setting_changed)

    # ---- 配置加载与保存 ----

    def _load_from_config(self) -> None:
        """把 AppConfig 字段同步到 UI 控件。"""
        widgets = (
            self._camera_index,
            self._camera_width,
            self._camera_height,
            self._camera_fps,
            self._microphone_index,
            self._mic_sample_rate,
            self._mic_block_size,
            self._model_path_edit,
        )
        for widget in widgets:
            widget.blockSignals(True)

        self._populate_camera_options(self._config.camera_index)
        self._populate_microphone_options(self._config.microphone_index)
        self._camera_width.setValue(self._config.camera_width)
        self._camera_height.setValue(self._config.camera_height)
        self._set_combo_value(self._camera_fps, f"{self._config.camera_fps} fps")
        self._set_combo_value(self._mic_sample_rate, f"{self._config.mic_sample_rate} Hz")
        self._mic_block_size.setValue(self._config.mic_block_size)
        self._model_path_edit.setText(self._config.model_paths.get(self._config.model_name, ""))

        for widget in widgets:
            widget.blockSignals(False)

    def _populate_camera_options(self, selected_index: int) -> None:
        """刷新摄像头下拉项，并保留当前配置索引。"""
        available_indices = list_available_camera_indices()
        indices = sorted(set(available_indices + [selected_index]))

        self._camera_index.clear()
        for index in indices:
            suffix = "" if index in available_indices else "（未检测）"
            self._camera_index.addItem(f"摄像头 {index}{suffix}", index)

        selected_row = self._camera_index.findData(selected_index)
        if selected_row >= 0:
            self._camera_index.setCurrentIndex(selected_row)

    def _populate_microphone_options(self, selected_index: int) -> None:
        """刷新麦克风下拉项，并保留当前配置索引。"""
        try:
            devices = list_available_microphone_devices()
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("扫描麦克风设备失败：%s", exc)
            devices = []

        device_map = {index: name for index, name in devices}
        if selected_index not in device_map:
            if device_map:
                selected_index = sorted(device_map)[0]
            else:
                device_map[selected_index] = f"麦克风 {selected_index}（未检测）"

        self._microphone_index.clear()
        for index, name in sorted(device_map.items()):
            self._microphone_index.addItem(f"{name}  [{index}]", index)

        selected_row = self._microphone_index.findData(selected_index)
        if selected_row >= 0:
            self._microphone_index.setCurrentIndex(selected_row)
            self._config.microphone_index = int(selected_index)

    def _refresh_camera_options(self) -> None:
        """手动重新扫描摄像头设备。"""
        selected_index = self._camera_index.currentData()
        if selected_index is None:
            selected_index = self._config.camera_index
        self._populate_camera_options(int(selected_index))
        self._on_setting_changed()

    def _refresh_microphone_options(self) -> None:
        """手动重新扫描麦克风设备。"""
        selected_index = self._microphone_index.currentData()
        if selected_index is None:
            selected_index = self._config.microphone_index
        self._populate_microphone_options(int(selected_index))
        self._on_setting_changed()

    def _set_combo_value(self, combo_box: QComboBox, text: str) -> None:
        """根据文本设置下拉框当前值。"""
        index = combo_box.findText(text)
        if index < 0:
            combo_box.addItem(text)
            index = combo_box.findText(text)
        combo_box.setCurrentIndex(index)

    def _browse_model_file(self) -> None:
        """打开文件选择器并写入 Live2D 模型路径。"""
        current_path = resolve_project_path(self._model_path_edit.text())
        start_dir = current_path.parent if current_path.parent.exists() else resolve_project_path("models")
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择 Live2D 模型文件",
            str(start_dir),
            "Live2D 模型 (*.model3.json);;JSON 文件 (*.json);;所有文件 (*)",
        )
        if not file_path:
            return

        self._model_path_edit.setText(project_relative_path(Path(file_path)))

    def _on_setting_changed(self, *_args) -> None:
        """控件值变更 -> 写入 AppConfig -> 通知外部。"""
        camera_index = self._camera_index.currentData()
        microphone_index = self._microphone_index.currentData()
        if camera_index is not None:
            self._config.camera_index = int(camera_index)
        if microphone_index is not None:
            self._config.microphone_index = int(microphone_index)

        self._config.camera_width = self._camera_width.value()
        self._config.camera_height = self._camera_height.value()
        self._config.camera_fps = int(self._camera_fps.currentText().split()[0])
        self._config.mic_sample_rate = int(self._mic_sample_rate.currentText().split()[0])
        self._config.mic_block_size = self._mic_block_size.value()
        self._config.model_paths[self._config.model_name] = self._model_path_edit.text()

        LOGGER.info(
            "配置已更新：camera=%s %dx%d@%dfps mic=%s %sHz block=%s",
            self._config.camera_index,
            self._config.camera_width,
            self._config.camera_height,
            self._config.camera_fps,
            self._config.microphone_index,
            self._config.mic_sample_rate,
            self._config.mic_block_size,
        )

        for callback in self._on_config_changed_callbacks:
            try:
                callback(self._config)
            except Exception as exc:  # noqa: BLE001
                LOGGER.error("配置变更回调异常：%s", exc)
