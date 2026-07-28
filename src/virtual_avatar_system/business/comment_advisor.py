"""观众评论话术建议模块。

职责：
- 接收直播间观众评论文本
- 识别评论对应的业务语义标签
- 为主播生成当前推荐回复和推荐讲解重点
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any


LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class CommentAdvice:
    """一条观众评论对应的话术建议。"""

    audience_comment: str
    semantic_label: str
    recommended_reply: str
    explanation_focus: str
    source: str = "rule"
    error: str = ""


@dataclass(slots=True)
class CommentLLMConfig:
    """观众评论 LLM 分析配置。"""

    base_url: str = ""
    api_key: str = ""
    model: str = ""
    timeout_seconds: float = 6.0
    temperature: float = 0.2
    prompt_mode: str = "course_qa"
    prompt_text: str = ""
    live_content: str = ""
    host_persona: str = ""
    answer_boundary: str = ""
    custom_prompt: str = ""


def analyze_audience_comment(comment: str) -> CommentAdvice:
    """根据观众评论生成最小可用的话术建议。"""
    normalized = " ".join(comment.strip().split())
    if not normalized:
        return CommentAdvice(
            audience_comment="",
            semantic_label="等待观众评论",
            recommended_reply="请输入或接入观众评论后再生成推荐回复。",
            explanation_focus="等待评论输入",
        )

    rule = _match_comment_rule(normalized)
    return CommentAdvice(
        audience_comment=normalized,
        semantic_label=rule["semantic_label"],
        recommended_reply=rule["recommended_reply"],
        explanation_focus=rule["explanation_focus"],
    )


def analyze_audience_comment_with_llm(comment: str, config: CommentLLMConfig) -> CommentAdvice:
    """优先调用 LLM 生成话术建议，失败时回退到本地规则模板。"""
    fallback = analyze_audience_comment(comment)
    if not fallback.audience_comment:
        return fallback
    if not config.api_key or not config.model:
        return CommentAdvice(
            audience_comment=fallback.audience_comment,
            semantic_label=fallback.semantic_label,
            recommended_reply=fallback.recommended_reply,
            explanation_focus=fallback.explanation_focus,
            source="rule-fallback",
            error="LLM 配置不完整",
        )

    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        from langchain_openai import ChatOpenAI

        client = ChatOpenAI(
            model=config.model,
            api_key=config.api_key,
            base_url=config.base_url or None,
            temperature=config.temperature,
            timeout=config.timeout_seconds,
            max_tokens=256,
        )
        payload = {
            "audience_comment": fallback.audience_comment,
            "business_context": _build_business_context(config),
            "required_fields": ["semantic_label", "recommended_reply", "explanation_focus"],
        }
        response = client.invoke([
            SystemMessage(content=_build_comment_system_prompt(config)),
            HumanMessage(content=json.dumps(payload, ensure_ascii=False)),
        ])
        data = _coerce_json(_extract_content(response))
        return _build_llm_advice(fallback, data)
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("观众评论 LLM 分析失败，使用规则兜底：%s", exc)
        return CommentAdvice(
            audience_comment=fallback.audience_comment,
            semantic_label=fallback.semantic_label,
            recommended_reply=fallback.recommended_reply,
            explanation_focus=fallback.explanation_focus,
            source="rule-fallback",
            error=f"{type(exc).__name__}: {exc}",
        )


def _build_comment_system_prompt(config: CommentLLMConfig) -> str:
    """构建观众评论话术建议的稳定输出提示词。"""
    prompt_text = config.prompt_text.strip()
    custom_prompt = config.custom_prompt.strip()
    if prompt_text:
        # UI 中维护的是完整 Prompt，这里只追加输出格式约束，避免模型返回不可解析内容。
        scenario_prompt = prompt_text
    elif config.prompt_mode == "custom" and custom_prompt:
        scenario_prompt = custom_prompt
    else:
        scenario_prompt = _build_default_scenario_prompt(config)

    return f"""你是直播主播的智能话术助手，负责分析观众评论并给主播生成简洁可直接口播的建议。

业务背景：
{scenario_prompt}

输出要求：
- 只返回 JSON，不要 Markdown，不要额外解释。
- semantic_label 使用“一级类别 / 二级类别”，例如“用户提问 / 使用场景”。
- recommended_reply 面向主播口播，控制在 80 个中文字符以内。
- explanation_focus 用中文顿号或逗号分隔，控制在 5 个重点以内。
- 回答必须遵守直播内容、主播人设和回答边界，不要偏离当前直播主题。

