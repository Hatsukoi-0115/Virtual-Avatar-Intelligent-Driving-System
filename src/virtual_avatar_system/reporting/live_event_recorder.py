"""直播事件记录器。

职责：
- 维护直播过程中的实时状态快照
- 在关键字段变化时记录事件
- 为后续直播结束报告提供结构化数据
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal


EventType = Literal["asr", "emotion", "semantic", "motion", "reply"]


@dataclass(slots=True)
class LiveEvent:
    """单条直播事件。"""

    event_type: EventType
    timestamp: float
    asr_text: str = ""
    emotion: str = ""
    semantic_label: str = ""
    current_action: str = ""
    suggested_reply: str = ""


@dataclass(slots=True)
class LiveSessionSnapshot:
    """直播当前状态快照。"""

    asr_text: str = ""
    emotion: str = "中性"
    semantic_label: str = "待识别"
    current_action: str = "Idle"
    suggested_reply: str = ""


@dataclass(slots=True)
class LiveSessionRecord:
    """一次直播会话记录。"""

    started_at: float = 0.0
    stopped_at: float = 0.0
    started_at_text: str = ""
    stopped_at_text: str = ""
    snapshot: LiveSessionSnapshot = field(default_factory=LiveSessionSnapshot)
    events: list[LiveEvent] = field(default_factory=list)

    @property
    def duration_seconds(self) -> float:
        """返回本次直播时长。"""
        end_time = self.stopped_at or time.time()
        if self.started_at <= 0:
            return 0.0
        return max(0.0, end_time - self.started_at)


class LiveEventRecorder:
    """直播事件记录器。"""

    def __init__(self) -> None:
        self._record = LiveSessionRecord()

    @property
    def record(self) -> LiveSessionRecord:
        """读取当前直播记录。"""
        return self._record

    def start_session(self) -> None:
        """开始一场新的直播记录。"""
        now = time.time()
        # 每次开播重新创建记录，避免上一场直播的数据串入下一场。
        self._record = LiveSessionRecord(
            started_at=now,
            started_at_text=self._format_time(now),
        )

    def stop_session(self) -> LiveSessionRecord:
        """结束当前直播记录并返回最终数据。"""
        now = time.time()
        self._record.stopped_at = now
        self._record.stopped_at_text = self._format_time(now)
        return self._record

    def record_asr_text(self, text: str) -> None:
        """记录 FunASR 文本识别事件。"""
        normalized = text.strip()
        if not normalized or normalized == self._record.snapshot.asr_text:
            return
        self._record.snapshot.asr_text = normalized
        self._append_event("asr")

    def record_emotion(self, emotion: str) -> None:
        """记录情绪识别事件。"""
        normalized = emotion.strip() or "中性"
        if normalized == self._record.snapshot.emotion:
            return
        self._record.snapshot.emotion = normalized
        self._append_event("emotion")

    def record_semantic(self, semantic_label: str, suggested_reply: str = "") -> None:
        """记录 LLM 语义标签和推荐回复事件。"""
        normalized_label = semantic_label.strip() or "待识别"
        normalized_reply = suggested_reply.strip()
        if (
            normalized_label == self._record.snapshot.semantic_label
            and normalized_reply == self._record.snapshot.suggested_reply
        ):
            return
        self._record.snapshot.semantic_label = normalized_label
        self._record.snapshot.suggested_reply = normalized_reply
        self._append_event("semantic")

    def record_motion(self, motion_label: str) -> None:
        """记录当前动作事件。"""
        normalized = motion_label.strip() or "Idle"
        if normalized == self._record.snapshot.current_action:
            return
        self._record.snapshot.current_action = normalized
        self._append_event("motion")

    def _append_event(self, event_type: EventType) -> None:
        """用当前快照生成一条事件记录。"""
        snapshot = self._record.snapshot
        self._record.events.append(
            LiveEvent(
                event_type=event_type,
                timestamp=time.time(),
                asr_text=snapshot.asr_text,
                emotion=snapshot.emotion,
                semantic_label=snapshot.semantic_label,
                current_action=snapshot.current_action,
                suggested_reply=snapshot.suggested_reply,
            )
        )

    @staticmethod
    def _format_time(timestamp: float) -> str:
        """格式化本地时间，便于后续报告展示。"""
        return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
