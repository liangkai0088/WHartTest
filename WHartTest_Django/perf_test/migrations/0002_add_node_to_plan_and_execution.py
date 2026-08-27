import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('perf_test', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='perftestplan',
            name='node',
            field=models.ForeignKey(
                blank=True,
                help_text='可选，指定本次压测绑定的节点；为空则使用后端本地执行',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='perf_test_plans',
                to='perf_test.perftestnode',
                verbose_name='目标施压节点',
            ),
        ),
        migrations.AddField(
            model_name='perftestexecution',
            name='node',
            field=models.ForeignKey(
                blank=True,
                help_text='记录本次压测实际绑定的节点',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='perf_test_executions',
                to='perf_test.perftestnode',
                verbose_name='执行节点',
            ),
        ),
    ]
