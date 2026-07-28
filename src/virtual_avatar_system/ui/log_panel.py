"""日志输出面板模块。

提供线程安全的后端日志输出展示组件，用于在直播开始界面上
实时显示 ASR、情绪分类、LLM 语义等后端模块的运行输出。
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QObject, Signal
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QIcon, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

ASSETS_DIR = Path(__file__).resolve().parent / "assets"


class LogSignal(QObject):
    """跨线程安全的日志信号，用于将后台线程输出安全地投递到 UI 线程。"""

    append = Signal(str)


class LogPanel(QWidget):
    """后端输出日志面板。

    使用方式：
        panel = LogPanel()
        panel.append_log("[ASR] 你好世界")
        panel.append_log("[LLM] 句子=你好 标签=wave")

    append_log() 可从任意线程调用，内部通过 Qt 信号确保 UI 更新在主线程执行。
    """

    _MAX_BLOCK_COUNT = 500

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._signal = LogSignal()
        self._signal.append.connect(self._on_append_log, Qt.ConnectionType.QueuedConnection)

        self._setup_ui()

    # ---- 公共接口 ----

    def append_log(self, text: str) -> None:
        """追加一行日志（线程安全）。"""
        self._signal.append.emit(text)

    def clear(self) -> None:
        """清空所有日志内容。"""
        self._log_view.clear()

    # ---- UI 构建 ----

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # 标题栏
        header = QFrame(self)
        header.setObjectName("logPanelHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(12)

        icon_badge = QFrame(self)
        icon_badge.setObjectName("logHeaderIconBadge")
        icon_badge.setFixedSize(42, 42)
        icon_layout = QVBoxLayout(icon_badge)
        icon_layout.setContentsMargins(0, 0, 0, 0)

        icon_label = QLabel(self)
        icon_label.setObjectName("logHeaderIcon")
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setPixmap(QIcon(str(ASSETS_DIR / "terminal.svg")).pixmap(QSize(22, 22)))
        icon_layout.addWidget(icon_label)
        header_layout.addWidget(icon_badge)

        title_group = QVBoxLayout()
        title_group.setContentsMargins(0, 0, 0, 0)
        title_group.setSpacing(3)

        title_label = QLabel("后台输出", self)
        title_label.setObjectName("logPanelTitle")
        title_group.addWidget(title_label)

        subtitle_label = QLabel("实时展示摄像头、麦克风、ASR、LLM 与人物驱动日志", self)
        subtitle_label.setObjectName("logPanelSubtitle")
        title_group.addWidget(subtitle_label)
        header_layout.addLayout(title_group, stretch=1)

        header_layout.addStretch()

        clear_button = QPushButton("清空", self)
        clear_button.setObjectName("logClearButton")
        clear_button.setFixedSize(62, 32)
        clear_button.clicked.connect(self.clear)
        header_layout.addWidget(clear_button)

        layout.addWidget(header)

        # 日志内容区
        self._log_view = QTextEdit(self)
        self._log_view.setObjectName("logView")
        self._log_view.setReadOnly(True)
        self._log_view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._log_view.setMinimumHeight(390)
        self._log_view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        layout.addWidget(self._log_view, stretch=1)

        self._apply_styles()

    def _apply_styles(self) -> None:
        self.setStyleSheet("""
            QFrame#logPanelHeader {
                background: transparent;
            }
            QFrame#logHeaderIconBadge {
                background: #EAF5FF;
                border: 0;
                border-radius: 10px;
            }
            QLabel#logHeaderIcon {
                background: transparent;
                border: 0;
            }
            QLabel#logPanelTitle {
                color: #0F172A;
                font-size: 18px;
                font-weight: 800;
            }
            QLabel#logPanelSubtitle {
                color: #64748B;
                font-size: 12px;
                font-weight: 600;
            }
            QPushButton#logClearButton {
                background: #F8FAFC;
                border: 1px solid #DDE3EA;
                border-radius: 7px;
                color: #0F5FD7;
                font-size: 12px;
                font-weight: 700;
                padding: 0 12px;
            }
            QPushButton#logClearButton:hover {
                background: #EAF5FF;
                border-color: #9CCBFF;
                color: #1677FF;
            }
            QTextEdit#logView {
                background: #0B1220;
                border: 1px solid #1E293B;
                border-radius: 10px;
                color: #DDE7F3;
                font-family: "Cascadia Code", "Consolas", "Noto Sans SC", monospace;
                font-size: 12px;
                line-height: 1.35;
                padding: 12px 14px;
                selection-background-color: #334155;
            }
            QTextEdit#logView QScrollBar:vertical {
                background: #0B1220;
                width: 6px;
                margin: 0;
            }
            QTextEdit#logView QScrollBar::handle:vertical {
                background: #64748B;
                border-radius: 3px;
                min-height: 30px;
            }
            QTextEdit#logView QScrollBar::handle:vertical:hover {
                background: #94A3B8;
            }
            QTextEdit#logView QScrollBar::add-line:vertical,
            QTextEdit#logView QScrollBar::sub-line:vertical {
                height: 0;
            }
        """)

    # ---- 内部方法 ----

    def _on_append_log(self, text: str) -> None:
        """在主线程中实际追加日志（由信号触发）。"""
        doc = self._log_view.document()

        # 限制最大行数，避免内存增长
        if doc.blockCount() > self._MAX_BLOCK_COUNT:
            cursor = QTextCursor(doc.begin())
            cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
            while cursor.blockNumber() < 20:
                cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
                cursor.removeSelectedText()
                cursor.deleteChar()
                cursor.movePosition(QTextCursor.MoveOperation.NextBlock)

        # 追加新行
        self._log_view.moveCursor(QTextCursor.MoveOperation.End)

        fmt = QTextCharFormat()
        cleaned = text.strip()

        # 根据前缀着色
        if cleaned.startswith("[ASR]") or cleaned.startswith("[ASR_FULL]"):
            fmt.setForeground(QColor("#38BDF8"))  # 天蓝
        elif cleaned.startswith("[Emotion"):
            fmt.setForeground(QColor("#A78BFA"))  # 紫色
        elif cleaned.startswith("[LLM]"):
            fmt.setForeground(QColor("#34D399"))  # 绿色
        elif cleaned.startswith("[C]"):
            fmt.setForeground(QColor("#FBBF24"))  # 黄色
        elif "ERROR" in cleaned or "错误" in cleaned or "失败" in cleaned:
            fmt.setForeground(QColor("#F87171"))  # 红色
        elif "WARNING" in cleaned or "警告" in cleaned:
            fmt.setForeground(QColor("#FB923C"))  # 橙色
        else:
            fmt.setForeground(QColor("#CBD5E1"))  # 浅灰

        cursor = self._log_view.textCursor()
        cursor.insertText(text + "\n", fmt)

        # 自动滚动到底部
        scrollbar = self._log_view.verticalScrollBar()
        if scrollbar is not None:
            scrollbar.setValue(scrollbar.maximum())
