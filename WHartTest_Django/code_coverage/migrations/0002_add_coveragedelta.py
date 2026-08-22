import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '__first__'),
        ('code_coverage', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='CoverageDelta',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('git_commit', models.CharField(max_length=64, verbose_name='Git Commit')),
                ('base_commit', models.CharField(blank=True, max_length=64, null=True, verbose_name='基线 Commit')),
                ('summary', models.JSONField(blank=True, default=dict, verbose_name='增量汇总')),
                ('files', models.JSONField(blank=True, default=list, verbose_name='文件级增量明细')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='创建时间')),
                ('base_report', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='base_deltas', to='code_coverage.coveragereport', verbose_name='基线报告')),
                ('project', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='coverage_deltas', to='projects.project', verbose_name='所属项目')),
                ('report', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='deltas', to='code_coverage.coveragereport', verbose_name='当前提交报告')),
                ('uploader', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='uploaded_coverage_deltas', to=settings.AUTH_USER_MODEL, verbose_name='生成人')),
            ],
            options={
                'verbose_name': '增量覆盖率',
                'verbose_name_plural': '增量覆盖率',
                'ordering': ['-created_at'],
                'indexes': [
                    models.Index(fields=['project', 'git_commit'], name='cov_delta_proj_commit_idx'),
                ],
            },
        ),
    ]
