"""直播结束报告生成器。

职责：
- 汇总一次直播中的事件记录
- 统计语义标签、情绪结果、观众评论数量和高频评论
- 输出适合老师审查和演示的 Markdown 报告
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from virtual_avatar_system.reporting.live_event_recorder import LiveEvent, LiveSessionRecord


QUESTION_KEYWORDS: tuple[str, ...] = (
    "?",
    "？",
    "吗",
    "呢",
    "么",
    "如何",
    "怎么",
    "为什么",
    "多少",
    "是否",
    "能否",
    "可以",
    "适合",
)


@dataclass(slots=True)
class LiveReportSummary:
    """直播报告摘要，用于停播后的 UI 摘要页展示。"""

    started_at_text: str = "未知"
    stopped_at_text: str = "未知"
    duration_text: str = "0 秒"
    event_count: int = 0
    asr_text_count: int = 0
    comment_count: int = 0
    semantic_distribution: list[tuple[str, int]] = field(default_factory=list)
    emotion_distribution: list[tuple[str, int]] = field(default_factory=list)
    action_distribution: list[tuple[str, int]] = field(default_factory=list)
    high_frequency_comments: list[tuple[str, int]] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    report_path: str = ""


def save_live_report(record: LiveSessionRecord, reports_dir: Path) -> Path:
    """保存直播结束报告并返回报告路径。"""
    reports_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = reports_dir / f"live_report_{timestamp}.md"
    report_path.write_text(generate_live_report(record), encoding="utf-8")
    return report_path


def build_live_report_summary(record: LiveSessionRecord, report_path: Path | None = None) -> LiveReportSummary:
    """构建停播后摘要页需要的结构化数据。"""
    asr_texts, comment_texts, semantic_counter, emotion_counter, action_counter = _collect_report_data(record)
    recommendations = _build_recommendation_items(
        record,
        asr_texts,
        comment_texts,
        semantic_counter,
        emotion_counter,
    )
    comment_counter = Counter(comment_texts)
    return LiveReportSummary(
        started_at_text=record.started_at_text or "未知",
        stopped_at_text=record.stopped_at_text or "未知",
        duration_text=_format_duration(record.duration_seconds),
        event_count=len(record.events),
        asr_text_count=len(asr_texts),
        comment_count=len(comment_texts),
        semantic_distribution=semantic_counter.most_common(),
        emotion_distribution=emotion_counter.most_common(),
        action_distribution=action_counter.most_common(),
        high_frequency_comments=comment_counter.most_common(5),
        recommendations=recommendations,
        report_path=str(report_path) if report_path else "",
    )


def generate_live_report(record: LiveSessionRecord) -> str:
    """根据直播事件生成 Markdown 报告。"""
    asr_texts, comment_texts, semantic_counter, emotion_counter, action_counter = _collect_report_data(record)

    lines = [
        "# 直播结束报告",
        "",
        "## 基本信息",
        "",
        f"- 开始时间：{record.started_at_text or '未知'}",
        f"- 结束时间：{record.stopped_at_text or '未知'}",
        f"- 本次直播时长：{_format_duration(record.duration_seconds)}",
        f"- 系统工作记录数：{len(record.events)}",
        f"- FunASR 文本条数：{len(asr_texts)}",
        f"- 观众评论数量：{len(comment_texts)}",
        "",
        "## 主要语义标签分布",
        "",
        _format_counter(semantic_counter, "暂无有效语义标签"),
        "",
        "## 情绪结果分布",
        "",
        _format_counter(emotion_counter, "暂无明显情绪变化"),
        "",
        "## 当前动作分布",
        "",
        _format_counter(action_counter, "暂无动作变化记录"),
        "",
        "## 高频评论",
        "",
        _format_comments(comment_texts),
        "",
        "## 关键事件明细",
        "",
        _format_event_table(record.events),
        "",
        "## 推荐改进点",
        "",
        _format_recommendations(record, asr_texts, comment_texts, semantic_counter, emotion_counter),
        "",
    ]
    return "\n".join(lines)


def build_suggested_reply(asr_text: str, semantic_label: str) -> str:
    """根据当前识别文本和语义标签生成最小可用推荐回复。"""
    text = asr_text.strip()
    label = semantic_label.strip() or "当前主题"
    if not text:
        return f"建议围绕“{label}”继续补充讲解。"
    if _is_question(text):
        return f"建议先正面回答用户问题，再围绕“{label}”补充一个具体例子。"
    return f"建议承接当前内容，围绕“{label}”提炼一句清晰卖点。"


def _unique_non_empty(values) -> list[str]:
    """按出现顺序去重并过滤空文本。"""
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _collect_report_data(
    record: LiveSessionRecord,
) -> tuple[list[str], list[str], Counter[str], Counter[str], Counter[str]]:
    """收集报告和摘要页共用的统计数据。"""
    asr_texts = _unique_non_empty(event.asr_text for event in record.events if event.event_type == "asr")
    comment_texts = [
        event.audience_comment.strip()
        for event in record.events
        if event.event_type == "comment" and event.audience_comment.strip()
    ]
    semantic_counter = Counter(
        event.semantic_label for event in record.events if event.semantic_label and event.semantic_label != "待识别"
    )
    emotion_counter = Counter(
        event.emotion for event in record.events if event.emotion and event.emotion != "中性"
    )
    action_counter = Counter(
        event.current_action for event in record.events if event.current_action and event.current_action != "Idle"
    )
    return asr_texts, comment_texts, semantic_counter, emotion_counter, action_counter


def _is_question(text: str) -> bool:
    """用关键词粗略判断一段文本是否为用户问题。"""
    normalized = text.strip()
    return any(keyword in normalized for keyword in QUESTION_KEYWORDS)


def _format_duration(seconds: float) -> str:
    """格式化直播时长。"""
    total_seconds = int(seconds)
    minutes, second = divmod(total_seconds, 60)
    hour, minute = divmod(minutes, 60)
    if hour:
        return f"{hour} 小时 {minute} 分 {second} 秒"
    if minute:
        return f"{minute} 分 {second} 秒"
    return f"{second} 秒"


def _format_counter(counter: Counter[str], empty_text: str) -> str:
    """把计数器格式化为 Markdown 列表。"""
    if not counter:
        return f"- {empty_text}"
    return "\n".join(f"- {label}：{count} 次" for label, count in counter.most_common())


def _format_comments(comment_texts: list[str]) -> str:
    """格式化高频评论列表。"""
    if not comment_texts:
        return "- 暂未记录到观众评论"
    counter = Counter(comment_texts)
    return "\n".join(f"- {comment}（{count} 次）" for comment, count in counter.most_common(5))


def _format_event_table(events: list[LiveEvent]) -> str:
    """格式化关键事件表格。"""
    if not events:
        return "暂无事件记录"

    rows = [
        "| 类型 | FunASR 文本 | 观众评论 | 情绪 | LLM 语义 | 当前动作 | 推荐回复 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for event in events[-30:]:
        rows.append(
            "| {event_type} | {asr} | {comment} | {emotion} | {semantic} | {action} | {reply} |".format(
                event_type=_escape_table_text(event.event_type),
                asr=_escape_table_text(event.asr_text),
                comment=_escape_table_text(event.audience_comment),
                emotion=_escape_table_text(event.emotion),
                semantic=_escape_table_text(event.semantic_label),
                action=_escape_table_text(event.current_action),
                reply=_escape_table_text(event.suggested_reply),
            )
        )
    return "\n".join(rows)


def _format_recommendations(
    record: LiveSessionRecord,
    asr_texts: list[str],
    comment_texts: list[str],
    semantic_counter: Counter[str],
    emotion_counter: Counter[str],
) -> str:
    """根据统计结果生成简单改进建议。"""
    return "\n".join(
        f"- {item}"
        for item in _build_recommendation_items(
            record,
            asr_texts,
            comment_texts,
            semantic_counter,
            emotion_counter,
        )
    )


def _build_recommendation_items(
    record: LiveSessionRecord,
    asr_texts: list[str],
    comment_texts: list[str],
    semantic_counter: Counter[str],
    emotion_counter: Counter[str],
) -> list[str]:
    """根据统计结果生成改进建议列表。"""
    suggestions: list[str] = []
    if not asr_texts:
        suggestions.append("本次直播未记录到有效 FunASR 文本，建议检查麦克风输入和说话音量。")
    if not comment_texts:
        suggestions.append("本次直播未记录到观众评论，后续可使用手动输入或接入 B站评论增强互动数据。")
    if len(semantic_counter) <= 1:
        suggestions.append("语义标签较集中，后续可补充更多业务场景话术，提高互动覆盖面。")
    if emotion_counter and emotion_counter.most_common(1)[0][0] in {"消极", "愤怒", "厌恶", "悲伤"}:
        suggestions.append("检测到偏消极情绪，建议增加安抚性回复和解释性话术。")
    if record.duration_seconds < 30:
        suggestions.append("本次直播时长较短，建议延长演示时间以覆盖 ASR、情绪、LLM 和动作联动。")

    if not suggestions:
        suggestions.append("本次直播链路较完整，后续可继续补充推荐回复质量和业务标签细分。")
    return suggestions


def _escape_table_text(text: str) -> str:
    """转义 Markdown 表格中的特殊字符。"""
    return (text or "-").replace("|", "\\|").replace("\n", " ")[:80]
