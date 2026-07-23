"""Live2D 渲染封装。

职责：
- 模型加载、重载
- 参数更新
- 表情切换
- 动作播放
- 渲染帧输出
- 不包含任何业务判断
"""

from __future__ import annotations

import logging
from pathlib import Path

import live2d.v3 as live2d

LOGGER = logging.getLogger(__name__)


class Live2DRenderer:
    """Live2D 渲染器最小封装。

    只负责接收参数并调用底层 API，不做融合或决策。
    """

    def __init__(self) -> None:
        self._model: live2d.LAppModel | None = None
        self._expressions: list[str] = []
        self._model_loaded = False

    # ---- 生命周期 ----

    def load_model(self, model_json_path: Path) -> None:
        """加载模型并初始化 Live2D 上下文。"""
        if self._model_loaded:
            LOGGER.warning("模型已加载，跳过重复初始化")
            return

        live2d.init()
        live2d.glInit()

        self._model = live2d.LAppModel()
        self._model.LoadModelJson(str(model_json_path))
        self._model.SetAutoBlinkEnable(True)
        self._model.SetAutoBreathEnable(True)

        # 加载表情文件
        expressions_dir = model_json_path.parent / "expressions"
        for exp_file in sorted(expressions_dir.glob("*.exp3.json")):
            exp_id = exp_file.stem.replace(".exp3", "")
            self._model.LoadExtraExpression(exp_id, str(exp_file))
            self._expressions.append(exp_id)
            LOGGER.info("已加载表情：%s", exp_id)

        self._model_loaded = True
        LOGGER.info("Live2D 模型已加载：%s", model_json_path.name)

    def release(self) -> None:
        """释放模型和 Live2D 上下文。"""
        if self._model:
            self._model.DestroyRenderer()
        live2d.glRelease()
        live2d.dispose()
        self._model_loaded = False

    @property
    def model(self) -> live2d.LAppModel | None:
        """获取底层模型对象，供渲染循环直接使用。"""
        return self._model

    @property
    def expressions(self) -> list[str]:
        """已加载的表情列表。"""
        return self._expressions

    # ---- 渲染 ----

    def resize(self, width: int, height: int) -> None:
        """更新渲染视口尺寸。"""
        if self._model:
            self._model.Resize(width, height)

    def update(self) -> None:
        """更新模型（眨眼、呼吸等自动行为）。"""
        if self._model:
            self._model.Update()

    def draw(self) -> None:
        """绘制一帧。"""
        if self._model:
            self._model.Draw()

    # ---- 参数更新 ----

    def set_parameter(self, param_id: str, value: float) -> None:
        """设置单个模型参数。"""
        if self._model:
            self._model.SetParameterValue(param_id, value)

    def set_parameters(self, params: dict[str, float]) -> None:
        """批量设置模型参数。"""
        if not self._model:
            return
        for param_id, value in params.items():
            self._model.SetParameterValue(param_id, value)

    # ---- 表情 ----

    def set_expression(self, expression_id: str) -> None:
        """切换到指定表情。"""
        if self._model:
            self._model.SetExpression(expression_id)

    # ---- 动作 ----

    def start_motion(self, group: str, index: int, priority: int = 3) -> None:
        """播放指定动作。"""
        if self._model:
            self._model.StartMotion(group, index, priority)
