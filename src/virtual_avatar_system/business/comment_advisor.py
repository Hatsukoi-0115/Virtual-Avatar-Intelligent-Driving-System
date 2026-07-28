"""观众评论话术建议模块。

职责：
- 接收直播间观众评论文本
- 识别评论对应的业务语义标签
- 为主播生成当前推荐回复和推荐讲解重点
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class CommentAdvice:
    """一条观众评论对应的话术建议。"""

    audience_comment: str
    semantic_label: str
    recommended_reply: str
    explanation_focus: str


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
