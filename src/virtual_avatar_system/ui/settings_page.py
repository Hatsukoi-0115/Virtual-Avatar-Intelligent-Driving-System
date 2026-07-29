"""设置页模块。

职责：
- 提供摄像头、麦克风、模型路径等配置界面
- 配置变更后同步写入 AppConfig
- 只负责设置项采集，不直接启动业务链路
"""

from __future__ import annotations

import logging
import contextlib
import json
import threading
import time
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QSize, Signal, Qt
from PySide6.QtGui import QColor, QIcon, QIntValidator, QPalette
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFileDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from virtual_avatar_system.audio.source import list_available_microphone_devices
from virtual_avatar_system.config.app_config import (
    AppConfig,
    DEFAULT_COURSE_QA_PROMPT,
    DEFAULT_ECOMMERCE_PROMPT,
    get_comment_prompt_text,
    normalize_comment_prompt_mode,
    project_relative_path,
    resolve_project_path,
)
from virtual_avatar_system.vision.camera_source import list_available_camera_indices

LOGGER = logging.getLogger(__name__)
ASSETS_DIR = Path(__file__).resolve().parent / "assets"
CONTROL_HEIGHT = 40
LABEL_WIDTH = 70
SETTINGS_CONTENT_MAX_WIDTH = 580


class NoWheelComboBox(QComboBox):
    """禁止鼠标滚轮在未展开下拉菜单时误切换选项。"""

    def wheelEvent(self, event) -> None:
        """忽略滚轮事件，避免滚动页面时改掉配置。"""
        event.ignore()


