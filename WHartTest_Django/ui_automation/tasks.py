"""UI 自动化周期任务"""

import logging
import os
from datetime import datetime, timedelta, timezone

from celery import shared_task
from django.conf import settings

from .models import UiExecutionRecord

logger = logging.getLogger(__name__)


@shared_task(name='ui_automation.tasks.cleanup_ui_traces')
def cleanup_ui_traces():
    """清理 media/ui_traces 下「超过保留天数且未被执行记录引用」的 trace 文件，默认保留 14 天。"""
    try:
        retention_days = max(int(os.environ.get('UI_TRACE_RETENTION_DAYS', '14') or 14), 1)
    except (TypeError, ValueError):
        retention_days = 14

    trace_root = os.path.join(settings.MEDIA_ROOT, 'ui_traces')
    if not os.path.isdir(trace_root):
        logger.info('ui_traces 目录不存在，跳过清理: dir=%s', trace_root)
        return {
            'status': 'success',
            'retention_days': retention_days,
            'removed': 0,
            'freed_bytes': 0,
        }

    # 时间基线统一使用 UTC 感知时间，避免与本地时区混用
    cutoff_time = datetime.now(timezone.utc) - timedelta(days=retention_days)

    # 被执行记录引用的 trace 相对路径集合（trace_path 形如 ui_traces/{日期}/{文件名}）
    referenced = set()
    for path in (
        UiExecutionRecord.objects
        .exclude(trace_path__isnull=True)
        .exclude(trace_path='')
        .values_list('trace_path', flat=True)
        .iterator()
    ):
        referenced.add(str(path).replace('\\', '/').lstrip('/'))

    removed = 0
    freed_bytes = 0
    media_root = settings.MEDIA_ROOT
    for dirpath, _dirnames, filenames in os.walk(trace_root):
        for filename in filenames:
            file_path = os.path.join(dirpath, filename)
            try:
                stat = os.stat(file_path)
            except OSError:
                continue
            # 文件 mtime 转 UTC 感知时间后与截止时间比较
            mtime_dt = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
            if mtime_dt >= cutoff_time:
                continue
            rel_path = os.path.relpath(file_path, media_root).replace('\\', '/')
            if rel_path in referenced:
                continue
            try:
                os.remove(file_path)
            except OSError as exc:
                logger.warning('清理 trace 文件失败: path=%s, error=%s', file_path, exc)
                continue
            removed += 1
            freed_bytes += stat.st_size

    logger.info(
        'UI Trace 文件清理完成: retention_days=%s, cutoff_time=%s, removed=%s, freed_bytes=%s',
        retention_days,
        cutoff_time.isoformat(),
        removed,
        freed_bytes,
    )
    return {
        'status': 'success',
        'retention_days': retention_days,
        'cutoff_time': cutoff_time.isoformat(),
        'removed': removed,
        'freed_bytes': freed_bytes,
    }
