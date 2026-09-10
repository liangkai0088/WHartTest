import json
from datetime import time, timedelta
from unittest.mock import AsyncMock, Mock, patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone
from django_celery_beat.models import PeriodicTask
from rest_framework.test import APIClient

from projects.models import Project, ProjectMember
from ui_automation.models import UiBatchExecutionRecord, UiModule, UiTestCase
from .models import ScheduledTask, TaskExecution
from .tasks import execute_scheduled_task


class ScheduledTaskResultTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser('retry-tester', password='test-only')
        self.project = Project.objects.create(name='Retry regression')
        ProjectMember.objects.create(project=self.project, user=self.user, role='admin')
        module = UiModule.objects.create(project=self.project, name='Module')
        self.case = UiTestCase.objects.create(project=self.project, module=module, name='Case')
        self.task = ScheduledTask.objects.create(
            project=self.project, creator=self.user, name='Retry test',
            module='ui_automation', schedule_type='daily', daily_time=time(12),
            status='running', retry_enabled=True, retry_count=1, retry_interval=1,
        )
        self.task.ui_testcases.add(self.case)
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.actuator = Mock(send_json=AsyncMock())
        self.socket_patch = patch('ui_automation.consumers.SocketUserManager.get_actuator', return_value=self.actuator)
        self.socket_patch.start()
        self.addCleanup(self.socket_patch.stop)
        self.http_patch = patch('requests.post', side_effect=self._post_batch)
        self.http = self.http_patch.start()
        self.addCleanup(self.http_patch.stop)

    def _post_batch(self, url, json, **kwargs):
        return self.client.post('/api/ui-automation/trigger-batch/', json, format='json')

    def run_task(self):
        execute_scheduled_task.run(self.task.id, 'manual')
        return TaskExecution.objects.filter(task=self.task).latest('id')

    def finish_batch(self, batch, failed=True):
        batch.status = 4 if failed else 2
        batch.failed_cases = 1 if failed else 0
        batch.passed_cases = 0 if failed else 1
        batch.end_time = timezone.now()
        with self.captureOnCommitCallbacks(execute=True):
            batch.save()

    def test_submission_is_running_until_batch_finishes(self):
        execution = self.run_task()
        self.assertEqual(execution.status, 'running')
        self.assertIsNone(execution.finished_at)
        self.assertEqual(execution.ui_batch_id, UiBatchExecutionRecord.objects.get().id)
        self.assertNotIn('batch_id=None', execution.log)
        self.finish_batch(execution.ui_batch, failed=False)
        execution.refresh_from_db()
        self.assertEqual(execution.status, 'success')
        self.assertIsNotNone(execution.finished_at)
        self.assertFalse(PeriodicTask.objects.filter(name__startswith='task_retry_').exists())

    def test_actual_failure_schedules_exactly_one_retry_at_configured_interval(self):
        execution = self.run_task()
        batch = UiBatchExecutionRecord.objects.get()
        self.finish_batch(batch)
        execution.refresh_from_db()
        self.assertEqual(execution.status, 'failed')
        retry = PeriodicTask.objects.get(name=f'task_retry_{execution.id}')
        self.assertTrue(retry.one_off)
        self.assertEqual(retry.clocked.clocked_time, execution.finished_at + timedelta(minutes=1))
        self.finish_batch(batch)
        self.assertEqual(PeriodicTask.objects.filter(name=retry.name).count(), 1)

    def test_retry_limit_and_duplicate_delivery(self):
        initial = self.run_task()
        self.finish_batch(initial.ui_batch)
        execute_scheduled_task.run(self.task.id, 'retry', retry_of_id=initial.id)
        retry = TaskExecution.objects.get(retry_of=initial)
        self.assertEqual((retry.trigger_type, retry.retry_attempt, retry.retry_limit), ('retry', 1, 1))
        self.assertEqual(retry.ui_batch.trigger_type, 'retry')
        self.assertNotEqual(retry.ui_batch_id, initial.ui_batch_id)
        execute_scheduled_task.run(self.task.id, 'retry', retry_of_id=initial.id)
        self.assertEqual(TaskExecution.objects.count(), 2)
        self.assertEqual(UiBatchExecutionRecord.objects.count(), 2)
        self.finish_batch(retry.ui_batch)
        self.assertFalse(PeriodicTask.objects.filter(name=f'task_retry_{retry.id}').exists())
        execute_scheduled_task.run(self.task.id, 'retry', retry_of_id=retry.id)
        self.assertEqual(TaskExecution.objects.count(), 2)

    def test_disabled_retry_does_not_register_job(self):
        self.task.retry_enabled = False
        self.task.save()
        execution = self.run_task()
        self.finish_batch(execution.ui_batch)
        execution.refresh_from_db()
        self.assertEqual(execution.status, 'failed')
        self.assertFalse(PeriodicTask.objects.filter(name__startswith='task_retry_').exists())

    def test_partial_failure_retries(self):
        execution = self.run_task()
        batch = execution.ui_batch
        batch.status = 3
        batch.total_cases = 2
        batch.passed_cases = batch.failed_cases = 1
        with self.captureOnCommitCallbacks(execute=True):
            batch.save()
        execution.refresh_from_db()
        self.assertEqual(execution.status, 'failed')
        self.assertTrue(PeriodicTask.objects.filter(name=f'task_retry_{execution.id}').exists())

    def test_manual_trigger_is_not_relabelled_scheduled(self):
        execution = self.run_task()
        self.assertEqual(execution.ui_batch.trigger_type, 'manual')

    def test_submission_error_uses_same_retry_limit(self):
        self.http.side_effect = ConnectionError('offline')
        execution = self.run_task()
        self.assertEqual(execution.status, 'failed')
        self.assertTrue(PeriodicTask.objects.filter(name=f'task_retry_{execution.id}').exists())
        execute_scheduled_task.run(self.task.id, 'retry', retry_of_id=execution.id)
        retry = TaskExecution.objects.get(retry_of=execution)
        self.assertEqual(retry.status, 'failed')
        self.assertFalse(PeriodicTask.objects.filter(name=f'task_retry_{retry.id}').exists())

    def test_timeout_after_dispatch_waits_for_linked_batch(self):
        def dispatch_then_timeout(*args, **kwargs):
            self._post_batch(*args, **kwargs)
            raise TimeoutError('response timed out')

        self.http.side_effect = dispatch_then_timeout
        execution = self.run_task()
        self.assertEqual(execution.status, 'running')
        self.assertIsNotNone(execution.ui_batch_id)
        self.assertFalse(PeriodicTask.objects.filter(name__startswith='task_retry_').exists())
        self.finish_batch(execution.ui_batch)
        execution.refresh_from_db()
        self.assertEqual(execution.status, 'failed')

    def test_result_arriving_before_dispatch_response_is_not_overwritten(self):
        def dispatch_then_finish(*args, **kwargs):
            response = self._post_batch(*args, **kwargs)
            self.finish_batch(UiBatchExecutionRecord.objects.get())
            return response

        self.http.side_effect = dispatch_then_finish
        execution = self.run_task()
        self.assertEqual(execution.status, 'failed')
        self.assertIn('已安排第 1/1 次重试', execution.log)
        self.assertTrue(PeriodicTask.objects.filter(name=f'task_retry_{execution.id}').exists())

    def test_once_task_is_disabled_only_after_retry_chain_finishes(self):
        self.task.schedule_type = 'once'
        self.task.save()
        initial = self.run_task()
        self.finish_batch(initial.ui_batch)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, 'running')
        execute_scheduled_task.run(self.task.id, 'retry', retry_of_id=initial.id)
        retry = TaskExecution.objects.get(retry_of=initial)
        self.finish_batch(retry.ui_batch)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, 'disabled')

    def test_duplicate_batch_submission_returns_existing_batch(self):
        execution = self.run_task()
        payload = self.http.call_args.kwargs['json']
        response = self._post_batch('unused', payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data']['batch_id'], execution.ui_batch_id)
        self.assertEqual(UiBatchExecutionRecord.objects.count(), 1)
        self.assertEqual(self.actuator.send_json.await_count, 1)

    def test_cannot_attach_batch_to_another_users_execution(self):
        execution = self.run_task()
        other = User.objects.create_user('other-user')
        self.client.force_authenticate(other)
        response = self._post_batch('unused', self.http.call_args.kwargs['json'])
        self.assertEqual(response.status_code, 403)
        self.assertEqual(UiBatchExecutionRecord.objects.count(), 1)

    def test_invalid_execution_id_returns_validation_error(self):
        response = self._post_batch('unused', {'case_ids': [self.case.id], 'task_execution_id': 'invalid'})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(UiBatchExecutionRecord.objects.exists())

    def test_initial_celery_redelivery_does_not_duplicate_batch(self):
        execute_scheduled_task.push_request(id='same-delivery')
        try:
            self.run_task()
            self.run_task()
        finally:
            execute_scheduled_task.pop_request()
        self.assertEqual(TaskExecution.objects.count(), 1)
        self.assertEqual(UiBatchExecutionRecord.objects.count(), 1)

    def test_retry_uses_original_limit_and_interval(self):
        initial = self.run_task()
        self.finish_batch(initial.ui_batch)
        self.task.retry_count = 5
        self.task.retry_interval = 10
        self.task.save()
        execute_scheduled_task.run(self.task.id, 'retry', retry_of_id=initial.id)
        retry = TaskExecution.objects.get(retry_of=initial)
        self.assertEqual((retry.retry_limit, retry.retry_interval), (1, 1))
        self.finish_batch(retry.ui_batch)
        self.assertFalse(PeriodicTask.objects.filter(name=f'task_retry_{retry.id}').exists())

    def test_retry_job_targets_the_original_execution_and_queue(self):
        initial = self.run_task()
        self.finish_batch(initial.ui_batch)
        job = PeriodicTask.objects.get(name=f'task_retry_{initial.id}')
        self.assertEqual(json.loads(job.args), [self.task.id, 'retry'])
        self.assertEqual(json.loads(job.kwargs), {'retry_of_id': initial.id})
        self.assertEqual(job.queue, 'task_center')

    def test_websocket_dispatch_error_is_failed_and_retryable(self):
        self.actuator.send_json.side_effect = RuntimeError('socket closed')
        execution = self.run_task()
        self.assertEqual(execution.status, 'failed')
        self.assertEqual(execution.ui_batch.status, 4)
        self.assertTrue(PeriodicTask.objects.filter(name=f'task_retry_{execution.id}').exists())

    def run_suite_task(self):
        from testcases.models import TestSuite

        self.task.module = 'test_suite'
        self.task.test_suite = TestSuite.objects.create(project=self.project, creator=self.user, name='Retry suite')
        self.task.save()
        with patch('testcases.tasks.execute_test_suite.delay'):
            return self.run_task()

    def test_suite_waits_for_actual_result_and_completed_failures_retry(self):
        execution = self.run_suite_task()
        self.assertEqual(execution.status, 'running')
        result = execution.suite_execution
        result.status = 'completed'
        result.total_count = result.failed_count = 1
        result.completed_at = timezone.now()
        with self.captureOnCommitCallbacks(execute=True):
            result.save()
        execution.refresh_from_db()
        self.assertEqual(execution.status, 'failed')
        self.assertTrue(PeriodicTask.objects.filter(name=f'task_retry_{execution.id}').exists())

    def test_cancelled_suite_does_not_restart(self):
        execution = self.run_suite_task()
        result = execution.suite_execution
        result.status = 'cancelled'
        with self.captureOnCommitCallbacks(execute=True):
            result.save()
        execution.refresh_from_db()
        self.assertEqual(execution.status, 'failed')
        self.assertFalse(PeriodicTask.objects.filter(name=f'task_retry_{execution.id}').exists())

    def test_successful_suite_does_not_retry(self):
        execution = self.run_suite_task()
        result = execution.suite_execution
        result.status = 'completed'
        result.total_count = result.passed_count = 1
        with self.captureOnCommitCallbacks(execute=True):
            result.save()
        execution.refresh_from_db()
        self.assertEqual(execution.status, 'success')
        self.assertFalse(PeriodicTask.objects.filter(name=f'task_retry_{execution.id}').exists())
