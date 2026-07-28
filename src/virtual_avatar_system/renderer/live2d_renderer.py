"""Live2D 渲染层。

职责：
- 作为独立进程打开 Live2D 窗口
- 接收 Avatar Controller 输出并实时更新模型参数
- 维持 Live2D 的眨眼、呼吸、表情与动作播放
- 不承载任何感知或融合逻辑
"""

from __future__ import annotations

import ctypes
import logging
import math
import multiprocessing as mp
import os
import queue
import time
from ctypes import wintypes
from pathlib import Path

import live2d.v3 as live2d
import pygame
from OpenGL.GL import GL_BLEND, GL_ONE_MINUS_SRC_ALPHA, GL_SRC_ALPHA, glBlendFunc, glEnable, glGetError
from pygame.locals import DOUBLEBUF, KEYDOWN, K_ESCAPE, MOUSEBUTTONDOWN, MOUSEBUTTONUP, MOUSEMOTION, NOFRAME, OPENGL, QUIT

from virtual_avatar_system.controller.avatar_controller import AvatarOutputState

LOGGER = logging.getLogger(__name__)
DEFAULT_WINDOW_SIZE: tuple[int, int] = (360, 640)
MIN_WINDOW_SIZE: tuple[int, int] = (240, 360)
MAX_WINDOW_SIZE: tuple[int, int] = (960, 1080)
# 逐像素 alpha 透明：清屏时 alpha=0 表示完全透明，DWM 负责与桌面合成
TRANSPARENT_CLEAR_RGBA: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)

user32 = ctypes.windll.user32
GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2
SWP_NOSIZE = 0x0001
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010

# DWM 模糊背景常量
DWM_BB_ENABLE = 0x00000001


class _DwmBlurBehind(ctypes.Structure):
    """DWM 模糊背景参数结构体。"""

    _fields_ = [
        ("dwFlags", wintypes.DWORD),
        ("fEnable", wintypes.BOOL),
        ("hRgnBlur", wintypes.HRGN),
        ("fTransitionOnMaximized", wintypes.BOOL),
    ]


class _Margins(ctypes.Structure):
    """窗口边距结构体，用于 DwmExtendFrameIntoClientArea。"""

    _fields_ = [
        ("cxLeftWidth", wintypes.INT),
        ("cxRightWidth", wintypes.INT),
        ("cyTopHeight", wintypes.INT),
        ("cyBottomHeight", wintypes.INT),
    ]


def _get_window_handle() -> int:
    """获取 Pygame 窗口句柄。"""
    window_info = pygame.display.get_wm_info()
    hwnd = window_info.get("window")
    if not hwnd:
        raise RuntimeError("无法获取窗口句柄，透明窗口设置失败")
    return int(hwnd)


def _get_valid_window_handle(retry_count: int = 20, interval_seconds: float = 0.05) -> int:
    """等待并获取可用的 Windows 窗口句柄。"""
    last_hwnd = 0
    for _ in range(retry_count):
        pygame.event.pump()
        try:
            last_hwnd = _get_window_handle()
        except RuntimeError:
            last_hwnd = 0
        # Pygame 创建 OpenGL 窗口后，句柄可能需要短暂时间才被系统识别。
        if last_hwnd and user32.IsWindow(last_hwnd):
            return last_hwnd
        time.sleep(interval_seconds)

    raise RuntimeError(f"无法获取有效窗口句柄：{last_hwnd}")


def _get_window_position(hwnd: int) -> tuple[int, int]:
    """读取窗口左上角坐标，用于拖动窗口。"""
    rect = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        raise ctypes.WinError()
    return rect.left, rect.top


def _get_cursor_position() -> tuple[int, int]:
    """读取当前鼠标的屏幕坐标。"""
    point = wintypes.POINT()
    if not user32.GetCursorPos(ctypes.byref(point)):
        raise ctypes.WinError()
    return point.x, point.y


