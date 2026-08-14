"""
执行进度看板服务层。

- emit_execution_event: 事件日志 + WebSocket 推送的唯一出口（永不抛异常）
- compute_eta: 剩余时间估算
"""
import logging
from statistics import median

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.utils import timezone

from .models import ExecutionEventLog

logger = logging.getLogger(__name__)

# 单用例历史 EWMA 平滑系数
EWMA_ALPHA = 0.3
# 单用例历史最多取最近完成的 N 条
PER_CASE_HISTORY_LIMIT = 10
# 套件级兜底历史最多取最近完成的 N 条
SUITE_HISTORY_LIMIT = 20
# 无任何历史时的默认单节点估算（秒）
DEFAULT_NODE_ESTIMATE = 60.0


def _build_envelope(event_type, payload):
    """构建 WS 扁平信封: {"event","ts","data"}"""
    return {
        "event": event_type,
        "ts": timezone.now().isoformat(),
        "data": payload,
    }


def emit_execution_event(run, event_type, *, node_id=None, status="", payload=None):
    """
    记录执行事件日志并推送 WebSocket 消息。

    这是日志与实时推送的唯一来源。任何一步失败都不影响测试执行：
    数据库写入与 WS 推送各自独立 try/except。
    """
    payload = dict(payload or {})
    # 自动补充 run_id 与 project_id（幂等：调用方显式传入时不覆盖）
    payload.setdefault("run_id", run.id)
    try:
        payload.setdefault("project_id", run.suite.project_id)
    except Exception:  # 防御：suite 关系异常时不阻塞事件
        logger.exception("无法获取 run=%s 的 project_id", run.id)

    # 1. 持久化事件日志
    try:
        ExecutionEventLog.objects.create(
            run=run,
            node_id=node_id,
            event_type=event_type,
            status=status,
            payload=payload,
        )
    except Exception:
        logger.exception("写入 ExecutionEventLog 失败: run=%s event=%s", run.id, event_type)

    # 2. 推送 WebSocket 消息
    try:
        channel_layer = get_channel_layer()
        if channel_layer is None:
            return
        project_id = payload.get("project_id")
        if project_id is None:
            return
        message = _build_envelope(event_type, payload)
        # channels 要求事件 dict 携带 type 键，对应 consumer 的 exec_dash_event 方法
        message["type"] = "exec_dash_event"
        async_to_sync(channel_layer.group_send)(
            f"exec_dash_proj_{project_id}", message
        )
    except Exception:
        logger.exception("推送 WS 事件失败: run=%s event=%s", run.id, event_type)


def _ewma(values):
    """EWMA(α=0.3) 平滑。values 按时间从旧到新排列。"""
    if not values:
        return None
    avg = values[0]
    for value in values[1:]:
        avg = EWMA_ALPHA * value + (1 - EWMA_ALPHA) * avg
    return avg


def _median(values):
    if not values:
        return None
    return median(values)


def _per_case_history(testcase_id):
    """同一测试用例最近完成的 ≤10 条耗时（pass/fail/error，旧→新）。"""
    from testcases.models import TestCaseResult

    return list(
        TestCaseResult.objects.filter(
            testcase_id=testcase_id,
            execution_time__isnull=False,
            status__in=["pass", "fail", "error"],
        )
        .order_by("id")[:PER_CASE_HISTORY_LIMIT]
        .values_list("execution_time", flat=True)
    )


def _suite_fallback_history(execution):
    """同一测试套件最近完成的 ≤20 条耗时（pass/fail/error，最新在前取中位数）。"""
    from testcases.models import TestCaseResult

    return list(
        TestCaseResult.objects.filter(
            execution__suite=execution.suite,
            execution_time__isnull=False,
            status__in=["pass", "fail", "error"],
        )
        .order_by("-id")[:SUITE_HISTORY_LIMIT]
        .values_list("execution_time", flat=True)
    )


def compute_eta(execution):
    """
    估算执行剩余时间。

    - 单用例 EWMA(α=0.3) 最近 ≤10 条同用例历史；无历史时用同套件最近 ≤20 条中位数；再无则 60s
    - 本轮已完成 ≥1 条时，E(c) = 0.7 * EWMA + 0.3 * 本轮已完成平均耗时
    - remaining = Σ E(c)（pending ∪ running）/ suite.max_concurrent_tasks
    - eta_seconds = 已耗时 + remaining
    """
    from testcases.models import TestCaseResult

    total = execution.total_count or 0
    results = list(
        TestCaseResult.objects.filter(execution=execution).only(
            "testcase_id", "status", "execution_time"
        )
    )

    completed = [r for r in results if r.status in ("pass", "fail", "error", "skip")]
    pending_running = [r for r in results if r.status in ("pending", "running")]

    progress = len(completed) / total if total else 0.0

    # 本轮已完成节点平均耗时（in-run blend 使用）
    completed_times = [r.execution_time for r in completed if r.execution_time is not None]
    run_mean = (sum(completed_times) / len(completed_times)) if completed_times else None

    # 套件级兜底中位数（惰性计算，首次需要时才查询）
    suite_median = None

    # 单用例历史缓存（同一用例在本轮可能出现在多个结果节点中，避免重复查询）
    history_cache = {}

    def _history(testcase_id):
        if testcase_id not in history_cache:
            history_cache[testcase_id] = _per_case_history(testcase_id)
        return history_cache[testcase_id]

    # 逐个 pending/running 节点估算耗时
    remaining = 0.0
    per_case_history_count = 0
    has_any_node = bool(pending_running)

    for r in pending_running:
        history = _history(r.testcase_id)
        per_case_history_count = max(per_case_history_count, len(history))
        estimate = _ewma(history)
        if estimate is None and suite_median is None:
            suite_median = _median(_suite_fallback_history(execution))
        if estimate is None:
            estimate = suite_median
        if estimate is None:
            estimate = DEFAULT_NODE_ESTIMATE
        if run_mean is not None:
            estimate = 0.7 * estimate + 0.3 * run_mean
        remaining += estimate

    # 本轮已无待执行节点（执行完成）时，用已完成节点的历史量评估置信度
    if not pending_running:
        for r in completed:
            per_case_history_count = max(
                per_case_history_count, len(_history(r.testcase_id))
            )

    if has_any_node:
        max_concurrent = getattr(execution.suite, "max_concurrent_tasks", None) or 1
        remaining /= max_concurrent
    else:
        remaining = 0.0

    elapsed = 0.0
    if execution.started_at:
        elapsed = (timezone.now() - execution.started_at).total_seconds()

    eta_seconds = elapsed + remaining

    # 置信度：单用例历史(全部节点中最大历史量) ≥5 且完成 ≥20% => high；
    # 有任意单用例历史 => medium；否则 low
    if per_case_history_count >= 5 and progress >= 0.2:
        confidence = "high"
    elif per_case_history_count >= 1:
        confidence = "medium"
    else:
        confidence = "low"

    return {
        "eta_seconds": round(eta_seconds, 1),
        "remaining_seconds": round(remaining, 1),
        "confidence": confidence,
        "progress": round(progress, 4),
    }
