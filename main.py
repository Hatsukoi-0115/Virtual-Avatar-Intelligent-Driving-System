"""Live2D 多模态虚拟形象驱动系统 — 应用入口。

职责：
- 初始化 QApplication
- 加载配置
- 创建主窗口、系统托盘
- 连接开始/停止事件（后续接入 Avatar Controller）
- 启动事件循环
"""

from __future__ import annotations

import logging
import random
import signal
import sys
import time
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

# 确保 src 目录在 Python 搜索路径中
PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from virtual_avatar_system.utils.runtime_dependencies import ensure_ffmpeg_on_path

ensure_ffmpeg_on_path()

from virtual_avatar_system.config.app_config import load_config, resolve_project_path, save_config, get_model_path
from virtual_avatar_system.controller.avatar_controller import AvatarController, AvatarInputState
from virtual_avatar_system.audio.live_speech_service import (
    LiveSpeechServiceConfig,
    LiveSpeechUnderstandingService,
)
from virtual_avatar_system.ui.main_window import MainWindow
from virtual_avatar_system.ui.system_tray import AppSystemTray
from virtual_avatar_system.renderer.live2d_renderer import Live2DRenderer
from virtual_avatar_system.vision.camera_source import CameraFrameSource
from virtual_avatar_system.vision.face_inference import FaceLandmarkInferencer
from virtual_avatar_system.llm.semantic import get_idle_labels
from virtual_avatar_system.reporting.live_event_recorder import LiveEventRecorder
from virtual_avatar_system.reporting.live_report_generator import (
    build_live_report_summary,
    build_suggested_reply,
    save_live_report,
)


class UiLogHandler(logging.Handler):
    """将 logging 输出安全转发到 Qt 后端输出面板。"""

    def __init__(self, append_log: Callable[[str], None]) -> None:
        super().__init__()
        self._append_log = append_log

    def emit(self, record: logging.LogRecord) -> None:
        """格式化日志记录并投递到 UI 线程安全入口。"""
        try:
            self._append_log(self.format(record))
        except Exception:  # noqa: BLE001
            self.handleError(record)


