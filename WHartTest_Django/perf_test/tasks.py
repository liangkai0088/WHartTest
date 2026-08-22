"""性能测试 Celery 任务入口。"""

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name='perf_test.tasks.run_perf_test')
def run_perf_test(execution_id):
    """异步执行一次压测。"""
    from .runner import run_perf_test as _run

    logger.info(f"开始执行压测 execution={execution_id}")
    return _run(execution_id)


@shared_task(name='perf_test.tasks.diagnose_perf_report')
def diagnose_perf_report(report_id):
    """异步对压测报告执行 AI 诊断。"""
    from .diagnose import diagnose_report

    logger.info(f"开始 AI 诊断压测报告 report={report_id}")
    return diagnose_report(report_id)
