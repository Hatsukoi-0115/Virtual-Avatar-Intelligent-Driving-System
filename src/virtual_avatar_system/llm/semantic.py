"""低频 LLM 语义理解封装。"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

LOGGER = logging.getLogger(__name__)

MOTION_LABELS: Final[tuple[str, ...]] = (
    "idle_calm",
    "idle_relaxed",
    "idle_curious",
    "flick_bounce",
    "flick_surprise",
    "flick_nod",
    "tap_excited",
    "tap_think",
    "tap_agree",
    "tap_emphasize",
    "tap_cheerful",
    "tap_curious",
    "flick_right_glance",
    "flick_right_talk",
    "flick_right_reply",
    "flick3_double_bounce",
    "flick3_greet",
    "flick3_laugh",
    "flick_left_glance",
    "flick_left_respond",
    "flick_left_talk",
    "shake_deny",
    "shake_surprise",
)

MOTION_DESCRIPTIONS: Final[tuple[str, ...]] = (
    "待机、平静站立",
    "放松、轻微倾斜",
    "好奇、左右观望",
    "点头、认同",
    "摇头、否认",
    "托下巴、思考",
    "不满、强调",
    "双手合十、开心",
    "后仰、惊讶",
    "反问、强调",
    "疑问",
    "害羞、脸红",
    "恶作剧、窃喜",
    "惊喜、身体一震",
    "回复后的默认状态",
    "认同、点头",
    "开心、打招呼",
    "开心、轻笑",
    "垂头、无奈",
    "发表见解、明白",
    "被逗笑",
    "害羞、惊喜、疑惑",
    "激动、兴奋",
)

MOTION_CANDIDATES: Final[str] = "\n".join(
    f"- {label}: {description}"
    for label, description in zip(MOTION_LABELS, MOTION_DESCRIPTIONS, strict=True)
)

SYSTEM_PROMPT: Final[str] = f"""你是虚拟形象的低频语义理解器。根据一段自然语句，从候选动作标签中选择最匹配的一项。

候选标签：
{MOTION_CANDIDATES}

