"""Multi-agent review pipeline service."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

from asgiref.sync import sync_to_async
from django.utils import timezone
from langchain_core.messages import HumanMessage, SystemMessage

from requirements.services import extract_json_from_response

from .agent_review_prompts import render_repair_prompt, render_review_prompt
from .models import AgentReviewRun

logger = logging.getLogger(__name__)

REVIEW_MODE_SINGLE = "single"
REVIEW_MODE_MULTI = "multi_review"
REVIEWER_TYPES = ("ui_locator", "assertion_logic", "boundary_scenario")
DEFAULT_REVIEW_THRESHOLDS = {
    "quality_score": 80,
    "confidence": 0.7,
    "issue_confidence": 0.75,
}
BLOCKING_SEVERITIES = {"critical", "high"}
MAX_GENERATED_CONTENT_CHARS = 12000
MAX_TOOL_RESULTS = 20
MAX_TOOL_RESULT_CHARS = 4000


@dataclass(frozen=True)
class ReviewPipelineResult:
    """Normalized review pipeline result used by the Agent Loop view."""

    review_run: AgentReviewRun
    status: str
    review_results: List[Dict[str, Any]]
    aggregate_score: float
    aggregate_confidence: float
    needs_repair: bool
    route_reason: str
    repair_prompt: str
    confirmed_issues: List[Dict[str, Any]]

    def to_event_payload(self) -> Dict[str, Any]:
        """Return a JSON-serializable event payload."""

        return {
            "mode": REVIEW_MODE_MULTI,
            "status": self.status,
            "quality_score": self.aggregate_score,
            "confidence": self.aggregate_confidence,
            "needs_repair": self.needs_repair,
            "route_reason": self.route_reason,
            "review_run_id": self.review_run.id,
            "review_results": self.review_results,
        }

    def to_complete_payload(self) -> Dict[str, Any]:
        """Return the compact payload attached to the final complete event."""

        return {
            "mode": REVIEW_MODE_MULTI,
            "status": self.status,
            "quality_score": self.aggregate_score,
            "confidence": self.aggregate_confidence,
            "needs_repair": self.needs_repair,
            "review_run_id": self.review_run.id,
            "route_reason": self.route_reason,
        }


def normalize_review_mode(raw_mode: Any) -> str:
    """Normalize the request review mode to a supported value."""

    if raw_mode == REVIEW_MODE_MULTI:
        return REVIEW_MODE_MULTI
    return REVIEW_MODE_SINGLE


def normalize_review_thresholds(options: Optional[Dict[str, Any]]) -> Dict[str, float]:
    """Merge and clamp review threshold options."""

    raw_options = options if isinstance(options, dict) else {}
    aliases = {
        "quality_score": ("quality_score", "quality_threshold"),
        "confidence": ("confidence", "confidence_threshold"),
        "issue_confidence": ("issue_confidence", "issue_confidence_threshold"),
    }
    normalized: Dict[str, float] = {}
    for key, option_names in aliases.items():
        value = DEFAULT_REVIEW_THRESHOLDS[key]
        for option_name in option_names:
            if option_name in raw_options:
                value = raw_options[option_name]
                break
        normalized[key] = _clamp_float(value, 0, 100 if key == "quality_score" else 1)
    return normalized


def build_generation_snapshot(
    *,
    user_message: str,
    generated_content: str,
    tool_results: Iterable[Dict[str, Any]],
    project_id: str,
    session_id: str,
    test_case_id: Optional[int] = None,
    generate_playwright_script: bool = False,
) -> Dict[str, Any]:
    """Build a bounded review snapshot from generation output and tool results."""

    bounded_tool_results = []
    for item in list(tool_results)[:MAX_TOOL_RESULTS]:
        if not isinstance(item, dict):
            continue
        bounded_tool_results.append(
            {
                "tool_name": str(item.get("tool_name") or "")[:120],
                "step": item.get("step"),
                "summary": str(item.get("summary") or "")[:MAX_TOOL_RESULT_CHARS],
                "tool_output": str(item.get("tool_output") or "")[:MAX_TOOL_RESULT_CHARS],
            }
        )

    return {
        "user_message": str(user_message or "")[:MAX_GENERATED_CONTENT_CHARS],
        "generated_content": str(generated_content or "")[:MAX_GENERATED_CONTENT_CHARS],
        "tool_results": bounded_tool_results,
        "project_id": str(project_id),
        "session_id": str(session_id),
        "test_case_id": test_case_id,
        "generate_playwright_script": bool(generate_playwright_script),
    }


async def run_review_pipeline(
    *,
    llm: Any,
    review_run: AgentReviewRun,
    generation_snapshot: Dict[str, Any],
    thresholds: Dict[str, float],
) -> ReviewPipelineResult:
    """Run reviewer agents and persist the structured review result."""

    snapshot_text = json.dumps(generation_snapshot, ensure_ascii=False, indent=2)
    review_results = await asyncio.gather(
        *[
            _run_single_reviewer(llm, reviewer_type, snapshot_text)
            for reviewer_type in REVIEWER_TYPES
        ]
    )
    aggregate_score = _average(
        _clamp_float(result.get("quality_score"), 0, 100) for result in review_results
    )
    aggregate_confidence = _average(
        _clamp_float(result.get("confidence"), 0, 1) for result in review_results
    )
    confirmed_issues = _get_confirmed_issues(
        review_results,
        issue_confidence_threshold=thresholds["issue_confidence"],
    )
    status, needs_repair, route_reason = _decide_route(
        aggregate_score=aggregate_score,
        aggregate_confidence=aggregate_confidence,
        confirmed_issues=confirmed_issues,
        thresholds=thresholds,
    )
    repair_prompt = ""
    if needs_repair:
        repair_prompt = render_repair_prompt(
            user_message=str(generation_snapshot.get("user_message") or ""),
            generated_content=str(generation_snapshot.get("generated_content") or ""),
            confirmed_issues=json.dumps(confirmed_issues, ensure_ascii=False, indent=2),
        )

    review_run.status = "repairing" if needs_repair else status
    review_run.review_results = review_results
    review_run.aggregate_score = aggregate_score
    review_run.aggregate_confidence = aggregate_confidence
    review_run.needs_repair = needs_repair
    review_run.route_reason = route_reason
    review_run.repair_prompt = repair_prompt
    await sync_to_async(review_run.save)(
        update_fields=[
            "status",
            "review_results",
            "aggregate_score",
            "aggregate_confidence",
            "needs_repair",
            "route_reason",
            "repair_prompt",
            "updated_at",
        ]
    )

    return ReviewPipelineResult(
        review_run=review_run,
        status="repairing" if needs_repair else status,
        review_results=review_results,
        aggregate_score=aggregate_score,
        aggregate_confidence=aggregate_confidence,
        needs_repair=needs_repair,
        route_reason=route_reason,
        repair_prompt=repair_prompt,
        confirmed_issues=confirmed_issues,
    )


def complete_review_run(
    review_run: AgentReviewRun,
    *,
    status: str,
    repair_result: str = "",
    error_message: str = "",
) -> None:
    """Mark a review run as completed, repaired, skipped, or failed."""

    review_run.status = status
    review_run.repair_result = repair_result
    review_run.error_message = error_message
    review_run.completed_at = timezone.now()
    review_run.save(
        update_fields=[
            "status",
            "repair_result",
            "error_message",
            "completed_at",
            "updated_at",
        ]
    )


async def _run_single_reviewer(
    llm: Any,
    reviewer_type: str,
    snapshot_text: str,
) -> Dict[str, Any]:
    """Invoke one reviewer and normalize its JSON output."""

    prompt = render_review_prompt(reviewer_type, snapshot_text)
    try:
        response = await llm.ainvoke(
            [
                SystemMessage(content="你是只输出 JSON 的测试审查 Agent。"),
                HumanMessage(content=prompt),
            ]
        )
        content = response.content if hasattr(response, "content") else str(response)
        parsed = extract_json_from_response(content)
        return _normalize_review_result(reviewer_type, parsed, raw_content=content)
    except Exception as exc:
        logger.warning(
            "Agent reviewer failed. reviewer_type=%s, error=%s",
            reviewer_type,
            exc,
            exc_info=True,
        )
        return _failed_review_result(reviewer_type, f"审查调用失败: {exc}")


def _normalize_review_result(
    reviewer_type: str,
    parsed: Optional[Dict[str, Any]],
    *,
    raw_content: str,
) -> Dict[str, Any]:
    if not isinstance(parsed, dict):
        return _failed_review_result(
            reviewer_type,
            "审查 Agent 未返回可解析 JSON",
            raw_content=raw_content[:1000],
        )

    issues = parsed.get("issues") if isinstance(parsed.get("issues"), list) else []
    normalized_issues = [
        _normalize_issue(reviewer_type, issue)
        for issue in issues
        if isinstance(issue, dict)
    ]
    return {
        "reviewer_type": reviewer_type,
        "passed": bool(parsed.get("passed", not normalized_issues)),
        "quality_score": _clamp_float(parsed.get("quality_score"), 0, 100),
        "confidence": _clamp_float(parsed.get("confidence"), 0, 1),
        "summary": str(parsed.get("summary") or "")[:1000],
        "issues": normalized_issues,
    }


def _normalize_issue(reviewer_type: str, issue: Dict[str, Any]) -> Dict[str, Any]:
    severity = str(issue.get("severity") or "medium").lower()
    if severity not in {"critical", "high", "medium", "low"}:
        severity = "medium"
    category = str(issue.get("category") or reviewer_type)
    if category not in REVIEWER_TYPES:
        category = reviewer_type
    return {
        "category": category,
        "severity": severity,
        "target": str(issue.get("target") or "")[:500],
        "evidence": str(issue.get("evidence") or "")[:2000],
        "recommendation": str(issue.get("recommendation") or "")[:2000],
        "confidence": _clamp_float(issue.get("confidence"), 0, 1),
    }


def _failed_review_result(
    reviewer_type: str,
    summary: str,
    *,
    raw_content: str = "",
) -> Dict[str, Any]:
    result = {
        "reviewer_type": reviewer_type,
        "passed": False,
        "quality_score": 0,
        "confidence": 0,
        "summary": summary,
        "issues": [],
    }
    if raw_content:
        result["raw_content"] = raw_content
    return result


def _get_confirmed_issues(
    review_results: Iterable[Dict[str, Any]],
    *,
    issue_confidence_threshold: float,
) -> List[Dict[str, Any]]:
    confirmed = []
    for result in review_results:
        for issue in result.get("issues", []):
            severity = str(issue.get("severity") or "").lower()
            confidence = _clamp_float(issue.get("confidence"), 0, 1)
            if severity in BLOCKING_SEVERITIES and confidence >= issue_confidence_threshold:
                confirmed.append(issue)
    return confirmed


def _decide_route(
    *,
    aggregate_score: float,
    aggregate_confidence: float,
    confirmed_issues: List[Dict[str, Any]],
    thresholds: Dict[str, float],
) -> tuple[str, bool, str]:
    if aggregate_confidence < thresholds["confidence"]:
        return "skipped", False, "审查整体置信度低于阈值，跳过自动修复"
    if confirmed_issues:
        return "repairing", True, "发现高置信度阻断问题，自动路由到修复 Agent"
    if aggregate_score < thresholds["quality_score"]:
        return "repairing", True, "审查质量分低于阈值，自动路由到修复 Agent"
    return "passed", False, "审查通过，无需自动修复"


def _average(values: Iterable[float]) -> float:
    numbers = list(values)
    if not numbers:
        return 0
    return round(sum(numbers) / len(numbers), 2)


def _clamp_float(value: Any, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = minimum
    return max(minimum, min(maximum, number))
