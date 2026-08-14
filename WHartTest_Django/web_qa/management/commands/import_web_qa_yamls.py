"""导入 web-qa-bot yaml 目录为 QaSuite。

用法：
  python manage.py import_web_qa_yamls <dir> <group> [--project-id N] [--engine agent_browser|midscene]
"""

from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from web_qa.yaml_loader import count_tests


class Command(BaseCommand):
    help = '导入目录下 *.yaml 为 web_qa 套件'

    def add_arguments(self, parser):
        parser.add_argument('dir', help='yaml 文件目录')
        parser.add_argument('group', help='套件分组，如 car_web')
        parser.add_argument('--project-id', type=int, default=None, help='目标项目 ID（缺省取第一个项目）')
        parser.add_argument('--engine', default='agent_browser', choices=['agent_browser', 'midscene'], help='执行引擎')

    def handle(self, *args, **options):
        from projects.models import Project
        from web_qa.models import QaSuite
        from web_qa.yaml_loader import parse_suite

        src_dir = Path(options['dir'])
        if not src_dir.is_dir():
            raise CommandError(f'目录不存在: {src_dir}')

        project = None
        if options['project_id']:
            project = Project.objects.filter(id=options['project_id']).first()
            if project is None:
                raise CommandError(f'项目不存在: {options["project_id"]}')
        else:
            project = Project.objects.first()
            if project is None:
                raise CommandError('无任何项目，请先创建项目或指定 --project-id')

        engine = options['engine']
        group = options['group']
        files = sorted(src_dir.glob('*.yaml')) + sorted(src_dir.glob('*.yml'))

        if not files:
            self.stdout.write(self.style.WARNING('目录下无 *.yaml / *.yml 文件'))

        imported = 0
        for path in files:
            try:
                content = path.read_text(encoding='utf-8')
            except Exception as e:  # noqa: BLE001
                self.stderr.write(f'跳过 {path.name}: 读取失败 {e}')
                continue

            suite_info = parse_suite(content, tolerant=True)
            name = suite_info.name or path.stem

            suite = QaSuite.objects.create(
                project=project,
                name=name[:200],
                group=group,
                engine=engine,
                base_url=suite_info.base_url or '',
                description='',
                yaml_content=content,
                source='manual',
                status='ready',
            )
            suite.test_count = count_tests(content)
            suite.save(update_fields=['test_count'])
            imported += 1
            self.stdout.write(f'已导入: {name} (tests={suite.test_count}, engine={engine})')

        self.stdout.write(self.style.SUCCESS(f'完成，共导入 {imported} 个套件到项目 "{project.name}" 分组 "{group}"'))
