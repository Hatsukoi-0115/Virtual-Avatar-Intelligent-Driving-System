"""直播报告摘要页模块。

职责：
- 在停止直播后展示本次直播的关键摘要
- 呈现报告文件位置、基础指标、分布概览和推荐改进点
- 只负责 UI 展示，不负责生成报告内容
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from virtual_avatar_system.reporting.live_report_generator import LiveReportSummary


class LiveReportSummaryPage(QWidget):
    """停止直播后的报告摘要页。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("reportSummaryPage")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._setup_ui()

    def set_summary(self, summary: LiveReportSummary) -> None:
        """把报告摘要数据刷新到界面。"""
        self._duration_value.setText(summary.duration_text)
        self._time_range_value.setText(f"{summary.started_at_text}  至  {summary.stopped_at_text}")
        self._event_count_value.setText(f"{summary.event_count} 条")
        self._asr_count_value.setText(f"{summary.asr_text_count} 条")
        self._comment_count_value.setText(f"{summary.comment_count} 条")
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
        scroll_area.viewport().setObjectName("reportScrollViewport")
        scroll_area.viewport().setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        content = QWidget(scroll_area)
        content.setObjectName("reportContent")
        content.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(2, 2, 2, 18)
        layout.setSpacing(12)

        header = self._build_header()
        layout.addWidget(header)

        self._report_path_value = self._create_info_row(layout, "报告存放位置", "等待生成", selectable=True)

        self._duration_value, self._time_range_value = self._create_time_summary_card(layout)

        metrics = QGridLayout()
        metrics.setContentsMargins(0, 0, 0, 0)
        metrics.setHorizontalSpacing(12)
        metrics.setVerticalSpacing(12)
        self._event_count_value = self._create_metric_card(metrics, "系统工作记录数", 0, 0)
        self._asr_count_value = self._create_metric_card(metrics, "FunASR 文本条数", 0, 1)
        self._comment_count_value = self._create_metric_card(metrics, "观众评论数量", 1, 0, column_span=2)
        layout.addLayout(metrics)

        self._recommendations_value = self._create_recommendation_card(layout)

        overview = QGridLayout()
        overview.setContentsMargins(0, 0, 0, 0)
        overview.setHorizontalSpacing(12)
        overview.setVerticalSpacing(12)
        self._semantic_value = self._create_overview_card(overview, "LLM 语义标签分布", 0, 0)
        self._emotion_value = self._create_overview_card(overview, "情绪结果分布", 0, 1)
        self._action_value = self._create_overview_card(overview, "当前动作分布", 1, 0)
        self._comments_value = self._create_overview_card(overview, "高频评论", 1, 1)
        layout.addLayout(overview)

        layout.addStretch()

        scroll_area.setWidget(content)
        outer_layout.addWidget(scroll_area)
        self._apply_styles()

    def _build_header(self) -> QFrame:
        """创建报告页标题区域。"""
        header = QFrame(self)
        header.setObjectName("reportHeader")
        layout = QVBoxLayout(header)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(8)

        title = QLabel("直播报告摘要", self)
        title.setObjectName("reportTitle")
        layout.addWidget(title)

        subtitle = QLabel("本次直播已结束，系统已沉淀 ASR、情绪、语义和动作事件记录。", self)
        subtitle.setObjectName("reportSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)
        return header

    def _create_time_summary_card(self, parent_layout: QVBoxLayout) -> tuple[QLabel, QLabel]:
        """创建直播时间和时长合并卡片。"""
        card = QFrame(self)
        card.setObjectName("reportTimeCard")
        card.setMinimumHeight(98)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 13, 16, 13)
        layout.setSpacing(7)

        title = QLabel("直播时间与时长", self)
        title.setObjectName("reportInfoTitle")
        layout.addWidget(title)

        duration = QLabel("-", self)
        duration.setObjectName("reportTimeDuration")
        duration.setWordWrap(True)
        layout.addWidget(duration)

        time_range = QLabel("等待生成", self)
        time_range.setObjectName("reportTimeRange")
        time_range.setWordWrap(True)
        layout.addWidget(time_range)

        parent_layout.addWidget(card)
        return duration, time_range

    def _create_metric_card(
        self,
        parent_layout: QGridLayout,
        title_text: str,
        row: int,
        column: int,
        column_span: int = 1,
    ) -> QLabel:
        """创建顶部基础指标卡片。"""
        card = QFrame(self)
        card.setObjectName("reportMetricCard")
        card.setMinimumHeight(78)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 11, 14, 11)
        layout.setSpacing(5)

        title = QLabel(title_text, self)
        title.setObjectName("reportMetricTitle")
        layout.addWidget(title)

        value = QLabel("-", self)
        value.setObjectName("reportMetricValue")
        value.setWordWrap(True)
        layout.addWidget(value)

        parent_layout.addWidget(card, row, column, 1, column_span)
        return value

    def _create_info_row(self, parent_layout: QVBoxLayout, title_text: str, value_text: str, selectable: bool = False) -> QLabel:
        """创建单行信息区块。"""
        card = QFrame(self)
        card.setObjectName("reportInfoCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 11, 14, 11)
        layout.setSpacing(6)

        title = QLabel(title_text, self)
        title.setObjectName("reportInfoTitle")
        layout.addWidget(title)

        value = QLabel(value_text, self)
        value.setObjectName("reportInfoValue")
        value.setWordWrap(True)
        value.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        if selectable:
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(value)

        parent_layout.addWidget(card)
        return value

    def _create_overview_card(self, parent_layout: QGridLayout, title_text: str, row: int, column: int) -> QLabel:
        """创建分布概览卡片。"""
        card = QFrame(self)
        card.setObjectName("reportOverviewCard")
        card.setMinimumHeight(112)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 11, 14, 12)
        layout.setSpacing(8)

        title = QLabel(title_text, self)
        title.setObjectName("reportInfoTitle")
        layout.addWidget(title)

        value = QLabel("-", self)
        value.setObjectName("reportOverviewValue")
        value.setWordWrap(True)
        layout.addWidget(value)
        layout.addStretch()

        parent_layout.addWidget(card, row, column)
        return value

    def _create_recommendation_card(self, parent_layout: QVBoxLayout) -> QLabel:
        """创建推荐改进点区域。"""
        card = QFrame(self)
        card.setObjectName("reportRecommendationCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        title = QLabel("推荐改进点", self)
        title.setObjectName("reportInfoTitle")
        layout.addWidget(title)

        value = QLabel("-", self)
        value.setObjectName("reportRecommendationValue")
        value.setWordWrap(True)
        layout.addWidget(value)

        parent_layout.addWidget(card)
        return value

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
        return "\n".join(f"{index}. {item}" for index, item in enumerate(items[:4], start=1))

    @staticmethod
    def _format_report_path(report_path: str) -> str:
        """把很长的报告路径压缩成适合界面展示的形式。"""
        if not report_path:
            return "报告文件暂未生成"
        path = Path(report_path)
        # 页面只展示关键目录和文件名，完整路径保留在悬停提示里。
        if path.parent.name:
            return str(Path(path.parent.name) / path.name)
        return path.name

    def _apply_styles(self) -> None:
        """设置报告摘要页样式。"""
        self.setStyleSheet(
            """
            QWidget#reportSummaryPage,
            QWidget#reportContent,
            QWidget#reportScrollViewport {
                background: #F6F8FB;
            }
            QScrollArea#reportScrollArea {
                background: #F6F8FB;
                border: 0;
            }
            QFrame#reportHeader {
                background: #FFFFFF;
                border: 1px solid #DDE7F3;
                border-radius: 8px;
            }
            QFrame#reportTimeCard,
            QFrame#reportMetricCard,
            QFrame#reportInfoCard,
            QFrame#reportOverviewCard,
            QFrame#reportRecommendationCard {
                background: #FFFFFF;
                border: 1px solid #E5EAF1;
                border-radius: 8px;
            }
            QLabel#reportTitle {
                color: #0F172A;
                font-size: 17px;
                font-weight: 800;
            }
            QLabel#reportSubtitle,
            QLabel#reportInfoValue,
            QLabel#reportOverviewValue,
            QLabel#reportRecommendationValue {
                color: #334155;
                font-size: 13px;
                font-weight: 500;
                line-height: 1.35;
            }
            QLabel#reportMetricTitle,
            QLabel#reportInfoTitle {
                color: #64748B;
                font-size: 12px;
                font-weight: 700;
            }
            QLabel#reportMetricValue {
                color: #0F172A;
                font-size: 17px;
                font-weight: 800;
            }
            QLabel#reportTimeDuration {
                color: #0F172A;
                font-size: 20px;
                font-weight: 800;
            }
            QLabel#reportTimeRange {
                color: #475569;
                font-size: 13px;
                font-weight: 600;
            }
            """
        )
