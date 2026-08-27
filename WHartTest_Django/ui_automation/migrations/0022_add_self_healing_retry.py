from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ui_automation', '0021_add_self_healing_record'),
    ]

    operations = [
        migrations.AddField(
            model_name='uiselfhealingrecord',
            name='max_retry',
            field=models.IntegerField(default=0, verbose_name='最大自愈重试次数'),
        ),
        migrations.AddField(
            model_name='uiselfhealingrecord',
            name='retry_count',
            field=models.IntegerField(default=0, verbose_name='已重试次数'),
        ),
    ]
