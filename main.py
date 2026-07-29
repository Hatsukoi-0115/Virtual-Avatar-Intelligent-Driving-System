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
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

# 确保 src 目录在 Python 搜索路径中
PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

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


class StartupSplash(QWidget):
    """应用启动小窗口，用于 exe 启动阶段给用户明确反馈。"""

    def __init__(self) -> None:
        super().__init__()
        # 进度条使用千分制，避免百分制每次推进一大格造成“跳段”观感。
        self._progress_value = 80
        self._progress_target = 180
        self._progress_ceiling = 240
        self._slow_progress_ticks = 0
        self.setWindowTitle("虚拟形象智能驱动系统")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(460, 210)
        self._setup_ui()
        self._setup_progress_timer()
        self._center_on_screen()

    def update_stage(
        self,
        text: str,
        progress: int | None = None,
        ceiling: int | None = None,
    ) -> None:
        """更新启动阶段提示并立即刷新界面。"""
        self._stage_label.setText(text)
        if progress is not None:
            target = min(progress, 98) * 10
            ceiling_value = min(ceiling if ceiling is not None else progress + 8, 98) * 10
            self._progress_target = max(self._progress_value, target)
            # 当前阶段设置一个缓冲上限，耗时导入期间进度条会慢慢推进但不会提前跑满。
            self._progress_ceiling = max(
                self._progress_target,
                ceiling_value,
            )
            self._slow_progress_ticks = 0
        self._advance_progress()
        _flush_ui_events()

    def _setup_ui(self) -> None:
        """构建启动小窗口界面。"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(0)

        card = QFrame(self)
        card.setObjectName("startupCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(24, 22, 24, 20)
        card_layout.setSpacing(14)

        shadow = QGraphicsDropShadowEffect(card)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(15, 23, 42, 48))
        card.setGraphicsEffect(shadow)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(12)

        badge = QLabel("VA", self)
        badge.setObjectName("startupBadge")
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setFixedSize(44, 44)
        header_row.addWidget(badge)

        title_group = QVBoxLayout()
        title_group.setContentsMargins(0, 0, 0, 0)
        title_group.setSpacing(3)

        title = QLabel("虚拟形象智能驱动系统", self)
        title.setObjectName("startupTitle")
        title_group.addWidget(title)

        subtitle = QLabel("Virtual Avatar Intelligent Driving System", self)
        subtitle.setObjectName("startupSubtitle")
        title_group.addWidget(subtitle)
        header_row.addLayout(title_group, stretch=1)
        card_layout.addLayout(header_row)

        status_box = QFrame(self)
        status_box.setObjectName("startupStatusBox")
        status_layout = QVBoxLayout(status_box)
        status_layout.setContentsMargins(14, 11, 14, 12)
        status_layout.setSpacing(8)

        self._stage_label = QLabel("正在启动虚拟形象智能驱动系统...", self)
        self._stage_label.setObjectName("startupStage")
        self._stage_label.setWordWrap(True)
        status_layout.addWidget(self._stage_label)

        self._progress_bar = QProgressBar(self)
        self._progress_bar.setObjectName("startupProgress")
        self._progress_bar.setRange(0, 1000)
        self._progress_bar.setValue(self._progress_value)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setFixedHeight(6)
        status_layout.addWidget(self._progress_bar)
        card_layout.addWidget(status_box)

        hint = QLabel("请稍候，正在准备桌面运行环境", self)
        hint.setObjectName("startupHint")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(hint)

        layout.addWidget(card)

        self.setStyleSheet(
            """
            QFrame#startupCard {
                background: #FFFFFF;
                border: 1px solid #DCE7F3;
                border-radius: 14px;
            }
            QLabel#startupBadge {
                background: #EFF6FF;
                border: 1px solid #BFDBFE;
                border-radius: 10px;
                color: #2563EB;
                font-size: 16px;
                font-weight: 800;
            }
            QFrame#startupStatusBox {
                background: #F8FAFC;
                border: 1px solid #E2E8F0;
                border-radius: 10px;
            }
            QLabel {
                border: 0;
                background: transparent;
            }
            QLabel#startupTitle {
                color: #0F172A;
                font-size: 18px;
                font-weight: 800;
            }
            QLabel#startupSubtitle {
                color: #64748B;
                font-size: 11px;
                font-weight: 600;
            }
            QLabel#startupStage {
                color: #2563EB;
                font-size: 13px;
                font-weight: 700;
            }
            QLabel#startupHint {
                color: #64748B;
                font-size: 12px;
                font-weight: 600;
            }
            QProgressBar#startupProgress {
                background: #E2E8F0;
                border: 0;
                border-radius: 3px;
            }
            QProgressBar#startupProgress::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #2563EB, stop:1 #60A5FA);
                border-radius: 3px;
            }
            """
        )

    def _setup_progress_timer(self) -> None:
        """创建启动进度动画定时器，让进度条在耗时阶段也持续移动。"""
        self._progress_timer = QTimer(self)
        self._progress_timer.setInterval(45)
        self._progress_timer.timeout.connect(self._advance_progress)
        self._progress_timer.start()

    def _advance_progress(self) -> None:
        """把进度值平滑推进到当前阶段目标值。"""
        if self._progress_value < self._progress_target:
            diff = self._progress_target - self._progress_value
            # 逐帧细推到阶段目标，避免直接跳到下一段。
            step = 4 if diff > 80 else 2
            self._progress_value = min(self._progress_value + step, self._progress_target)
        elif self._progress_value < self._progress_ceiling:
            # 重资源加载时主阶段不变，但以较慢节奏继续补间，避免视觉上停住。
            self._slow_progress_ticks += 1
            if self._slow_progress_ticks < 2:
                return
            self._slow_progress_ticks = 0
            self._progress_value += 2
        else:
            return
        self._progress_bar.setValue(self._progress_value)

    def finish_progress(self) -> None:
        """启动完成前补满进度条。"""
        self._progress_target = 1000
        self._progress_value = 1000
        self._progress_bar.setValue(1000)
        self._progress_timer.stop()
        _flush_ui_events()

    def pulse_progress(self) -> None:
        """手动推进一次进度动画，用于后台任务等待期间。"""
        self._advance_progress()
        _flush_ui_events()

    def _center_on_screen(self) -> None:
        """把启动小窗口移动到当前屏幕中央。"""
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        screen_geometry = screen.availableGeometry()
        x = screen_geometry.center().x() - self.width() // 2
        y = screen_geometry.center().y() - self.height() // 2
        self.move(x, y)


def _run_startup_task(
    startup_splash: StartupSplash,
    text: str,
    progress: int,
    ceiling: int,
    task: Callable[[], Any],
) -> Any:
    """在后台执行启动阶段任务，主线程持续刷新启动进度。"""
    startup_splash.update_stage(text, progress, ceiling)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(task)
        while not future.done():
            # 导入 FunASR、音频等重模块时保持启动页流动，降低卡顿感。
            startup_splash.pulse_progress()
            time.sleep(0.045)
        return future.result()


def _hold_startup_stage(startup_splash: StartupSplash, seconds: float = 0.18) -> None:
    """短暂保留启动阶段提示，避免快速阶段在人眼中一闪而过。"""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        startup_splash.pulse_progress()
        time.sleep(0.045)


def main() -> None:
    """启动桌面应用骨架。"""
    _configure_logging()
    logger = logging.getLogger(__name__)

    # ---- Qt 应用初始化 ----
    app = QApplication(sys.argv)
    app.setApplicationName("Virtual Avatar Intelligent Driving System")
    app.setOrganizationName("VAIDS")

    startup_splash = StartupSplash()
    startup_splash.show()
    startup_splash.update_stage("正在启动虚拟形象智能驱动系统...", 12)

    # ---- 延迟导入项目模块，让 exe 启动时尽早显示启动小窗口 ----
    startup_splash.update_stage("正在检查运行环境...", 22, 30)
    from virtual_avatar_system.utils.runtime_dependencies import ensure_ffmpeg_on_path

    ensure_ffmpeg_on_path()

    def _load_speech_modules() -> tuple[type, type]:
        """加载语音识别服务模块，放入后台线程避免启动页静止。"""
        from virtual_avatar_system.audio.live_speech_service import (
            LiveSpeechServiceConfig,
            LiveSpeechUnderstandingService,
        )

        return LiveSpeechServiceConfig, LiveSpeechUnderstandingService

    LiveSpeechServiceConfig, LiveSpeechUnderstandingService = _run_startup_task(
        startup_splash,
        "正在加载语音识别模块...",
        32,
        80,
        _load_speech_modules,
    )

    startup_splash.update_stage("正在加载配置系统...", 81, 82)
    from virtual_avatar_system.config.app_config import (
        get_model_path,
        load_config,
        load_param_mappings,
        resolve_project_path,
        save_config,
    )

    startup_splash.update_stage("正在加载虚拟形象控制器...", 83, 84)
    from virtual_avatar_system.controller.avatar_controller import AvatarController, AvatarInputState

    startup_splash.update_stage("正在加载 LLM 语义模块...", 85, 86)
    from virtual_avatar_system.llm.semantic import get_idle_labels

    startup_splash.update_stage("正在加载 Live2D 渲染模块...", 87, 88)
    from virtual_avatar_system.renderer.live2d_renderer import Live2DRenderer

    startup_splash.update_stage("正在加载直播报告模块...", 89, 90)
    from virtual_avatar_system.reporting.live_event_recorder import LiveEventRecorder
    from virtual_avatar_system.reporting.live_report_generator import (
        build_live_report_summary,
        build_suggested_reply,
        save_live_report,
    )

    startup_splash.update_stage("正在加载主窗口界面...", 91, 93)
    from virtual_avatar_system.ui.main_window import MainWindow
    from virtual_avatar_system.ui.system_tray import AppSystemTray

    startup_splash.update_stage("正在加载摄像头与人脸检测模块...", 94, 95)
    from virtual_avatar_system.vision.camera_source import CameraFrameSource
    from virtual_avatar_system.vision.face_inference import FaceLandmarkInferencer

    # ---- 加载配置 ----
    startup_splash.update_stage("正在读取本地配置...", 95, 95)
    config = load_config()
    speech_service: LiveSpeechUnderstandingService | None = None

    # ---- 创建窗口 ----
    startup_splash.update_stage("正在初始化主窗口...", 96, 96)
    main_window = MainWindow(config)
    startup_splash.update_stage("正在接入后端日志...", 97, 97)
    ui_log_handler = _attach_ui_log_handler(main_window)
    logger.info("后端输出日志面板已连接")

    # ---- 系统托盘 ----
    startup_splash.update_stage("正在初始化系统托盘...", 97, 98)
    tray = AppSystemTray(main_window)
    tray.show()

    main_window.set_system_tray(tray)

    # ---- 融合层与渲染层 ----
    startup_splash.update_stage("正在准备运行控制器...", 97, 98)
    _hold_startup_stage(startup_splash, 0.2)
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
    # 标记当前是否处于待机状态（面部丢失后已触发 Idle 动作）
    _in_idle_state = False
    _idle_labels = get_idle_labels(config.model_name)

    def _consume_features() -> None:
        nonlocal latest_expression, _face_was_detected, _last_idle_trigger_time, _in_idle_state
        packets = inferencer.pop_features()
        if not packets:
            return
        latest = packets[-1]
        # 人脸重新检测到：打断待机动作，恢复实时驱动
        if _in_idle_state and latest.face_detected:
            _in_idle_state = False
            avatar_controller._input.interrupt_motion = True
            avatar_controller._input.motion_group = ""
            avatar_controller._input.motion_index = 0
            logger.info("人脸重新检测到，打断待机动作，恢复实时驱动")
            main_window.update_current_action("实时驱动")

        # 面部丢失时触发随机 Idle 待机动作（冷却时间内不重复触发）
        now = time.monotonic()
        if _face_was_detected and not latest.face_detected and (now - _last_idle_trigger_time) >= _IDLE_COOLDOWN and not _in_idle_state:
            _last_idle_trigger_time = now
            _in_idle_state = True
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

    def _shutdown_runtime(
        stage_callback: Callable[[str], None] | None = None,
        progress_callback: Callable[[], None] | None = None,
    ) -> None:
        """停止视觉采集、推理和渲染链路。"""
        nonlocal camera_source
        if stage_callback is not None:
            stage_callback("正在停止视觉桥接定时器...")
        feed_timer.stop()
        consume_timer.stop()
        if stage_callback is not None:
            stage_callback("正在关闭人脸推理...")
        inferencer.stop(progress_callback)
        if camera_source is not None:
            if stage_callback is not None:
                stage_callback("正在关闭摄像头...")
            camera_source.stop(progress_callback)
            camera_source = None
        if stage_callback is not None:
            stage_callback("正在关闭人物模型...")
        live2d_renderer.stop(progress_callback)

    # ---- 语音、情绪与 LLM 链路 ----
    def _shutdown_speech(
        stage_callback: Callable[[str], None] | None = None,
        progress_callback: Callable[[], None] | None = None,
    ) -> None:
        """停止 C 链路并释放麦克风与 FunASR 资源。"""
        nonlocal speech_service
        if speech_service is not None:
            if stage_callback is not None:
                stage_callback("正在关闭麦克风和语音识别...")
            speech_service.stop(progress_callback)
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
            # 加载当前模型的参数 ID 映射表，适配不同命名规范的模型
            param_mappings = load_param_mappings(main_window.config.model_name)
            live2d_renderer.start(
                resolve_project_path(get_model_path(main_window.config)),
                window_size=(current_config.preview_width, current_config.preview_height),
                always_on_top=current_config.preview_always_on_top,
                param_mappings=param_mappings if param_mappings else None,
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
            main_window.update_startup_stage("正在加载语音识别和情绪模型...")
            _flush_ui_events()
            speech_ready = speech_service.wait_until_ready(
                timeout=60.0,
                progress_callback=lambda: (
                    main_window.pulse_loading_animation(),
                    _flush_ui_events(),
                ),
            )
            if not speech_ready:
                error_message = speech_service.startup_error or "语音识别模型加载失败"
                raise RuntimeError(error_message)
            main_window.update_microphone_connection_status("已连接")
            main_window.update_microphone_listening_status("正在监听")
            main_window.update_startup_stage("直播运行中")
            _flush_ui_events()
            # 所有开播必要链路均已就绪后，再切换到直播运行页。
            main_window.state_machine.on_ready()
        except Exception as exc:  # noqa: BLE001
            logger.warning("语音/情绪/LLM 链路启动失败：%s", exc)
            main_window.update_microphone_connection_status("连接失败")
            main_window.update_microphone_listening_status("未监听")
            main_window.update_startup_stage("语音链路启动失败")
            _shutdown_speech()
            _shutdown_runtime()
            main_window.state_machine.on_error(str(exc))
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
        def _pulse_stop_animation() -> None:
            """同步释放资源时强制推进停止页加载图标。"""
            main_window.pulse_loading_animation()

        def _update_stop_stage(text: str) -> None:
            """刷新停止阶段提示，并立即处理 UI 事件。"""
            main_window.update_startup_stage(text)
            main_window.pulse_loading_animation(2)
            _flush_ui_events()

        _update_stop_stage("正在停止直播...")
        main_window.update_microphone_connection_status("已停止")
        main_window.update_microphone_listening_status("已停止")
        main_window.update_camera_connection_status("已停止")
        main_window.update_face_detection_status("已停止")
        _shutdown_speech(_update_stop_stage, _pulse_stop_animation)
        _shutdown_runtime(_update_stop_stage, _pulse_stop_animation)
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

    startup_splash.update_stage("启动完成，正在打开主窗口...", 98)
    _hold_startup_stage(startup_splash, 0.16)
    startup_splash.finish_progress()
    main_window.show()
    startup_splash.close()
    startup_splash.deleteLater()

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
