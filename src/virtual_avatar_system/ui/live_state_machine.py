"""直播状态机模块。

职责：
- 定义直播五状态及其转换规则
- 提供状态变更回调，供 UI 层订阅
- 保证非法状态转换被拒绝并记录日志

状态说明：
- IDLE      未准备
- PREPARING 准备中
- RUNNING   运行中
- STOPPING  停止中
- ERROR     错误恢复
"""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass, field
from typing import Callable, ClassVar

LOGGER = logging.getLogger(__name__)


class LiveState(enum.Enum):
    """直播状态枚举。"""

    IDLE = "idle"
    PREPARING = "preparing"
    RUNNING = "running"
    STOPPING = "stopping"
    ERROR = "error"


@dataclass(slots=True)
class LiveStateMachine:
    """直播状态机。

    只允许以下转换：
    - IDLE -> PREPARING
    - PREPARING -> RUNNING
    - PREPARING -> ERROR
    - RUNNING -> STOPPING
    - RUNNING -> ERROR
    - STOPPING -> IDLE
    - STOPPING -> ERROR
    - ERROR -> IDLE
    """

    current_state: LiveState = LiveState.IDLE
    error_message: str = ""
    _state_change_callbacks: list[Callable[[LiveState, LiveState], None]] = field(default_factory=list)

    _ALLOWED_TRANSITIONS: ClassVar[dict[LiveState, tuple[LiveState, ...]]] = {
        LiveState.IDLE: (LiveState.PREPARING,),
        LiveState.PREPARING: (LiveState.RUNNING, LiveState.ERROR),
        LiveState.RUNNING: (LiveState.STOPPING, LiveState.ERROR),
        LiveState.STOPPING: (LiveState.IDLE, LiveState.ERROR),
        LiveState.ERROR: (LiveState.IDLE,),
    }

    # ---- 状态查询 ----

    @property
    def can_start(self) -> bool:
        """当前是否能开始直播。"""
        return self.current_state == LiveState.IDLE

    @property
    def can_stop(self) -> bool:
        """当前是否能停止直播。"""
        return self.current_state in (LiveState.RUNNING, LiveState.PREPARING)

    @property
    def is_running(self) -> bool:
        """直播是否正在运行中。"""
        return self.current_state == LiveState.RUNNING

    # ---- 状态变更 ----

    def on_state_changed(self, callback: Callable[[LiveState, LiveState], None]) -> None:
        """注册状态变更回调。

        回调参数：(old_state, new_state)
        """
        self._state_change_callbacks.append(callback)

    # ---- 公共操作 ----

    def start(self) -> None:
        """开始直播：IDLE -> PREPARING。"""
        self._transition_to(LiveState.PREPARING)

    def on_ready(self) -> None:
        """所有模块就绪：PREPARING -> RUNNING。"""
        self._transition_to(LiveState.RUNNING)

    def stop(self) -> None:
        """停止直播：RUNNING -> STOPPING。"""
        self._transition_to(LiveState.STOPPING)

    def on_stopped(self) -> None:
        """资源已释放：STOPPING -> IDLE。"""
        self._transition_to(LiveState.IDLE)

    def on_error(self, message: str) -> None:
        """进入错误状态。"""
        self.error_message = message
        self._transition_to(LiveState.ERROR)

    def reset(self) -> None:
        """从错误恢复：ERROR -> IDLE。"""
        self.error_message = ""
        self._transition_to(LiveState.IDLE)

    # ---- 内部实现 ----

    def _transition_to(self, target: LiveState) -> None:
        """执行状态转换并触发回调。"""
        allowed = self._ALLOWED_TRANSITIONS.get(self.current_state, ())
        if target not in allowed:
            LOGGER.warning("非法状态转换：%s -> %s", self.current_state.value, target.value)
            return

        old_state = self.current_state
        self.current_state = target
        LOGGER.info("状态变更：%s -> %s", old_state.value, target.value)

        for callback in self._state_change_callbacks:
            try:
                callback(old_state, target)
            except Exception as exc:  # noqa: BLE001
                LOGGER.error("状态回调异常：%s", exc)
