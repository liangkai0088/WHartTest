"""使用 `midscene model verify` 校验 LLMConfig 视觉连通性。

用法：
  python manage.py verify_midscene_model <llm_config_id>

按 web_qa.midscene.build_env 为指定 LLMConfig 构造运行时环境变量
（含自动探测的 MIDSCENE_MODEL_FAMILY），执行 `midscene model verify`
（text / vision / aiLocate 三项连通性检查），输出结果。
"""

from __future__ import annotations

import os
import subprocess

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = '使用 midscene model verify 校验 LLMConfig 的模型连通性（含 modelFamily 探测）'

    def add_arguments(self, parser):
        parser.add_argument('llm_config_id', type=int, help='langgraph_integration.LLMConfig 的 ID')
        parser.add_argument(
            '--timeout', type=int, default=180, help='verify 命令超时（秒，默认 180）',
        )

    def handle(self, *args, **options):
        from langgraph_integration.models import LLMConfig
        from web_qa.midscene import build_env, MIDSCENE_BIN

        llm_config = LLMConfig.objects.filter(id=options['llm_config_id']).first()
        if llm_config is None:
            raise CommandError(f'LLMConfig {options["llm_config_id"]} 不存在')

        env = build_env(llm_config)

        self.stdout.write('== LLMConfig ==')
        self.stdout.write(f'  model     : {getattr(llm_config, "name", "")}')
        self.stdout.write(f'  base_url  : {getattr(llm_config, "api_url", "")}')
        self.stdout.write(f'  provider  : {getattr(llm_config, "provider", "")}')
        self.stdout.write(f'  vision    : {getattr(llm_config, "supports_vision", False)}')
        self.stdout.write(f'  family    : {env.get("MIDSCENE_MODEL_FAMILY", "(未设置)")}')
        self.stdout.write('')
        self.stdout.write('== midscene model verify ==')
        self.stdout.flush()

        try:
            result = subprocess.run(
                [MIDSCENE_BIN, 'model', 'verify'],
                env=env,
                capture_output=True,
                text=True,
                timeout=options['timeout'],
            )
        except subprocess.TimeoutExpired:
            raise CommandError(f'midscene model verify 超时（{options["timeout"]}s）')
        except FileNotFoundError:
            raise CommandError(
                'midscene CLI 不存在，请先执行: npm install -g @midscene/cli'
            )

        output = (result.stdout or '').strip()
        if result.stderr:
            output = f'{output}\n--- stderr ---\n{result.stderr.strip()}'

        self.stdout.write(output or '(无输出)')

        if result.returncode == 0 and 'failed' not in output.lower():
            self.stdout.write(self.style.SUCCESS('== 校验完成：模型配置可用 =='))
        else:
            self.stdout.write(self.style.WARNING(
                '== 校验未通过：请检查 base_url / api_key / modelFamily =='
            ))
            if result.returncode != 0:
                raise CommandError(f'midscene model verify 退出码 {result.returncode}')
