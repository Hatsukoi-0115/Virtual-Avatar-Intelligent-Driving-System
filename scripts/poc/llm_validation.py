"""LLM 1.6 验证脚本。

用途：
- 验证 LLM 调用是否会显著拖慢主循环
- 验证 LLM 能否根据主播语句输出匹配的动作标签
- 为后续语义驱动层提供延迟和稳定性基准

运行方式：
- uv run python scripts/poc/llm_validation.py "今天天气真好"
- uv run python scripts/poc/llm_validation.py --duration 10 进入持续验证模式
- 配置写在项目根目录的 .env 文件中（参考 .env.example）
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

LOGGER = logging.getLogger(__name__)
PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
DOTENV_PATH: Final[Path] = PROJECT_ROOT / ".env"

# ---- 23 个动作标签及其描述（供 LLM 匹配） ----
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
    "待机（平静站立，微微呼吸）",
    "待机（放松状态，轻微倾斜）",
    "待机（略带好奇的左右观望）",
    "点头、认同",
    "摇头、双臂交叉、否认",
    "单手托下巴、思考",
    "双手叉腰、不满",
    "双手合十、开心",
    "后仰、惊讶、吓一跳",
    "双手叉腰、反问",
    "疑问",
    "脸红、双臂交叉、害羞",
    "双臂交叉、恶作剧、窃喜",
    "身体一震、惊喜",
    "待机（回复后的默认状态）",
    "双手合十、点头、认同",
    "开心（打招呼式）",
    "开心（轻笑）",
    "垂头、无奈",
    "发表见解、原来如此",
    "被逗笑、不忍直视",
    "脸红、害羞、惊喜、疑惑",
    "激动、兴奋",
)

# 组装成 LLM 可读的候选列表
MOTION_CANDIDATES: Final[str] = "\n".join(
    f"- {label}: {desc}" for label, desc in zip(MOTION_LABELS, MOTION_DESCRIPTIONS)
)

MOTION_LABEL_TO_DESCRIPTION: Final[dict[str, str]] = dict(
    zip(MOTION_LABELS, MOTION_DESCRIPTIONS, strict=True)
)

SYSTEM_PROMPT: Final[str] = f"""你是一个虚拟形象动作选择器。根据主播说的一句话，分析主播的状态符合哪一种描述，返回对应的标签。

标签与对应的描述：
{MOTION_CANDIDATES}

规则：
1. 只返回 **一个** 动作标签，不要返回描述。
2. 不要返回额外解释、标点或换行。
3. 如果语句情感不明确，返回 "idle_calm"。"""


@dataclass(slots=True)
class LLMValidationResult:
    """单次 LLM 调用结果。"""

    label: str = ""
    latency_ms: float = 0.0
    error: str = ""


@dataclass(slots=True)
class SessionStats:
    """持续验证会话统计。"""

    calls: int = 0
    total_latency_ms: float = 0.0
    min_latency_ms: float = float("inf")
    max_latency_ms: float = 0.0
    errors: int = 0
    unknown_labels: int = 0
    history: list[LLMValidationResult] = field(default_factory=list)


def _configure_logging() -> None:
    """配置日志输出。"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


def _load_env_config() -> dict[str, str]:
    """从项目根目录 .env 加载 LLM 配置。"""
    config: dict[str, str] = {}
    if not DOTENV_PATH.exists():
        raise FileNotFoundError(
            f"未找到配置文件：{DOTENV_PATH}\n"
            "请将 .env.example 复制为 .env 并填入实际参数后重试"
        )

    with DOTENV_PATH.open("r", encoding="utf-8") as env_file:
        for line in env_file:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            config[key.strip()] = value.strip()

    for required_key in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"):
        if required_key not in config:
            raise ValueError(f".env 文件中缺少必需配置项：{required_key}")

    return config


def _build_llm_client(config: dict[str, str]) -> ChatOpenAI:
    """构建 ChatOpenAI 对话引擎实例。"""
    return ChatOpenAI(
        model=config["LLM_MODEL"],
        api_key=config["LLM_API_KEY"],
        base_url=config["LLM_BASE_URL"],
        temperature=0.1,
        max_tokens=32,
    )


def _normalize_label(raw_label: str) -> str:
    """对 LLM 返回的标签文本进行标准化处理。"""
    normalized = raw_label.strip().lower()
    normalized = normalized.strip('"\'“”‘’.,!?。；：:;，。、（）()[]{}<>')
    return normalized


def _match_motion_label(raw_label: str) -> str:
    """尝试将 LLM 返回值映射到预定义动作标签。"""
    normalized = _normalize_label(raw_label)
    if not normalized:
        return ""

    # 直接精确匹配
    if normalized in MOTION_LABELS:
        return normalized

    # 尝试匹配可能带有引号或描述的返回值
    for label in MOTION_LABELS:
        if label in normalized:
            return label

    # 搜索常见的标点切分结果，避免模型返回“标签：idle_calm”之类的形式
    for token in normalized.replace("/", " ").replace("-", " ").split():
        if token in MOTION_LABELS:
            return token

    return ""


def _get_motion_description(label: str) -> str:
    """根据动作标签获取对应描述。"""
    return MOTION_LABEL_TO_DESCRIPTION.get(label, "未知描述")


def _extract_raw_content(response: object) -> str:
    """从 ChatOpenAI 返回中提取文本内容。"""
    content = getattr(response, "content", "")
    if content is None:
        return ""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            text = getattr(item, "text", None)
            if text:
                parts.append(str(text))
        return "".join(parts).strip()
    return str(content).strip()


