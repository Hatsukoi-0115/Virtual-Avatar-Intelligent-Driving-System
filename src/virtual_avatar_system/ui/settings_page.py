"""设置页模块。

职责：
- 提供摄像头、麦克风、渲染相关选项的配置界面
- 配置变更后同步写入持久化文件
- 未来可扩展 LLM 密钥、模型路径等选项
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QGroupBox,
    QSpinBox,
    QComboBox,
    QPushButton,
    QLabel,
    QLineEdit,
    QCheckBox,
)

from virtual_avatar_system.config.app_config import AppConfig

LOGGER = logging.getLogger(__name__)


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
        main_layout = QVBoxLayout(self)

        # ---- 设备组 ----
        device_group = QGroupBox("设备选择", self)
        device_form = QFormLayout(device_group)

        self._camera_combo = QComboBox(self)
        self._camera_combo.addItems([f"摄像头 {i}" for i in range(4)])
        device_form.addRow("摄像头：", self._camera_combo)

        self._mic_combo = QComboBox(self)
        self._mic_combo.addItems([f"麦克风 {i}" for i in range(4)])
        device_form.addRow("麦克风：", self._mic_combo)

        main_layout.addWidget(device_group)

        # ---- 摄像头参数组 ----
        camera_group = QGroupBox("摄像头参数", self)
        camera_form = QFormLayout(camera_group)

        self._camera_width = QSpinBox(self)
        self._camera_width.setRange(320, 3840)
        self._camera_width.setSingleStep(160)
        camera_form.addRow("分辨率宽度：", self._camera_width)

        self._camera_height = QSpinBox(self)
        self._camera_height.setRange(240, 2160)
        self._camera_height.setSingleStep(120)
        camera_form.addRow("分辨率高度：", self._camera_height)

        self._camera_fps = QSpinBox(self)
        self._camera_fps.setRange(10, 60)
        camera_form.addRow("帧率：", self._camera_fps)

        main_layout.addWidget(camera_group)

        # ---- 预览组 ----
        preview_group = QGroupBox("预览窗口", self)
        preview_form = QFormLayout(preview_group)

        self._preview_always_on_top = QCheckBox("始终置顶", self)
        preview_form.addRow(self._preview_always_on_top)

        main_layout.addWidget(preview_group)

        # ---- 模型路径 ----
        model_group = QGroupBox("模型", self)
        model_form = QFormLayout(model_group)

        self._model_path_edit = QLineEdit(self)
        model_form.addRow("Live2D 模型路径：", self._model_path_edit)

        main_layout.addWidget(model_group)

        main_layout.addStretch()

        # ---- 连接信号 ----
        self._connect_signals()

    def _connect_signals(self) -> None:
        """将控件变更连接到保存逻辑。"""
        self._camera_combo.currentIndexChanged.connect(self._on_setting_changed)
        self._mic_combo.currentIndexChanged.connect(self._on_setting_changed)
        self._camera_width.valueChanged.connect(self._on_setting_changed)
        self._camera_height.valueChanged.connect(self._on_setting_changed)
        self._camera_fps.valueChanged.connect(self._on_setting_changed)
        self._preview_always_on_top.toggled.connect(self._on_setting_changed)
        self._model_path_edit.textChanged.connect(self._on_setting_changed)

    # ---- 配置加载与保存 ----

    def _load_from_config(self) -> None:
        """把 AppConfig 字段同步到 UI 控件。"""
        # 初始化时阻塞信号，避免控件值变更触发保存逻辑覆盖配置
        for widget in (
            self._camera_combo,
            self._mic_combo,
            self._camera_width,
            self._camera_height,
            self._camera_fps,
            self._preview_always_on_top,
            self._model_path_edit,
        ):
            widget.blockSignals(True)

        self._camera_combo.setCurrentIndex(self._config.camera_index)
        self._mic_combo.setCurrentIndex(self._config.microphone_index)
        self._camera_width.setValue(self._config.camera_width)
        self._camera_height.setValue(self._config.camera_height)
        self._camera_fps.setValue(self._config.camera_fps)
        self._preview_always_on_top.setChecked(self._config.preview_always_on_top)
        self._model_path_edit.setText(self._config.model_path)

        # 填充完成后恢复信号
        for widget in (
            self._camera_combo,
            self._mic_combo,
            self._camera_width,
            self._camera_height,
            self._camera_fps,
            self._preview_always_on_top,
            self._model_path_edit,
        ):
            widget.blockSignals(False)

    def _on_setting_changed(self) -> None:
        """控件值变更 -> 写入 AppConfig -> 通知外部。"""
        self._config.camera_index = self._camera_combo.currentIndex()
        self._config.microphone_index = self._mic_combo.currentIndex()
        self._config.camera_width = self._camera_width.value()
        self._config.camera_height = self._camera_height.value()
        self._config.camera_fps = self._camera_fps.value()
        self._config.preview_always_on_top = self._preview_always_on_top.isChecked()
        self._config.model_path = self._model_path_edit.text()

        LOGGER.info("配置已更新：camera=%s mic=%s", self._config.camera_index, self._config.microphone_index)

        for callback in self._on_config_changed_callbacks:
            try:
                callback(self._config)
            except Exception as exc:  # noqa: BLE001
                LOGGER.error("配置变更回调异常：%s", exc)
