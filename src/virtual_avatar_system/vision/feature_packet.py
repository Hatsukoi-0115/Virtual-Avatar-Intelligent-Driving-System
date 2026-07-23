"""视觉特征数据结构定义。

供视觉链路产出，供 Avatar Controller 消费。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class VisualFeaturePacket:
    """视觉特征输出包。

    每条包对应一帧的推理结果。
    只包含归一化后的特征值，不包含原始图像数据。
    """

    # ---- 时间信息 ----
    timestamp: float = 0.0
    """采集时刻的 perf_counter 时间戳"""

    # ---- 人脸检测 ----
    face_detected: bool = False
    """当前帧是否检测到人脸"""

    # ---- 头部姿态（归一化值，范围约 -1 到 1） ----
    head_yaw: float = 0.0
    """偏航角近似，-1=左转 +1=右转"""

    head_pitch: float = 0.0
    """俯仰角近似，-1=低头 +1=抬头"""

    head_roll: float = 0.0
    """翻滚角近似，-1=左倾 +1=右倾"""

    # ---- 眼部（范围 0=闭合 1=正常睁开） ----
    eye_open_left: float = 1.0
    eye_open_right: float = 1.0

    # ---- 嘴部（0=闭合，值越大嘴张得越大） ----
    mouth_open: float = 0.0

    # ---- 统计信息 ----
    frame_index: int = 0
    """自启动以来的累计帧序号"""

    inference_ms: float = 0.0
    """本帧 MediaPipe 推理耗时（毫秒）"""