def _call_llm(client: ChatOpenAI, model: str, sentence: str) -> LLMValidationResult:
    """调用 LLM 并返回匹配的动作标签。"""
    result = LLMValidationResult()
    call_start = time.perf_counter()

    try:
        response = client.invoke([
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=sentence),
        ], model=model)
        result.latency_ms = (time.perf_counter() - call_start) * 1000
        raw_label = _extract_raw_content(response)

        # 保存原始返回用于排查
        LOGGER.debug("LLM 原始返回：%r", raw_label)

        # 逐级尝试匹配标签
        matched = _match_motion_label(raw_label)
        if matched:
            result.label = matched
        else:
            result.label = raw_label or "idle_calm"
    except Exception as exc:  # noqa: BLE001
        result.latency_ms = (time.perf_counter() - call_start) * 1000
        result.label = "idle_calm"
        result.error = f"{type(exc).__name__}: {exc}"
        LOGGER.debug("LLM 调用异常详情：%s", exc, exc_info=True)

    return result


def _build_parser() -> argparse.ArgumentParser:
    """构建命令行参数。"""
    parser = argparse.ArgumentParser(description="LLM 1.6 验证脚本")
    parser.add_argument("sentence", nargs="*", help="要分析的主播语句（可包含空格，无需引号）")
    parser.add_argument("--duration", type=float, default=0.0, help="持续验证时长（秒），0 表示只发一句话后退出")
    return parser


def _print_validation_result(result: LLMValidationResult) -> None:
    """打印单次验证结果。"""
    status = "OK" if not result.error else f"ERROR: {result.error}"
    description = _get_motion_description(result.label)
    print(
        f"  标签：{result.label: <25s}  描述：{description:<24s}  延迟：{result.latency_ms:7.1f}ms  {status}",
        flush=True,
    )


def _run_single_check(client: ChatOpenAI, model: str, sentence: str) -> None:
    """单次验证：发一句话，查看结果。"""
    LOGGER.info("输入语句：%s", sentence)
    result = _call_llm(client, model, sentence)
    _print_validation_result(result)


def _run_continuous_check(client: ChatOpenAI, model: str, duration: float) -> None:
    """持续验证：在指定时间内反复发测试语句。"""
    # 先做一次连通性检查，避免全部请求失败时才看到错误
    LOGGER.info("先执行连通性检查……")
    test_result = _call_llm(client, model, "测试")
    if test_result.error:
        LOGGER.error("连通性检查失败：%s", test_result.error)
        LOGGER.error("请检查 .env 中的 LLM_BASE_URL、LLM_API_KEY、LLM_MODEL 是否正确")
        return
    LOGGER.info("连通性检查通过，标签=%s 延迟=%.0fms", test_result.label, test_result.latency_ms)

    test_sentences = [
        "今天天气真好啊",
        "你说的完全不对",
        "让我想想这个问题怎么解决",
        "太棒了！",
        "不是吧，真的假的？",
        "你为什么要这样对我",
        "嘿嘿，其实我早就知道了",
        "天呐！这是什么情况？",
        "我实在受不了了",
        "原来如此，我明白了",
    ]

    stats = SessionStats()
    sentence_index = 0
    start_time = time.perf_counter()

    LOGGER.info("开始持续验证，时长：%.0f 秒，模型：%s", duration, model)
    print(f"{'序号':>4s}  {'输入语句':<30s}  {'标签':<22s}  {'延迟':>8s}  状态", flush=True)
    print("-" * 100, flush=True)

    try:
        while (time.perf_counter() - start_time) < duration:
            sentence = test_sentences[sentence_index % len(test_sentences)]
            sentence_index += 1
            stats.calls += 1

            result = _call_llm(client, model, sentence)
            stats.total_latency_ms += result.latency_ms
            stats.min_latency_ms = min(stats.min_latency_ms, result.latency_ms)
            stats.max_latency_ms = max(stats.max_latency_ms, result.latency_ms)
            stats.history.append(result)

            if result.error:
                stats.errors += 1
            if result.label and result.label not in MOTION_LABELS and not result.error:
                stats.unknown_labels += 1

            status = "OK" if not result.error else "ERR"
            description = _get_motion_description(result.label)
            print(
                f"{stats.calls:4d}  {sentence:<30s}  {result.label:<22s}  {description:<24s}  {result.latency_ms:7.1f}ms  {status}",
                flush=True,
            )

    except KeyboardInterrupt:
        LOGGER.info("收到 Ctrl+C，提前结束验证")

    total_elapsed = time.perf_counter() - start_time
    LOGGER.info("")
    LOGGER.info("=== 验证统计 ===")
    LOGGER.info("总调用次数：%s", stats.calls)
    LOGGER.info("总耗时：%.2fs", total_elapsed)
    LOGGER.info("平均延迟：%.1fms", stats.total_latency_ms / max(stats.calls, 1))
    LOGGER.info("最小延迟：%.1fms", stats.min_latency_ms if stats.calls else 0)
    LOGGER.info("最大延迟：%.1fms", stats.max_latency_ms)
    LOGGER.info("错误次数：%s", stats.errors)
    LOGGER.info("未知标签次数：%s", stats.unknown_labels)
    LOGGER.info("有效调用：%s", stats.calls - stats.errors)
    if stats.calls:
        LOGGER.info("错误率：%.1f%%", stats.errors / stats.calls * 100)


def main() -> None:
    """执行 1.6 验证流程。"""
    _configure_logging()

    parser = _build_parser()
    args = parser.parse_args()

    config = _load_env_config()
    client = _build_llm_client(config)
    model = config["LLM_MODEL"]

    # 组装输入语句
    sentence = " ".join(args.sentence) if args.sentence else None

    if args.duration > 0:
        _run_continuous_check(client, model, args.duration)
    elif sentence:
        _run_single_check(client, model, sentence)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
