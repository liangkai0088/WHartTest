"""幂等注册/移除 code_analysis git 同步的 django-celery-beat 定时任务。

用法：
  python manage.py register_git_sync_beat            # 注册（每日 03:00）
  python manage.py register_git_sync_beat --disable  # 移除
"""

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = '注册/移除 code_analysis git 同步的 django-celery-beat 定时任务'

    def add_arguments(self, parser):
        parser.add_argument('--disable', action='store_true', help='移除定时任务')

    def handle(self, *args, **options):
        from code_analysis.beat import register_git_sync_beat, unregister_git_sync_beat

        if options['disable']:
            deleted = unregister_git_sync_beat()
            self.stdout.write(self.style.SUCCESS(f'已移除 {deleted} 个 beat 条目'))
            return
        name = register_git_sync_beat()
        self.stdout.write(self.style.SUCCESS(f'已注册 beat 条目: {name}'))
