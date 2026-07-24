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
# 按序播放的 23 个动作：(分组名, 组内索引, 简要标签)
ALL_MOTIONS: Final[list[tuple[str, int, str]]] = [
    # Idle 组 — 待机动作
    ("Idle", 0, "idle_calm"),
    ("Idle", 1, "idle_relaxed"),
    ("Idle", 2, "idle_curious"),
    # Flick 组 — 轻弹方向
    ("Flick", 0, "flick_bounce"),
    ("Flick", 1, "flick_surprise"),
    ("Flick", 2, "flick_nod"),
    # Tap 组 — 强调/互动
    ("Tap", 0, "tap_excited"),
    ("Tap", 1, "tap_think"),
    ("Tap", 2, "tap_agree"),
    ("Tap", 3, "tap_emphasize"),
    ("Tap", 4, "tap_cheerful"),
    ("Tap", 5, "tap_curious"),
    # FlickRight 组 — 向右
    ("FlickRight", 0, "flick_right_glance"),
    ("FlickRight", 1, "flick_right_talk"),
    ("FlickRight", 2, "flick_right_reply"),
    # Flick3 组 — 交替弹动
    ("Flick3", 0, "flick3_double_bounce"),
    ("Flick3", 1, "flick3_greet"),
    ("Flick3", 2, "flick3_laugh"),
    # FlickLeft 组 — 向左
    ("FlickLeft", 0, "flick_left_glance"),
    ("FlickLeft", 1, "flick_left_respond"),
    ("FlickLeft", 2, "flick_left_talk"),
    # Shake 组 — 摇晃
    ("Shake", 0, "shake_deny"),
    ("Shake", 1, "shake_surprise"),
]
TOTAL_MOTIONS: Final[int] = len(ALL_MOTIONS)

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


def _load_model_expressions(model: live2d.LAppModel) -> list[str]:
    """显式加载模型表情文件。

    有些封装不会自动把 runtime/expressions 下的表情全部挂到模型里，
    这里显式加载后再切换，避免 SetExpression 找不到目标表情。
    """
    expressions_dir = MODEL_JSON.parent / "expressions"
    expression_ids: list[str] = []
    for expression_file in sorted(expressions_dir.glob("*.exp3.json")):
        expression_id = expression_file.stem.replace(".exp3", "")
        model.LoadExtraExpression(expression_id, str(expression_file))
        expression_ids.append(expression_id)
        LOGGER.info("已加载表情：%s -> %s", expression_id, expression_file.name)

    if not expression_ids:
        raise FileNotFoundError(f"未找到可加载的表情文件：{expressions_dir}")

    return expression_ids


def _play_current_motion(model: live2d.LAppModel, index: int) -> None:
    """播放下一个预设动作。"""
    if index >= TOTAL_MOTIONS:
        return
    group, motion_no, label = ALL_MOTIONS[index]
    model.StartMotion(group, motion_no, live2d.MotionPriority.FORCE)
    LOGGER.info(
        "动作 %s/%s：group=%s index=%s label=%s",
        index + 1,
        TOTAL_MOTIONS,
        group,
        motion_no,
        label,
    )


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
    expression_ids = _load_model_expressions(model)

    clock = pygame.time.Clock()
    tick = 0
    running = True
    dragging = False
    drag_window_origin = (0, 0)
    drag_cursor_origin = (0, 0)
    motion_index = 0
    expression_index = 0

    # 启动时自动播放第一个动作
    _play_current_motion(model, motion_index)

    try:
        while running:
            for event in pygame.event.get():
                if event.type == QUIT:
                    # 用户关闭窗口，直接结束预览。
                    running = False
                elif event.type == MOUSEBUTTONDOWN and event.button == 1:
                    # 按住左键开始拖动窗口。
                    dragging = True
                    drag_window_origin = _get_window_position(hwnd)
                    drag_cursor_origin = _get_cursor_position()
                elif event.type == KEYDOWN and event.key == K_ESCAPE:
                    # 按下 ESC 退出 POC。
                    running = False
                elif event.type == KEYDOWN and event.key == K_1:
                    # 按下 1：播放下一个预设动作。
                    motion_index += 1
                    if motion_index >= TOTAL_MOTIONS:
                        # 全部播完，自动退出。
                        LOGGER.info("全部 %s 个动作已播放完毕，关闭窗口", TOTAL_MOTIONS)
                        running = False
                    else:
                        _play_current_motion(model, motion_index)
                elif event.type == KEYDOWN and event.key == K_2:
                    # 按下 2：按序切换到下一个表情，到末尾后循环回到第一个。
                    if expression_ids:
                        selected = expression_ids[expression_index]
                        model.SetExpression(selected)
                        LOGGER.info(
                            "表情 %s/%s：%s",
                            expression_index + 1,
                            len(expression_ids),
                            selected,
                        )
                        expression_index = (expression_index + 1) % len(expression_ids)
                    else:
                        LOGGER.warning("没有可用的表情")
                elif event.type == KEYDOWN and event.key == K_3:
                    # 按下 3：播放 Idle 动作，验证待机动作循环。
                    model.StartRandomMotion("Idle", live2d.MotionPriority.NORMAL)
                elif event.type == KEYDOWN and event.key == K_4:
                    # 按下 4：播放 Tap 动作，验证较强的交互动作表现。
                    model.StartRandomMotion("Tap", live2d.MotionPriority.NORMAL)
                elif event.type == MOUSEBUTTONUP and event.button == 1:
                    # 松开左键，结束窗口拖动。
                    dragging = False
                elif event.type == MOUSEMOTION and dragging and event.buttons[0]:
                    # 拖动过程中同步移动无边框窗口。
                    cursor_x, cursor_y = _get_cursor_position()
                    delta_x = cursor_x - drag_cursor_origin[0]
                    delta_y = cursor_y - drag_cursor_origin[1]
                    _move_window(hwnd, drag_window_origin[0] + delta_x, drag_window_origin[1] + delta_y)

            # 更新模型（动作、眨眼、呼吸等），但不覆盖正在播放的动作参数。
            model.Update()

            # 先清空背景，再绘制 Live2D 模型，绿色会被窗口层当作透明色键抠掉。
            live2d.clearBuffer(*TRANSPARENT_CLEAR_RGBA)
            model.Draw()

            if glGetError() != 0:
                # 如果 OpenGL 产生错误，写日志便于后续排查渲染问题。
                LOGGER.warning("OpenGL 渲染过程中检测到错误")

            # 刷新到屏幕。
            pygame.display.flip()
            # 将刷新率限制为 60 FPS，避免空转占满 CPU。
            clock.tick(60)
            tick += 1
    finally:
        # 退出前按顺序释放渲染器、Live2D 上下文和 Pygame 资源。
        # 退出时按顺序释放资源，避免 OpenGL 上下文和 Live2D 状态残留。
        model.DestroyRenderer()
        live2d.glRelease()
        live2d.dispose()
        pygame.quit()


if __name__ == "__main__":
    main()
