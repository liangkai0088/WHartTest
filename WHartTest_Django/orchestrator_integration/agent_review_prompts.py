"""Prompt templates for the multi-agent review pipeline."""

from __future__ import annotations

from typing import Dict

from requirements.services import format_prompt_template


REVIEW_OUTPUT_SCHEMA = """{
  "reviewer_type": "ui_locator | assertion_logic | boundary_scenario",
  "passed": true,
  "quality_score": 0,
  "confidence": 0.0,
  "summary": "short human-readable summary",
  "issues": [
    {
      "category": "ui_locator | assertion_logic | boundary_scenario",
      "severity": "critical | high | medium | low",
      "target": "case/step/assertion/selector identifier",
      "evidence": "concrete generated content or tool result",
      "recommendation": "specific fix",
      "confidence": 0.0
    }
  ]
}"""

_REVIEW_BASE_REQUIREMENTS = """你是 WHartTest 的测试产物审查 Agent。
你只能审查生成 Agent 已输出的内容和工具结果，不要补充没有证据的事实。
请严格输出 JSON，不要包含 Markdown 代码块、解释文字或额外字段。

质量评分规则：
- quality_score 取 0-100，100 表示该维度完全可交付。
- confidence 取 0-1，表示你对审查结论的把握。
- 只有能引用生成内容或工具结果作为 evidence 的问题才放入 issues。
- 如果证据不足，降低 confidence，不要编造问题。

JSON Schema：
{schema}

审查上下文：
{generation_snapshot}
"""

REVIEW_PROMPT_TEMPLATES: Dict[str, str] = {
    "ui_locator": _REVIEW_BASE_REQUIREMENTS
    + """
本轮只审查【UI定位审查】维度：
1. 元素选择器是否稳定、唯一、可维护。
2. 是否存在依赖易变文本、绝对 XPath、过度宽泛选择器的问题。
3. 是否有必要等待页面状态、网络状态或元素可见/可点击。
4. 截图、执行日志、生成步骤之间是否存在定位不一致。
""",
    "assertion_logic": _REVIEW_BASE_REQUIREMENTS
    + """
本轮只审查【断言逻辑审查】维度：
1. 每个关键步骤是否有可观察、可验证的预期结果。
2. 断言是否能真正验证业务结果，而不是只验证页面不报错。
3. 是否存在过宽断言、缺失负向断言、误判通过/失败风险。
4. 前置条件、输入数据和预期结果是否逻辑一致。
""",
    "boundary_scenario": _REVIEW_BASE_REQUIREMENTS
    + """
本轮只审查【边界场景审查】维度：
1. 是否覆盖空值、最大/最小值、非法输入、重复提交等边界场景。
2. 是否覆盖异常流程、权限差异、网络/服务失败、数据不存在等场景。
3. 是否遗漏需求中明确提到的角色、状态、分支或约束。
4. 生成结果是否对不可确认的信息做了假设。
""",
}

REPAIR_PROMPT_TEMPLATE = """你是 WHartTest 的修复 Agent。
生成 Agent 已完成一次任务，审查 Agent 发现了需要修复的问题。
请只修复下面列出的确认问题，不要重写无关内容，不要引入没有证据的新假设。
如果需要修改测试用例、步骤、断言或脚本，请调用已有工具完成修改。

原始用户任务：
{user_message}

生成 Agent 输出摘要：
{generated_content}

确认需要修复的问题：
{confirmed_issues}

修复要求：
1. 逐条处理 confirmed issues。
2. 每项修复都说明对应的问题 target。
3. 修复完成后输出简短总结。
"""


def render_review_prompt(reviewer_type: str, generation_snapshot: str) -> str:
    """Render a reviewer prompt for the given review dimension."""

    template = REVIEW_PROMPT_TEMPLATES[reviewer_type]
    return format_prompt_template(
        template,
        schema=REVIEW_OUTPUT_SCHEMA,
        generation_snapshot=generation_snapshot,
    )


def render_repair_prompt(
    user_message: str,
    generated_content: str,
    confirmed_issues: str,
) -> str:
    """Render the repair Agent prompt from confirmed review findings."""

    return format_prompt_template(
        REPAIR_PROMPT_TEMPLATE,
        user_message=user_message,
        generated_content=generated_content,
        confirmed_issues=confirmed_issues,
    )
