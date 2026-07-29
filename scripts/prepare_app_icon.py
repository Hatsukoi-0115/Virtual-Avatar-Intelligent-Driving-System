"""准备 Windows 桌面应用图标。

职责：
- 检查项目内的 PNG 图标资源
- 生成 PyInstaller 和 Windows shell 需要的多尺寸 ICO 文件
"""

from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image

LOGGER = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[1]
ASSETS_DIR = PROJECT_ROOT / "src" / "virtual_avatar_system" / "ui" / "assets"
ICON_PNG = ASSETS_DIR / "app_icon.png"
ICON_ICO = ASSETS_DIR / "app_icon.ico"
ICON_SIZES = (
    (16, 16),
    (24, 24),
    (32, 32),
    (48, 48),
    (64, 64),
    (128, 128),
    (256, 256),
)


def prepare_icon() -> Path:
    """从 PNG 生成包含多分辨率的 ICO 图标。"""
    if not ICON_PNG.exists():
        raise FileNotFoundError(f"未找到 PNG 图标资源：{ICON_PNG}")

    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    with Image.open(ICON_PNG) as image:
        # Windows 图标需要 RGBA 通道，否则透明背景会被错误填充。
        image.convert("RGBA").save(ICON_ICO, sizes=list(ICON_SIZES))
    LOGGER.info("已生成桌面图标：%s", ICON_ICO)
    return ICON_ICO


def main() -> None:
    """命令行入口。"""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
    prepare_icon()


if __name__ == "__main__":
    main()