JSON 格式：
{{"semantic_label":"...","recommended_reply":"...","explanation_focus":"..."}}"""


def _build_default_scenario_prompt(config: CommentLLMConfig) -> str:
    """根据配置模式生成默认业务约束 Prompt。"""
    live_content = config.live_content.strip() or "虚拟形象智能驱动系统直播演示。"
    host_persona = config.host_persona.strip() or "课程项目演示主播，表达清晰、客观专业。"
    answer_boundary = config.answer_boundary.strip() or "回答必须围绕当前直播内容，不夸大未实现能力。"

    if config.prompt_mode == "teaching_demo":
        scene_hint = "当前重点是课程教学与课堂展示场景，优先说明学习成本、教学演示、互动讲解和验收价值。"
    else:
        scene_hint = "当前重点是产品功能演示，优先说明系统能力、使用流程、互动效果和项目亮点。"

    return "\n".join([
        f"- 直播内容：{live_content}",
        f"- 主播人设：{host_persona}",
        f"- 回答边界：{answer_boundary}",
        f"- 场景策略：{scene_hint}",
        "- 观众可能是老师、学生、课程验收人员或直播间普通观众。",
    ])


def _build_business_context(config: CommentLLMConfig) -> str:
    """给 HumanMessage 提供简短业务上下文，帮助模型聚焦当前直播。"""
    live_content = config.live_content.strip() or "虚拟形象智能驱动系统直播演示"
    host_persona = config.host_persona.strip() or "课程项目演示主播"
    return f"{live_content}；主播人设：{host_persona}"


def _extract_content(response: object) -> str:
    """从 LLM 响应中提取文本内容。"""
    content = getattr(response, "content", "")
    if isinstance(content, str):
        return content.strip()
    return str(content).strip()


def _coerce_json(raw: str) -> dict[str, Any]:
    """兼容模型返回代码块或附加文字的情况。"""
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            raise
        data = json.loads(cleaned[start : end + 1])

    if not isinstance(data, dict):
        raise ValueError("LLM 未返回 JSON 对象")
    return data


def _build_llm_advice(fallback: CommentAdvice, data: dict[str, Any]) -> CommentAdvice:
    """把 LLM JSON 转换成话术建议，缺字段时使用规则结果补齐。"""
    semantic_label = _clean_field(data.get("semantic_label"), fallback.semantic_label, 28)
    recommended_reply = _clean_field(data.get("recommended_reply"), fallback.recommended_reply, 100)
    explanation_focus = _clean_field(data.get("explanation_focus"), fallback.explanation_focus, 80)
    return CommentAdvice(
        audience_comment=fallback.audience_comment,
        semantic_label=semantic_label,
        recommended_reply=recommended_reply,
        explanation_focus=explanation_focus,
        source="llm",
    )


def _clean_field(value: object, fallback: str, max_length: int) -> str:
    """清洗 LLM 字段，保证 UI 展示内容稳定可控。"""
    if isinstance(value, list):
        text = "、".join(str(item).strip() for item in value if str(item).strip())
        return text[:max_length] if text else fallback
    text = str(value or "").strip()
    if not text:
        return fallback
    return text[:max_length]


def _match_comment_rule(comment: str) -> dict[str, str]:
    """按业务关键词匹配评论类型并返回对应话术模板。"""
    lowered = comment.lower()

    # 使用场景类问题优先匹配，适合课堂演示和老师验收。
    if _contains_any(lowered, ("学生", "学校", "课堂", "课程", "教学", "适合", "场景", "直播讲解")):
        return {
            "semantic_label": "用户提问 / 使用场景",
            "recommended_reply": "适合学生使用，主要优势是操作简单、学习成本低，可用于课程展示和直播讲解。",
            "explanation_focus": "学生使用场景、操作简单、学习成本低、课程展示、直播互动",
        }

    if _contains_any(lowered, ("功能", "能做", "有什么用", "作用", "介绍", "亮点", "优势")):
        return {
            "semantic_label": "用户提问 / 产品功能",
            "recommended_reply": "它可以把语音识别、情绪理解、语义分析和虚拟形象动作联动起来，帮助主播更自然地完成讲解和互动。",
            "explanation_focus": "多模态识别、LLM 语义理解、动作联动、主播辅助",
        }

    if _contains_any(lowered, ("价格", "多少钱", "收费", "购买", "怎么买", "贵不贵")):
        return {
            "semantic_label": "用户提问 / 购买咨询",
            "recommended_reply": "具体价格可以根据部署方式和功能范围来确定，演示版重点展示核心能力，后续可以按实际场景扩展。",
            "explanation_focus": "部署方式、功能范围、演示版能力、后续扩展",
        }

    if _contains_any(lowered, ("怎么用", "如何使用", "操作", "上手", "复杂", "配置")):
        return {
            "semantic_label": "用户提问 / 操作方法",
            "recommended_reply": "使用流程比较简单，先完成摄像头、麦克风和 LLM 配置，再开始直播，系统会实时给出状态和话术建议。",
            "explanation_focus": "配置流程、开始直播、实时状态、话术建议",
        }

    if _contains_any(lowered, ("卡", "延迟", "不准", "失败", "问题", "风险", "稳定")):
        return {
            "semantic_label": "用户反馈 / 稳定性问题",
            "recommended_reply": "这类问题主要和设备性能、网络和模型响应有关，系统会通过状态面板和报告记录帮助定位问题。",
            "explanation_focus": "设备性能、网络状态、模型响应、报告记录",
        }

    if _contains_any(lowered, ("谢谢", "感谢", "不错", "很好", "喜欢")):
        return {
            "semantic_label": "观众反馈 / 正向评价",
            "recommended_reply": "谢谢认可，后续我们还会继续优化评论理解、主播话术建议和虚拟形象表现效果。",
            "explanation_focus": "正向反馈、后续优化、评论理解、形象表现",
        }

    if _contains_any(lowered, ("你好", "来了", "在吗", "开播", "主播")):
        return {
            "semantic_label": "观众互动 / 欢迎问候",
            "recommended_reply": "欢迎来到直播间，大家可以直接在评论区提问，系统会辅助主播整理问题和推荐回复。",
            "explanation_focus": "欢迎互动、评论提问、主播辅助、实时推荐",
        }

    return {
        "semantic_label": "观众评论 / 待跟进",
        "recommended_reply": f"可以先回应观众的这条评论：“{comment}”，再结合当前演示内容补充一个具体应用场景。",
        "explanation_focus": "先回应评论、结合当前内容、补充应用场景",
    }


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    """判断文本中是否包含任一关键词。"""
    return any(keyword in text for keyword in keywords)
