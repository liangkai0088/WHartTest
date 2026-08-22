import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ui_automation', '0020_remove_db2_support'),
    ]

    operations = [
        migrations.CreateModel(
            name='UiSelfHealingRecord',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('step_id', models.IntegerField(blank=True, null=True, verbose_name='失败步骤 ID')),
                ('failure_message', models.TextField(blank=True, verbose_name='失败信息')),
                ('status', models.CharField(choices=[('pending', '待诊断'), ('diagnosing', '诊断中'), ('healed', '已自愈'), ('failed', '自愈失败'), ('ignored', '已忽略')], default='pending', max_length=20, verbose_name='状态')),
                ('diagnosis', models.JSONField(blank=True, default=dict, verbose_name='诊断结果')),
                ('fix_summary', models.JSONField(blank=True, default=dict, verbose_name='回写摘要')),
                ('rerun_batch_id', models.IntegerField(blank=True, null=True, verbose_name='重跑批次 ID')),
                ('rerun_success', models.BooleanField(blank=True, null=True, verbose_name='重跑是否成功')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='创建时间')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='更新时间')),
                ('element', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='self_healing_records', to='ui_automation.uielement', verbose_name='目标元素')),
                ('execution_record', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='self_healing_records', to='ui_automation.uiexecutionrecord', verbose_name='关联执行记录')),
                ('test_case', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='self_healing_records', to='ui_automation.uitestcase', verbose_name='关联用例')),
            ],
            options={
                'verbose_name': 'UI 自愈记录',
                'verbose_name_plural': 'UI 自愈记录',
                'ordering': ['-created_at'],
                'db_table': 'ui_self_healing_record',
                'indexes': [
                    models.Index(fields=['status', 'created_at'], name='ui_heal_status_created_idx'),
                ],
            },
        ),
    ]
