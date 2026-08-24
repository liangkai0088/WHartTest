"""web_qa celery 任务。"""

from __future__ import annotations

import logging

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger('web_qa')


@shared_task
def run_web_qa_suite(run_id):
    """执行单个 Web QA 套件（按引擎分发）。"""
    from .models import QaRun
    from .runner import run_suite

    try:
        run = QaRun.objects.get(id=run_id)
    except QaRun.DoesNotExist:
        return {'error': f'run {run_id} not found'}

    run.status = 'running'
    run.started_at = timezone.now()
    run.save(update_fields=['status', 'started_at'])

    try:
        result = run_suite(run_id)
        logger.info('[web_qa] run %s finished: %s', run_id, result)
        return result
    except Exception as e:  # noqa: BLE001
        logger.exception('[web_qa] run %s 任务异常: %s', run_id, e)
        try:
            run.status = 'failed'
            run.error = str(e)
            run.finished_at = timezone.now()
            run.save(update_fields=['status', 'error', 'finished_at'])
        except Exception:  # noqa: BLE001
            pass
        return {'run_id': run_id, 'status': 'failed', 'error': str(e)}


@shared_task
def run_web_qa_batch(batch_id):
    """顺序执行批次内所有套件并汇总。"""
    from .models import QaBatchRun, QaRun

    try:
        batch = QaBatchRun.objects.get(id=batch_id)
    except QaBatchRun.DoesNotExist:
        return {'error': f'batch {batch_id} not found'}

    batch.status = 'running'
    batch.save(update_fields=['status'])

    suite_ids = list(batch.suite_ids or [])
    # 视图已预建 run 行；无 run 行时（直接调用任务）由任务补建
    runs = list(batch.runs.all().order_by('id'))
    if not runs:
        for suite_id in suite_ids:
            runs.append(QaRun.objects.create(
                suite_id=suite_id, batch=batch, status='pending', created_by=batch.created_by,
            ))

    summary = {'total': len(runs), 'passed': 0, 'failed': 0, 'cancelled': 0, 'pending': 0}
    results = []

    for run in runs:
        suite_id = run.suite_id
        try:
            result = run_web_qa_suite.run(run.id)
            run.refresh_from_db()
            results.append({'suite_id': suite_id, 'run_id': run.id, 'status': run.status, 'error': run.error})
            if run.status == 'passed':
                summary['passed'] += 1
            elif run.status == 'failed':
                summary['failed'] += 1
            else:
                summary['cancelled'] += 1
            logger.info('[web_qa] batch %s suite %s -> %s', batch_id, suite_id, run.status)
        except Exception as e:  # noqa: BLE001
            logger.exception('[web_qa] batch %s suite %s 异常: %s', batch_id, suite_id, e)
            results.append({'suite_id': suite_id, 'run_id': run.id, 'status': 'failed', 'error': str(e)})
            summary['failed'] += 1

    if summary['failed'] > 0 and summary['passed'] > 0:
        batch.status = 'partial'
    elif summary['failed'] > 0:
        batch.status = 'failed'
    else:
        batch.status = 'passed'
    summary['runs'] = results
    batch.summary = summary
    batch.save(update_fields=['status', 'summary', 'updated_at'])
    return {'batch_id': batch_id, 'status': batch.status, 'summary': summary}


@shared_task
def generate_web_qa_suite_from_prd(suite_id):
    """PRD → Midscene YAML 生成任务。"""
    from .prd_generator import generate_suite_from_prd

    return generate_suite_from_prd(suite_id)