class NumberComboBox(NoWheelComboBox):
    """用于分辨率数值选择的下拉框。"""

    valueChanged = Signal(int)

    def __init__(
        self,
        values: tuple[int, ...],
        width: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("resolutionSelect")
        self.setFixedSize(width, CONTROL_HEIGHT)
        self.addItems([str(value) for value in values])
        self.currentTextChanged.connect(self._on_text_changed)

    def value(self) -> int:
        """读取当前下拉数值。"""
        return int(self.currentText())

    def setValue(self, value: int) -> None:
        """设置下拉数值，配置中不存在时自动补入。"""
        text = str(value)
        index = self.findText(text)
        if index < 0:
            self.addItem(text)
            index = self.findText(text)
        self.setCurrentIndex(index)

    def _on_text_changed(self, text: str) -> None:
        """把文本变化转换成数值信号。"""
        if self.signalsBlocked() or not text:
            return
        self.valueChanged.emit(int(text))


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
        layout.setContentsMargins(12, 0, 0, 0)
        layout.setSpacing(0)

        self._line_edit = QLineEdit(self)
        self._line_edit.setObjectName("unitInputEdit")
        self._line_edit.setValidator(QIntValidator(minimum, maximum, self))
        self._line_edit.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._line_edit.textChanged.connect(self._on_text_changed)
        layout.addWidget(self._line_edit, stretch=1)

        unit_label = QLabel(unit, self)
        unit_label.setObjectName("unitSuffix")
        unit_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        unit_label.setFixedWidth(42)
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


class SettingsNavItem(QFrame):
    """左侧配置导航项，支持标题和说明使用不同字号。"""

    clicked = Signal()

    def __init__(
        self,
        icon: QIcon,
        title: str,
        description: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._checked = False
        self.setObjectName("settingsNavButton")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(56)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self._icon_label = QLabel(self)
        self._icon_label.setObjectName("settingsNavIcon")
        self._icon_label.setPixmap(icon.pixmap(QSize(21, 21)))
        self._icon_label.setFixedSize(24, 24)
        self._icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._icon_label, alignment=Qt.AlignmentFlag.AlignVCenter)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(0)

        self._title_label = QLabel(title, self)
        self._title_label.setObjectName("settingsNavTitle")
        self._title_label.setFixedHeight(22)
        self._title_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        text_layout.addWidget(self._title_label)

        self._description_label = QLabel(description, self)
        self._description_label.setObjectName("settingsNavDescription")
        self._description_label.setWordWrap(False)
        self._description_label.setFixedHeight(16)
        self._description_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        text_layout.addWidget(self._description_label)

        layout.addLayout(text_layout, stretch=1)

    def setChecked(self, checked: bool) -> None:
        """同步选中态到导航项和内部文字。"""
        self._checked = checked
        for widget in (self, self._title_label, self._description_label):
            widget.setProperty("active", checked)
            widget.style().unpolish(widget)
            widget.style().polish(widget)

    def isChecked(self) -> bool:
        """返回当前导航项是否选中。"""
        return self._checked

    def mousePressEvent(self, event) -> None:
        """点击导航项时发出切换信号。"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)


class SettingsPage(QWidget):
    """应用设置页。

    修改后立即写入 AppConfig，不依赖外部保存按钮。
    """

    config_validity_changed = Signal(bool)
    device_test_finished = Signal(str, bool, str)

    def __init__(self, config: AppConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._config = config
        self._is_config_valid = False
        self._camera_test_running = False
        self._microphone_test_running = False
        self._model_test_running = False
        self._llm_test_running = False
        self._test_results = {
            "camera": "idle",
            "microphone": "idle",
            "model": "idle",
            "llm": "idle",
        }
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
        outer_layout = QHBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(14)

        outer_layout.addWidget(self._build_settings_sidebar())

        self._settings_stack = QStackedWidget(self)
        self._settings_stack.setObjectName("settingsContentStack")
        self._settings_stack.setMaximumWidth(SETTINGS_CONTENT_MAX_WIDTH)
        self._settings_stack.addWidget(self._build_device_config_page())
        self._settings_stack.addWidget(self._build_avatar_model_page())
        self._settings_stack.addWidget(self._build_llm_config_page())
        self._settings_stack.addWidget(self._build_prompt_config_page())
        outer_layout.addWidget(self._settings_stack, stretch=1)
        outer_layout.addStretch()

        self._apply_styles()
        self._set_active_settings_panel(0)
        self._connect_signals()

    def _build_settings_sidebar(self) -> QFrame:
        """创建左侧配置分类导航。"""
        sidebar = QFrame(self)
        sidebar.setObjectName("settingsSidebar")
        sidebar.setFixedWidth(178)
        sidebar.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(8, 8, 8, 10)
        layout.setSpacing(7)

        self._settings_nav_buttons: list[SettingsNavItem] = []
        nav_items = (
            ("camera.svg", "设备配置", "摄像头与麦克风设置"),
            ("user.svg", "人物模型配置", "3D模型与动作设置"),
            ("robot.svg", "LLM模型配置", "语言模型与对话设置"),
            ("prompt.svg", "Prompt配置", "直播内容与主播人设"),
        )
        for index, (icon_name, title, description) in enumerate(nav_items):
            nav_item = SettingsNavItem(self._asset_icon(icon_name), title, description, self)
            nav_item.clicked.connect(lambda page_index=index: self._set_active_settings_panel(page_index))
            layout.addWidget(nav_item)
            self._settings_nav_buttons.append(nav_item)

        layout.addStretch()

        status_card = QFrame(self)
        status_card.setObjectName("sidebarStatusCard")
        status_layout = QGridLayout(status_card)
        status_layout.setContentsMargins(12, 11, 10, 11)
        status_layout.setHorizontalSpacing(6)
        status_layout.setVerticalSpacing(7)
        status_layout.setColumnStretch(0, 1)

        status_title = QLabel("系统状态", self)
        status_title.setObjectName("sidebarStatusTitle")
        status_layout.addWidget(status_title, 0, 0, 1, 2)

        self._sidebar_status_label = QLabel("● 未就绪", self)
        self._sidebar_status_label.setObjectName("sidebarStatusLabel")
        self._sidebar_status_label.setProperty("state", "idle")
        status_layout.addWidget(self._sidebar_status_label, 1, 0)

        self._sidebar_status_detail = QLabel("所有设备连接正常", self)
        self._sidebar_status_detail.setObjectName("sidebarStatusDetail")
        self._sidebar_status_detail.setWordWrap(True)
        status_layout.addWidget(self._sidebar_status_detail, 2, 0, 1, 2)

        watermark = QLabel(self)
        watermark.setObjectName("sidebarStatusWatermark")
        watermark.setPixmap(self._asset_icon("shield-watermark.svg").pixmap(QSize(58, 58)))
        watermark.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        status_layout.addWidget(watermark, 1, 1, 2, 1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)
        layout.addWidget(status_card)
        return sidebar

    def _build_device_config_page(self) -> QWidget:
        """创建设备配置页，包含摄像头和麦克风。"""
        page = QWidget(self)
        page.setObjectName("settingsPanelPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(self._build_camera_card())
        layout.addWidget(self._build_microphone_card())
        layout.addStretch()
        return page

    def _build_avatar_model_page(self) -> QWidget:
        """创建人物模型配置页。"""
        page = QWidget(self)
        page.setObjectName("settingsPanelPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        layout.addWidget(self._build_model_card())
        layout.addStretch()
        return page

    def _build_llm_config_page(self) -> QWidget:
        """创建 LLM 模型配置页。"""
        page = QWidget(self)
        page.setObjectName("settingsPanelPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        layout.addWidget(self._build_llm_card())
        layout.addStretch()
        return page

    def _build_prompt_config_page(self) -> QWidget:
        """创建观众评论 Prompt 配置页。"""
        page = QWidget(self)
        page.setObjectName("settingsPanelPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        layout.addWidget(self._build_prompt_card())
        layout.addStretch()
        return page

    def _set_active_settings_panel(self, index: int) -> None:
        """切换右侧配置内容页并同步左侧导航状态。"""
        self._settings_stack.setCurrentIndex(index)
        for button_index, button in enumerate(self._settings_nav_buttons):
            button.setChecked(button_index == index)
            button.setProperty("active", button_index == index)
            button.style().unpolish(button)
            button.style().polish(button)

    def _build_camera_card(self) -> QFrame:
        """创建摄像头参数卡片。"""
        card = self._create_card("cameraCard")
        layout = self._create_card_layout(card)

        self._add_card_header(layout, "camera.svg", "摄像头参数", "配置摄像头分辨率、帧率等参数")

        form = QGridLayout()
        form.setContentsMargins(0, 2, 0, 0)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)
        form.setColumnMinimumWidth(0, LABEL_WIDTH)
        form.setColumnStretch(1, 1)

        self._camera_index = NoWheelComboBox(self)
        self._camera_index.setObjectName("cameraSelect")
        self._camera_index.setFixedHeight(CONTROL_HEIGHT)
        self._configure_combo_width(self._camera_index)
        self._apply_combo_popup_style(self._camera_index)

        self._refresh_cameras_button = QPushButton("刷新", self)
        self._refresh_cameras_button.setObjectName("refreshIconButton")
        self._refresh_cameras_button.setIcon(self._asset_icon("refresh.svg"))
        self._refresh_cameras_button.setIconSize(QSize(18, 18))
        self._refresh_cameras_button.setToolTip("刷新摄像头列表")
        self._refresh_cameras_button.setFixedSize(76, CONTROL_HEIGHT)
        self._refresh_cameras_button.clicked.connect(self._refresh_camera_options)

        device_row = QHBoxLayout()
        device_row.setContentsMargins(0, 0, 0, 0)
        device_row.setSpacing(10)
        device_row.addWidget(self._camera_index, stretch=1)
        device_row.addWidget(self._refresh_cameras_button)
        form.addWidget(self._create_field_label("摄像头"), 0, 0)
        form.addLayout(device_row, 0, 1)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)
        row.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self._camera_width = NumberComboBox((320, 640, 800, 1280, 1920), width=96, parent=self)
        self._apply_combo_popup_style(self._camera_width)
        row.addWidget(self._camera_width)

        separator = QLabel("×", self)
        separator.setObjectName("resolutionSeparator")
        separator.setAlignment(Qt.AlignmentFlag.AlignCenter)
        separator.setFixedWidth(18)
        row.addWidget(separator)

        self._camera_height = NumberComboBox((240, 480, 600, 720, 1080), width=96, parent=self)
        self._apply_combo_popup_style(self._camera_height)
        row.addWidget(self._camera_height)

        row.addSpacing(4)
        fps_label = QLabel("帧率", self)
        fps_label.setObjectName("inlineFieldLabel")
        row.addWidget(fps_label)

        self._camera_fps = NoWheelComboBox(self)
        self._camera_fps.setObjectName("fpsSelect")
        self._camera_fps.setFixedHeight(CONTROL_HEIGHT)
        self._camera_fps.addItems(["60 FPS", "30 FPS", "24 FPS", "15 FPS"])
        self._configure_combo_width(self._camera_fps)
        self._apply_combo_popup_style(self._camera_fps)
        self._camera_fps.setFixedWidth(124)
        row.addWidget(self._camera_fps)
        row.addStretch()

        form.addWidget(self._create_field_label("分辨率"), 1, 0)
        form.addLayout(row, 1, 1)

        test_row = QHBoxLayout()
        test_row.setContentsMargins(0, 0, 0, 0)
        test_row.setSpacing(12)
        test_row.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self._camera_test_button = QPushButton("测试摄像头", self)
        self._camera_test_button.setObjectName("testButton")
        self._camera_test_button.setIcon(self._asset_icon("camera.svg"))
        self._camera_test_button.setIconSize(QSize(18, 18))
        self._camera_test_button.setFixedSize(120, CONTROL_HEIGHT)
        self._camera_test_button.clicked.connect(self._start_camera_test)
        test_row.addWidget(self._camera_test_button)

        self._camera_test_status = QLabel("● 未测试", self)
        self._camera_test_status.setObjectName("deviceTestStatus")
        self._camera_test_status.setProperty("result", "idle")
        self._camera_test_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._camera_test_status.setFixedHeight(30)
        test_row.addWidget(self._camera_test_status)
        test_row.addStretch()
        form.addWidget(self._create_field_label("连接测试"), 2, 0)
        form.addLayout(test_row, 2, 1)

        layout.addLayout(form)
        return card

    def _build_microphone_card(self) -> QFrame:
        """创建麦克风参数卡片。"""
        card = self._create_card("microphoneCard")
        layout = self._create_card_layout(card)

        self._add_card_header(layout, "microphone.svg", "麦克风参数", "配置麦克风采样率、缓冲大小等参数")

        form = QGridLayout()
        form.setContentsMargins(0, 2, 0, 0)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)
        form.setColumnMinimumWidth(0, LABEL_WIDTH)
        form.setColumnStretch(1, 1)

        self._microphone_index = NoWheelComboBox(self)
        self._microphone_index.setObjectName("microphoneSelect")
        self._microphone_index.setFixedHeight(CONTROL_HEIGHT)
        self._configure_combo_width(self._microphone_index)
        self._apply_combo_popup_style(self._microphone_index)

        self._refresh_microphones_button = QPushButton("刷新", self)
        self._refresh_microphones_button.setObjectName("refreshIconButton")
        self._refresh_microphones_button.setIcon(self._asset_icon("refresh.svg"))
        self._refresh_microphones_button.setIconSize(QSize(18, 18))
        self._refresh_microphones_button.setToolTip("刷新麦克风列表")
        self._refresh_microphones_button.setFixedSize(76, CONTROL_HEIGHT)
        self._refresh_microphones_button.clicked.connect(self._refresh_microphone_options)

        device_row = QHBoxLayout()
        device_row.setContentsMargins(0, 0, 0, 0)
        device_row.setSpacing(10)
        device_row.addWidget(self._microphone_index, stretch=1)
        device_row.addWidget(self._refresh_microphones_button)
        form.addWidget(self._create_field_label("麦克风"), 0, 0)
        form.addLayout(device_row, 0, 1)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)
        row.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self._mic_sample_rate = NoWheelComboBox(self)
        self._mic_sample_rate.setObjectName("sampleRateSelect")
        self._mic_sample_rate.setFixedHeight(CONTROL_HEIGHT)
        self._mic_sample_rate.addItems(["16000 Hz", "44100 Hz", "48000 Hz"])
        self._configure_combo_width(self._mic_sample_rate)
        self._apply_combo_popup_style(self._mic_sample_rate)
        self._mic_sample_rate.setFixedWidth(158)
        row.addWidget(self._mic_sample_rate)

        block_label = QLabel("块大小", self)
        block_label.setObjectName("inlineFieldLabel")
        row.addWidget(block_label)
        self._mic_block_size = UnitInput("B", 320, 8192, self)
        self._mic_block_size.setFixedWidth(128)
        row.addWidget(self._mic_block_size)
        row.addStretch()
        form.addWidget(self._create_field_label("采样率"), 1, 0)
        form.addLayout(row, 1, 1)

        test_row = QHBoxLayout()
        test_row.setContentsMargins(0, 0, 0, 0)
        test_row.setSpacing(12)
        test_row.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self._microphone_test_button = QPushButton("测试麦克风", self)
        self._microphone_test_button.setObjectName("testButton")
        self._microphone_test_button.setIcon(self._asset_icon("microphone.svg"))
        self._microphone_test_button.setIconSize(QSize(18, 18))
        self._microphone_test_button.setFixedSize(120, CONTROL_HEIGHT)
        self._microphone_test_button.clicked.connect(self._start_microphone_test)
        test_row.addWidget(self._microphone_test_button)

        self._microphone_test_status = QLabel("● 未测试", self)
        self._microphone_test_status.setObjectName("deviceTestStatus")
        self._microphone_test_status.setProperty("result", "idle")
        self._microphone_test_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._microphone_test_status.setFixedHeight(30)
        test_row.addWidget(self._microphone_test_status)
        test_row.addStretch()
        form.addWidget(self._create_field_label("连接测试"), 2, 0)
        form.addLayout(test_row, 2, 1)

        layout.addLayout(form)
        return card

    def _build_model_card(self) -> QFrame:
        """创建人物模型选择卡片。

        包含模型名称下拉框（取自 model_paths 的键）、
        当前路径只读展示和浏览按钮，允许为每个模型单独指定路径。
        """
        card = self._create_card("modelCard")
        layout = self._create_card_layout(card)
        layout.setSpacing(10)

        title = QLabel("人物模型配置", self)
        title.setObjectName("cardTitle")
        layout.addWidget(title)

        # 模型名称下拉框
        name_row = QHBoxLayout()
        name_row.setSpacing(10)
        name_row.addWidget(self._create_field_label("选择模型"))
        self._model_selector = QComboBox(self)
        self._model_selector.setObjectName("modelSelector")
        self._model_selector.setMinimumWidth(0)
        self._model_selector.setToolTip("从已配置的模型列表中选择当前使用的 Live2D 形象")
        name_row.addWidget(self._model_selector, stretch=1)
        layout.addLayout(name_row)

        # 模型路径输入 + 浏览
        path_label = QLabel("模型文件路径", self)
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

        test_row = QHBoxLayout()
        test_row.setSpacing(10)
        test_row.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        test_row.addWidget(self._create_field_label("连接测试"))

        self._model_test_button = QPushButton("测试人物模型", self)
        self._model_test_button.setObjectName("secondaryButton")
        self._model_test_button.setIcon(self._asset_icon("user.svg"))
        self._model_test_button.setIconSize(QSize(18, 18))
        self._model_test_button.setFixedHeight(CONTROL_HEIGHT)
        self._model_test_button.clicked.connect(self._start_model_test)
        test_row.addWidget(self._model_test_button)

        self._model_test_status = QLabel("● 未测试", self)
        self._model_test_status.setObjectName("deviceTestStatus")
        self._model_test_status.setProperty("result", "idle")
        self._model_test_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._model_test_status.setFixedHeight(28)
        test_row.addWidget(self._model_test_status, stretch=1)
        layout.addLayout(test_row)
        return card

    def _build_llm_card(self) -> QFrame:
        """创建 LLM 配置卡片。"""
        card = self._create_card("llmCard")
        layout = self._create_card_layout(card)
        layout.setSpacing(10)

        title = QLabel("LLM模型配置", self)
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

        test_row = QHBoxLayout()
        test_row.setSpacing(10)
        test_row.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        test_row.addWidget(self._create_field_label("连接测试"))

        self._llm_test_button = QPushButton("测试LLM", self)
        self._llm_test_button.setObjectName("secondaryButton")
        self._llm_test_button.setFixedHeight(CONTROL_HEIGHT)
        self._llm_test_button.clicked.connect(self._start_llm_test)
        test_row.addWidget(self._llm_test_button)

        self._llm_test_status = QLabel("● 未测试", self)
        self._llm_test_status.setObjectName("deviceTestStatus")
        self._llm_test_status.setProperty("result", "idle")
        self._llm_test_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._llm_test_status.setFixedHeight(28)
        test_row.addWidget(self._llm_test_status, stretch=1)
        layout.addLayout(test_row)

        return card

    def _build_prompt_card(self) -> QFrame:
        """创建观众评论话术 Prompt 配置卡片。"""
        card = self._create_card("promptCard")
        layout = self._create_card_layout(card)
        layout.setSpacing(14)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(12)

        icon_badge = QFrame(self)
        icon_badge.setObjectName("cardIconBadge")
        icon_badge.setFixedSize(38, 38)
        icon_layout = QVBoxLayout(icon_badge)
        icon_layout.setContentsMargins(0, 0, 0, 0)

        icon = QLabel(self)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setPixmap(self._asset_icon("prompt.svg").pixmap(QSize(20, 20)))
        icon_layout.addWidget(icon)
        header.addWidget(icon_badge)

        title_group = QVBoxLayout()
        title_group.setContentsMargins(0, 0, 0, 0)
        title_group.setSpacing(3)
        title = QLabel("Prompt配置", self)
        title.setObjectName("cardTitle")
        title_group.addWidget(title)
        subtitle = QLabel("提前限定直播内容、主播人设和回答边界", self)
        subtitle.setObjectName("cardDescription")
        title_group.addWidget(subtitle)
        header.addLayout(title_group, stretch=1)

        self._prompt_mode_group = QButtonGroup(self)
        self._prompt_mode_group.setExclusive(True)
        self._prompt_mode_buttons: dict[str, QPushButton] = {}
        for mode, text in (
            ("course_qa", "课程答疑"),
            ("ecommerce", "电商带货"),
            ("custom", "自定义"),
            ("no_prompt", "不添加Prompt"),
        ):
            button = QPushButton(text, self)
            button.setObjectName("promptModeButton")
            button.setCheckable(True)
            button.setFixedHeight(32)
            button.clicked.connect(lambda _checked=False, value=mode: self._on_prompt_mode_button_clicked(value))
            self._prompt_mode_group.addButton(button)
            self._prompt_mode_buttons[mode] = button
            header.addWidget(button)
        layout.addLayout(header)

        self._comment_prompt_edit = QTextEdit(self)
        self._comment_prompt_edit.setObjectName("promptTextArea")
        self._comment_prompt_edit.setPlaceholderText("请写清楚直播内容、主播人设、目标观众、回答边界和禁止偏离的话题。")
        self._comment_prompt_edit.setMinimumHeight(330)
        self._comment_prompt_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self._comment_prompt_edit, stretch=1)

        prompt_action_row = QHBoxLayout()
        prompt_action_row.setContentsMargins(0, 0, 0, 0)
        prompt_action_row.setSpacing(8)

        self._prompt_confirm_status = QLabel("当前 Prompt 未确认", self)
        self._prompt_confirm_status.setObjectName("promptConfirmStatus")
        self._prompt_confirm_status.setProperty("state", "idle")
        prompt_action_row.addWidget(self._prompt_confirm_status, stretch=1)

        self._restore_prompt_button = QPushButton("恢复默认", self)
        self._restore_prompt_button.setObjectName("promptActionButton")
        self._restore_prompt_button.setFixedHeight(32)
        self._restore_prompt_button.clicked.connect(self._on_restore_prompt_default)
        prompt_action_row.addWidget(self._restore_prompt_button)

        self._save_prompt_button = QPushButton("保存当前模板", self)
        self._save_prompt_button.setObjectName("promptActionButton")
        self._save_prompt_button.setFixedHeight(32)
        self._save_prompt_button.clicked.connect(self._on_save_prompt_template)
        prompt_action_row.addWidget(self._save_prompt_button)

        self._confirm_prompt_button = QPushButton("确认Prompt", self)
        self._confirm_prompt_button.setObjectName("promptConfirmButton")
        self._confirm_prompt_button.setFixedHeight(32)
        self._confirm_prompt_button.clicked.connect(self._on_confirm_prompt)
        prompt_action_row.addWidget(self._confirm_prompt_button)
        layout.addLayout(prompt_action_row)

        prompt_hint = QLabel("该 Prompt 仅用于观众评论的话术建议，不影响 ASR 语义分析、表情和动作映射。", self)
        prompt_hint.setObjectName("promptHint")
        prompt_hint.setWordWrap(True)
        layout.addWidget(prompt_hint)
        return card

    def _create_card(self, object_name: str) -> QFrame:
        """创建统一卡片容器。"""
        card = QFrame(self)
        card.setObjectName(object_name)
        card.setFrameShape(QFrame.Shape.NoFrame)
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        shadow = QGraphicsDropShadowEffect(card)
        shadow.setBlurRadius(14)
        shadow.setOffset(0, 3)
        shadow.setColor(QColor(15, 23, 42, 12))
        card.setGraphicsEffect(shadow)
        return card

    def _create_card_layout(self, card: QFrame) -> QVBoxLayout:
        """创建卡片内部统一布局。"""
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(11)
        return layout

    def _asset_icon(self, icon_name: str) -> QIcon:
        """读取本地 SVG 图标资产。"""
        return QIcon(str(ASSETS_DIR / icon_name))

    def _add_card_header(self, layout: QVBoxLayout, icon_name: str, title: str, description: str) -> None:
        """添加带图标和说明的卡片标题区。"""
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(13)

        icon_badge = QFrame(self)
        icon_badge.setObjectName("cardIconBadge")
        icon_badge.setFixedSize(38, 38)
        icon_layout = QVBoxLayout(icon_badge)
        icon_layout.setContentsMargins(0, 0, 0, 0)

        icon = QLabel(self)
        icon.setObjectName("cardIconText")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setPixmap(self._asset_icon(icon_name).pixmap(QSize(20, 20)))
        icon_layout.addWidget(icon)
        header.addWidget(icon_badge)

        text_group = QVBoxLayout()
        text_group.setContentsMargins(0, 0, 0, 0)
        text_group.setSpacing(3)

        title_label = QLabel(title, self)
        title_label.setObjectName("cardTitle")
        text_group.addWidget(title_label)

        description_label = QLabel(description, self)
        description_label.setObjectName("cardDescription")
        text_group.addWidget(description_label)
        header.addLayout(text_group, stretch=1)

        layout.addLayout(header)

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
        combo_box.setIconSize(QSize(18, 18))
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
            QStackedWidget#settingsContentStack,
            QWidget#settingsPanelPage {
                background: transparent;
                border: 0;
            }
            QFrame#settingsSidebar {
                background: rgba(255, 255, 255, 170);
                border: 1px solid rgba(226, 232, 240, 170);
                border-radius: 12px;
            }
            QFrame#settingsNavButton {
                background: transparent;
                border: 0;
                border-radius: 8px;
            }
            QFrame#settingsNavButton:hover {
                background: #F6FAFF;
            }
            QFrame#settingsNavButton[active="true"] {
                background: #EAF5FF;
                border: 0;
            }
            QLabel#settingsNavIcon {
                background: transparent;
                border: 0;
            }
            QLabel#settingsNavTitle {
                background: transparent;
                border: 0;
                color: #0F172A;
                font-size: 16px;
                font-weight: 800;
                padding: 0;
            }
            QLabel#settingsNavTitle[active="true"] {
                color: #1677FF;
            }
            QLabel#settingsNavDescription {
                background: transparent;
                border: 0;
                color: #64748B;
                font-size: 11px;
                font-weight: 500;
                padding: 0;
            }
            QLabel#settingsNavDescription[active="true"] {
                color: #1677FF;
            }
            QFrame#sidebarStatusCard {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 rgba(246, 250, 255, 170), stop:1 rgba(239, 246, 255, 170));
                border: 1px solid rgba(219, 234, 254, 160);
                border-radius: 10px;
            }
            QLabel#sidebarStatusTitle {
                color: #0F172A;
                font-size: 13px;
                font-weight: 800;
            }
            QLabel#sidebarStatusLabel {
                color: #DC2626;
                font-size: 12px;
                font-weight: 800;
            }
            QLabel#sidebarStatusLabel[state="ready"] {
                color: #52C41A;
            }
            QLabel#sidebarStatusDetail {
                color: #64748B;
                font-size: 11px;
                font-weight: 500;
            }
            QLabel#sidebarStatusWatermark {
                background: transparent;
                border: 0;
            }
            QFrame#cameraCard,
            QFrame#microphoneCard,
            QFrame#modelCard,
            QFrame#llmCard,
            QFrame#promptCard {
                background: rgba(255, 255, 255, 185);
                border: 1px solid rgba(229, 234, 242, 170);
                border-radius: 12px;
            }
            QFrame#cardIconBadge {
                background: #E6F4FF;
                border: 0;
                border-radius: 8px;
            }
            QLabel#cardIconText {
                background: transparent;
                border: 0;
            }
            QLabel#cardTitle {
                color: #0F172A;
                font-size: 19px;
                font-weight: 800;
            }
            QLabel#cardDescription {
                color: #64748B;
                font-size: 12px;
                font-weight: 500;
            }
            QLabel#fieldLabel {
                color: #172033;
                font-size: 14px;
                font-weight: 700;
            }
            QLabel#inlineFieldLabel {
                color: #172033;
                font-size: 14px;
                font-weight: 700;
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
            QLabel#deviceTestStatus {
                color: #64748B;
                background: #F8FAFC;
                border: 1px solid #E2E8F0;
                border-radius: 14px;
                font-size: 14px;
                font-weight: 700;
                padding: 0 10px;
            }
            QLabel#deviceTestStatus[result="success"] {
                background: #ECFDF5;
                border: 1px solid #BBF7D0;
                color: #059669;
            }
            QLabel#deviceTestStatus[result="error"] {
                background: #FEF2F2;
                border: 1px solid #FECACA;
                color: #DC2626;
            }
            QLabel#deviceTestStatus[result="testing"] {
                background: #EFF6FF;
                border: 1px solid #BFDBFE;
                color: #2563EB;
            }
            QLabel#resolutionSeparator {
                color: #94A3B8;
                font-size: 18px;
                font-weight: 700;
            }
            QLineEdit#numberInput,
            QLineEdit#llmInput,
            QTextEdit#promptTextArea,
            QFrame#unitInput,
            QComboBox#resolutionSelect,
            QComboBox#fpsSelect,
            QComboBox#cameraSelect,
            QComboBox#microphoneSelect,
            QComboBox#sampleRateSelect,
            QComboBox#promptModeSelect {
                background: rgba(255, 255, 255, 190);
                border: 1px solid rgba(221, 227, 234, 170);
                border-radius: 6px;
                color: #0F172A;
                font-size: 14px;
            }
            QLineEdit#numberInput {
                padding: 0 10px;
            }
            QLineEdit#numberInput:focus,
            QLineEdit#llmInput:focus,
            QTextEdit#promptTextArea:focus,
            QComboBox#resolutionSelect:focus,
            QComboBox#fpsSelect:focus,
            QComboBox#cameraSelect:focus,
            QComboBox#microphoneSelect:focus,
            QComboBox#sampleRateSelect:focus,
            QComboBox#promptModeSelect:focus {
                border: 1px solid #4096FF;
                background: #FFFFFF;
            }
            QLineEdit#llmInput {
                padding: 0 12px;
                min-height: 46px;
            }
            QTextEdit#promptTextArea {
                padding: 10px 12px;
                selection-background-color: #BFDBFE;
                line-height: 150%;
                font-size: 14px;
                color: #0F172A;
            }
            QLabel#promptHint {
                color: #64748B;
                font-size: 12px;
                font-weight: 500;
                padding: 2px 0 0 0;
            }
            QPushButton#promptModeButton {
                background: #F8FAFC;
                border: 1px solid #D6E2F0;
                border-radius: 16px;
                color: #475569;
                font-size: 12px;
                font-weight: 700;
                padding: 0 10px;
            }
            QPushButton#promptModeButton:hover {
                background: #EEF6FF;
                border-color: #9CCBFF;
                color: #0F5FD7;
            }
            QPushButton#promptModeButton:checked {
                background: #1677FF;
                border: 1px solid #1677FF;
                color: #FFFFFF;
            }
            QLabel#promptConfirmStatus {
                color: #DC2626;
                background: #FEF2F2;
                border: 1px solid #FECACA;
                border-radius: 16px;
                font-size: 12px;
                font-weight: 800;
                padding: 0 12px;
                min-height: 30px;
            }
            QLabel#promptConfirmStatus[state="ready"] {
                color: #059669;
                background: #ECFDF5;
                border: 1px solid #BBF7D0;
            }
            QLabel#promptConfirmStatus[state="saved"] {
                color: #2563EB;
                background: #EFF6FF;
                border: 1px solid #BFDBFE;
            }
            QPushButton#promptActionButton {
                background: #F8FAFC;
                border: 1px solid #CBD5E1;
                border-radius: 6px;
                color: #334155;
                font-size: 13px;
                font-weight: 700;
                padding: 0 12px;
            }
            QPushButton#promptActionButton:hover {
                background: #EEF6FF;
                border-color: #9CCBFF;
                color: #0F5FD7;
            }
            QPushButton#promptConfirmButton {
                background: #1677FF;
                border: 1px solid #1677FF;
                border-radius: 6px;
                color: #FFFFFF;
                font-size: 13px;
                font-weight: 800;
                padding: 0 14px;
            }
            QPushButton#promptConfirmButton:hover {
                background: #4096FF;
                border-color: #4096FF;
            }
            QLineEdit#unitInputEdit {
                background: transparent;
                border: 0;
                color: #1E293B;
                font-size: 14px;
                padding: 0;
            }
            QLabel#unitSuffix {
                background: #FAFAFA;
                border-left: 1px solid #D9D9D9;
                color: #64748B;
                font-size: 14px;
                font-weight: 600;
            }
            QComboBox#fpsSelect,
            QComboBox#resolutionSelect,
            QComboBox#cameraSelect,
            QComboBox#microphoneSelect,
            QComboBox#sampleRateSelect,
            QComboBox#promptModeSelect {
                padding-left: 10px;
                padding-right: 28px;
            }
            QComboBox::drop-down {
                border: 0;
                width: 34px;
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
                background: rgba(248, 250, 252, 170);
                border: 1px solid rgba(226, 232, 240, 170);
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
            QPushButton#secondaryButton:hover,
            QPushButton#testButton:hover,
            QPushButton#refreshIconButton:hover {
                background: #EEF6FF;
                border-color: #9CCBFF;
            }
            QPushButton#browseButton:pressed,
            QPushButton#secondaryButton:pressed,
            QPushButton#testButton:pressed,
            QPushButton#refreshIconButton:pressed {
                background: #CBD5E1;
            }
            QPushButton#secondaryButton,
            QPushButton#testButton {
                background: #F8FAFC;
                border: 1px solid #CBD5E1;
                border-radius: 6px;
                color: #0F5FD7;
                font-size: 13px;
                font-weight: 700;
                padding: 0 14px;
            }
            QPushButton#testButton {
                min-width: 126px;
            }
            QPushButton#refreshIconButton {
                background: #F8FAFC;
                border: 1px solid #D6E2F0;
                border-radius: 6px;
                color: #0F2748;
                font-size: 13px;
                font-weight: 700;
                padding: 0;
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
        self._model_selector.currentIndexChanged.connect(self._on_model_selected)
        self._model_path_edit.textChanged.connect(self._on_setting_changed)
        self._llm_base_url_edit.textChanged.connect(self._on_setting_changed)
        self._llm_api_key_edit.textChanged.connect(self._on_setting_changed)
        self._llm_model_edit.textChanged.connect(self._on_setting_changed)
        self._comment_prompt_edit.textChanged.connect(self._on_prompt_text_changed)
        self.device_test_finished.connect(self._on_device_test_finished)

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
            self._model_selector,
            self._model_path_edit,
            self._llm_base_url_edit,
            self._llm_api_key_edit,
            self._llm_model_edit,
            self._comment_prompt_edit,
        )
        for widget in widgets:
            widget.blockSignals(True)

        self._populate_camera_options(self._config.camera_index)
        self._populate_microphone_options(self._config.microphone_index)
        self._camera_width.setValue(self._config.camera_width)
        self._camera_height.setValue(self._config.camera_height)
        self._set_combo_value(self._camera_fps, f"{self._config.camera_fps} FPS")
        self._set_combo_value(self._mic_sample_rate, f"{self._config.mic_sample_rate} Hz")
        self._mic_block_size.setValue(self._config.mic_block_size)

        # 模型下拉框：从 model_paths 的键生成选项，选中 model_name
        self._model_selector.clear()
        model_names = list(self._config.model_paths.keys())
        for name in model_names:
            self._model_selector.addItem(name, name)
        selected_idx = self._model_selector.findData(self._config.model_name)
        if selected_idx >= 0:
            self._model_selector.setCurrentIndex(selected_idx)
        # 同步路径显示
        self._model_path_edit.setText(self._config.model_paths.get(self._config.model_name, ""))

        self._llm_base_url_edit.setText(self._config.llm_base_url)
        self._llm_api_key_edit.setText(self._config.llm_api_key)
        self._llm_model_edit.setText(self._config.llm_model)
        self._active_prompt_mode = normalize_comment_prompt_mode(self._config.comment_prompt_mode)
        self._set_prompt_mode_button_state(self._active_prompt_mode)
        self._comment_prompt_edit.setPlainText(get_comment_prompt_text(self._config))
        self._sync_prompt_editor_state()

        for widget in widgets:
            widget.blockSignals(False)

        self._update_model_path_state()
        self._refresh_prompt_confirm_state()

    def _populate_camera_options(self, selected_index: int) -> None:
        """刷新摄像头下拉项，并保留当前配置索引。"""
        available_indices = list_available_camera_indices()
        indices = sorted(set(available_indices + [selected_index]))

        self._camera_index.clear()
        camera_icon = self._asset_icon("camera.svg")
        for index in indices:
            suffix = "" if index in available_indices else "（未检测）"
            self._camera_index.addItem(camera_icon, f"摄像头 {index}{suffix}", index)

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
        microphone_icon = self._asset_icon("microphone.svg")
        for index, name in sorted(device_map.items()):
            self._microphone_index.addItem(microphone_icon, f"{name}  [{index}]", index)

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

    # ---- 设备测试 ----

    def _start_camera_test(self) -> None:
        """在后台测试摄像头能否打开并读取画面。"""
        if self._camera_test_running:
            return

        camera_index = self._camera_index.currentData()
        if camera_index is None:
            self._set_device_test_status("camera", "error", "连接失败：未选择摄像头")
            return

        self._camera_test_running = True
        self._camera_test_button.setEnabled(False)
        self._set_device_test_status("camera", "testing", "检测中...")

        width = self._camera_width.value()
        height = self._camera_height.value()
        fps = int(self._camera_fps.currentText().split()[0])
        worker = threading.Thread(
            target=self._run_camera_test,
            args=(int(camera_index), width, height, fps),
            name="camera-device-test",
            daemon=True,
        )
        worker.start()

    def _start_microphone_test(self) -> None:
        """在后台测试麦克风能否打开并采样。"""
        if self._microphone_test_running:
            return

        microphone_index = self._microphone_index.currentData()
        if microphone_index is None:
            self._set_device_test_status("microphone", "error", "连接失败：未选择麦克风")
            return

        self._microphone_test_running = True
        self._microphone_test_button.setEnabled(False)
        self._set_device_test_status("microphone", "testing", "检测中...")

        sample_rate = int(self._mic_sample_rate.currentText().split()[0])
        block_size = self._mic_block_size.value()
        worker = threading.Thread(
            target=self._run_microphone_test,
            args=(int(microphone_index), sample_rate, block_size),
            name="microphone-device-test",
            daemon=True,
        )
        worker.start()

    def _start_model_test(self) -> None:
        """在后台测试 Live2D 人物模型文件是否可加载。"""
        if self._model_test_running:
            return

        model_path_text = self._config.model_paths.get(self._config.model_name, "")
        model_path = resolve_project_path(model_path_text)
        if not model_path_text:
            self._set_device_test_status("model", "error", "连接失败：请先选择人物模型文件")
            return
        if not model_path.is_file():
            self._set_device_test_status("model", "error", "连接失败：模型文件不存在")
            return

        self._model_test_running = True
        self._model_test_button.setEnabled(False)
        self._set_device_test_status("model", "testing", "检测中...")

        worker = threading.Thread(
            target=self._run_model_test,
            args=(model_path,),
            name="live2d-model-test",
            daemon=True,
        )
        worker.start()

    def _start_llm_test(self) -> None:
        """在后台测试 LLM 接口是否可用。"""
        if self._llm_test_running:
            return

        base_url = self._llm_base_url_edit.text().strip()
        api_key = self._llm_api_key_edit.text().strip()
        model = self._llm_model_edit.text().strip()
        if not api_key or not model:
            self._set_device_test_status("llm", "error", "连接失败：请先填写 API Key 和模型名称")
            return

        self._llm_test_running = True
        self._llm_test_button.setEnabled(False)
        self._set_device_test_status("llm", "testing", "检测中...")

        worker = threading.Thread(
            target=self._run_llm_test,
            args=(base_url, api_key, model),
            name="llm-device-test",
            daemon=True,
        )
        worker.start()

    def _run_camera_test(self, camera_index: int, width: int, height: int, fps: int) -> None:
        """后台执行摄像头测试，避免阻塞设置页。"""
        try:
            import cv2

            # 按开播前预检思路连续读取约 1 秒，避免偶发一帧成功造成误判。
            capture = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW)
            try:
                if not capture.isOpened():
                    self.device_test_finished.emit("camera", False, f"连接失败：无法打开摄像头 {camera_index}")
                    return

                capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
                capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
                capture.set(cv2.CAP_PROP_FPS, fps)

                success_count = 0
                last_frame = None
                brightness_values: list[float] = []
                texture_values: list[float] = []
                deadline = time.monotonic() + 1.0
                while time.monotonic() < deadline:
                    success, frame = capture.read()
                    if success and frame is not None:
                        success_count += 1
                        last_frame = frame
                        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                        brightness_values.append(float(gray.mean()))
                        texture_values.append(float(gray.std()))
                    time.sleep(0.02)

                if success_count < 3 or last_frame is None:
                    self.device_test_finished.emit("camera", False, "连接失败：1 秒内未稳定读取到画面")
                    return

                avg_brightness = sum(brightness_values) / len(brightness_values)
                avg_texture = sum(texture_values) / len(texture_values)
                # 摄像头被关闭或隐私遮挡时，部分驱动仍会返回纯色占位帧，必须把这种无细节画面判为失败。
                if avg_texture < 2.0 or (avg_brightness < 8.0 and avg_texture < 4.0):
                    self.device_test_finished.emit("camera", False, "连接失败：摄像头画面为空白、黑屏或无有效细节")
                    return

                frame_height, frame_width = last_frame.shape[:2]
                self.device_test_finished.emit("camera", True, f"连接正常，1 秒读取 {success_count} 帧 {frame_width}×{frame_height}")
            finally:
                capture.release()
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("摄像头连接测试失败：%s", exc)
            self.device_test_finished.emit("camera", False, f"连接失败：{self._format_test_error(exc)}")

    def _run_microphone_test(self, microphone_index: int, sample_rate: int, block_size: int) -> None:
        """后台执行麦克风测试，确认输入流可以采样。"""
        try:
            import sounddevice as sd

            # 按直播实际采样参数打开输入流，连续采样约 1 秒并检查是否有有效输入。
            frames = max(block_size, int(sample_rate * 1.0))
            stream = sd.InputStream(
                device=microphone_index,
                samplerate=sample_rate,
                channels=1,
                dtype="float32",
                blocksize=block_size,
            )
            try:
                stream.start()
                samples, overflowed = stream.read(frames)
            finally:
                with contextlib.suppress(Exception):
                    stream.stop()
                with contextlib.suppress(Exception):
                    stream.close()

            if samples is None or len(samples) == 0:
                self.device_test_finished.emit("microphone", False, "连接失败：未采样到音频")
                return

            peak = float(abs(samples).max())
            if peak <= 1e-6:
                self.device_test_finished.emit("microphone", False, "连接失败：未检测到有效输入，请检查静音或权限")
                return

            suffix = "，采样有溢出" if overflowed else ""
            self.device_test_finished.emit("microphone", True, f"预检通过，已采样 1 秒，峰值 {peak:.4f}{suffix}")
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("麦克风连接测试失败：%s", exc)
            self.device_test_finished.emit("microphone", False, f"连接失败：{self._format_test_error(exc)}")

    def _run_model_test(self, model_path: Path) -> None:
        """后台执行人物模型测试，校验模型 JSON 并真实渲染第一帧。"""
        renderer = None
        try:
            from virtual_avatar_system.renderer.live2d_renderer import Live2DRenderer

            # 先做资源完整性校验，能更快给出缺文件这类确定错误。
            model_data = json.loads(model_path.read_text(encoding="utf-8"))
            file_references = model_data.get("FileReferences", {})
            if not isinstance(file_references, dict):
                self.device_test_finished.emit("model", False, "连接失败：模型缺少 FileReferences")
                return

            model_dir = model_path.parent
            missing_files: list[str] = []

            moc_file = file_references.get("Moc")
            if isinstance(moc_file, str) and not (model_dir / moc_file).is_file():
                missing_files.append(moc_file)

            textures = file_references.get("Textures", [])
            if isinstance(textures, list):
                for texture in textures:
                    if isinstance(texture, str) and not (model_dir / texture).is_file():
                        missing_files.append(texture)

            if missing_files:
                preview = "、".join(missing_files[:2])
                suffix = "..." if len(missing_files) > 2 else ""
                self.device_test_finished.emit("model", False, f"连接失败：缺少资源 {preview}{suffix}")
                return

            # 再启动一次真实 Live2D 渲染，等待第一帧完成后立即关闭。
            renderer = Live2DRenderer()
            # 加载参数映射表，确保测试时使用正确的参数 ID
            from virtual_avatar_system.config.app_config import load_param_mappings
            test_mappings = load_param_mappings(self._config.model_name)
            renderer.start(
                model_path,
                window_size=(240, 360),
                always_on_top=False,
                param_mappings=test_mappings if test_mappings else None,
            )
            # Live2D 首次加载会解析动作、表情和纹理资源，部分机器上会超过 8 秒。
            deadline = time.monotonic() + 15.0
            while time.monotonic() < deadline:
                if renderer.is_ready:
                    self.device_test_finished.emit("model", True, "预检通过，Live2D 已完成第一帧渲染")
                    return
                if not renderer.is_running:
                    self.device_test_finished.emit("model", False, "连接失败：Live2D 渲染进程提前退出")
                    return
                time.sleep(0.05)

            self.device_test_finished.emit("model", False, "连接失败：Live2D 15 秒内未完成渲染")
        except json.JSONDecodeError as exc:
            LOGGER.warning("人物模型 JSON 解析失败：%s", exc)
            self.device_test_finished.emit("model", False, "连接失败：模型 JSON 格式异常")
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("人物模型连接测试失败：%s", exc)
            self.device_test_finished.emit("model", False, f"连接失败：{self._format_test_error(exc)}")
        finally:
            if renderer is not None:
                with contextlib.suppress(Exception):
                    renderer.stop()

    def _run_llm_test(self, base_url: str, api_key: str, model: str) -> None:
        """后台执行 LLM 测试，使用直播语义理解链路完成一次真实调用。"""
        try:
            from virtual_avatar_system.llm.semantic import SemanticInterpreter, SemanticInterpreterConfig

            # 使用直播时相同的 SemanticInterpreter，而不是单独走一套 OpenAI SDK 测试逻辑。
            interpreter = SemanticInterpreter(
                SemanticInterpreterConfig.from_sources(
                    base_url=base_url,
                    api_key=api_key,
                    model=model,
                    model_name=self._config.model_name,
                    min_interval_ms=0,
                )
            )
            result = interpreter.interpret(
                "观众提问：这个虚拟形象系统适合课堂展示和直播讲解吗？",
                context={"scene": "preflight_test"},
                force=True,
            )
            if result.error:
                self.device_test_finished.emit("llm", False, f"连接失败：{self._format_test_error(RuntimeError(result.error))}")
                return

            if result.label:
                self.device_test_finished.emit("llm", True, f"预检通过，语义标签：{result.label}")
                return

            self.device_test_finished.emit("llm", False, "连接失败：语义模块未返回有效标签")
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("LLM 连接测试失败：%s", self._format_test_error(exc))
            self.device_test_finished.emit("llm", False, f"连接失败：{self._format_test_error(exc)}")

    def _on_device_test_finished(self, device_type: str, success: bool, message: str) -> None:
        """接收后台线程测试结果并刷新界面状态。"""
        result = "success" if success else "error"
        self._set_device_test_status(device_type, result, message)

        if device_type == "camera":
            self._camera_test_running = False
            self._camera_test_button.setEnabled(True)
            return

        if device_type == "microphone":
            self._microphone_test_running = False
            self._microphone_test_button.setEnabled(True)
            return

        if device_type == "model":
            self._model_test_running = False
            self._model_test_button.setEnabled(True)
            return

        if device_type == "llm":
            self._llm_test_running = False
            self._llm_test_button.setEnabled(True)

    def _set_device_test_status(self, device_type: str, result: str, message: str) -> None:
        """统一更新设备测试标签样式。"""
        status_labels = {
            "camera": self._camera_test_status,
            "microphone": self._microphone_test_status,
            "model": self._model_test_status,
            "llm": self._llm_test_status,
        }
        self._test_results[device_type] = result
        label = status_labels[device_type]
        status_text_map = {
            "idle": "● 未测试",
            "testing": "● 检测中",
            "success": "● 连接正常",
            "error": "● 连接异常",
        }
        label.setText(status_text_map.get(result, message))
        label.setToolTip(message)
        label.setProperty("result", result)
        label.style().unpolish(label)
        label.style().polish(label)
        self._set_config_valid(self._compute_config_validity())

    def _format_test_error(self, exc: Exception) -> str:
        """把底层异常压缩成适合界面展示的短提示。"""
        text = str(exc).strip() or exc.__class__.__name__
        return text if len(text) <= 46 else f"{text[:43]}..."

    def _set_combo_value(self, combo_box: QComboBox, text: str) -> None:
        """根据文本设置下拉框当前值。"""
        index = combo_box.findText(text)
        if index < 0:
            combo_box.addItem(text)
            index = combo_box.findText(text)
        combo_box.setCurrentIndex(index)

    def _on_prompt_mode_button_clicked(self, mode: str) -> None:
        """切换 Prompt 页签，切换前先保存当前文本。"""
        previous_mode = getattr(self, "_active_prompt_mode", normalize_comment_prompt_mode(self._config.comment_prompt_mode))
        self._store_prompt_text(previous_mode, self._comment_prompt_edit.toPlainText())

        self._active_prompt_mode = normalize_comment_prompt_mode(mode)
        self._config.comment_prompt_mode = self._active_prompt_mode
        self._set_prompt_mode_button_state(self._active_prompt_mode)

        self._comment_prompt_edit.blockSignals(True)
        self._comment_prompt_edit.setPlainText(self._get_prompt_text_for_mode(self._active_prompt_mode))
        self._comment_prompt_edit.blockSignals(False)
        self._sync_prompt_editor_state()
        self._notify_prompt_config_changed()
        self._refresh_prompt_confirm_state("切换模板后，请确认Prompt")

    def _on_prompt_text_changed(self) -> None:
        """保存当前 Prompt 文本，不重置设备连接测试结果。"""
        mode = getattr(self, "_active_prompt_mode", normalize_comment_prompt_mode(self._config.comment_prompt_mode))
        if mode == "no_prompt":
            return
        self._store_prompt_text(mode, self._comment_prompt_edit.toPlainText())
        self._config.comment_prompt_mode = mode
        self._notify_prompt_config_changed()
        self._refresh_prompt_confirm_state("当前 Prompt 已修改，请重新确认")

    def _on_restore_prompt_default(self) -> None:
        """恢复当前页签的默认 Prompt，并要求重新确认。"""
        mode = getattr(self, "_active_prompt_mode", normalize_comment_prompt_mode(self._config.comment_prompt_mode))
        if mode == "ecommerce":
            default_text = DEFAULT_ECOMMERCE_PROMPT
        elif mode == "custom":
            default_text = ""
        elif mode == "no_prompt":
            default_text = self._get_prompt_text_for_mode(mode)
        else:
            default_text = DEFAULT_COURSE_QA_PROMPT

        self._comment_prompt_edit.blockSignals(True)
        self._comment_prompt_edit.setPlainText(default_text)
        self._comment_prompt_edit.blockSignals(False)
        self._store_prompt_text(mode, default_text)
        self._notify_prompt_config_changed()
        self._refresh_prompt_confirm_state("已恢复默认，请确认Prompt")

    def _on_save_prompt_template(self) -> None:
        """保存当前模板文本，但不代表开播时已确认使用。"""
        mode = getattr(self, "_active_prompt_mode", normalize_comment_prompt_mode(self._config.comment_prompt_mode))
        if mode == "no_prompt":
            self._config.comment_prompt_mode = mode
            self._notify_prompt_config_changed()
            self._refresh_prompt_confirm_state("不添加Prompt模式无需保存，请确认Prompt")
            return
        self._store_prompt_text(mode, self._comment_prompt_edit.toPlainText())
        self._config.comment_prompt_mode = mode
        self._notify_prompt_config_changed()
        self._refresh_prompt_confirm_state("模板已保存，请确认Prompt")

    def _on_confirm_prompt(self) -> None:
        """确认开播时使用当前页签和当前文本。"""
        mode = getattr(self, "_active_prompt_mode", normalize_comment_prompt_mode(self._config.comment_prompt_mode))
        prompt_text = self._comment_prompt_edit.toPlainText().strip()
        self._store_prompt_text(mode, prompt_text)
        self._config.comment_prompt_mode = mode
        if mode == "no_prompt":
            self._config.comment_prompt_confirmed_mode = mode
            self._config.comment_prompt_confirmed_text = ""
            self._notify_prompt_config_changed()
            self._refresh_prompt_confirm_state()
            self._set_config_valid(self._compute_config_validity())
            return
        if not prompt_text:
            self._config.comment_prompt_confirmed_mode = ""
            self._config.comment_prompt_confirmed_text = ""
            self._notify_prompt_config_changed()
            self._refresh_prompt_confirm_state("Prompt 为空，无法确认")
            return

        self._config.comment_prompt_confirmed_mode = mode
        self._config.comment_prompt_confirmed_text = prompt_text
        self._notify_prompt_config_changed()
        self._refresh_prompt_confirm_state()
        self._set_config_valid(self._compute_config_validity())

    def _set_prompt_mode_button_state(self, mode: str) -> None:
        """同步 Prompt 三段按钮选中态。"""
        for button_mode, button in self._prompt_mode_buttons.items():
            button.blockSignals(True)
            button.setChecked(button_mode == mode)
            button.blockSignals(False)

    def _get_prompt_text_for_mode(self, mode: str) -> str:
        """读取指定模式的完整 Prompt 文本。"""
        normalized_mode = normalize_comment_prompt_mode(mode)
        if normalized_mode == "no_prompt":
            return "当前选择不添加额外 Prompt。\n\n确认后，系统仍会分析观众评论并生成推荐回复，但不会使用课程答疑、电商带货或自定义提示词约束。"
        if normalized_mode == "ecommerce":
            return self._config.comment_ecommerce_prompt or DEFAULT_ECOMMERCE_PROMPT
        if normalized_mode == "custom":
            return self._config.comment_custom_prompt
        return self._config.comment_course_prompt or DEFAULT_COURSE_QA_PROMPT

    def _store_prompt_text(self, mode: str, text: str) -> None:
        """把当前编辑框内容保存到对应 Prompt 模板字段。"""
        normalized_mode = normalize_comment_prompt_mode(mode)
        cleaned = text.strip()
        if normalized_mode == "no_prompt":
            return
        if normalized_mode == "ecommerce":
            self._config.comment_ecommerce_prompt = cleaned
            return
        if normalized_mode == "custom":
            self._config.comment_custom_prompt = cleaned
            return
        self._config.comment_course_prompt = cleaned

    def _notify_prompt_config_changed(self) -> None:
        """通知主窗口持久化 Prompt，但不改变设备预检状态。"""
        for callback in self._on_config_changed_callbacks:
            try:
                callback(self._config)
            except Exception as exc:  # noqa: BLE001
                LOGGER.error("Prompt 配置变更回调异常：%s", exc)

    def _is_prompt_confirmed(self) -> bool:
        """判断当前页签和当前文本是否已经被用户确认用于开播。"""
        mode = getattr(self, "_active_prompt_mode", normalize_comment_prompt_mode(self._config.comment_prompt_mode))
        if mode == "no_prompt":
            return normalize_comment_prompt_mode(self._config.comment_prompt_confirmed_mode) == "no_prompt"
        prompt_text = self._comment_prompt_edit.toPlainText().strip()
        return (
            bool(prompt_text)
            and normalize_comment_prompt_mode(self._config.comment_prompt_confirmed_mode) == mode
            and self._config.comment_prompt_confirmed_text.strip() == prompt_text
        )

    def _prompt_mode_display_name(self, mode: str) -> str:
        """把 Prompt 模式转换成界面展示名称。"""
        return {
            "course_qa": "课程答疑",
            "ecommerce": "电商带货",
            "custom": "自定义",
            "no_prompt": "不添加Prompt",
        }.get(normalize_comment_prompt_mode(mode), "课程答疑")

    def _sync_prompt_editor_state(self) -> None:
        """根据当前 Prompt 模式同步编辑框和模板按钮状态。"""
        is_no_prompt = getattr(self, "_active_prompt_mode", normalize_comment_prompt_mode(self._config.comment_prompt_mode)) == "no_prompt"
        self._comment_prompt_edit.setReadOnly(is_no_prompt)
        self._restore_prompt_button.setEnabled(not is_no_prompt)
        self._save_prompt_button.setEnabled(not is_no_prompt)
        self._comment_prompt_edit.setToolTip("不添加Prompt模式下无需编辑提示词。" if is_no_prompt else "")

    def _refresh_prompt_confirm_state(self, message: str | None = None) -> None:
        """刷新 Prompt 确认状态，并同步开播前有效性。"""
        if self._is_prompt_confirmed():
            mode_name = self._prompt_mode_display_name(self._config.comment_prompt_confirmed_mode)
            self._prompt_confirm_status.setText(f"● 已确认使用：{mode_name}")
            self._prompt_confirm_status.setProperty("state", "ready")
        else:
            self._prompt_confirm_status.setText(f"● {message or '当前 Prompt 未确认'}")
            self._prompt_confirm_status.setProperty("state", "saved" if message and "保存" in message else "idle")
        self._prompt_confirm_status.style().unpolish(self._prompt_confirm_status)
        self._prompt_confirm_status.style().polish(self._prompt_confirm_status)
        self._set_config_valid(self._compute_config_validity())

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

    def _on_model_selected(self) -> None:
        """下拉框切换模型时，更新 model_name 并同步路径显示和测试状态。"""
        new_name = self._model_selector.currentData()
        if new_name is None or new_name == self._config.model_name:
            return
        self._config.model_name = new_name
        self._model_path_edit.setText(self._config.model_paths.get(new_name, ""))
        self._update_model_path_state()
        self._reset_test_results()
        self._set_config_valid(self._compute_config_validity())

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

        self._reset_test_results()
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
        model_path_valid = self._update_model_path_state()
        return model_path_valid and self._is_prompt_confirmed() and all(result == "success" for result in self._test_results.values())

    def startup_blocker_text(self) -> str:
        """返回阻止开播的主要原因，供主窗口按钮提示使用。"""
        pending_text = self._build_pending_test_text()
        if pending_text == "Prompt未确认":
            return "请先确认Prompt"
        if pending_text == "请完成连接测试":
            return "请先完成摄像头、麦克风、人物模型和 LLM 连接测试"
        return pending_text

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
        self._update_sidebar_status(valid)
        if self._is_config_valid == valid:
            return
        self._is_config_valid = valid
        if emit:
            self.config_validity_changed.emit(valid)

    def _update_sidebar_status(self, valid: bool) -> None:
        """同步左侧系统状态卡片。"""
        self._sidebar_status_label.setText("● 已就绪" if valid else "● 未就绪")
        self._sidebar_status_label.setProperty("state", "ready" if valid else "idle")
        self._sidebar_status_detail.setText("所有设备连接正常" if valid else self._build_pending_test_text())
        self._sidebar_status_label.style().unpolish(self._sidebar_status_label)
        self._sidebar_status_label.style().polish(self._sidebar_status_label)

    def _reset_test_results(self) -> None:
        """配置发生变化后重置连接测试状态。"""
        for device_type in self._test_results:
            self._set_device_test_status(device_type, "idle", "配置已变化，请重新测试")

    def _build_pending_test_text(self) -> str:
        """生成未就绪时左下角状态说明。"""
        device_names = {
            "camera": "摄像头",
            "microphone": "麦克风",
            "model": "人物模型",
            "llm": "LLM",
        }
        parts: list[str] = []
        for result_type, suffix in (("error", "连接异常"), ("testing", "检测中"), ("idle", "未测试")):
            names = [device_names[key] for key, result in self._test_results.items() if result == result_type]
            if names:
                parts.append(f"{'、'.join(names)}{suffix}")
        if not self._is_prompt_confirmed():
            parts.append("Prompt未确认")
        return "；".join(parts) if parts else "请完成连接测试"
