"""Avatar Controller 融合层。

职责：
- 接收视觉特征、情绪、语义等输入
- 按优先级规则融合
- 输出 AvatarOutputState 供渲染层消费
- 只做决策，不做采集、推理和渲染
"""

from __future__ import annotations

import enum
import logging
import time
from dataclasses import dataclass, field

from virtual_avatar_system.emotion.types import EmotionResult
from virtual_avatar_system.vision.feature_packet import VisualFeaturePacket

LOGGER = logging.getLogger(__name__)
EMOTION_TO_EXPRESSION: dict[str, str] = {
    "开心": "Smile",
    "难过": "Sad",
    "愤怒": "Angry",
    "疑问": "Surprised",
    "惊讶": "Surprised",
    "平静": "Normal",
}
EMOTION_MIN_CONFIDENCE = 0.50
EMOTION_EXPRESSION_SECONDS = 2.2
EMOTION_SWITCH_COOLDOWN_SECONDS = 0.35
HEAD_YAW_DEGREES = 60.0
HEAD_PITCH_UP_DEGREES = 180.0
HEAD_PITCH_DOWN_DEGREES = 60.0
HEAD_ROLL_DEGREES = 30.0


def _map_head_pitch(value: float) -> float:
    """抬头方向稍微放大，低头保持克制，避免默认姿态看起来偏低。"""
    degrees = HEAD_PITCH_UP_DEGREES if value > 0 else HEAD_PITCH_DOWN_DEGREES
    return max(-HEAD_PITCH_DOWN_DEGREES, min(HEAD_PITCH_UP_DEGREES, value * degrees))


class InputPriority(enum.IntEnum):
    """输入源优先级。

    数值越小，级别越低，在冲突时会被覆盖。
    """

    LOW = 0
    NORMAL = 50
    HIGH = 100


@dataclass(slots=True)
class AvatarInputState:
    """统一输入状态。

    所有输入源（视觉、音频、情绪、语义）汇总到这一个结构体。
    """

    # ---- 视觉特征 ----
    visual: VisualFeaturePacket | None = None

    # ---- 表情指令 ----
    expression: str = "Normal"
    """预设表情 ID"""

    expression_priority: InputPriority = InputPriority.LOW
    """表情指令的优先级"""

    # ---- 情绪输入 ----
    emotion: EmotionResult | None = None
    """语音链路输出的最新情绪结果"""

    # ---- 设备状态 ----
    device_status: dict[str, str] = field(default_factory=dict)
    """各设备当前状态，键为设备名，值为 'ok' / 'error' / 'disconnected'"""

    # ---- 时间戳 ----
    timestamp: float = 0.0
    """最后更新的时间戳（perf_counter）"""


@dataclass(slots=True)
class AvatarOutputState:
    """统一输出状态。

    渲染层只消费这一类结构体，不关心输入来源。
    """

    # ---- 头部姿态 ----
    param_angle_x: float = 0.0
    param_angle_y: float = 0.0
    param_angle_z: float = 0.0

    # ---- 眼部 ----
    param_eye_l_open: float = 1.0
    param_eye_r_open: float = 1.0

    # ---- 嘴部 ----
    param_mouth_open_y: float = 0.0

    # ---- 表情 ----
    expression: str = "Normal"


class AvatarController:
    """统一控制层。

    核心职责：
    - 接收所有输入
    - 按优先级融合
    - 生成最终输出状态
    """

    def __init__(self) -> None:
        self._input: AvatarInputState = AvatarInputState()
        self._active_expression = "Normal"
        self._expression_expires_at = 0.0
        self._last_expression_switch_at = 0.0

    # ---- 输入 ----

    def ingest(self, state: AvatarInputState) -> None:
        """接收输入状态。"""
        self._input = state

    @property
    def current_visual(self) -> VisualFeaturePacket | None:
        """获取当前视觉特征。"""
        return self._input.visual

    # ---- 决策 ----

    def resolve(self) -> AvatarOutputState:
        """融合所有输入并返回最终输出状态。

        当前阶段只做视觉特征 → Live2D 参数映射。
        后续加入情绪/语义后在此处实现冲突消解。
        """
        output = AvatarOutputState()

        # 视觉特征映射
        visual = self._input.visual
        if visual and visual.face_detected:
            # 头部姿态：归一化值 [-1, 1] 映射到 Live2D 角度
            output.param_angle_x = max(-HEAD_YAW_DEGREES, min(HEAD_YAW_DEGREES, visual.head_yaw * HEAD_YAW_DEGREES))
            output.param_angle_y = _map_head_pitch(visual.head_pitch)
            output.param_angle_z = max(-HEAD_ROLL_DEGREES, min(HEAD_ROLL_DEGREES, visual.head_roll * HEAD_ROLL_DEGREES))

            # 眼部：0=闭合, 1=睁开
            output.param_eye_l_open = max(0.0, min(1.0, visual.eye_open_left))
            output.param_eye_r_open = max(0.0, min(1.0, visual.eye_open_right))

            # 嘴部：0=闭合, 1=张开
            output.param_mouth_open_y = max(0.0, min(1.0, visual.mouth_open))

        self._resolve_expression()
        output.expression = self._active_expression

        return output

    def _resolve_expression(self) -> None:
        """把情绪输入解析成稳定的 Live2D 表情。"""
        now = time.monotonic()
        emotion = self._input.emotion

        if emotion is not None:
            self._maybe_apply_emotion(emotion, now)

        if self._active_expression != "Normal" and now >= self._expression_expires_at:
            self._active_expression = "Normal"

    def _maybe_apply_emotion(self, emotion: EmotionResult, now: float) -> None:
        """按置信度和冷却时间应用情绪，避免每个词都切换表情。"""
        expression = EMOTION_TO_EXPRESSION.get(emotion.label)
        if expression is None:
            return
        if emotion.confidence < EMOTION_MIN_CONFIDENCE:
            return

        if expression == "Normal":
            if self._active_expression == "Normal":
                return
            if now < self._expression_expires_at:
                return

        if (
            expression != self._active_expression
            and now - self._last_expression_switch_at < EMOTION_SWITCH_COOLDOWN_SECONDS
        ):
            return

        self._active_expression = expression
        self._expression_expires_at = now + EMOTION_EXPRESSION_SECONDS
        self._last_expression_switch_at = now
        LOGGER.info(
            "Emotion expression applied: %s -> %s confidence=%.2f source=%s",
            emotion.label,
            expression,
            emotion.confidence,
            emotion.source,
        )
