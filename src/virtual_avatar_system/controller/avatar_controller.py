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


# 动作标签到 Live2D 动作组的映射
# 格式：{动作标签: (动作组名, 组内索引)}
MOTION_LABEL_TO_GROUP: dict[str, tuple[str, int]] = {
    # Idle 组 — 待机动作
    "idle_calm": ("Idle", 0),
    "idle_relaxed": ("Idle", 1),
    "idle_curious": ("Idle", 2),
    # Flick 组 — 轻弹方向
    "flick_bounce": ("Flick", 0),
    "flick_surprise": ("Flick", 1),
    "flick_nod": ("Flick", 2),
    # Tap 组 — 强调/互动
    "tap_excited": ("Tap", 0),
    "tap_think": ("Tap", 1),
    "tap_agree": ("Tap", 2),
    "tap_emphasize": ("Tap", 3),
    "tap_cheerful": ("Tap", 4),
    "tap_curious": ("Tap", 5),
    # FlickRight 组 — 向右
    "flick_right_glance": ("FlickRight", 0),
    "flick_right_talk": ("FlickRight", 1),
    "flick_right_reply": ("FlickRight", 2),
    # Flick3 组 — 交替弹动
    "flick3_double_bounce": ("Flick3", 0),
    "flick3_greet": ("Flick3", 1),
    "flick3_laugh": ("Flick3", 2),
    # FlickLeft 组 — 向左
    "flick_left_glance": ("FlickLeft", 0),
    "flick_left_respond": ("FlickLeft", 1),
    "flick_left_talk": ("FlickLeft", 2),
    # Shake 组 — 摇晃
    "shake_deny": ("Shake", 0),
    "shake_surprise": ("Shake", 1),
}


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

    # ---- 动作指令 ----
    motion_group: str = ""
    """动作组名称（如 'Idle', 'Flick', 'Tap' 等）"""

    motion_index: int = 0
    """动作组内的索引"""

    motion_priority: InputPriority = InputPriority.LOW
    """动作指令的优先级"""

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

    # ---- 身体姿态 ----
    param_body_angle_x: float = 0.0
    param_body_angle_y: float = 0.0
    param_body_angle_z: float = 0.0
    body_detected: bool = False

    # ---- 表情 ----
    expression: str = "Normal"

    # ---- 动作 ----
    motion_group: str = ""
    """动作组名称（如 'Idle', 'Flick', 'Tap' 等）"""

    motion_index: int = 0
    """动作组内的索引"""


class AvatarController:
    """统一控制层。

    核心职责：
    - 接收所有输入
    - 按优先级融合
    - 生成最终输出状态
    """

    def __init__(self) -> None:
        self._input: AvatarInputState = AvatarInputState()
        # 缓存最后一帧有效的面部/身体参数，面部丢失时保持不动
        self._last_angle_x = 0.0
        self._last_angle_y = 0.0
        self._last_angle_z = 0.0
        self._last_eye_l = 1.0
        self._last_eye_r = 1.0
        self._last_mouth = 0.0
        self._last_body_x = 0.0
        self._last_body_y = 0.0
        self._last_body_z = 0.0
        self._last_body_detected = False

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
            self._last_angle_x = max(-45.0, min(45.0, visual.head_yaw * 45.0))
            self._last_angle_y = max(-45.0, min(45.0, visual.head_pitch * 45.0))
            self._last_angle_z = max(-30.0, min(30.0, visual.head_roll * 30.0))
            # 眼部：0=闭合, 1=睁开
            self._last_eye_l = max(0.0, min(1.0, visual.eye_open_left))
            self._last_eye_r = max(0.0, min(1.0, visual.eye_open_right))
            # 嘴部：0=闭合, 1=张开
            self._last_mouth = max(0.0, min(1.0, visual.mouth_open))

        # 始终输出缓存的头部/眼部/嘴部参数（面部丢失时保持最后一帧位置）
        output.param_angle_x = self._last_angle_x
        output.param_angle_y = self._last_angle_y
        output.param_angle_z = self._last_angle_z
        output.param_eye_l_open = self._last_eye_l
        output.param_eye_r_open = self._last_eye_r
        output.param_mouth_open_y = self._last_mouth

        # 身体姿态：方案2，头部带动身体，同样缓存最后一帧
        if visual:
            self._last_body_x = max(-20.0, min(20.0, visual.body_yaw * 20.0))
            self._last_body_y = max(-20.0, min(20.0, visual.body_pitch * 20.0))
            self._last_body_z = max(-20.0, min(20.0, visual.body_roll * 20.0))
            self._last_body_detected = visual.body_detected

        output.param_body_angle_x = self._last_body_x
        output.param_body_angle_y = self._last_body_y
        output.param_body_angle_z = self._last_body_z
        output.body_detected = self._last_body_detected

        # 表情指令（后续接入情绪/语义后在此处做优先级判断）
        output.expression = self._input.expression

        # 动作指令
        output.motion_group = self._input.motion_group
        output.motion_index = self._input.motion_index

        return output

    # ---- 辅助方法 ----

    def set_motion_from_label(self, label: str) -> None:
        """根据动作标签设置动作指令。

        Args:
            label: 动作标签（如 'idle_calm', 'flick_bounce' 等）
        """
        if label in MOTION_LABEL_TO_GROUP:
            group, index = MOTION_LABEL_TO_GROUP[label]
            self._input.motion_group = group
            self._input.motion_index = index
            LOGGER.debug("动作标签映射：%s -> (%s, %d)", label, group, index)
        else:
            LOGGER.warning("未知的动作标签：%s", label)
