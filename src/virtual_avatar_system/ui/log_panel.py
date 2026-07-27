"""日志输出面板模块。

提供线程安全的后端日志输出展示组件，用于在直播开始界面上
实时显示 ASR、情绪分类、LLM 语义等后端模块的运行输出。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QObject, Signal
from PySide6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
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


class LogSignal(QObject):
    """跨线程安全的日志信号，用于将后台线程输出安全地投递到 UI 线程。"""

    append = Signal(str)


class LogPanel(QWidget):
    """可折叠的后端输出日志面板。

    使用方式：
        panel = LogPanel()
        panel.append_log("[ASR] 你好世界")
        panel.append_log("[LLM] 句子=你好 标签=wave")

    append_log() 可从任意线程调用，内部通过 Qt 信号确保 UI 更新在主线程执行。
    """

    _MAX_BLOCK_COUNT = 500

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._collapsed = False

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
        layout.setSpacing(6)

        # 标题栏
        header = QFrame(self)
        header.setObjectName("logPanelHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(4, 6, 4, 6)
        header_layout.setSpacing(8)

        title_label = QLabel("📋 后端输出", self)
        title_label.setObjectName("logPanelTitle")
        header_layout.addWidget(title_label)

        header_layout.addStretch()

        self._toggle_button = QPushButton("收起 ▲", self)
        self._toggle_button.setObjectName("logToggleButton")
        self._toggle_button.setFixedSize(60, 22)
        self._toggle_button.clicked.connect(self._toggle_collapse)
        header_layout.addWidget(self._toggle_button)

        clear_button = QPushButton("清空", self)
        clear_button.setObjectName("logClearButton")
        clear_button.setFixedSize(44, 22)
        clear_button.clicked.connect(self.clear)
        header_layout.addWidget(clear_button)

        layout.addWidget(header)

        # 日志内容区
        self._log_view = QTextEdit(self)
        self._log_view.setObjectName("logView")
        self._log_view.setReadOnly(True)
        self._log_view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._log_view.setMinimumHeight(120)
        self._log_view.setMaximumHeight(260)
        self._log_view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        layout.addWidget(self._log_view, stretch=1)

        self._apply_styles()

    def _apply_styles(self) -> None:
        self.setStyleSheet("""
            QWidget#logPanelHeader {
                background: transparent;
            }
            QLabel#logPanelTitle {
                color: #334155;
                font-size: 12px;
                font-weight: 600;
            }
            QPushButton#logToggleButton,
            QPushButton#logClearButton {
                background: #F1F5F9;
                border: 1px solid #E2E8F0;
                border-radius: 4px;
                color: #475569;
                font-size: 11px;
                padding: 2px 8px;
            }
            QPushButton#logToggleButton:hover,
            QPushButton#logClearButton:hover {
                background: #E2E8F0;
                color: #1E293B;
            }
            QTextEdit#logView {
                background: #1E293B;
                border: 1px solid #E2E8F0;
                border-radius: 6px;
                color: #E2E8F0;
                font-family: "Cascadia Code", "Consolas", "Noto Sans SC", monospace;
                font-size: 11px;
                padding: 8px 10px;
                selection-background-color: #334155;
            }
            QTextEdit#logView QScrollBar:vertical {
                background: #1E293B;
                width: 6px;
                margin: 0;
            }
            QTextEdit#logView QScrollBar::handle:vertical {
                background: #475569;
                border-radius: 3px;
                min-height: 30px;
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

    def _toggle_collapse(self) -> None:
        """折叠/展开日志内容区。"""
        self._collapsed = not self._collapsed
        self._log_view.setVisible(not self._collapsed)
        self._toggle_button.setText("展开 ▼" if self._collapsed else "收起 ▲")
