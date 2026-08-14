import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ('projects', '__first__'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='CoverageReport',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('name', models.CharField(max_length=200, verbose_name='报告名称')),
                ('format', models.CharField(choices=[('cobertura', 'Cobertura XML'), ('lcov', 'LCOV')], max_length=20, verbose_name='报告格式')),
                ('test_type', models.CharField(choices=[('api', '接口自动化'), ('ui', 'UI 自动化'), ('unit', '单元测试'), ('manual', '手工测试')], default='api', max_length=20, verbose_name='测试类型')),
                ('test_execution_ref', models.CharField(blank=True, help_text='关联的测试执行记录标识', max_length=200, null=True, verbose_name='关联测试执行')),
                ('git_commit', models.CharField(blank=True, max_length=64, null=True, verbose_name='Git Commit')),
                ('status', models.CharField(choices=[('processing', '处理中'), ('completed', '已完成'), ('failed', '失败')], default='processing', max_length=20, verbose_name='状态')),
                ('error_message', models.TextField(blank=True, null=True, verbose_name='错误信息')),
                ('summary', models.JSONField(blank=True, default=dict, verbose_name='汇总指标')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='创建时间')),
                ('project', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='coverage_reports', to='projects.project', verbose_name='所属项目')),
                ('uploader', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='uploaded_coverage_reports', to=settings.AUTH_USER_MODEL, verbose_name='上传人')),
            ],
            options={
                'verbose_name': '覆盖率报告',
                'verbose_name_plural': '覆盖率报告',
                'ordering': ['-created_at'],
                'indexes': [
                    models.Index(fields=['project', 'created_at'], name='cov_report_proj_created_idx'),
                ],
            },
        ),
        migrations.CreateModel(
            name='CoverageFile',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('file_path', models.CharField(max_length=500, verbose_name='文件路径')),
                ('line_coverage', models.FloatField(default=0, verbose_name='行覆盖率(%)')),
                ('branch_coverage', models.FloatField(blank=True, null=True, verbose_name='分支覆盖率(%)')),
                ('lines_total', models.IntegerField(default=0, verbose_name='总行数')),
                ('lines_covered', models.IntegerField(default=0, verbose_name='覆盖行数')),
                ('lines_detail', models.JSONField(blank=True, default=dict, verbose_name='行级明细')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='创建时间')),
                ('report', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='files', to='code_coverage.coveragereport', verbose_name='所属报告')),
            ],
            options={
                'verbose_name': '覆盖率文件明细',
                'verbose_name_plural': '覆盖率文件明细',
                'ordering': ['file_path'],
                'indexes': [
                    models.Index(fields=['report', 'file_path'], name='cov_file_report_path_idx'),
                ],
            },
        ),
    ]