def _enable_transparent_window(hwnd: int) -> None:
    """使用 DWM 逐像素 alpha 实现真正的透明窗口，无色键溢边。"""
    ex_style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex_style | WS_EX_LAYERED)

    # DwmEnableBlurBehindWindow 让 DWM 按 alpha 通道合成窗口
    # alpha=0 的像素完全透明，alpha=1 的像素完全显示，边缘自然过渡
    dwmapi = ctypes.windll.dwmapi
    blur = _DwmBlurBehind()
    blur.dwFlags = DWM_BB_ENABLE
    blur.fEnable = True
    blur.hRgnBlur = None
    blur.fTransitionOnMaximized = False
    result = dwmapi.DwmEnableBlurBehindWindow(hwnd, ctypes.byref(blur))
    if result != 0:
        LOGGER.warning("DWM 透明窗口设置失败（错误码 %s），窗口背景可能不透明", result)
        return

    # 将 DWM 帧扩展到整个客户区，确保逐像素 alpha 合成覆盖全窗口
    margins = _Margins(-1, -1, -1, -1)
    result2 = dwmapi.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(margins))
    if result2 != 0:
        LOGGER.warning("DwmExtendFrameIntoClientArea 失败（错误码 %s）", result2)


def _move_window(hwnd: int, x: int, y: int) -> None:
    """移动无边框窗口。"""
    if not user32.SetWindowPos(hwnd, None, x, y, 0, 0, SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE):
        raise ctypes.WinError()


def _set_window_topmost(hwnd: int, enabled: bool) -> bool:
    """设置 Live2D 窗口置顶，避免被主窗口遮住。"""
    if not user32.IsWindow(hwnd):
        LOGGER.warning("Live2D 窗口句柄无效，跳过置顶设置：%s", hwnd)
        return False

    insert_after = HWND_TOPMOST if enabled else HWND_NOTOPMOST
    if not user32.SetWindowPos(hwnd, insert_after, 0, 0, 0, 0, SWP_NOSIZE | SWP_NOACTIVATE):
        LOGGER.warning("Live2D 窗口置顶设置失败：%s", ctypes.WinError())
        return False
    return True


