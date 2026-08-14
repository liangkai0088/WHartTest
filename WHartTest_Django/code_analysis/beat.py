"""code_analysis git 同步调度注册（django-celery-beat DB 调度器）。

项目约定：不使用 settings 级 CELERY_BEAT_SCHEDULE，
而是通过 django-celery-beat 的 PeriodicTask 数据库行（见 task_center/scheduler.py）。
"""

import logging

from django.utils import timezone
from django_celery_beat.models import CrontabSchedule, PeriodicTask

logger = logging.getLogger('code_analysis')

GIT_SYNC_TASK = 'code_analysis.tasks.sync_all_git_code_projects'
GIT_SYNC_BEAT_NAME = 'code_analysis_git_sync_daily'
GIT_SYNC_DESCRIPTION = '每日同步 git 代码项目（源码级 AI 智能分析）'

# 每日 03:00 执行一次
GIT_SYNC_SCHEDULE = {
    'minute': '0',
    'hour': '3',
    'day_of_week': '*',
    'day_of_month': '*',
    'month_of_year': '*',
}


def register_git_sync_beat(enabled: bool = True) -> str:
    """幂等创建/更新 git 同步的 PeriodicTask 行，返回 beat 条目名称。"""
    crontab_kwargs = dict(GIT_SYNC_SCHEDULE)
    crontab_kwargs['timezone'] = timezone.get_current_timezone()
    crontab, _ = CrontabSchedule.objects.get_or_create(**crontab_kwargs)

    PeriodicTask.objects.update_or_create(
        name=GIT_SYNC_BEAT_NAME,
        defaults={
            'task': GIT_SYNC_TASK,
            'args': '[]',
            'kwargs': '{}',
            'crontab': crontab,
            'interval': None,
            'clocked': None,
            'enabled': enabled,
            'description': GIT_SYNC_DESCRIPTION,
        },
    )
    logger.info('[code_analysis] beat entry registered: %s', GIT_SYNC_BEAT_NAME)
    return GIT_SYNC_BEAT_NAME


def unregister_git_sync_beat() -> int:
    """移除 git 同步的 PeriodicTask 行，返回删除数量。"""
    deleted, _ = PeriodicTask.objects.filter(name=GIT_SYNC_BEAT_NAME).delete()
    if deleted:
        logger.info('[code_analysis] beat entry removed: %s', GIT_SYNC_BEAT_NAME)
    return deleted
