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
from dataclasses import dataclass, field

from virtual_avatar_system.vision.feature_packet import VisualFeaturePacket

LOGGER = logging.getLogger(__name__)


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
            # 头部姿态：归一化值 [-1, 1] 映射到 Live2D 角度 [-30°, 30°]
            output.param_angle_x = max(-30.0, min(30.0, visual.head_yaw * 30.0))
            output.param_angle_y = max(-30.0, min(30.0, visual.head_pitch * 30.0))
            output.param_angle_z = max(-30.0, min(30.0, visual.head_roll * 30.0))

            # 眼部：0=闭合, 1=睁开
            output.param_eye_l_open = max(0.0, min(1.0, visual.eye_open_left))
            output.param_eye_r_open = max(0.0, min(1.0, visual.eye_open_right))

            # 嘴部：0=闭合, 1=张开
            output.param_mouth_open_y = max(0.0, min(1.0, visual.mouth_open))

        # 表情指令（后续接入情绪/语义后在此处做优先级判断）
        output.expression = self._input.expression

        return output
