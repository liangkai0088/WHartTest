from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('prompts', '0010_alter_userprompt_prompt_type'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='userprompt',
            name='unique_user_program_prompt_type',
        ),
        migrations.AddConstraint(
            model_name='userprompt',
            constraint=models.UniqueConstraint(
                fields=['user', 'prompt_type'],
                condition=~models.Q(prompt_type='general'),
                name='unique_user_program_prompt_type',
            ),
        ),
    ]
