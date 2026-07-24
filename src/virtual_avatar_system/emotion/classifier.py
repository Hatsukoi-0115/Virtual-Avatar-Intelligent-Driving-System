"""Hugging Face 情绪分类器接入。"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import torch

from virtual_avatar_system.emotion.types import EmotionResult

LOGGER = logging.getLogger(__name__)
PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
DEFAULT_MODEL_PATH: Final[Path] = PROJECT_ROOT / "models" / "hf_cache" / "Johnson8187__Chinese-Emotion-Small"

LABEL_MAPPING: Final[dict[int, str]] = {
    0: "平静",
    1: "关切",
    2: "开心",
    3: "愤怒",
    4: "难过",
    5: "疑问",
    6: "惊讶",
    7: "厌恶",
}

# 情绪标签到 Live2D 表情 ID 的映射
# 表情文件：Angry / Blushing / f01 / f02 / Normal / Sad / Smile / Surprised
# 对应关系（按分类器索引）：0→Normal 1→Blushing 2→Smile 3→Angry 4→Sad 5/6→Surprised 7→f02
EMOTION_TO_EXPRESSION: Final[dict[str, str]] = {
    "平静": "Normal",
    "关切": "Blushing",
    "开心": "Smile",
    "愤怒": "Angry",
    "难过": "Sad",
    "疑问": "Surprised",
    "惊讶": "Surprised",
    "厌恶": "f02",
}


def emotion_to_expression(label: str) -> str:
    """把情绪标签转换为 Live2D 表情 ID，未知标签回退为 Normal。"""
    return EMOTION_TO_EXPRESSION.get(label, "Normal")


RULE_KEYWORDS: Final[dict[str, tuple[str, ...]]] = {
    "开心": ("开心", "太好了", "棒", "哈哈", "喜欢", "完成了"),
    "愤怒": ("生气", "过分", "讨厌", "受不了", "不对", "气死"),
    "难过": ("难过", "伤心", "心痛", "失落", "哭"),
    "疑问": ("吗", "呢", "为什么", "怎么办", "真的假的"),
    "惊讶": ("天哪", "不可思议", "惊", "居然", "什么情况"),
}


@dataclass(slots=True)
class EmotionClassifierConfig:
    """情绪分类器配置。"""

    model_path: str = str(DEFAULT_MODEL_PATH)
    local_files_only: bool = True
    fallback_to_rules: bool = True


class EmotionClassifier:
    """优先使用本地 Hugging Face 模型，缺失时回退到规则分类。"""

    def __init__(self, config: EmotionClassifierConfig | None = None) -> None:
        self.config = config or EmotionClassifierConfig()
        self._tokenizer: Any | None = None
        self._model: Any | None = None
        self._device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    def load(self) -> None:
        """加载本地情绪分类模型。"""
        if self._model is not None and self._tokenizer is not None:
            return

        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        model_path = Path(self.config.model_path)
        if self.config.local_files_only and not model_path.exists():
            raise FileNotFoundError(f"未找到本地情绪模型：{model_path}")

        LOGGER.info("加载情绪分类模型：%s", model_path)
        self._tokenizer = AutoTokenizer.from_pretrained(str(model_path), local_files_only=self.config.local_files_only)
        self._model = AutoModelForSequenceClassification.from_pretrained(
            str(model_path),
            local_files_only=self.config.local_files_only,
        ).to(self._device)
        self._model.eval()

    def classify(self, text: str) -> EmotionResult:
        """输出情绪标签和置信度。"""
        timestamp = time.time()
        normalized = text.strip()
        if not normalized:
            return EmotionResult(label="平静", confidence=0.0, source="empty", timestamp=timestamp)

        try:
            self.load()
            return self._classify_with_model(normalized, timestamp)
        except Exception as exc:  # noqa: BLE001
            if not self.config.fallback_to_rules:
                raise
            LOGGER.warning("情绪模型不可用，使用规则回退：%s", exc)
            return self._classify_with_rules(normalized, timestamp)

    def _classify_with_model(self, text: str, timestamp: float) -> EmotionResult:
        """使用 Hugging Face 模型分类。"""
        assert self._tokenizer is not None
        assert self._model is not None

        inputs = self._tokenizer(text, return_tensors="pt", truncation=True, padding=True).to(self._device)
        with torch.no_grad():
            outputs = self._model(**inputs)

        probabilities = torch.softmax(outputs.logits, dim=-1)[0]
        confidence, predicted = torch.max(probabilities, dim=0)
        raw_index = int(predicted.item())
        label = LABEL_MAPPING.get(raw_index, "平静")
        return EmotionResult(
            label=label,
            confidence=float(confidence.item()),
            source="hf-transformers",
            timestamp=timestamp,
            raw_label=str(raw_index),
        )

    @staticmethod
    def _classify_with_rules(text: str, timestamp: float) -> EmotionResult:
        """轻量规则回退，保证没有模型时仍能输出结构化结果。"""
        for label, keywords in RULE_KEYWORDS.items():
            if any(keyword in text for keyword in keywords):
                return EmotionResult(label=label, confidence=0.55, source="rule-fallback", timestamp=timestamp)
        return EmotionResult(label="平静", confidence=0.4, source="rule-fallback", timestamp=timestamp)


def main() -> None:
    """允许模块独立运行，方便调试中文情绪分类。"""
    import argparse

    parser = argparse.ArgumentParser(description="中文情绪分类调试")
    parser.add_argument("text", nargs="+", help="要分类的文本")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    classifier = EmotionClassifier()
    result = classifier.classify(" ".join(args.text))
    print(
        f"标签={result.label} 置信度={result.confidence:.2f} 来源={result.source} 原始标签={result.raw_label}",
        flush=True,
    )


if __name__ == "__main__":
    main()
