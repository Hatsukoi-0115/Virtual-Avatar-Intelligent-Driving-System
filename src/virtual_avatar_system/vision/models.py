from __future__ import annotations
from dataclasses import dataclass

@dataclass(slots=True)
class VisualFeaturePacket:
    timestamp: float = 0.0
    face_detected: bool = False
    head_yaw: float = 0.0
    head_pitch: float = 0.0
    head_roll: float = 0.0
    eye_open_left: float = 1.0
    eye_open_right: float = 1.0
    mouth_open: float = 0.0