"""运行路径解析工具。

职责：
- 统一解析源码运行和 PyInstaller 打包运行时的根目录
- 为配置、模型和 UI 资源提供稳定的路径入口
"""

from __future__ import annotations

import sys
from pathlib import Path


def get_runtime_root() -> Path:
    """获取当前应用运行根目录。

    源码运行时返回项目根目录；PyInstaller 打包后返回 exe 所在目录。
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[3]


def resolve_runtime_path(*parts: str) -> Path:
    """把运行根目录下的相对路径拼成绝对路径。"""
    return get_runtime_root().joinpath(*parts)


def get_ui_assets_dir() -> Path:
    """获取 UI 资源目录，兼容源码和打包后的目录布局。"""
    return resolve_runtime_path("src", "virtual_avatar_system", "ui", "assets")


def get_ui_asset_path(filename: str) -> Path:
    """获取单个 UI 资源文件路径。"""
    return get_ui_assets_dir() / filename
