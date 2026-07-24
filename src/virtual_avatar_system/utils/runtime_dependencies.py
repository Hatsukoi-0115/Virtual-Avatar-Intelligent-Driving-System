"""运行时外部依赖补齐。"""

from __future__ import annotations

import logging
import os
from pathlib import Path

LOGGER = logging.getLogger(__name__)


def ensure_ffmpeg_on_path() -> str:
    """把项目依赖提供的 ffmpeg 加入当前进程 PATH。

    Windows 用户可能没有全局安装 ffmpeg。项目依赖 imageio-ffmpeg 会携带一个
    可执行文件，这里在运行期注入 PATH，供 torchaudio / FunASR 自动发现。
    """
    try:
        import imageio_ffmpeg

        ffmpeg_path = Path(imageio_ffmpeg.get_ffmpeg_exe()).resolve()
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("无法定位 imageio-ffmpeg 提供的 ffmpeg：%s", exc)
        return ""

    ffmpeg_dir = str(ffmpeg_path.parent)
    current_path = os.environ.get("PATH", "")
    path_parts = current_path.split(os.pathsep) if current_path else []
    if ffmpeg_dir not in path_parts:
        os.environ["PATH"] = ffmpeg_dir + os.pathsep + current_path
        LOGGER.info("已将 ffmpeg 加入运行时 PATH：%s", ffmpeg_path)

    # torchaudio 同时会尊重 FFMPEG_BINARY，设置它可让依赖定位更稳定。
    os.environ.setdefault("FFMPEG_BINARY", str(ffmpeg_path))
    return str(ffmpeg_path)
