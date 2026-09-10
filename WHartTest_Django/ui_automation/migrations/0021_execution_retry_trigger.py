from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('ui_automation', '0020_remove_db2_support')]
    operations = [
        migrations.AlterField(
            model_name=model_name, name='trigger_type',
            field=models.CharField(
                choices=[('manual', '手动执行'), ('scheduled', '定时执行'), ('api', 'API 触发'), ('retry', '重试')],
                default='manual', max_length=20, verbose_name='触发类型',
            ),
        )
        for model_name in ('uibatchexecutionrecord', 'uiexecutionrecord')
    ]
