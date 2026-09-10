import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('task_center', '0004_remove_executing_status'),
        ('ui_automation', '0003_add_batch_execution_record'),
        ('testcases', '0008_testsuite_testexecution_testcaseresult'),
    ]

    operations = [
        migrations.AddField(
            model_name='taskexecution', name='ui_batch',
            field=models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                       related_name='task_execution', to='ui_automation.uibatchexecutionrecord', verbose_name='UI执行批次'),
        ),
        migrations.AddField(
            model_name='taskexecution', name='suite_execution',
            field=models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                       related_name='scheduled_task_execution', to='testcases.testexecution', verbose_name='套件执行记录'),
        ),
        migrations.AddField(
            model_name='taskexecution', name='retry_of',
            field=models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                       related_name='retry_execution', to='task_center.taskexecution', verbose_name='重试来源'),
        ),
        migrations.AddField(model_name='taskexecution', name='retry_attempt', field=models.PositiveSmallIntegerField(default=0, verbose_name='当前重试次数')),
        migrations.AddField(model_name='taskexecution', name='retry_limit', field=models.PositiveSmallIntegerField(default=0, verbose_name='本轮重试上限')),
        migrations.AddField(model_name='taskexecution', name='retry_interval', field=models.PositiveSmallIntegerField(default=1, verbose_name='本轮重试间隔(分钟)')),
        migrations.AlterField(
            model_name='taskexecution', name='trigger_type',
            field=models.CharField(max_length=10, choices=[('scheduled', '定时调度'), ('manual', '手动执行'), ('api', 'API 触发'), ('retry', '重试')], verbose_name='触发方式'),
        ),
    ]
