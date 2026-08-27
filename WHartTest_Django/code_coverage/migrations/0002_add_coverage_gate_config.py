from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('code_coverage', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='CoverageGateConfig',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('enabled', models.BooleanField(default=False, verbose_name='启用门禁')),
                ('min_line_coverage', models.FloatField(default=80.0, verbose_name='最小行覆盖率阈值(%)')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='创建时间')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='更新时间')),
                ('project', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='coverage_gate', to='projects.project', verbose_name='所属项目')),
            ],
            options={
                'verbose_name': '覆盖率门禁配置',
                'verbose_name_plural': '覆盖率门禁配置',
                'ordering': ['-created_at'],
            },
        ),
    ]
