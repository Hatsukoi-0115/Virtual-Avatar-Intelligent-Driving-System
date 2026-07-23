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
import multiprocessing as mp
import os
import queue
from ctypes import wintypes
from pathlib import Path

import live2d.v3 as live2d
import pygame
from OpenGL.GL import glGetError
from pygame.locals import DOUBLEBUF, KEYDOWN, K_ESCAPE, MOUSEBUTTONDOWN, MOUSEBUTTONUP, MOUSEMOTION, NOFRAME, OPENGL, QUIT

from virtual_avatar_system.controller.avatar_controller import AvatarOutputState

LOGGER = logging.getLogger(__name__)
WINDOW_SIZE: tuple[int, int] = (1280, 720)
TRANSPARENT_KEY_RGB: tuple[int, int, int] = (0, 255, 0)
TRANSPARENT_CLEAR_RGBA: tuple[float, float, float, float] = (0.0, 1.0, 0.0, 1.0)

user32 = ctypes.windll.user32
GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
LWA_COLORKEY = 0x00000001
SWP_NOSIZE = 0x0001
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010


def _rgb_colorref(red: int, green: int, blue: int) -> int:
    """把 RGB 值转换成 Windows 颜色键需要的 COLORREF。"""
    return red | (green << 8) | (blue << 16)


def _get_window_handle() -> int:
    """获取 Pygame 窗口句柄。"""
    window_info = pygame.display.get_wm_info()
    hwnd = window_info.get("window")
    if not hwnd:
        raise RuntimeError("无法获取窗口句柄，透明窗口设置失败")
    return int(hwnd)


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
    """把窗口设置为分层窗口，并使用颜色键抠掉背景。"""
    ex_style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex_style | WS_EX_LAYERED)
    color_key = _rgb_colorref(*TRANSPARENT_KEY_RGB)
    if not user32.SetLayeredWindowAttributes(hwnd, color_key, 0, LWA_COLORKEY):
        raise ctypes.WinError()


def _move_window(hwnd: int, x: int, y: int) -> None:
    """移动无边框窗口。"""
    if not user32.SetWindowPos(hwnd, None, x, y, 0, 0, SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE):
        raise ctypes.WinError()


def _configure_logging() -> None:
    """配置日志，便于定位渲染和模型加载问题。"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


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


def _apply_avatar_output(model: live2d.LAppModel, output: AvatarOutputState, last_expression: str) -> str:
    """把控制层输出映射到 Live2D 参数。"""
    model.SetParameterValue("PARAM_ANGLE_X", output.param_angle_x)
    model.SetParameterValue("PARAM_ANGLE_Y", output.param_angle_y)
    model.SetParameterValue("PARAM_ANGLE_Z", output.param_angle_z)
    model.SetParameterValue("PARAM_EYE_L_OPEN", output.param_eye_l_open)
    model.SetParameterValue("PARAM_EYE_R_OPEN", output.param_eye_r_open)
    model.SetParameterValue("PARAM_MOUTH_OPEN_Y", output.param_mouth_open_y)

    if output.expression and output.expression != last_expression:
        model.SetExpression(output.expression)
        last_expression = output.expression

    return last_expression


def _render_worker(model_json_path_str: str, command_queue: mp.Queue[AvatarOutputState], stop_event: mp.Event) -> None:
    """独立渲染进程入口。"""
    _configure_logging()

    if os.name != "nt":
        raise RuntimeError("当前渲染实现仅支持 Windows")

    model_json_path = Path(model_json_path_str)
    if not model_json_path.exists():
        raise FileNotFoundError(f"未找到 Live2D 模型入口文件：{model_json_path}")

    pygame.init()
    pygame.display.set_caption("Live2D 形象窗口")
    pygame.display.set_mode(WINDOW_SIZE, DOUBLEBUF | OPENGL | NOFRAME)
    pygame.mouse.set_visible(True)

    hwnd = _get_window_handle()
    _enable_transparent_window(hwnd)

    live2d.init()
    live2d.glInit()

    model = live2d.LAppModel()
    model.LoadModelJson(str(model_json_path))
    model.Resize(*WINDOW_SIZE)
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

            last_expression = _apply_avatar_output(model, latest_output, last_expression)

            # 先更新模型，再绘制当前帧。
            model.Update()
            live2d.clearBuffer(*TRANSPARENT_CLEAR_RGBA)
            model.Draw()

            if glGetError() != 0:
                LOGGER.warning("OpenGL 渲染过程中检测到错误")

            pygame.display.flip()
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
        self._model_json_path: Path | None = None
        self._latest_output = AvatarOutputState()

    # ---- 生命周期 ----

    def start(self, model_json_path: Path) -> None:
        """启动 Live2D 渲染窗口。"""
        if self.is_running:
            LOGGER.warning("Live2D 渲染进程已在运行")
            return

        model_json_path = Path(model_json_path)
        if not model_json_path.exists():
            raise FileNotFoundError(f"未找到 Live2D 模型入口文件：{model_json_path}")

        context = mp.get_context("spawn")
        self._command_queue = context.Queue(maxsize=2)
        self._stop_event = context.Event()
        self._model_json_path = model_json_path

        self._process = context.Process(
            target=_render_worker,
            name="live2d-renderer",
            args=(str(model_json_path), self._command_queue, self._stop_event),
            daemon=True,
        )
        self._process.start()
        LOGGER.info("Live2D 渲染窗口已启动：%s", model_json_path.name)

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
        self._model_json_path = None
        self._latest_output = AvatarOutputState()
        LOGGER.info("Live2D 渲染窗口已停止")

    @property
    def is_running(self) -> bool:
        """当前渲染进程是否存活。"""
        return self._process is not None and self._process.is_alive()

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