def _configure_logging() -> None:
    """配置全局日志输出。"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


def _attach_ui_log_handler(main_window: MainWindow) -> UiLogHandler:
    """把后端日志流接入主窗口日志面板。"""
    handler = UiLogHandler(main_window.append_backend_log)
    handler.setLevel(logging.INFO)
    handler.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    )
    logging.getLogger().addHandler(handler)
    return handler


def _flush_ui_events() -> None:
    """立即处理 UI 事件，让启动阶段文本在重资源加载前先显示出来。"""
    app = QApplication.instance()
    if app is not None:
        app.processEvents()


def main() -> None:
    """启动桌面应用骨架。"""
    _configure_logging()
    logger = logging.getLogger(__name__)

    # ---- Qt 应用初始化 ----
    app = QApplication(sys.argv)
    app.setApplicationName("Virtual Avatar Intelligent Driving System")
    app.setOrganizationName("VAIDS")

    # ---- 加载配置 ----
    config = load_config()
    speech_service: LiveSpeechUnderstandingService | None = None

    # ---- 创建窗口 ----
    main_window = MainWindow(config)
    ui_log_handler = _attach_ui_log_handler(main_window)
    logger.info("后端输出日志面板已连接")
    main_window.show()

    # ---- 系统托盘 ----
    tray = AppSystemTray(main_window)
    tray.show()

    main_window.set_system_tray(tray)

    # ---- 融合层与渲染层 ----
    avatar_controller = AvatarController(model_name=config.model_name)
    live2d_renderer = Live2DRenderer()
    event_recorder = LiveEventRecorder()

    def _on_audience_comment(comment: str, semantic_label: str, suggested_reply: str) -> None:
        """观众评论回调：沉淀评论内容、语义标签和推荐回复。"""
        event_recorder.record_audience_comment(comment, semantic_label, suggested_reply)

    main_window.on_audience_comment(_on_audience_comment)

    # 当前情绪表情 ID，由语音链路回调更新，供视觉桥接定时器带入 AvatarInputState
    latest_expression = "Normal"
    # 当前动作标签，由 LLM 语义回调更新
    latest_motion_label = ""

    def _on_asr_text(text: str) -> None:
        """ASR 文本回调：刷新直播状态页的最近识别文本。"""
        main_window.update_asr_text(text)
        event_recorder.record_asr_text(text)

    def _on_emotion(expression_id: str, confidence: float, emotion_label: str) -> None:
        """语音情绪分类回调：更新当前表情，下一帧渲染时生效。"""
        nonlocal latest_expression
        if expression_id != latest_expression:
            logger.info("表情切换：%s → %s（置信度 %.2f）", latest_expression, expression_id, confidence)
        latest_expression = expression_id
        main_window.update_emotion_result(emotion_label)
        event_recorder.record_emotion(emotion_label)

    def _on_semantic(label: str, confidence: float, summary: str) -> None:
        """LLM 语义理解回调：更新当前动作标签，下一帧渲染时生效。"""
        nonlocal latest_motion_label
        # 待机动作不由 LLM 触发，仅用于面部丢失时随机选择
        if label in _idle_labels:
            return
        if label != latest_motion_label:
            logger.info("动作标签：%s（置信度 %.2f，摘要：%s）", label, confidence, summary)
            latest_motion_label = label
            main_window.update_semantic_label(summary or label)
            main_window.update_current_action(label)
            suggested_reply = build_suggested_reply(event_recorder.record.snapshot.asr_text, summary or label)
            event_recorder.record_semantic(summary or label, suggested_reply)
            event_recorder.record_motion(label)
            avatar_controller.set_motion_from_label(label)

    # ---- 视觉链路：摄像头采集 + MediaPipe 推理 ----
    # 摄像头采集器在点击“开始直播”时按最新配置创建，确保开播前修改参数立即生效。
    camera_source: CameraFrameSource | None = None
    inferencer = FaceLandmarkInferencer()

    # 桥接定时器：摄像头帧 → 推理器
    feed_timer = QTimer()
    feed_timer.setInterval(16)

    def _feed_frames() -> None:
        if camera_source is None:
            return
        for frame_packet in camera_source.pop_frames():
            if frame_packet.bgr_data:
                inferencer.feed_frame(
                    frame_packet.bgr_data,
                    frame_packet.width,
                    frame_packet.height,
                )

    feed_timer.timeout.connect(_feed_frames)

    # 桥接定时器：推理结果 → Avatar Controller → Live2D 渲染
    consume_timer = QTimer()
    consume_timer.setInterval(16)
    # 面部丢失触发 Idle 动作的冷却时间（秒）
    _IDLE_COOLDOWN = 3.0
    _last_idle_trigger_time = 0.0
    _face_was_detected = False
    _idle_labels = get_idle_labels(config.model_name)

    def _consume_features() -> None:
        nonlocal latest_expression, _face_was_detected, _last_idle_trigger_time
        packets = inferencer.pop_features()
        if not packets:
            return
        latest = packets[-1]
        # 面部丢失时触发随机 Idle 待机动作（冷却时间内不重复触发）
        now = time.monotonic()
        if _face_was_detected and not latest.face_detected and (now - _last_idle_trigger_time) >= _IDLE_COOLDOWN:
            _last_idle_trigger_time = now
            idle_label = random.choice(_idle_labels)
            logger.info("面部丢失，触发随机 Idle 动作：%s", idle_label)
            main_window.update_current_action(idle_label)
            event_recorder.record_motion(idle_label)
            avatar_controller.set_motion_from_label(idle_label)
        _face_was_detected = latest.face_detected
        main_window.update_face_detection_status("检测到人脸" if latest.face_detected else "未检测到人脸")
        # 更新视觉特征和表情，保留动作信息
        avatar_controller._input.visual = latest
        avatar_controller._input.expression = latest_expression
        avatar_controller._input.timestamp = latest.timestamp
        
        avatar_output = avatar_controller.resolve()
        live2d_renderer.submit_state(avatar_output)
        # 视觉链路仍持续运行并驱动 Live2D；终端默认不输出视觉推理结果。
        # 后续调试视觉链路时，可在这里临时打开 logger.debug / logger.info。

    consume_timer.timeout.connect(_consume_features)

    def _shutdown_runtime(stage_callback: Callable[[str], None] | None = None) -> None:
        """停止视觉采集、推理和渲染链路。"""
        nonlocal camera_source
        if stage_callback is not None:
            stage_callback("正在停止视觉桥接定时器...")
        feed_timer.stop()
        consume_timer.stop()
        if stage_callback is not None:
            stage_callback("正在关闭人脸推理...")
        inferencer.stop()
        if camera_source is not None:
            if stage_callback is not None:
                stage_callback("正在关闭摄像头...")
            camera_source.stop()
            camera_source = None
        if stage_callback is not None:
            stage_callback("正在关闭人物模型...")
        live2d_renderer.stop()

    # ---- 语音、情绪与 LLM 链路 ----
    def _shutdown_speech(stage_callback: Callable[[str], None] | None = None) -> None:
        """停止 C 链路并释放麦克风与 FunASR 资源。"""
        nonlocal speech_service
        if speech_service is not None:
            if stage_callback is not None:
                stage_callback("正在关闭麦克风和语音识别...")
            speech_service.stop()
            speech_service = None

    # ---- 开始 / 停止事件：B 视觉 + C 语音/情绪/LLM + D 渲染 ----
    def on_start() -> None:
        """开始直播时的回调。

        当前已接入：
        - 摄像头采集线程
        - MediaPipe 视觉推理线程
        - Avatar Controller 与 Live2D 渲染进程
        - 麦克风采集线程
        - FunASR 流式识别
        - 中文分词后的情绪分类
        - 自然句结束后的 LLM 标签匹配
        """
        nonlocal speech_service, camera_source
        logger.info("开始直播：启动视觉、渲染、语音/情绪/LLM 链路")
        event_recorder.start_session()
        main_window.reset_live_dashboard()
        main_window.update_startup_stage("准备启动")
        main_window.update_camera_connection_status("连接中")
        main_window.update_face_detection_status("等待检测")
        main_window.update_microphone_connection_status("连接中")
        main_window.update_microphone_listening_status("等待监听")
        _flush_ui_events()
        try:
            current_config = main_window.config
            main_window.update_startup_stage("创建摄像头采集器")
            _flush_ui_events()
            camera_source = CameraFrameSource(
                camera_index=current_config.camera_index,
                width=current_config.camera_width,
                height=current_config.camera_height,
                fps=current_config.camera_fps,
            )
            logger.info(
                "使用摄像头配置：camera=%s %sx%s@%sfps",
                current_config.camera_index,
                current_config.camera_width,
                current_config.camera_height,
                current_config.camera_fps,
            )
            # Live2D 窗口使用配置中的紧凑尺寸，减少透明窗口对其他应用的遮挡。
            main_window.update_startup_stage("正在加载模型和渲染人物...")
            _flush_ui_events()
            live2d_renderer.start(
                resolve_project_path(get_model_path(main_window.config)),
                window_size=(current_config.preview_width, current_config.preview_height),
                always_on_top=current_config.preview_always_on_top,
            )
            main_window.update_startup_stage("正在加载模型和渲染人物...")
            _flush_ui_events()
            render_ready_deadline = time.monotonic() + 15.0
            while not live2d_renderer.is_ready:
                # 等待子进程完成第一帧绘制，让主窗口在人物即将出现后再切到运行页。
                if not live2d_renderer.is_running:
                    raise RuntimeError("Live2D 渲染进程异常退出")
                if time.monotonic() >= render_ready_deadline:
                    logger.warning("等待 Live2D 第一帧渲染超时，继续启动后续链路")
                    main_window.update_startup_stage("人物渲染较慢，继续启动直播")
                    break
                _flush_ui_events()
                time.sleep(0.05)
            if live2d_renderer.is_ready:
                main_window.update_startup_stage("人物已渲染")
                _flush_ui_events()
            main_window.update_startup_stage("打开摄像头")
            _flush_ui_events()
            camera_source.start()
            main_window.update_camera_connection_status("已连接")
            main_window.update_face_detection_status("检测中")
            main_window.update_startup_stage("启动 MediaPipe 人脸推理")
            _flush_ui_events()
            inferencer.start()
            main_window.update_startup_stage("启动视觉桥接定时器")
            _flush_ui_events()
            feed_timer.start()
            consume_timer.start()
            main_window.update_startup_stage("视觉链路已就绪")
            _flush_ui_events()

            main_window.state_machine.on_ready()
        except Exception as exc:  # noqa: BLE001
            logger.exception("启动视觉/渲染链路失败")
            _shutdown_runtime()
            main_window.state_machine.on_error(str(exc))
            return

        # 语音/情绪/LLM 链路独立启动，失败时不影响视觉驱动
        try:
            if speech_service is None:
                main_window.update_startup_stage("初始化语音/情绪/LLM 服务")
                _flush_ui_events()
                speech_service = LiveSpeechUnderstandingService(
                    LiveSpeechServiceConfig.from_app_config(main_window.config)
                )
                speech_service.on_asr_text(_on_asr_text)
                speech_service.on_emotion(_on_emotion)
                speech_service.on_semantic(_on_semantic)
            main_window.update_startup_stage("启动麦克风监听")
            _flush_ui_events()
            speech_service.start()
            main_window.update_microphone_connection_status("已连接")
            main_window.update_microphone_listening_status("正在监听")
            main_window.update_startup_stage("直播运行中")
        except Exception as exc:  # noqa: BLE001
            logger.warning("语音/情绪/LLM 链路启动失败，仅保留视觉驱动：%s", exc)
            main_window.update_microphone_connection_status("连接失败")
            main_window.update_microphone_listening_status("未监听")
            main_window.update_startup_stage("语音链路启动失败，视觉链路运行中")
            speech_service = None

    def on_stop() -> None:
        """停止直播时的回调。

        当前已接入：
        - 停止视觉采集和推理
        - 停止 Live2D 渲染进程
        - 停止麦克风采集
        - 释放 FunASR 识别器
        - 停止 C 链路后台线程
        """
        logger.info("停止直播：释放视觉、渲染、语音/情绪/LLM 链路")
        def _update_stop_stage(text: str) -> None:
            """刷新停止阶段提示，并立即处理 UI 事件。"""
            main_window.update_startup_stage(text)
            _flush_ui_events()

        _update_stop_stage("正在停止直播...")
        main_window.update_microphone_connection_status("已停止")
        main_window.update_microphone_listening_status("已停止")
        main_window.update_camera_connection_status("已停止")
        main_window.update_face_detection_status("已停止")
        _shutdown_speech(_update_stop_stage)
        _shutdown_runtime(_update_stop_stage)
        session_record = event_recorder.stop_session()
        report_path = save_live_report(session_record, PROJECT_ROOT / "reports")
        report_summary = build_live_report_summary(session_record, report_path)
        logger.info(
            "直播事件记录已完成：时长 %.1f 秒，事件数 %d，报告：%s",
            session_record.duration_seconds,
            len(session_record.events),
            report_path,
        )
        _update_stop_stage("直播已停止")
        main_window.state_machine.on_stopped()
        main_window.show_live_report_summary(report_summary)

    main_window.on_start(on_start)
    main_window.on_stop(on_stop)

    # ---- 统一退出入口 ----
    def _quit_application() -> None:
        """统一退出函数，供关闭按钮、Ctrl+C、托盘菜单复用。"""
        logger.info("开始执行退出流程…")
        logging.getLogger().removeHandler(ui_log_handler)
        _shutdown_speech()
        _shutdown_runtime()
        save_config(main_window.config)
        main_window.close()
        app.quit()

    # 托盘退出只执行统一退出流程
    tray.on_quit(_quit_application)

    # ---- 注册 Ctrl+C / SIGTERM 信号处理 ----
    def _handle_sigint(signum, frame) -> None:
        """收到 SIGINT (Ctrl+C) 时安全退出事件循环。"""
        logger.info("收到 Ctrl+C，正在退出…")
        _quit_application()

    signal.signal(signal.SIGINT, _handle_sigint)
    signal.signal(signal.SIGTERM, _handle_sigint)

    # ---- 让 Qt 事件循环周期性处理信号 ----
    sigint_pump = QTimer()
    sigint_pump.setInterval(100)
    sigint_pump.timeout.connect(lambda: None)
    sigint_pump.start()

    # ---- 进入事件循环 ----
    exit_code = app.exec()
    logger.info("应用已退出")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
