"""独立预览窗口模块。

职责：
- 以独立置顶小窗形式展示 Live2D 虚拟形象
- 支持显示/隐藏、拖拽移动
- 未来接入 Live2D 渲染层后在此窗口内绘制
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Final

from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QColor, QMouseEvent
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel

LOGGER = logging.getLogger(__name__)

# 默认预览窗口尺寸与背景色
DEFAULT_WIDTH: Final[int] = 360
DEFAULT_HEIGHT: Final[int] = 640
BG_COLOR: Final[QColor] = QColor(0, 255, 0)  # 绿色背景，后续与 Live2D 透明窗口配合


class PreviewWindow(QWidget):
    """Live2D 虚拟形象预览小窗。

    关键行为：
    - 默认置顶
    - 无边框
    - 可鼠标拖动
    - 可显示/隐藏
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._dragging = False
        self._drag_offset = QPoint()

        self._setup_window()
        self._setup_ui()

    # ---- 窗口属性 ----

    def _setup_window(self) -> None:
        """配置窗口外观与行为。"""
        self.setWindowTitle("虚拟形象预览")
        self.setFixedSize(DEFAULT_WIDTH, DEFAULT_HEIGHT)
        # 无边框 + 置顶
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.resize(DEFAULT_WIDTH, DEFAULT_HEIGHT)

    def _setup_ui(self) -> None:
        """设置预览窗口内占位内容。"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        placeholder = QLabel("Live2D 预览区域\n（后续接入渲染层）", self)
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder.setStyleSheet(
            f"background-color: {BG_COLOR.name()}; color: white; font-size: 16px;"
        )
        layout.addWidget(placeholder)

    # ---- 拖动支持 ----

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """按下鼠标左键开始拖动窗口。"""
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """拖动过程中移动窗口。"""
        if self._dragging and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """松开鼠标结束拖动。"""
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
        super().mouseReleaseEvent(event)

    # ---- 公共接口 ----

    def toggle_visibility(self) -> None:
        """切换显示/隐藏。"""
        if self.isVisible():
            self.hide()
        else:
            self.show()
