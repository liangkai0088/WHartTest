from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from .execution_service import sync_batch_result, sync_suite_result


@receiver(post_save, sender='ui_automation.UiBatchExecutionRecord')
def on_ui_batch_finished(sender, instance, raw=False, **kwargs):
    if not raw and instance.status in (2, 3, 4):
        transaction.on_commit(lambda: sync_batch_result(instance.pk))


@receiver(post_save, sender='testcases.TestExecution')
def on_suite_finished(sender, instance, raw=False, **kwargs):
    if not raw and instance.status in ('completed', 'failed', 'cancelled'):
        transaction.on_commit(lambda: sync_suite_result(instance.pk))
