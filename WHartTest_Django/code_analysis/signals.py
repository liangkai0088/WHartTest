"""code_analysis Django signals。"""

import logging
import shutil
from pathlib import Path

from django.conf import settings
from django.db.models.signals import post_delete
from django.dispatch import receiver

logger = logging.getLogger('code_analysis')


@receiver(post_delete, sender='code_analysis.CodeProject')
def cleanup_code_project_media(sender, instance, **kwargs):
    """删除代码项目时清理持久化 git 镜像与快照媒体目录。"""
    root = Path(settings.MEDIA_ROOT) / 'code_projects' / str(instance.id)
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
        logger.info('[code_analysis] 已清理代码项目媒体目录: %s', root)
