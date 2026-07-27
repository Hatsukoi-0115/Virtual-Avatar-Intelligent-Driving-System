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

_PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
_MOTION_MAPS_PATH: Final[Path] = _PROJECT_ROOT / "configs" / "motion_maps.json"
# 懒加载缓存：{model_name: loaded_data}
_motion_map_cache: dict[str, dict[str, Any]] = {}
# 预编译缓存：{model_name: {description: [(label, group, index), ...]}}
_motion_group_cache: dict[str, dict[str, list[tuple[str, str, int]]]] = {}


def _load_motion_map(model_name: str) -> dict[str, Any]:
    """从 motion_maps.json 加载指定模型的动作映射，带缓存。"""
    if model_name in _motion_map_cache:
        return _motion_map_cache[model_name]

    if not _MOTION_MAPS_PATH.exists():
        LOGGER.warning("动作映射文件不存在：%s", _MOTION_MAPS_PATH)
        _motion_map_cache[model_name] = {}
        return {}

    try:
        with _MOTION_MAPS_PATH.open("r", encoding="utf-8") as f:
            all_maps = json.load(f)
        data = all_maps.get(model_name, {})
        _motion_map_cache[model_name] = data
        # 预编译 motions 字典为扁平的 description→[(label,group,index)] 结构
        motions_raw: dict[str, list[dict]] = data.get("motions", {})
        _motion_group_cache[model_name] = {
            desc: [(m["label"], m["group"], m["index"]) for m in entries]
            for desc, entries in motions_raw.items()
        }
        return data
    except json.JSONDecodeError as exc:
        LOGGER.warning("动作映射文件解析失败：%s", exc)
        _motion_map_cache[model_name] = {}
        _motion_group_cache[model_name] = {}
        return {}


def _build_system_prompt(model_name: str) -> str:
    """根据模型的动作映射动态生成 LLM system prompt。让 LLM 返回描述而非标签。"""
    data = _load_motion_map(model_name)
    descriptions = data.get("descriptions", [])
    if not descriptions:
        LOGGER.warning("模型 '%s' 无动作描述列表，LLM 将无法正常工作", model_name)
        return "你是虚拟形象的低频语义理解器。模型未配置动作映射，请检查配置。只返回 JSON。"

    candidates = "\n".join(f"- {d}" for d in descriptions)
    return f"""你是虚拟形象的低频语义理解器。根据一段自然语句，从候选描述中选择最匹配的一项，若均不匹配则选择"待机"。

候选描述：
{candidates}

返回 JSON：
{{"description":"上面候选描述之一","confidence":0.0到1.0,"summary":"不超过20个中文字符"}}
只返回 JSON，不要添加解释。"""


def _get_motion_entries(model_name: str) -> dict[str, list[tuple[str, str, int]]]:
    """获取预编译的 description → [(label, group, index)] 映射。"""
    if model_name not in _motion_group_cache:
        _load_motion_map(model_name)
    return _motion_group_cache.get(model_name, {})


def get_motion_label_to_group(model_name: str) -> dict[str, tuple[str, int]]:
    """获取指定模型的动作标签到动作组的扁平映射。"""
    entries = _get_motion_entries(model_name)
    return {
        label: (group, index)
        for motions in entries.values()
        for label, group, index in motions
    }


def match_motion_description(model_name: str, description: str) -> str:
    """根据 LLM 返回的描述字符串，从同描述的动作列表中随机选一个标签。
    找不到匹配时从"待机"描述中随机选一个。"""
    import random as _random

    entries = _get_motion_entries(model_name)
    # 精确匹配
    if description in entries:
        return _random.choice(entries[description])[0]
    # 模糊匹配：查找包含关系
    for desc, motions in entries.items():
        if description in desc or desc in description:
            return _random.choice(motions)[0]
    # 回退到待机
    idle_entries = entries.get("待机", [])
    if idle_entries:
        return _random.choice(idle_entries)[0]
    return "idle_calm"


def get_idle_labels(model_name: str) -> tuple[str, ...]:
    """获取模型的所有 idle 标签，用于面部丢失随机选择。"""
    entries = _get_motion_entries(model_name)
    idle_motions = entries.get("待机", [])
    if idle_motions:
        return tuple(label for label, _, _ in idle_motions)
    return ("idle_calm", "idle_relaxed", "idle_curious")


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
    model_name: str = "haru_ja"
    min_interval_ms: int = 5000
    timeout_seconds: float = 8.0
    temperature: float = 0.1

    @classmethod
    def from_sources(
        cls,
        base_url: str = "",
        api_key: str = "",
        model: str = "",
        model_name: str = "haru_ja",
        min_interval_ms: int = 5000,
        env_path: Path | None = None,
    ) -> "SemanticInterpreterConfig":
        """优先读取应用配置，缺失时回退到项目根目录 .env。"""
        config = cls(
            base_url=base_url,
            api_key=api_key,
            model=model,
            model_name=model_name,
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
            model_name=model_name,
            min_interval_ms=min_interval_ms,
        )


class SemanticInterpreter:
    """限制调用频率的 LLM 语义理解器。"""

    def __init__(self, config: SemanticInterpreterConfig) -> None:
        self.config = config
        self._client: ChatOpenAI | None = None
        self._last_call_at = 0.0
        # 用模型配置中的第一个 idle 标签作为默认值
        entries = _get_motion_entries(config.model_name)
        all_motions = [m for motions in entries.values() for m in motions]
        default_label = next((label for label, _, _ in all_motions if label.startswith("idle_")), "idle_calm")
        self._last_result = SemanticResult(
            label=default_label,
            confidence=0.0,
            summary="",
            timestamp=0.0,
            source="llm-cache",
        )
        # 缓存动态生成的 system prompt
        self._system_prompt = _build_system_prompt(config.model_name)

    def can_call(self, now: float | None = None) -> bool:
        """判断是否满足低频刷新间隔。"""
        timestamp = now if now is not None else time.monotonic()
        return (timestamp - self._last_call_at) * 1000 >= self.config.min_interval_ms

    def interpret(
        self,
        stable_text: str,
        context: dict[str, Any] | None = None,
        force: bool = False,
    ) -> SemanticResult:
        """对稳定文本做低频语义理解。"""
        timestamp = time.time()
        if not stable_text.strip():
            return self._last_result
        if not force and not self.can_call():
            return self._last_result

        self._last_call_at = time.monotonic()
        try:
            client = self._get_client()
            payload = {
                "text": stable_text.strip(),
                "context": context or {},
            }
            response = client.invoke([
                SystemMessage(content=self._system_prompt),
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

    def _parse_response(self, raw: str, timestamp: float) -> SemanticResult:
        """解析 LLM JSON 输出，将返回的描述映射为随机动作标签。"""
        data = _coerce_json(raw)
        description = str(data.get("description", "")).strip()
        label = match_motion_description(self.config.model_name, description)

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


def main() -> None:
    """允许模块独立运行，方便调试 LLM 标签匹配。"""
    import argparse

    parser = argparse.ArgumentParser(description="LLM 语义标签匹配调试")
    parser.add_argument("sentence", nargs="+", help="要匹配的自然语句")
    parser.add_argument("--model-name", default="haru_ja", help="模型名称")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    config = SemanticInterpreterConfig.from_sources(model_name=args.model_name)
    interpreter = SemanticInterpreter(config)
    result = interpreter.interpret(" ".join(args.sentence))
    print(f"标签={result.label} 置信度={result.confidence:.2f} 摘要={result.summary} 错误={result.error}", flush=True)


if __name__ == "__main__":
    main()
