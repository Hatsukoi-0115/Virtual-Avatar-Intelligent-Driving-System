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
CONTROL_HEIGHT = 36
LABEL_WIDTH = 65


class NoWheelComboBox(QComboBox):
    """禁止鼠标滚轮在未展开下拉菜单时误切换选项。"""

    def wheelEvent(self, event) -> None:
        """忽略滚轮事件，避免滚动页面时改掉配置。"""
        event.ignore()


class NumberInput(QLineEdit):
    """统一尺寸的数字输入框。"""

    valueChanged = Signal(int)

    def __init__(
        self,
        minimum: int,
        maximum: int,
        width: int = 86,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._minimum = minimum
        self._maximum = maximum

        self.setObjectName("numberInput")
        self.setValidator(QIntValidator(minimum, maximum, self))
        self.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.setFixedSize(width, CONTROL_HEIGHT)
        self.textChanged.connect(self._on_text_changed)

    def value(self) -> int:
        """读取当前数值，空值时回退到最小值。"""
        text = self.text().strip()
        if not text:
            return self._minimum
        return max(self._minimum, min(self._maximum, int(text)))

    def setValue(self, value: int) -> None:
        """设置输入框数值。"""
        self.blockSignals(True)
        self.setText(str(value))
        self.blockSignals(False)

    def _on_text_changed(self, text: str) -> None:
        if self.signalsBlocked() or not text:
            return
        self.valueChanged.emit(self.value())


class UnitInput(QFrame):
    """带右侧单位后缀的数字输入控件。"""

    valueChanged = Signal(int)

    def __init__(self, unit: str, minimum: int, maximum: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._minimum = minimum
        self._maximum = maximum

        self.setObjectName("unitInput")
        self.setFixedSize(112, CONTROL_HEIGHT)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 10, 0)
        layout.setSpacing(6)

        self._line_edit = QLineEdit(self)
        self._line_edit.setObjectName("unitInputEdit")
        self._line_edit.setValidator(QIntValidator(minimum, maximum, self))
        self._line_edit.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._line_edit.textChanged.connect(self._on_text_changed)
        layout.addWidget(self._line_edit, stretch=1)

        unit_label = QLabel(unit, self)
        unit_label.setObjectName("unitSuffix")
        unit_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        unit_label.setFixedWidth(18)
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
        if self.signalsBlocked() or not text:
            return
        self.valueChanged.emit(self.value())


class SettingsPage(QWidget):
    """应用设置页。

    修改后立即写入 AppConfig，不依赖外部保存按钮。
    """

    config_validity_changed = Signal(bool)

    def __init__(self, config: AppConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._config = config
        self._is_config_valid = False
        self._on_config_changed_callbacks: list[Callable[[AppConfig], None]] = []

        self._setup_ui()
        self._load_from_config()
        self._set_config_valid(self._compute_config_validity(), emit=False)

    # ---- 回调注册 ----

    def on_config_changed(self, callback: Callable[[AppConfig], None]) -> None:
        """注册配置变更回调。"""
        self._on_config_changed_callbacks.append(callback)

    def is_config_valid(self) -> bool:
        """当前配置是否足以启动直播。"""
        return self._is_config_valid

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
        main_layout.addWidget(self._build_llm_card())
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
        self._camera_index.setFixedHeight(CONTROL_HEIGHT)
        self._configure_combo_width(self._camera_index)
        self._apply_combo_popup_style(self._camera_index)
        device_row.addWidget(self._camera_index, stretch=1)

        self._refresh_cameras_button = QPushButton("刷新", self)
        self._refresh_cameras_button.setObjectName("secondaryButton")
        self._refresh_cameras_button.setFixedSize(64, CONTROL_HEIGHT)
        self._refresh_cameras_button.clicked.connect(self._refresh_camera_options)
        device_row.addWidget(self._refresh_cameras_button)
        layout.addLayout(device_row)

        row = QHBoxLayout()
        row.setSpacing(10)
        row.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self._create_field_label("分辨率"))

        self._camera_width = NumberInput(320, 3840, parent=self)
        row.addWidget(self._camera_width)

        separator = QLabel("×", self)
        separator.setObjectName("resolutionSeparator")
        separator.setAlignment(Qt.AlignmentFlag.AlignCenter)
        separator.setFixedWidth(12)
        row.addWidget(separator)

        self._camera_height = NumberInput(240, 2160, parent=self)
        row.addWidget(self._camera_height)

        row.addSpacing(6)
        row.addWidget(self._create_field_label("帧率"))

        self._camera_fps = NoWheelComboBox(self)
        self._camera_fps.setObjectName("fpsSelect")
        self._camera_fps.setFixedHeight(CONTROL_HEIGHT)
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
        self._microphone_index.setFixedHeight(CONTROL_HEIGHT)
        self._configure_combo_width(self._microphone_index)
        self._apply_combo_popup_style(self._microphone_index)
        device_row.addWidget(self._microphone_index, stretch=1)

        self._refresh_microphones_button = QPushButton("刷新", self)
        self._refresh_microphones_button.setObjectName("secondaryButton")
        self._refresh_microphones_button.setFixedSize(64, CONTROL_HEIGHT)
        self._refresh_microphones_button.clicked.connect(self._refresh_microphone_options)
        device_row.addWidget(self._refresh_microphones_button)
        layout.addLayout(device_row)

        row = QHBoxLayout()
        row.setSpacing(10)
        row.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self._create_field_label("采样率"))

        self._mic_sample_rate = NoWheelComboBox(self)
        self._mic_sample_rate.setObjectName("sampleRateSelect")
        self._mic_sample_rate.setFixedHeight(CONTROL_HEIGHT)
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
        layout.setSpacing(10)

        title = QLabel("模型配置", self)
        title.setObjectName("cardTitle")
        layout.addWidget(title)

        path_label = QLabel("Live2D 模型路径", self)
        path_label.setObjectName("subLabel")
        layout.addWidget(path_label)

        self._input_group = QFrame(self)
        self._input_group.setObjectName("inputGroup")
        input_layout = QHBoxLayout(self._input_group)
        input_layout.setContentsMargins(0, 0, 0, 0)
        input_layout.setSpacing(0)

        self._model_path_edit = QLineEdit(self)
        self._model_path_edit.setObjectName("pathInput")
        self._model_path_edit.setMinimumWidth(0)
        self._model_path_edit.setToolTip("Live2D 模型 .model3.json 文件路径")
        input_layout.addWidget(self._model_path_edit, stretch=1)

        self._browse_button = QPushButton("浏览...", self)
        self._browse_button.setObjectName("browseButton")
        self._browse_button.setFixedHeight(CONTROL_HEIGHT)
        self._browse_button.clicked.connect(self._browse_model_file)
        input_layout.addWidget(self._browse_button)

        layout.addWidget(self._input_group)

        self._model_path_error = QLabel("文件不存在", self)
        self._model_path_error.setObjectName("errorLabel")
        self._model_path_error.setVisible(False)
        layout.addWidget(self._model_path_error)
        return card

    def _build_llm_card(self) -> QFrame:
        """创建 LLM 配置卡片。"""
        card = self._create_card("llmCard")
        layout = self._create_card_layout(card)
        layout.setSpacing(10)

        title = QLabel("LLM 配置", self)
        title.setObjectName("cardTitle")
        layout.addWidget(title)

        base_url_row = QHBoxLayout()
        base_url_row.setSpacing(10)
        base_url_row.addWidget(self._create_field_label("API 地址"))
        self._llm_base_url_edit = QLineEdit(self)
        self._llm_base_url_edit.setObjectName("llmInput")
        self._llm_base_url_edit.setPlaceholderText("https://api.openai.com/v1")
        base_url_row.addWidget(self._llm_base_url_edit, stretch=1)
        layout.addLayout(base_url_row)

        api_key_row = QHBoxLayout()
        api_key_row.setSpacing(10)
        api_key_row.addWidget(self._create_field_label("API Key"))
        self._llm_api_key_edit = QLineEdit(self)
        self._llm_api_key_edit.setObjectName("llmInput")
        self._llm_api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._llm_api_key_edit.setPlaceholderText("sk-...")
        api_key_row.addWidget(self._llm_api_key_edit, stretch=1)
        layout.addLayout(api_key_row)

        model_row = QHBoxLayout()
        model_row.setSpacing(10)
        model_row.addWidget(self._create_field_label("模型名称"))
        self._llm_model_edit = QLineEdit(self)
        self._llm_model_edit.setObjectName("llmInput")
        self._llm_model_edit.setPlaceholderText("gpt-4o-mini")
        model_row.addWidget(self._llm_model_edit, stretch=1)
        layout.addLayout(model_row)

        return card

    def _create_card(self, object_name: str) -> QFrame:
        """创建统一卡片容器。"""
        card = QFrame(self)
        card.setObjectName(object_name)
        card.setFrameShape(QFrame.Shape.NoFrame)
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        shadow = QGraphicsDropShadowEffect(card)
        shadow.setBlurRadius(16)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(15, 23, 42, 14))
        card.setGraphicsEffect(shadow)
        return card

    def _create_card_layout(self, card: QFrame) -> QVBoxLayout:
        """创建卡片内部统一布局。"""
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 18)
        layout.setSpacing(13)
        return layout

    def _create_field_label(self, text: str) -> QLabel:
        """创建固定列宽字段标签。"""
        label = QLabel(text, self)
        label.setObjectName("fieldLabel")
        label.setFixedWidth(LABEL_WIDTH)
        label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
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
        palette.setColor(QPalette.ColorRole.Text, QColor("#1E293B"))
        palette.setColor(QPalette.ColorRole.WindowText, QColor("#1E293B"))
        palette.setColor(QPalette.ColorRole.Base, QColor("#FFFFFF"))
        palette.setColor(QPalette.ColorRole.Highlight, QColor("#F0F9FF"))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#0284C7"))
        view.setPalette(palette)
        view.setStyleSheet(
            """
            QListView {
                background: #FFFFFF;
                border: 1px solid #E2E8F0;
                border-radius: 8px;
                color: #1E293B;
                font-size: 13px;
                outline: 0;
                padding: 4px;
                selection-background-color: #F0F9FF;
                selection-color: #0284C7;
            }
            QListView::item {
                min-height: 30px;
                padding: 4px 10px;
                color: #1E293B;
            }
            QListView::item:hover,
            QListView::item:selected {
                background: #F0F9FF;
                color: #0284C7;
            }
            """
        )

    def _apply_styles(self) -> None:
        """集中设置设置页视觉样式。"""
        chevron_path = (Path(__file__).resolve().parent / "assets" / "chevron-down.svg").as_posix()
        style_sheet = (
            """
            QScrollArea#settingsScrollArea {
                background: transparent;
            }
            QWidget#settingsViewport,
            QWidget#settingsContent {
                background: #F6F8FB;
            }
            QFrame#cameraCard,
            QFrame#microphoneCard,
            QFrame#modelCard,
            QFrame#llmCard {
                background: #FFFFFF;
                border: 1px solid #E5E7EB;
                border-radius: 8px;
            }
            QLabel#cardTitle {
                color: #0F172A;
                font-size: 14px;
                font-weight: 700;
            }
            QLabel#fieldLabel {
                color: #475569;
                font-size: 13px;
                font-weight: 400;
            }
            QLabel#subLabel {
                color: #475569;
                font-size: 13px;
                font-weight: 400;
            }
            QLabel#errorLabel {
                color: #EF4444;
                font-size: 12px;
                padding-left: 1px;
            }
            QLabel#resolutionSeparator {
                color: #94A3B8;
                font-size: 13px;
                font-weight: 700;
            }
            QLineEdit#numberInput,
            QLineEdit#llmInput,
            QFrame#unitInput,
            QComboBox#fpsSelect,
            QComboBox#cameraSelect,
            QComboBox#microphoneSelect,
            QComboBox#sampleRateSelect {
                background: #F8FAFC;
                border: 1px solid #E2E8F0;
                border-radius: 6px;
                color: #1E293B;
                font-size: 13px;
            }
            QLineEdit#numberInput {
                padding: 0 10px;
            }
            QLineEdit#numberInput:focus,
            QLineEdit#llmInput:focus,
            QComboBox#fpsSelect:focus,
            QComboBox#cameraSelect:focus,
            QComboBox#microphoneSelect:focus,
            QComboBox#sampleRateSelect:focus {
                border: 1px solid #2563EB;
                background: #FFFFFF;
            }
            QLineEdit#llmInput {
                padding: 0 12px;
                min-height: 36px;
            }
            QLineEdit#unitInputEdit {
                background: transparent;
                border: 0;
                color: #1E293B;
                font-size: 13px;
                padding: 0;
            }
            QLabel#unitSuffix {
                color: #64748B;
                font-size: 12px;
                font-weight: 600;
            }
            QComboBox#fpsSelect,
            QComboBox#cameraSelect,
            QComboBox#microphoneSelect,
            QComboBox#sampleRateSelect {
                padding-left: 10px;
                padding-right: 28px;
            }
            QComboBox::drop-down {
                border: 0;
                width: 28px;
            }
            QComboBox::down-arrow {
                image: url("__CHEVRON_PATH__");
                width: 12px;
                height: 12px;
                margin-right: 8px;
            }
            QComboBox QAbstractItemView {
                background: #FFFFFF;
                border: 1px solid #E2E8F0;
                border-radius: 8px;
                color: #1E293B;
                font-size: 13px;
                outline: 0;
                padding: 4px;
                selection-background-color: #F0F9FF;
                selection-color: #0284C7;
            }
            QFrame#inputGroup {
                background: #F8FAFC;
                border: 1px solid #E2E8F0;
                border-radius: 6px;
            }
            QFrame#inputGroup[invalid="true"] {
                border: 1px solid #EF4444;
            }
            QLineEdit#pathInput {
                background: transparent;
                border: 0;
                color: #1E293B;
                font-family: "Cascadia Mono", "Consolas", "Microsoft YaHei UI", monospace;
                font-size: 13px;
                min-height: 36px;
                padding: 0 12px;
            }
            QPushButton#browseButton {
                background: #F1F5F9;
                border: 0;
                border-left: 1px solid #E2E8F0;
                border-top-right-radius: 6px;
                border-bottom-right-radius: 6px;
                color: #1E293B;
                font-size: 13px;
                font-weight: 600;
                padding: 0 14px;
            }
            QPushButton#browseButton:hover,
            QPushButton#secondaryButton:hover {
                background: #E2E8F0;
            }
            QPushButton#browseButton:pressed,
            QPushButton#secondaryButton:pressed {
                background: #CBD5E1;
            }
            QPushButton#secondaryButton {
                background: #FFFFFF;
                border: 1px solid #E2E8F0;
                border-radius: 6px;
                color: #1E293B;
                font-size: 13px;
                font-weight: 600;
                padding: 0 10px;
            }
            """
        )
        self.setStyleSheet(style_sheet.replace("__CHEVRON_PATH__", chevron_path))

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
        self._llm_base_url_edit.textChanged.connect(self._on_setting_changed)
        self._llm_api_key_edit.textChanged.connect(self._on_setting_changed)
        self._llm_model_edit.textChanged.connect(self._on_setting_changed)

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
            self._llm_base_url_edit,
            self._llm_api_key_edit,
            self._llm_model_edit,
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
        self._llm_base_url_edit.setText(self._config.llm_base_url)
        self._llm_api_key_edit.setText(self._config.llm_api_key)
        self._llm_model_edit.setText(self._config.llm_model)

        for widget in widgets:
            widget.blockSignals(False)

        self._update_model_path_state()

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
        self._config.model_paths[self._config.model_name] = self._model_path_edit.text().strip()
        self._config.llm_base_url = self._llm_base_url_edit.text().strip()
        self._config.llm_api_key = self._llm_api_key_edit.text().strip()
        self._config.llm_model = self._llm_model_edit.text().strip()

        self._set_config_valid(self._compute_config_validity())

        LOGGER.info(
            "配置已更新：camera=%s %dx%d@%dfps mic=%s %sHz block=%s llm_configured=%s valid=%s",
            self._config.camera_index,
            self._config.camera_width,
            self._config.camera_height,
            self._config.camera_fps,
            self._config.microphone_index,
            self._config.mic_sample_rate,
            self._config.mic_block_size,
            bool(self._config.llm_api_key and self._config.llm_model),
            self._is_config_valid,
        )

        for callback in self._on_config_changed_callbacks:
            try:
                callback(self._config)
            except Exception as exc:  # noqa: BLE001
                LOGGER.error("配置变更回调异常：%s", exc)

    def _compute_config_validity(self) -> bool:
        """校验关键启动参数。"""
        return self._update_model_path_state()

    def _update_model_path_state(self) -> bool:
        """刷新模型路径输入框的错误状态。"""
        model_path = self._model_path_edit.text().strip()
        valid = bool(model_path) and resolve_project_path(model_path).is_file()

        self._input_group.setProperty("invalid", not valid)
        self._model_path_error.setVisible(not valid)
        self._model_path_edit.setToolTip(str(resolve_project_path(model_path)) if model_path else "Live2D 模型路径不能为空")

        for widget in (self._input_group, self._model_path_edit):
            widget.style().unpolish(widget)
            widget.style().polish(widget)
        return valid

    def _set_config_valid(self, valid: bool, emit: bool = True) -> None:
        """保存校验状态并在变化时通知主窗口。"""
        if self._is_config_valid == valid:
            return
        self._is_config_valid = valid
        if emit:
            self.config_validity_changed.emit(valid)
