"""Task results follow the actual execution, not the dispatch response."""

import json
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from django_celery_beat.models import ClockedSchedule, PeriodicTask

from .models import ScheduledTask, TaskExecution


def append_execution_log(execution_id, message):
    with transaction.atomic():
        execution = TaskExecution.objects.select_for_update().get(pk=execution_id)
        execution.log += f"\n[{timezone.now().isoformat()}] {message}"
        execution.save(update_fields=['log'])


def finish_execution(execution_id, *, success, message, finished_at=None, allow_retry=True):
    # Finalization and retry registration commit together. Repeated results
    # must not reset the retry timer or register another attempt.
    with transaction.atomic():
        execution = TaskExecution.objects.select_for_update().get(pk=execution_id)
        if execution.status != TaskExecution.ExecutionStatus.RUNNING:
            return
        task = execution.task
        execution.status = 'success' if success else 'failed'
        execution.finished_at = finished_at or timezone.now()
        execution.error_message = '' if success else message
        execution.log += f"\n[{execution.finished_at.isoformat()}] {message}"

        if not success and allow_retry and execution.retry_attempt < execution.retry_limit:
            retry_at = execution.finished_at + timedelta(minutes=execution.retry_interval)
            clocked, _ = ClockedSchedule.objects.get_or_create(clocked_time=retry_at)
            PeriodicTask.objects.create(
                name=f'task_retry_{execution.id}',
                task='task_center.tasks.execute_scheduled_task',
                args=json.dumps([task.id, 'retry']),
                kwargs=json.dumps({'retry_of_id': execution.id}),
                queue='task_center', clocked=clocked, one_off=True, enabled=True,
            )
            execution.log += (
                f"\n已安排第 {execution.retry_attempt + 1}/{execution.retry_limit} 次重试，"
                f"间隔 {execution.retry_interval} 分钟，计划时间 {retry_at.isoformat()}"
            )
        elif task.schedule_type == ScheduledTask.ScheduleType.ONCE:
            ScheduledTask.objects.filter(pk=task.pk).update(status=ScheduledTask.TaskStatus.DISABLED)

        execution.save(update_fields=['status', 'finished_at', 'error_message', 'log'])


def sync_batch_result(batch_id):
    from ui_automation.models import UiBatchExecutionRecord

    batch = UiBatchExecutionRecord.objects.filter(pk=batch_id).first()
    if batch is None or batch.status not in (2, 3, 4):
        return
    execution_id = TaskExecution.objects.filter(ui_batch_id=batch_id).values_list('id', flat=True).first()
    if execution_id is not None:
        success = batch.status == 2
        finish_execution(
            execution_id, success=success, finished_at=batch.end_time,
            message=f"批次 {batch.id} 执行{'成功' if success else '失败'}："
                    f"通过 {batch.passed_cases}，失败 {batch.failed_cases}，共 {batch.total_cases} 条用例",
        )


def sync_suite_result(suite_execution_id):
    from testcases.models import TestExecution

    result = TestExecution.objects.filter(pk=suite_execution_id).first()
    if result is None or result.status not in ('completed', 'failed', 'cancelled'):
        return
    execution_id = TaskExecution.objects.filter(suite_execution_id=result.id).values_list('id', flat=True).first()
    if execution_id is not None:
        success = result.status == 'completed' and result.failed_count == 0 and result.error_count == 0
        finish_execution(
            execution_id, success=success, finished_at=result.completed_at,
            allow_retry=result.status != 'cancelled',
            message=f"套件执行 {result.id} {'成功' if success else '未通过'}："
                    f"通过 {result.passed_count}，失败 {result.failed_count}，错误 {result.error_count}",
        )
