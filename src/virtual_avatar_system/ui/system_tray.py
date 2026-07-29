"""系统托盘模块。

职责：
- 提供显示主窗口入口
- 提供退出功能
"""

from __future__ import annotations

import logging
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QSystemTrayIcon, QMenu, QApplication

LOGGER = logging.getLogger(__name__)


class AppSystemTray(QSystemTrayIcon):
    """系统托盘图标与菜单。

    能力：
    - 双击托盘图标恢复主窗口
    - 右键菜单包含：显示/隐藏预览、退出
    """

    def __init__(self, parent: QApplication | None = None) -> None:
        super().__init__(parent)
        self._on_quit_callbacks: list[Callable[[], None]] = []
        self._setup_icon()
        self._setup_menu()
        self._connect_signals()

    # ---- 回调注册 ----

    def on_quit(self, callback: Callable[[], None]) -> None:
        """注册退出回调。"""
        self._on_quit_callbacks.append(callback)

    # ---- 初始化 ----

    def _setup_icon(self) -> None:
        """设置托盘图标。

        使用系统内置图标作为占位，后续替换为项目图标。
        """
        icon = QApplication.style().standardIcon(
            QApplication.style().StandardPixmap.SP_ComputerIcon
        )
        self.setIcon(icon)
        self.setToolTip("虚拟形象驱动系统")

    def _setup_menu(self) -> None:
        """搭建右键菜单。"""
        menu = QMenu()

        show_action = QAction("显示主窗口", menu)
        menu.addAction(show_action)

        quit_action = QAction("退出", menu)
        menu.addAction(quit_action)

        # 保存引用以便信号连接
        self._show_action = show_action
        self._quit_action = quit_action

        self.setContextMenu(menu)

    def _connect_signals(self) -> None:
        """连接托盘菜单信号。"""
        self._show_action.triggered.connect(self._on_show_main)
        self._quit_action.triggered.connect(self._on_quit)
        # 双击托盘图标恢复主窗口
        self.activated.connect(self._on_activated)

    # ---- 信号处理 ----

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        """托盘图标双击等事件。"""
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._on_show_main()

    def _on_show_main(self) -> None:
        """显示主窗口。"""
        if self.parent() and hasattr(self.parent(), "show"):
            self.parent().show()
            self.parent().raise_()
            self.parent().activateWindow()

    def _on_quit(self) -> None:
        """退出应用。"""
        LOGGER.info("通过系统托盘退出应用")
        for callback in self._on_quit_callbacks:
            try:
                callback()
            except Exception as exc:  # noqa: BLE001
                LOGGER.error("退出回调异常：%s", exc)
        QApplication.quit()
