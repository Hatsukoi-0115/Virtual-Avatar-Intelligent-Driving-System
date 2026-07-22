"""Live2D POC 测试脚本。

用途：
- 验证 Live2D Python 封装是否能在 Windows 下打开窗口
- 验证模型加载、参数更新和基础表情切换
- 作为后续多模态驱动的最小可执行验证入口
"""

from __future__ import annotations

import ctypes
import logging
import os
from pathlib import Path
from typing import Final
from ctypes import wintypes

import live2d.v3 as live2d
import pygame
from OpenGL.GL import glGetError
from pygame.locals import DOUBLEBUF, OPENGL, NOFRAME, QUIT, KEYDOWN, MOUSEBUTTONDOWN, MOUSEBUTTONUP, MOUSEMOTION, K_ESCAPE, K_1, K_2, K_3, K_4

LOGGER = logging.getLogger(__name__)
PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
MODEL_JSON: Final[Path] = PROJECT_ROOT / "models" / "haru_ja" / "runtime" / "haru.model3.json"
WINDOW_SIZE: Final[tuple[int, int]] = (1280, 720)
TRANSPARENT_KEY_RGB: Final[tuple[int, int, int]] = (0, 255, 0)
TRANSPARENT_CLEAR_RGBA: Final[tuple[float, float, float, float]] = (0.0, 1.0, 0.0, 1.0)

user32 = ctypes.windll.user32
GWL_EXSTYLE: Final[int] = -20
WS_EX_LAYERED: Final[int] = 0x00080000
LWA_COLORKEY: Final[int] = 0x00000001
SWP_NOSIZE: Final[int] = 0x0001
SWP_NOZORDER: Final[int] = 0x0004
SWP_NOACTIVATE: Final[int] = 0x0010


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
    """配置日志，方便排查模型加载和渲染问题。"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


def _find_model_json() -> Path:
    """定位模型入口文件。

    这里优先使用 haru_ja/runtime/haru.model3.json，便于后续替换为其他模型目录。
    """
    if MODEL_JSON.exists():
        return MODEL_JSON

    raise FileNotFoundError(f"未找到 Live2D 模型入口文件：{MODEL_JSON}")


def _apply_demo_state(model: live2d.LAppModel, tick: int) -> None:
    """给模型施加简单的演示状态。

    这个 POC 不接入真实摄像头和麦克风，只用定时变化来验证参数更新链路。
    """
    wave = (tick % 240) / 240.0
    mouth_open = 0.15 + 0.25 * wave
    eye_open = 0.65 + 0.25 * (1.0 - wave)
    angle_x = -10.0 + 20.0 * wave

    model.SetParameterValue(live2d.StandardParams.ParamMouthOpenY, mouth_open)
    model.SetParameterValue(live2d.StandardParams.ParamEyeLOpen, eye_open)
    model.SetParameterValue(live2d.StandardParams.ParamEyeROpen, eye_open)
    model.SetParameterValue(live2d.StandardParams.ParamAngleX, angle_x)
    model.Update()


def main() -> None:
    """启动 Live2D POC 窗口。"""
    _configure_logging()
    if os.name != "nt":
        raise RuntimeError("当前 POC 仅支持 Windows")

    model_json = _find_model_json()
    LOGGER.info("使用模型文件：%s", model_json)

    pygame.init()
    pygame.display.set_caption("Live2D POC - haru_ja")
    pygame.display.set_mode(WINDOW_SIZE, DOUBLEBUF | OPENGL | NOFRAME)
    pygame.mouse.set_visible(True)

    hwnd = _get_window_handle()
    _enable_transparent_window(hwnd)

    live2d.init()
    live2d.glInit()

    model = live2d.LAppModel()
    model.LoadModelJson(str(model_json))
    model.Resize(*WINDOW_SIZE)
    model.SetAutoBlinkEnable(True)
    model.SetAutoBreathEnable(True)

    clock = pygame.time.Clock()
    tick = 0
    running = True
    dragging = False
    drag_window_origin = (0, 0)
    drag_cursor_origin = (0, 0)

    try:
        while running:
            for event in pygame.event.get():
                if event.type == QUIT:
                    running = False
                elif event.type == MOUSEBUTTONDOWN and event.button == 1:
                    dragging = True
                    drag_window_origin = _get_window_position(hwnd)
                    drag_cursor_origin = _get_cursor_position()
                elif event.type == KEYDOWN and event.key == K_ESCAPE:
                    running = False
                elif event.type == KEYDOWN and event.key == K_1:
                    model.SetRandomExpression()
                elif event.type == KEYDOWN and event.key == K_2:
                    model.SetExpression("Normal")
                elif event.type == KEYDOWN and event.key == K_3:
                    model.StartRandomMotion("Idle", live2d.MotionPriority.NORMAL)
                elif event.type == KEYDOWN and event.key == K_4:
                    model.StartRandomMotion("Tap", live2d.MotionPriority.NORMAL)
                elif event.type == MOUSEBUTTONUP and event.button == 1:
                    dragging = False
                elif event.type == MOUSEMOTION and dragging and event.buttons[0]:
                    cursor_x, cursor_y = _get_cursor_position()
                    delta_x = cursor_x - drag_cursor_origin[0]
                    delta_y = cursor_y - drag_cursor_origin[1]
                    _move_window(hwnd, drag_window_origin[0] + delta_x, drag_window_origin[1] + delta_y)

            # 这里用时间驱动的演示状态模拟后续的多模态输入，方便先验证参数更新链路。
            _apply_demo_state(model, tick)
            live2d.clearBuffer(*TRANSPARENT_CLEAR_RGBA)
            model.Draw()

            if glGetError() != 0:
                LOGGER.warning("OpenGL 渲染过程中检测到错误")

            pygame.display.flip()
            clock.tick(60)
            tick += 1
    finally:
        # 退出时按顺序释放资源，避免 OpenGL 上下文和 Live2D 状态残留。
        model.DestroyRenderer()
        live2d.glRelease()
        live2d.dispose()
        pygame.quit()


if __name__ == "__main__":
    main()
