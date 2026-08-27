"""分布式压测调度：worker 拉取(claim)、进度上报、结果回传的纯逻辑封装。

设计要点
--------
- pull 模型：worker 主动轮询 ``/api/perf-test/nodes/<id>/claim/`` 领任务，无需 master 推送。
- 原子认领：用 ``WHERE status='pending'`` 的条件更新防止多 worker 并发抢同一任务。
- 复用 ``render_locustfile``/``parse_locust_*`` 与既有 WS 推送，节点侧无需访问数据库。
"""

import logging

from django.conf import settings
from django.db import transaction

from .models import PerfTestExecution, PerfTestNode, PerfTestReport
from .push import push_execution_update
from .runner import load_execution_context

logger = logging.getLogger(__name__)


def distributed_enabled():
    """分布式施压总开关。"""
    return bool(getattr(settings, 'PERF_DISTRIBUTED_ENABLED', True))


def build_task_payload(execution):
    """为一次执行构建下发给 worker 的任务负载（含渲染后的 locustfile）。"""
    ctx = load_execution_context(execution)
    return {
        'execution_id': execution.id,
        'host': ctx['host'],
        'users': ctx['users'],
        'spawn_rate': ctx['spawn_rate'],
        'duration': ctx['duration'],
        'locustfile': ctx['locustfile'],
    }


def nodes_available(node):
    """节点是否可接单：在线才派发。"""
    return node is not None and node.status == 'online'


def claim_task(node_id):
    """认领绑定到某节点的一个待执行任务。

    :return: (execution, payload) 或 (None, None) —— 无任务时。
    """
    try:
        node = PerfTestNode.objects.get(id=node_id)
    except PerfTestNode.DoesNotExist:
        return None, None
    if not nodes_available(node):
        return None, None

    with transaction.atomic():
        execution = (
            PerfTestExecution.objects.select_for_update()
            .filter(node_id=node_id, status='pending')
            .order_by('created_at')
            .first()
        )
        if execution is None:
            return None, None
        # 原子认领：仅当仍处于 pending 时才置为 running，避免多 worker 重复领取。
        updated = PerfTestExecution.objects.filter(
            id=execution.id, status='pending'
        ).update(status='running')
        if not updated:
            return None, None
        execution.refresh_from_db()

    execution.start()
    payload = build_task_payload(execution)
    logger.info(f"节点 {node_id} 认领任务 execution={execution.id}")
    return execution, payload


def apply_progress(execution_id, progress, rps, users):
    """更新执行进度并推送实时面板，仅认领后的 running 任务生效。"""
    PerfTestExecution.objects.filter(
        id=execution_id, status='running'
    ).update(progress=progress)
    push_execution_update(
        execution_id,
        {'progress': progress, 'rps': rps or 0, 'users': users or 0},
    )


def apply_report(execution_id, stats, series, error=''):
    """worker 回传结果：成功则落库报告并完成，失败则标记失败。

    :param stats: 已解析的性能指标字典（与 PerfTestReport 字段对齐）。
    :param series: RPS 时序列表 [{time, rps}]。
    :param error: 失败信息；非空则执行失败。
    """
    execution = PerfTestExecution.objects.filter(id=execution_id).first()
    if execution is None:
        logger.warning(f"apply_report 找不到执行 execution={execution_id}")
        return None

    if error:
        execution.fail(error)
        return None

    metrics = dict(stats or {})
    metrics['rps_series'] = series or []
    report, _ = PerfTestReport.objects.update_or_create(
        execution=execution, defaults=metrics
    )
    execution.complete()
    logger.info(f"分布式结果已落库 report={report.id} execution={execution_id}")

    try:
        from .tasks import diagnose_perf_report

        diagnose_perf_report.delay(report.id)
    except Exception:
        logger.warning(f"触发 AI 诊断失败 report={report.id}", exc_info=True)
    return report.id
