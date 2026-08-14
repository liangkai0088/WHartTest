"""套件执行分发器：按 suite.engine 路由到对应引擎。"""

from __future__ import annotations

import logging

from .yaml_loader import count_tests

logger = logging.getLogger('web_qa')


def run_suite(run_id: int) -> dict:
    """按套件引擎分发执行。"""
    from .models import QaRun

    try:
        run = QaRun.objects.select_related('suite').get(id=run_id)
    except QaRun.DoesNotExist:
        return {'error': f'run {run_id} not found'}

    if run.suite.engine == 'midscene':
        from .midscene import run_midscene
        return run_midscene(run_id)

    from .runner_agent_browser import run_agent_browser_suite
    return run_agent_browser_suite(run_id)


def update_test_count(suite) -> int:
    """保存时计算 test_count（yaml_loader 容忍解析）。"""
    try:
        count = count_tests(suite.yaml_content or '')
    except Exception as e:  # noqa: BLE001
        logger.warning('[web_qa] test_count 计算失败 suite=%s: %s', suite.id, e)
        count = 0
    suite.test_count = count
    try:
        suite.save(update_fields=['test_count'])
    except Exception as e:  # noqa: BLE001
        logger.warning('[web_qa] test_count 保存失败 suite=%s: %s', suite.id, e)
    return count
