# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller Windows 打包配置。

此 spec 面向 PySide6 桌面应用，显式收集 Live2D、MediaPipe、OpenGL、
音频库以及项目模型/配置资源。PySide6、PyTorch、Transformers 等大包
主要交给 PyInstaller 官方 hooks 按实际导入收集，避免把无关模块全部打入包体。
"""

from __future__ import annotations

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None

PROJECT_ROOT = Path(SPECPATH)
APP_NAME = "VirtualAvatarIntelligentDrivingSystem"
ICON_PATH = PROJECT_ROOT / "src" / "virtual_avatar_system" / "ui" / "assets" / "app_icon.ico"


def _append_project_tree(datas: list[tuple[str, str]], source: Path, dest: str) -> None:
    """递归收集项目资源目录，跳过缓存和编译产物。"""
    if not source.exists():
        return

    ignored_parts = {"__pycache__", ".cache"}
    ignored_suffixes = {".pyc", ".pyo"}
    for path in source.rglob("*"):
        if not path.is_file():
            continue
        if ignored_parts.intersection(path.parts):
            continue
        if path.suffix in ignored_suffixes:
            continue
        relative_parent = path.relative_to(source).parent
        target_dir = Path(dest) / relative_parent
        datas.append((str(path), target_dir.as_posix()))


def _append_project_file(datas: list[tuple[str, str]], source: Path, dest: str) -> None:
    """收集单个项目资源文件。"""
    if source.exists():
        datas.append((str(source), dest))


def _collect_runtime_package(
    package_name: str,
    datas: list[tuple[str, str]],
    binaries: list[tuple[str, str]],
    hiddenimports: list[str],
) -> None:
    """收集依赖包的动态库、数据文件和隐藏导入。"""
    try:
        package_datas, package_binaries, package_hiddenimports = collect_all(package_name)
    except Exception as exc:  # noqa: BLE001
        print(f"跳过依赖收集 {package_name}: {exc}")
        return

    datas.extend(package_datas)
    binaries.extend(package_binaries)
    hiddenimports.extend(package_hiddenimports)


datas: list[tuple[str, str]] = []
binaries: list[tuple[str, str]] = []
hiddenimports: list[str] = [
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "PySide6.QtSvg",
    "mediapipe.tasks.python.core.base_options",
    "mediapipe.tasks.python.vision",
    "mediapipe.tasks.python.vision.face_landmarker",
    "funasr",
    "funasr.auto",
    "funasr.auto.auto_model",
    "funasr.auto.auto_frontend",
    "funasr.download.download_model_from_hub",
    "modelscope",
    "modelscope.hub.check_model",
    "modelscope.hub.snapshot_download",
    "modelscope.utils.constant",
    "cv2",
    "sounddevice",
    "soundfile",
    "imageio_ffmpeg",
    "sentencepiece",
    "tokenizers",
    "safetensors",
    "torch.testing._internal",
    "torch.testing._internal.optests",
]

for source_dir, target_dir in (
    (PROJECT_ROOT / "configs", "configs"),
    (PROJECT_ROOT / "models", "models"),
    (PROJECT_ROOT / "scripts" / "poc" / "assets", "scripts/poc/assets"),
    (
        PROJECT_ROOT / "src" / "virtual_avatar_system" / "ui" / "assets",
        "src/virtual_avatar_system/ui/assets",
    ),
):
    _append_project_tree(datas, source_dir, target_dir)

_append_project_file(datas, PROJECT_ROOT / ".env.example", ".")
for source_dir, target_dir in (
    (PROJECT_ROOT / ".venv" / "Lib" / "site-packages" / "funasr", "funasr"),
    (PROJECT_ROOT / ".venv" / "Lib" / "site-packages" / "modelscope", "modelscope"),
):
    _append_project_tree(datas, source_dir, target_dir)

hiddenimports.extend(
    collect_submodules(
        "funasr",
        filter=lambda name: not (
            ".test" in name
            or ".tests" in name
            or name.startswith("funasr.bin")
        ),
    )
)

for package in (
    "mediapipe",
    "live2d",
    "pygame",
    "OpenGL",
    "cv2",
    "sounddevice",
    "soundfile",
    "tokenizers",
    "safetensors",
    "huggingface_hub",
    "imageio_ffmpeg",
):
    _collect_runtime_package(package, datas, binaries, hiddenimports)

# 去重保持 PyInstaller 输入稳定，减少重复资源导致的构建噪声。
datas = list(dict.fromkeys(datas))
binaries = list(dict.fromkeys(binaries))
hiddenimports = list(dict.fromkeys(hiddenimports))


a = Analysis(
    ["main.py"],
    pathex=[str(PROJECT_ROOT), str(PROJECT_ROOT / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "pytest",
        "IPython",
        "jupyter",
        "notebook",
        "matplotlib.tests",
        "numpy.tests",
        "PySide6.Qt3DAnimation",
        "PySide6.Qt3DCore",
        "PySide6.Qt3DExtras",
        "PySide6.Qt3DInput",
        "PySide6.Qt3DLogic",
        "PySide6.Qt3DRender",
        "PySide6.QtBluetooth",
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.QtQuickWidgets",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICON_PATH),
    contents_directory=".",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=APP_NAME,
)
