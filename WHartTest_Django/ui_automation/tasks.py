"""UI 自动化 Celery 任务。"""

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name='ui_automation.tasks.diagnose_ui_failure')
def diagnose_ui_failure(healing_id):
    """异步执行 UI 定位失效的自愈诊断。"""
    from .self_healing import diagnose_failure

    logger.info(f"开始 UI 自愈诊断 healing={healing_id}")
    return diagnose_failure(healing_id)