def _configure_logging() -> None:
    """配置日志，便于定位渲染和模型加载问题。"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


def _normalize_window_size(window_size: tuple[int, int] | None) -> tuple[int, int]:
    """校验并限制 Live2D 窗口尺寸，避免透明区域过大或模型被过度裁切。"""
    if window_size is None:
        return DEFAULT_WINDOW_SIZE

    width, height = window_size
    width = max(MIN_WINDOW_SIZE[0], min(MAX_WINDOW_SIZE[0], int(width)))
    height = max(MIN_WINDOW_SIZE[1], min(MAX_WINDOW_SIZE[1], int(height)))
    return width, height


def _load_expressions(model: live2d.LAppModel, model_json_path: Path) -> list[str]:
    """显式加载模型表情文件。"""
    expressions_dir = model_json_path.parent / "expressions"
    expression_ids: list[str] = []
    if not expressions_dir.exists():
        return expression_ids

    for exp_file in sorted(expressions_dir.glob("*.exp3.json")):
        exp_id = exp_file.stem.replace(".exp3", "")
        model.LoadExtraExpression(exp_id, str(exp_file))
        expression_ids.append(exp_id)
        LOGGER.info("已加载表情：%s", exp_id)

    return expression_ids


def _apply_avatar_output(
    model: live2d.LAppModel,
    output: AvatarOutputState,
    last_expression: str,
    last_motion: tuple[str, int],
    motion_playing: bool,
) -> tuple[str, tuple[str, int], bool]:
    """把控制层输出映射到 Live2D 参数。

    Args:
        model: Live2D 模型实例
        output: 控制层输出状态
        last_expression: 上一次设置的表情
        last_motion: 上一次设置的动作 (group, index)
        motion_playing: 当前是否有动作正在播放

    Returns:
        (当前表情, 当前动作, 动作是否正在播放)
    """
   # 动作中断：人脸重新检测到时立即停止待机动作，恢复实时驱动
    # 不依赖 motion_playing 标志，因为该标志在 MOTION_MIN_DURATION 后会自动置 False，
    # 但实际动作可能仍在播放（循环或时长超过最小持续时间）
    if output.interrupt_motion and not model.IsMotionFinished():
        model.StopAllMotions()
        motion_playing = False
        last_motion = ("", 0)
        LOGGER.info("人脸重新检测到，打断待机动作")
    elif output.interrupt_motion:
        # 即使 IsMotionFinished 为 True，也重置状态，保持一致
        motion_playing = False
        last_motion = ("", 0)

    # 更新基础参数（头部姿态、眼部、嘴部）
    model.SetParameterValue("PARAM_ANGLE_X", output.param_angle_x)
    model.SetParameterValue("PARAM_ANGLE_Y", output.param_angle_y)
    model.SetParameterValue("PARAM_ANGLE_Z", output.param_angle_z)
    # 身体姿态
    model.SetParameterValue("PARAM_BODY_ANGLE_X", output.param_body_angle_x)
    model.SetParameterValue("PARAM_BODY_ANGLE_Y", output.param_body_angle_y)
    model.SetParameterValue("PARAM_BODY_ANGLE_Z", output.param_body_angle_z)
    model.SetParameterValue("PARAM_EYE_L_OPEN", output.param_eye_l_open)
    model.SetParameterValue("PARAM_EYE_R_OPEN", output.param_eye_r_open)
    model.SetParameterValue("PARAM_MOUTH_OPEN_Y", output.param_mouth_open_y)

    # 表情：允许被新的表情打断
    if output.expression and output.expression != last_expression:
        model.SetExpression(output.expression)
        last_expression = output.expression
        LOGGER.debug("播放表情：%s", output.expression)

    # 动作：不允许被新的动作打断
    # 只有在没有动作播放时，才播放新动作
    current_motion = (output.motion_group, output.motion_index)
    if output.motion_group and current_motion != last_motion and not motion_playing:
        model.StartMotion(output.motion_group, output.motion_index, live2d.MotionPriority.FORCE)
        last_motion = current_motion
        motion_playing = True
        LOGGER.info("播放动作：%s[%d]", output.motion_group, output.motion_index)

    return last_expression, last_motion, motion_playing


def _render_worker(
    model_json_path_str: str,
    window_size: tuple[int, int],
    always_on_top: bool,
    command_queue: mp.Queue[AvatarOutputState],
    stop_event: mp.Event,
    ready_event: mp.Event,
) -> None:
    """独立渲染进程入口。"""
    _configure_logging()

    if os.name != "nt":
        raise RuntimeError("当前渲染实现仅支持 Windows")

    model_json_path = Path(model_json_path_str)
    if not model_json_path.exists():
        raise FileNotFoundError(f"未找到 Live2D 模型入口文件：{model_json_path}")

    pygame.init()
    pygame.display.set_caption("Live2D 形象窗口")
    # 请求带 alpha 通道的 OpenGL 像素格式，DWM 才能按逐像素 alpha 合成透明背景
    pygame.display.gl_set_attribute(pygame.GL_ALPHA_SIZE, 8)
    pygame.display.gl_set_attribute(pygame.GL_DOUBLEBUFFER, 1)
    pygame.display.set_mode(window_size, DOUBLEBUF | OPENGL | NOFRAME)
    pygame.mouse.set_visible(True)
    LOGGER.info("Live2D 形象窗口尺寸：%sx%s", window_size[0], window_size[1])

    hwnd = _get_valid_window_handle()
    _enable_transparent_window(hwnd)
    topmost_applied = _set_window_topmost(hwnd, always_on_top)
    LOGGER.info(
        "Live2D 形象窗口置顶：%s",
        "开启" if always_on_top and topmost_applied else "未开启",
    )

    live2d.init()
    live2d.glInit()
    # 开启 OpenGL alpha 混合，模型边缘与透明背景自然过渡，无色键溢边
    glEnable(GL_BLEND)
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

    model = live2d.LAppModel()
    model.LoadModelJson(str(model_json_path))
    model.Resize(*window_size)
    # 眨眼由 MediaPipe 的眼部开合输入接管，不再使用 Live2D 内置自动眨眼。
    model.SetAutoBlinkEnable(False)
    model.SetAutoBreathEnable(True)
    expressions = _load_expressions(model, model_json_path)
    LOGGER.info("Live2D 模型已加载：%s", model_json_path.name)

    if expressions:
        LOGGER.info("可用表情数量：%s", len(expressions))

    clock = pygame.time.Clock()
    running = True
    dragging = False
    drag_window_origin = (0, 0)
    drag_cursor_origin = (0, 0)
    latest_output = AvatarOutputState()
    last_expression = ""
    last_motion: tuple[str, int] = ("", 0)
    motion_playing = False
    motion_start_time = 0.0
    MOTION_MIN_DURATION = 2.0
    first_frame_rendered = False
    # 方案3：呼吸待机动画
    breath_phase = 0.0
    BREATH_SPEED = 0.015
    BREATH_AMPLITUDE = 1.0

    try:
        while running and not stop_event.is_set():
            try:
                while True:
                    latest_output = command_queue.get_nowait()
            except queue.Empty:
                pass

            for event in pygame.event.get():
                if event.type == QUIT:
                    running = False
                    stop_event.set()
                elif event.type == KEYDOWN and event.key == K_ESCAPE:
                    running = False
                    stop_event.set()
                elif event.type == MOUSEBUTTONDOWN and event.button == 1:
                    dragging = True
                    drag_window_origin = _get_window_position(hwnd)
                    drag_cursor_origin = _get_cursor_position()
                elif event.type == MOUSEBUTTONUP and event.button == 1:
                    dragging = False
                elif event.type == MOUSEMOTION and dragging and event.buttons[0]:
                    cursor_x, cursor_y = _get_cursor_position()
                    delta_x = cursor_x - drag_cursor_origin[0]
                    delta_y = cursor_y - drag_cursor_origin[1]
                    _move_window(hwnd, drag_window_origin[0] + delta_x, drag_window_origin[1] + delta_y)

            # 检测动作是否播放完成（基于时间）
            current_time = pygame.time.get_ticks() / 1000.0
            if motion_playing and (current_time - motion_start_time) >= MOTION_MIN_DURATION:
                motion_playing = False
                LOGGER.debug("动作播放完成")

            last_expression, last_motion, motion_playing = _apply_avatar_output(
                model, latest_output, last_expression, last_motion, motion_playing
            )
            
            # 如果播放了新动作，记录开始时间
            if last_motion != ("", 0) and not motion_playing:
                motion_start_time = current_time

            # 方案3：呼吸待机动画，始终运行
            breath_phase += BREATH_SPEED
            if breath_phase > 2.0 * 3.14159:
                breath_phase -= 2.0 * 3.14159
            model.SetParameterValue("PARAM_BREATH", (math.sin(breath_phase) + 1.0) / 2.0 * BREATH_AMPLITUDE)

            # 先更新模型，再绘制当前帧。
            model.Update()
            live2d.clearBuffer(*TRANSPARENT_CLEAR_RGBA)
            model.Draw()

            if glGetError() != 0:
                LOGGER.warning("OpenGL 渲染过程中检测到错误")

            pygame.display.flip()
            if not first_frame_rendered:
                # 第一帧完成后通知主窗口，避免用户在模型加载期间看到空白等待。
                first_frame_rendered = True
                ready_event.set()
                LOGGER.info("Live2D 第一帧已渲染")
            clock.tick(60)
    finally:
        model.DestroyRenderer()
        live2d.glRelease()
        live2d.dispose()
        pygame.quit()


class Live2DRenderer:
    """Live2D 渲染进程管理器。

    主进程只负责向子进程投递 Avatar Controller 输出，
    子进程负责打开窗口、更新参数并完成绘制。
    """

    def __init__(self) -> None:
        self._process: mp.Process | None = None
        self._command_queue: mp.Queue[AvatarOutputState] | None = None
        self._stop_event: mp.Event | None = None
        self._ready_event: mp.Event | None = None
        self._model_json_path: Path | None = None
        self._latest_output = AvatarOutputState()

    # ---- 生命周期 ----

    def start(
        self,
        model_json_path: Path,
        window_size: tuple[int, int] | None = None,
        always_on_top: bool = True,
    ) -> None:
        """启动 Live2D 渲染窗口。"""
        if self.is_running:
            LOGGER.warning("Live2D 渲染进程已在运行")
            return

        normalized_window_size = _normalize_window_size(window_size)
        model_json_path = Path(model_json_path)
        if not model_json_path.exists():
            raise FileNotFoundError(f"未找到 Live2D 模型入口文件：{model_json_path}")

        context = mp.get_context("spawn")
        self._command_queue = context.Queue(maxsize=2)
        self._stop_event = context.Event()
        self._ready_event = context.Event()
        self._model_json_path = model_json_path

        self._process = context.Process(
            target=_render_worker,
            name="live2d-renderer",
            args=(
                str(model_json_path),
                normalized_window_size,
                always_on_top,
                self._command_queue,
                self._stop_event,
                self._ready_event,
            ),
            daemon=True,
        )
        self._process.start()
        LOGGER.info(
            "Live2D 渲染窗口已启动：%s %sx%s always_on_top=%s",
            model_json_path.name,
            normalized_window_size[0],
            normalized_window_size[1],
            always_on_top,
        )

    def stop(self) -> None:
        """停止渲染进程并释放资源。"""
        if self._stop_event is not None:
            self._stop_event.set()

        if self._process is not None:
            self._process.join(timeout=3.0)
            if self._process.is_alive():
                self._process.terminate()
                self._process.join(timeout=2.0)

        self._process = None
        self._command_queue = None
        self._stop_event = None
        self._ready_event = None
        self._model_json_path = None
        self._latest_output = AvatarOutputState()
        LOGGER.info("Live2D 渲染窗口已停止")

    @property
    def is_running(self) -> bool:
        """当前渲染进程是否存活。"""
        return self._process is not None and self._process.is_alive()

    @property
    def is_ready(self) -> bool:
        """当前渲染窗口是否已经完成第一帧绘制。"""
        return self._ready_event is not None and self._ready_event.is_set()

    # ---- 控制输入 ----

    def submit_state(self, output: AvatarOutputState) -> None:
        """提交最新控制层输出，供渲染进程消费。"""
        self._latest_output = output
        if self._command_queue is None:
            return

        try:
            self._command_queue.put_nowait(output)
        except queue.Full:
            try:
                self._command_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._command_queue.put_nowait(output)
            except queue.Full:
                LOGGER.debug("渲染命令队列已满，已丢弃一帧旧状态")

    def set_parameter(self, param_id: str, value: float) -> None:
        """兼容旧接口：直接修改本地缓存状态并立即提交。"""
        self._latest_output = self._set_cached_parameter(self._latest_output, param_id, value)
        self.submit_state(self._latest_output)

    def set_parameters(self, params: dict[str, float]) -> None:
        """兼容旧接口：批量修改本地缓存状态并立即提交。"""
        output = self._latest_output
        for param_id, value in params.items():
            output = self._set_cached_parameter(output, param_id, value)
        self._latest_output = output
        self.submit_state(output)

    def set_expression(self, expression_id: str) -> None:
        """兼容旧接口：更新表情并立即提交。"""
        self._latest_output.expression = expression_id
        self.submit_state(self._latest_output)

    def start_motion(self, group: str, index: int, priority: int = 3) -> None:
        """兼容旧接口：当前版本由渲染进程自动管理待机动作。"""
        LOGGER.info("当前版本由渲染进程自动管理动作：group=%s index=%s priority=%s", group, index, priority)

    def load_model(self, model_json_path: Path) -> None:
        """兼容旧接口：启动渲染窗口。"""
        self.start(model_json_path)

    def release(self) -> None:
        """兼容旧接口：停止渲染窗口。"""
        self.stop()

    # ---- 内部映射 ----

    def _set_cached_parameter(self, output: AvatarOutputState, param_id: str, value: float) -> AvatarOutputState:
        """把常见 Live2D 参数名映射到缓存状态字段。"""
        if param_id == "ParamAngleX":
            output.param_angle_x = value
        elif param_id == "ParamAngleY":
            output.param_angle_y = value
        elif param_id == "ParamAngleZ":
            output.param_angle_z = value
        elif param_id == "ParamEyeLOpen":
            output.param_eye_l_open = value
        elif param_id == "ParamEyeROpen":
            output.param_eye_r_open = value
        elif param_id == "ParamMouthOpenY":
            output.param_mouth_open_y = value
        return output
