"""直播报告摘要页模块。

职责：
- 在停止直播后展示本次直播的关键摘要
- 呈现报告文件位置、基础指标、分布概览和推荐改进点
- 只负责 UI 展示，不负责生成报告内容
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from virtual_avatar_system.reporting.live_report_generator import LiveReportSummary
from virtual_avatar_system.utils.paths import get_ui_assets_dir

ASSETS_DIR = get_ui_assets_dir()


class LiveReportSummaryPage(QWidget):
    """停止直播后的报告摘要页。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("reportSummaryPage")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._report_path = ""
        self._setup_ui()

    def set_summary(self, summary: LiveReportSummary) -> None:
        """把报告摘要数据刷新到界面。"""
        self._duration_value.setText(summary.duration_text)
        self._time_range_value.setText(f"{summary.started_at_text}  至  {summary.stopped_at_text}")
        self._event_count_value.setText(f"{summary.event_count} 条")
        self._asr_count_value.setText(f"{summary.asr_text_count} 条")
        self._comment_count_value.setText(f"{summary.comment_count} 条")
        self._report_path = summary.report_path
        self._report_path_value.setText(self._format_report_path(summary.report_path))
        self._report_path_value.setToolTip(summary.report_path)
        self._semantic_value.setText(self._format_distribution(summary.semantic_distribution, "暂无有效语义标签"))
        self._emotion_value.setText(self._format_distribution(summary.emotion_distribution, "暂无明显情绪变化"))
        self._action_value.setText(self._format_distribution(summary.action_distribution, "暂无动作变化记录"))
        self._comments_value.setText(self._format_comments(summary.high_frequency_comments))
        self._recommendations_value.setText(self._format_recommendations(summary.recommendations))

    def _setup_ui(self) -> None:
        """构建摘要页布局。"""
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        scroll_area = QScrollArea(self)
        scroll_area.setObjectName("reportScrollArea")
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.viewport().setObjectName("reportScrollViewport")
        scroll_area.viewport().setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        content = QWidget(scroll_area)
        content.setObjectName("reportContent")
        content.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(28, 24, 28, 18)
        layout.setSpacing(18)

        top_grid = QGridLayout()
        top_grid.setContentsMargins(0, 0, 0, 0)
        top_grid.setHorizontalSpacing(18)
        top_grid.setVerticalSpacing(14)
        time_card, self._duration_value, self._time_range_value = self._create_time_summary_card()
        path_card, self._report_path_value = self._create_info_card(
            "报告存放位置",
            "等待生成",
            "folder.svg",
            selectable=True,
        )
        top_grid.addWidget(time_card, 0, 0)
        top_grid.addWidget(path_card, 0, 1)
        top_grid.setColumnStretch(0, 7)
        top_grid.setColumnStretch(1, 5)
        layout.addLayout(top_grid)

        metrics = QGridLayout()
        metrics.setContentsMargins(0, 0, 0, 0)
        metrics.setHorizontalSpacing(18)
        metrics.setVerticalSpacing(18)
        self._event_count_value = self._create_metric_card(metrics, "系统工作记录数", "report.svg", 0, 0)
        self._asr_count_value = self._create_metric_card(metrics, "FunASR 文本条数", "text.svg", 0, 1)
        self._comment_count_value = self._create_metric_card(metrics, "观众评论数量", "comments.svg", 0, 2)
        metrics.setColumnStretch(0, 1)
        metrics.setColumnStretch(1, 1)
        metrics.setColumnStretch(2, 1)
        layout.addLayout(metrics)

        self._recommendations_value = self._create_recommendation_card(layout)

        overview = QGridLayout()
        overview.setContentsMargins(0, 0, 0, 0)
        overview.setHorizontalSpacing(18)
        overview.setVerticalSpacing(18)
        self._semantic_value = self._create_overview_card(overview, "LLM 语义标签分布", "robot.svg", 0, 0)
        self._emotion_value = self._create_overview_card(overview, "情绪结果分布", "smile.svg", 0, 1)
        self._action_value = self._create_overview_card(overview, "当前动作分布", "microphone.svg", 1, 0)
        self._comments_value = self._create_overview_card(overview, "高频评论", "message.svg", 1, 1)
        overview.setColumnStretch(0, 1)
        overview.setColumnStretch(1, 1)
        layout.addLayout(overview)

        layout.addStretch()

        scroll_area.setWidget(content)
        outer_layout.addWidget(scroll_area)
        self._apply_styles()

    def _build_header(self) -> QFrame:
        """创建报告页标题区域。"""
        header = QFrame(self)
        header.setObjectName("reportHeader")
        header.setMinimumHeight(78)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(4, 0, 6, 0)
        layout.setSpacing(18)

        icon_badge = self._create_icon_badge("report-white.svg", size=48)
        icon_badge.setObjectName("reportMainIconBadge")
        layout.addWidget(icon_badge, alignment=Qt.AlignmentFlag.AlignVCenter)

        title_group = QVBoxLayout()
        title_group.setContentsMargins(0, 0, 0, 0)
        title_group.setSpacing(5)

        title = QLabel("直播报告摘要", self)
        title.setObjectName("reportTitle")
        title_group.addWidget(title)

        subtitle = QLabel("本次直播已结束，系统已沉淀 ASR、情绪、语义和动作事件记录。", self)
        subtitle.setObjectName("reportSubtitle")
        subtitle.setWordWrap(True)
        subtitle.setMinimumWidth(0)
        title_group.addWidget(subtitle)
        layout.addLayout(title_group, stretch=1)

        status = QFrame(self)
        status.setObjectName("reportStatusBadge")
        status.setFixedHeight(46)
        status_layout = QHBoxLayout(status)
        status_layout.setContentsMargins(16, 0, 18, 0)
        status_layout.setSpacing(8)

        dot = QLabel(self)
        dot.setObjectName("reportStatusDot")
        dot.setFixedSize(8, 8)
        status_layout.addWidget(dot)

        status_text = QLabel("报告已生成", self)
        status_text.setObjectName("reportStatusText")
        status_layout.addWidget(status_text)
        layout.addWidget(status, alignment=Qt.AlignmentFlag.AlignVCenter)
        return header

    def _create_time_summary_card(self) -> tuple[QFrame, QLabel, QLabel]:
        """创建直播时间和时长合并卡片。"""
        card = QFrame(self)
        card.setObjectName("reportTimeCard")
        card.setMinimumHeight(104)
        self._apply_soft_shadow(card, blur=14, y_offset=4, alpha=13)
        layout = QHBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(14)

        layout.addWidget(self._create_icon_badge("clock.svg", size=38), alignment=Qt.AlignmentFlag.AlignTop)

        text_group = QVBoxLayout()
        text_group.setContentsMargins(0, 0, 0, 0)
        text_group.setSpacing(4)

        title = QLabel("直播时间与时长", self)
        title.setObjectName("reportInfoTitle")
        text_group.addWidget(title)

        duration = QLabel("-", self)
        duration.setObjectName("reportTimeDuration")
        duration.setWordWrap(True)
        duration.setMinimumWidth(0)
        text_group.addWidget(duration)

        time_range = QLabel("等待生成", self)
        time_range.setObjectName("reportTimeRange")
        time_range.setWordWrap(False)
        time_range.setMinimumWidth(0)
        text_group.addWidget(time_range)
        layout.addLayout(text_group, stretch=1)

        return card, duration, time_range

    def _create_metric_card(
        self,
        parent_layout: QGridLayout,
        title_text: str,
        icon_name: str,
        row: int,
        column: int,
        column_span: int = 1,
    ) -> QLabel:
        """创建顶部基础指标卡片。"""
        card = QFrame(self)
        card.setObjectName("reportMetricCard")
        card.setMinimumHeight(108)
        self._apply_soft_shadow(card, blur=16, y_offset=4, alpha=13)
        layout = QHBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(14)

        layout.addWidget(self._create_icon_badge(icon_name, size=38), alignment=Qt.AlignmentFlag.AlignTop)

        text_group = QVBoxLayout()
        text_group.setContentsMargins(0, 0, 0, 0)
        text_group.setSpacing(6)

        title = QLabel(title_text, self)
        title.setObjectName("reportMetricTitle")
        title.setWordWrap(True)
        title.setMinimumWidth(0)
        text_group.addWidget(title)

        value = QLabel("-", self)
        value.setObjectName("reportMetricValue")
        value.setWordWrap(True)
        value.setMinimumWidth(0)
        text_group.addWidget(value)
        text_group.addStretch()
        layout.addLayout(text_group, stretch=1)

        parent_layout.addWidget(card, row, column, 1, column_span)
        return value

    def _create_info_card(
        self,
        title_text: str,
        value_text: str,
        icon_name: str,
        selectable: bool = False,
    ) -> tuple[QFrame, QLabel]:
        """创建信息区块卡片。"""
        card = QFrame(self)
        card.setObjectName("reportInfoCard")
        card.setMinimumHeight(104)
        self._apply_soft_shadow(card, blur=14, y_offset=4, alpha=13)
        layout = QHBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(14)

        layout.addWidget(self._create_icon_badge(icon_name, size=38), alignment=Qt.AlignmentFlag.AlignTop)

        text_group = QVBoxLayout()
        text_group.setContentsMargins(0, 0, 0, 0)
        text_group.setSpacing(6)

        title = QLabel(title_text, self)
        title.setObjectName("reportInfoTitle")
        text_group.addWidget(title)

        value = QLabel(value_text, self)
        value.setObjectName("reportInfoValue")
        value.setWordWrap(True)
        value.setMinimumWidth(0)
        value.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        if selectable:
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        text_group.addWidget(value)
        layout.addLayout(text_group, stretch=1)

        if selectable:
            # 复制按钮会复制完整报告路径，界面上只展示压缩后的相对路径。
            copy_button = QPushButton(self)
            copy_button.setObjectName("reportCopyButton")
            copy_button.setFixedSize(30, 30)
            copy_button.setIcon(QIcon(str(ASSETS_DIR / "copy.svg")))
            copy_button.setIconSize(QSize(18, 18))
            copy_button.setToolTip("复制完整报告路径")
            copy_button.clicked.connect(self._copy_report_path)
            layout.addWidget(copy_button, alignment=Qt.AlignmentFlag.AlignVCenter)

        return card, value

    def _create_overview_card(
        self,
        parent_layout: QGridLayout,
        title_text: str,
        icon_name: str,
        row: int,
        column: int,
    ) -> QLabel:
        """创建分布概览卡片。"""
        card = QFrame(self)
        card.setObjectName("reportOverviewCard")
        card.setMinimumHeight(104)
        self._apply_soft_shadow(card, blur=16, y_offset=4, alpha=13)
        layout = QHBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(14)

        layout.addWidget(self._create_icon_badge(icon_name, size=38), alignment=Qt.AlignmentFlag.AlignTop)

        text_group = QVBoxLayout()
        text_group.setContentsMargins(0, 0, 0, 0)
        text_group.setSpacing(6)

        title = QLabel(title_text, self)
        title.setObjectName("reportInfoTitle")
        title.setWordWrap(True)
        title.setMinimumWidth(0)
        text_group.addWidget(title)

        value = QLabel("-", self)
        value.setObjectName("reportOverviewValue")
        value.setWordWrap(True)
        value.setMinimumWidth(0)
        text_group.addWidget(value)
        text_group.addStretch()
        layout.addLayout(text_group, stretch=1)

        parent_layout.addWidget(card, row, column)
        return value

    def _create_recommendation_card(self, parent_layout: QVBoxLayout) -> QLabel:
        """创建推荐改进点区域。"""
        card = QFrame(self)
        card.setObjectName("reportRecommendationCard")
        card.setMinimumHeight(158)
        self._apply_soft_shadow(card, blur=18, y_offset=5, alpha=15)
        layout = QHBoxLayout(card)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(20)

        layout.addWidget(self._create_icon_badge("lightbulb.svg", size=46), alignment=Qt.AlignmentFlag.AlignTop)

        text_group = QVBoxLayout()
        text_group.setContentsMargins(0, 0, 0, 0)
        text_group.setSpacing(8)

        title = QLabel("推荐改进点", self)
        title.setObjectName("reportRecommendationTitle")
        text_group.addWidget(title)

        value = QLabel("-", self)
        value.setObjectName("reportRecommendationValue")
        value.setWordWrap(True)
        value.setMinimumWidth(0)
        text_group.addWidget(value)
        layout.addLayout(text_group, stretch=1)

        parent_layout.addWidget(card)
        return value

    def _copy_report_path(self) -> None:
        """复制完整报告路径，便于用户快速定位本次直播报告。"""
        if not self._report_path:
            return
        clipboard = QApplication.clipboard()
        clipboard.setText(self._report_path)
        button = self.sender()
        if isinstance(button, QPushButton):
            button.setToolTip("已复制完整报告路径")

    def _create_icon_badge(self, icon_name: str, size: int) -> QFrame:
        """创建报告摘要卡片中的浅蓝图标底座。"""
        badge = QFrame(self)
        badge.setObjectName("reportIconBadge")
        badge.setFixedSize(size, size)
        layout = QVBoxLayout(badge)
        layout.setContentsMargins(0, 0, 0, 0)

        icon = QLabel(self)
        icon.setObjectName("reportIcon")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_size = 26 if size >= 48 else 22
        icon.setPixmap(QIcon(str(ASSETS_DIR / icon_name)).pixmap(QSize(icon_size, icon_size)))
        layout.addWidget(icon)
        return badge

    def _apply_soft_shadow(self, widget: QWidget, blur: int, y_offset: int, alpha: int) -> None:
        """给报告页卡片添加轻量阴影，提升页面层次。"""
        shadow = QGraphicsDropShadowEffect(widget)
        shadow.setBlurRadius(blur)
        shadow.setOffset(0, y_offset)
        shadow.setColor(QColor(15, 23, 42, alpha))
        widget.setGraphicsEffect(shadow)

    @staticmethod
    def _format_distribution(items: list[tuple[str, int]], empty_text: str) -> str:
        """格式化标签分布，最多展示前三项。"""
        if not items:
            return empty_text
        return "\n".join(f"{label}：{count} 次" for label, count in items[:3])

    @staticmethod
    def _format_comments(items: list[tuple[str, int]]) -> str:
        """格式化高频评论摘要。"""
        if not items:
            return "暂未记录到观众评论"
        return "\n".join(f"{comment}（{count} 次）" for comment, count in items[:3])

    @staticmethod
    def _format_recommendations(items: list[str]) -> str:
        """格式化推荐改进点。"""
        if not items:
            return "暂无推荐改进点"
        return "\n".join(f"{index}. {item}" for index, item in enumerate(items[:3], start=1))

    @staticmethod
    def _format_report_path(report_path: str) -> str:
        """把很长的报告路径压缩成适合界面展示的形式。"""
        if not report_path:
            return "报告文件暂未生成"
        path = Path(report_path)
        # 页面只展示关键目录和文件名，完整路径保留在悬停提示里。
        if path.parent.name:
            return f"{path.parent.name}/{path.name}"
        return path.name

    def _apply_styles(self) -> None:
        """设置报告摘要页样式。"""
        self.setStyleSheet(
            """
            QWidget#reportSummaryPage,
            QWidget#reportContent,
            QWidget#reportScrollViewport {
                background: #F8FBFF;
            }
            QScrollArea#reportScrollArea {
                background: #F8FBFF;
                border: 1px solid #DDE7F3;
                border-radius: 12px;
            }
            QFrame#reportHeader {
                background: transparent;
                border: 0;
                border-radius: 0;
            }
            QFrame#reportTimeCard,
            QFrame#reportMetricCard,
            QFrame#reportInfoCard,
            QFrame#reportOverviewCard,
            QFrame#reportRecommendationCard {
                background: #FFFFFF;
                border: 1px solid #E2E8F0;
                border-radius: 12px;
            }
            QFrame#reportRecommendationCard {
                background: #FFFFFF;
                border: 1px solid #C9DBF7;
                border-radius: 12px;
            }
            QFrame#reportIconBadge {
                background: #EAF2FF;
                border: 0;
                border-radius: 10px;
            }
            QFrame#reportMainIconBadge {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #2F7CFF, stop:1 #0F5AEF);
                border: 0;
                border-radius: 12px;
            }
            QFrame#reportStatusBadge {
                background: #ECFDF5;
                border: 1px solid #B7EBD4;
                border-radius: 17px;
            }
            QLabel#reportStatusDot {
                background: #10B981;
                border-radius: 4px;
            }
            QLabel#reportStatusText {
                color: #059669;
                font-size: 16px;
                font-weight: 800;
            }
            QLabel#reportTitle {
                color: #0B163F;
                font-size: 25px;
                font-weight: 800;
            }
            QLabel#reportSubtitle {
                color: #536581;
                font-size: 14px;
                font-weight: 600;
            }
            QLabel#reportMetricTitle,
            QLabel#reportInfoTitle {
                color: #344968;
                font-size: 14px;
                font-weight: 800;
            }
            QLabel#reportMetricValue {
                color: #07122F;
                font-size: 27px;
                font-weight: 800;
            }
            QLabel#reportTimeDuration {
                color: #07122F;
                font-size: 26px;
                font-weight: 800;
            }
            QLabel#reportTimeRange {
                color: #465B7A;
                font-size: 12px;
                font-weight: 600;
            }
            QLabel#reportInfoValue {
                color: #172554;
                font-size: 12px;
                font-weight: 700;
            }
            QLabel#reportOverviewValue {
                color: #475569;
                font-size: 13px;
                font-weight: 650;
            }
            QLabel#reportRecommendationTitle {
                color: #163A6B;
                font-size: 16px;
                font-weight: 900;
            }
            QLabel#reportRecommendationValue {
                color: #12305A;
                font-size: 14px;
                font-weight: 800;
            }
            QPushButton#reportCopyButton {
                background: transparent;
                border: 0;
                border-radius: 6px;
            }
            QPushButton#reportCopyButton:hover {
                background: #EAF2FF;
            }
            """
        )
