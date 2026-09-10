"""Celery entry point for scheduled executions and persisted retry attempts."""

import logging

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from .execution_service import append_execution_log, finish_execution, sync_batch_result
from .models import ScheduledTask, TaskExecution

logger = logging.getLogger(__name__)


@shared_task(bind=True, name='task_center.tasks.execute_scheduled_task')
def execute_scheduled_task(self, task_id: int, trigger_type: str = 'scheduled', retry_of_id=None):
    try:
        task = ScheduledTask.objects.get(id=task_id)
    except ScheduledTask.DoesNotExist:
        return {'status': 'error', 'message': f'任务 {task_id} 不存在'}

    if task.status == ScheduledTask.TaskStatus.DISABLED and trigger_type == 'scheduled':
        return {'status': 'skipped', 'message': '任务已禁用'}

    with transaction.atomic():
        if retry_of_id is None and self.request.id:
            ScheduledTask.objects.select_for_update().get(pk=task.pk)
            if TaskExecution.objects.filter(task=task, celery_task_id=self.request.id).exists():
                return {'status': 'skipped', 'message': '本次任务已经启动'}
        defaults = {
            'task': task, 'trigger_type': trigger_type,
            'status': TaskExecution.ExecutionStatus.RUNNING,
            'celery_task_id': self.request.id or '',
            'retry_limit': task.retry_count if task.retry_enabled else 0,
            'retry_interval': task.retry_interval,
        }
        if retry_of_id is not None:
            parent = TaskExecution.objects.select_for_update().filter(pk=retry_of_id, task=task).first()
            if parent is None or parent.status != 'failed' or parent.retry_attempt >= parent.retry_limit:
                return {'status': 'skipped', 'message': '重试来源无效或已达到次数上限'}
            if TaskExecution.objects.filter(retry_of=parent).exists():
                return {'status': 'skipped', 'message': '本次重试已经启动'}
            defaults.update(
                trigger_type='retry', retry_of=parent, retry_attempt=parent.retry_attempt + 1,
                retry_limit=parent.retry_limit, retry_interval=parent.retry_interval,
            )
        elif trigger_type == 'retry':
            return {'status': 'error', 'message': '重试必须指定来源执行记录'}
        execution = TaskExecution.objects.create(**defaults)

    ScheduledTask.objects.filter(pk=task.pk).update(last_run_at=timezone.now())
    append_execution_log(execution.pk, f'开始执行任务: {task.name}，触发方式: {execution.get_trigger_type_display()}')

    try:
        if task.module == ScheduledTask.TaskModule.UI_AUTOMATION:
            import requests
            from django.conf import settings
            from rest_framework_simplejwt.tokens import RefreshToken

            case_ids = list(task.ui_testcases.values_list('id', flat=True))
            if not case_ids:
                raise ValueError('未关联任何 UI 自动化用例')
            token = str(RefreshToken.for_user(task.creator).access_token)
            response = requests.post(
                f'{settings.BASE_URL}/api/ui-automation/trigger-batch/',
                json={
                    'case_ids': case_ids, 'actuator_id': task.actuator_id,
                    'batch_name': f'定时任务-{task.name}',
                    'trigger_type': execution.trigger_type, 'task_execution_id': execution.id,
                },
                headers={'Authorization': f'Bearer {token}'}, timeout=30,
            )
            if response.status_code >= 400:
                raise ValueError(f'触发批量执行失败，响应状态码: {response.status_code}')
            data = response.json().get('data', {})
            # Accept the old doubly wrapped response during rolling updates.
            batch_id = data.get('batch_id') or data.get('data', {}).get('batch_id')
            execution.refresh_from_db()
            if not batch_id or execution.ui_batch_id != batch_id:
                raise ValueError('批量执行响应缺少有效的任务批次关联')
            append_execution_log(execution.pk, f'批量执行已提交: batch_id={batch_id}，等待执行器返回最终结果')
            sync_batch_result(batch_id)

        elif task.module == ScheduledTask.TaskModule.TEST_SUITE:
            from testcases.models import TestExecution
            from testcases.tasks import execute_test_suite

            if not task.test_suite_id:
                raise ValueError('未关联测试套件')
            with transaction.atomic():
                suite_execution = TestExecution.objects.create(suite=task.test_suite, executor=task.creator, status='pending')
                TaskExecution.objects.filter(pk=execution.pk).update(suite_execution=suite_execution)
            execute_test_suite.delay(suite_execution.id)
            append_execution_log(execution.pk, f'套件执行已提交: execution_id={suite_execution.id}，等待最终结果')
        else:
            raise ValueError('不支持的任务模块')

    except Exception as exc:
        logger.exception('任务 [%s] 提交失败', task.name)
        execution.refresh_from_db()
        if execution.ui_batch_id:
            # A request may time out after dispatch. Never submit a second
            # batch while the linked batch is still running.
            append_execution_log(execution.pk, f'提交响应异常: {exc}；已关联批次，继续等待实际结果')
            sync_batch_result(execution.ui_batch_id)
        else:
            finish_execution(execution.pk, success=False, message=f'提交执行失败: {exc}')

    execution.refresh_from_db()
    return {'status': execution.status, 'execution_id': execution.execution_id}