返回 JSON：
{{"label":"上面候选标签之一","confidence":0.0到1.0,"summary":"不超过20个中文字符"}}
只返回 JSON，不要添加解释。"""


@dataclass(slots=True)
class SemanticResult:
    """LLM 语义输出。"""

    label: str
    confidence: float
    summary: str
    timestamp: float
    source: str = "llm"
    error: str = ""
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class SemanticInterpreterConfig:
    """LLM 调用配置。"""

    base_url: str = ""
    api_key: str = ""
    model: str = ""
    min_interval_ms: int = 5000
    timeout_seconds: float = 8.0
    temperature: float = 0.1

    @classmethod
    def from_sources(
        cls,
        base_url: str = "",
        api_key: str = "",
        model: str = "",
        min_interval_ms: int = 5000,
        env_path: Path | None = None,
    ) -> "SemanticInterpreterConfig":
        """优先读取应用配置，缺失时回退到项目根目录 .env。"""
        config = cls(
            base_url=base_url,
            api_key=api_key,
            model=model,
            min_interval_ms=min_interval_ms,
        )
        if config.api_key and config.model:
            return config

        dotenv = env_path or Path(__file__).resolve().parents[3] / ".env"
        env_values = _read_env_file(dotenv)
        return cls(
            base_url=config.base_url or env_values.get("LLM_BASE_URL", ""),
            api_key=config.api_key or env_values.get("LLM_API_KEY", ""),
            model=config.model or env_values.get("LLM_MODEL", ""),
            min_interval_ms=min_interval_ms,
        )


class SemanticInterpreter:
    """限制调用频率的 LLM 语义理解器。"""

    def __init__(self, config: SemanticInterpreterConfig) -> None:
        self.config = config
        self._client: ChatOpenAI | None = None
        self._last_call_at = 0.0
        self._last_result = SemanticResult(
            label="idle_calm",
            confidence=0.0,
            summary="",
            timestamp=0.0,
            source="llm-cache",
        )

    def can_call(self, now: float | None = None) -> bool:
        """判断是否满足低频刷新间隔。"""
        timestamp = now if now is not None else time.monotonic()
        return (timestamp - self._last_call_at) * 1000 >= self.config.min_interval_ms

    def interpret(self, stable_text: str, context: dict[str, Any] | None = None) -> SemanticResult:
        """对稳定文本做低频语义理解。"""
        timestamp = time.time()
        if not stable_text.strip():
            return self._last_result
        if not self.can_call():
            return self._last_result

        self._last_call_at = time.monotonic()
        try:
            client = self._get_client()
            payload = {
                "text": stable_text.strip(),
                "context": context or {},
            }
            response = client.invoke([
                SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(content=json.dumps(payload, ensure_ascii=False)),
            ])
            result = self._parse_response(self._extract_content(response), timestamp)
            self._last_result = result
            return result
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("LLM 语义理解失败：%s", exc)
            self._last_result = SemanticResult(
                label="idle_calm",
                confidence=0.0,
                summary="",
                timestamp=timestamp,
                error=f"{type(exc).__name__}: {exc}",
            )
            return self._last_result

    def _get_client(self) -> ChatOpenAI:
        """构建并缓存 LLM 客户端。"""
        if self._client is not None:
            return self._client
        if not self.config.api_key or not self.config.model:
            raise ValueError("LLM 配置不完整，请设置 api_key 和 model")

        self._client = ChatOpenAI(
            model=self.config.model,
            api_key=self.config.api_key,
            base_url=self.config.base_url or None,
            temperature=self.config.temperature,
            timeout=self.config.timeout_seconds,
            max_tokens=128,
        )
        return self._client

    @staticmethod
    def _extract_content(response: object) -> str:
        """从模型响应中提取文本。"""
        content = getattr(response, "content", "")
        if isinstance(content, str):
            return content.strip()
        return str(content).strip()

    @staticmethod
    def _parse_response(raw: str, timestamp: float) -> SemanticResult:
        """解析 LLM JSON 输出，异常格式回退到 neutral。"""
        data = _coerce_json(raw)
        label = _match_motion_label(str(data.get("label", "idle_calm")))

        confidence = float(data.get("confidence", 0.0))
        confidence = max(0.0, min(1.0, confidence))
        summary = str(data.get("summary", "")).strip()[:20]
        return SemanticResult(
            label=label,
            confidence=confidence,
            summary=summary,
            timestamp=timestamp,
        )


def _read_env_file(path: Path) -> dict[str, str]:
    """读取 .env 中的 LLM 配置，不向日志输出密钥内容。"""
    values: dict[str, str] = {}
    if not path.exists():
        return values

    with path.open("r", encoding="utf-8") as env_file:
        for line in env_file:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, _, value = stripped.partition("=")
            values[key.strip()] = value.strip()
    return values


def _coerce_json(raw: str) -> dict[str, Any]:
    """兼容模型返回 ```json 包裹或额外文字的情况。"""
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        cleaned = cleaned.removeprefix("json").strip()

    try:
        data = json.loads(cleaned)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            data = json.loads(cleaned[start:end + 1])
            return data if isinstance(data, dict) else {}
        raise


def _match_motion_label(raw_label: str) -> str:
    """把 LLM 返回文本映射到预定义动作标签。"""
    normalized = raw_label.strip().lower()
    normalized = normalized.strip('"\'“”‘’.,!?。；：:;，。、（）()[]{}<>')
    if normalized in MOTION_LABELS:
        return normalized
    for label in MOTION_LABELS:
        if label in normalized:
            return label
    return "idle_calm"


def main() -> None:
    """允许模块独立运行，方便调试 LLM 标签匹配。"""
    import argparse

    parser = argparse.ArgumentParser(description="LLM 语义标签匹配调试")
    parser.add_argument("sentence", nargs="+", help="要匹配的自然语句")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    interpreter = SemanticInterpreter(SemanticInterpreterConfig.from_sources())
    result = interpreter.interpret(" ".join(args.sentence))
    print(f"标签={result.label} 置信度={result.confidence:.2f} 摘要={result.summary} 错误={result.error}", flush=True)


if __name__ == "__main__":
    main()
