from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from asgiref.sync import async_to_sync
from django.test import SimpleTestCase

from .consumers import SocketUserManager, UiAutomationConsumer
from .views import ActuatorViewSet


class ActuatorSelectionTests(SimpleTestCase):
    def setUp(self):
        self.docker = self.actuator(headless=True)
        self.local = self.actuator(headless=False)
        self.disabled = self.actuator(headless=False, is_open=False)
        self.registry = {
            'disabled': self.disabled,
            'docker': self.docker,
            'local': self.local,
        }
        patcher = patch.object(SocketUserManager, '_actuator_users', self.registry)
        patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def actuator(**info):
        return SimpleNamespace(actuator_info=info, send_json=AsyncMock())

    def test_default_prefers_enabled_headed_browser_over_connection_order(self):
        self.assertIs(SocketUserManager.get_actuator(), self.local)

    def test_falls_back_to_headless_when_local_browser_disconnects(self):
        del self.registry['local']
        self.assertIs(SocketUserManager.get_actuator(), self.docker)

    def test_disabled_actuators_are_not_available(self):
        del self.registry['local'], self.registry['docker']
        self.assertIsNone(SocketUserManager.get_actuator())
        self.assertFalse(SocketUserManager.has_actuator())

    def test_explicit_actuator_is_honored(self):
        self.assertIs(SocketUserManager.get_actuator('docker'), self.docker)
        self.assertIsNone(SocketUserManager.get_actuator('missing'))

    def test_unknown_browser_mode_does_not_override_known_headed_browser(self):
        self.registry.clear()
        self.registry.update(unknown=self.actuator(), local=self.local)
        self.assertIs(SocketUserManager.get_actuator(), self.local)

    def test_actuator_list_uses_same_priority(self):
        request = SimpleNamespace(user=SimpleNamespace(is_staff=False))
        response = ActuatorViewSet().list_actuators(request)
        self.assertEqual(
            [item['id'] for item in response.data['data']['items']],
            ['local', 'docker', 'disabled'],
        )

    def test_websocket_task_is_sent_to_headed_browser_by_default(self):
        web = UiAutomationConsumer()
        web.user_id = 'web-user'
        web.send_json = AsyncMock()
        web.update_testcase_status = AsyncMock()
        async_to_sync(web.handle_execute_test_case)({'case_id': 57}, 'ignored')
        self.local.send_json.assert_awaited_once()
        self.docker.send_json.assert_not_awaited()
        task = self.local.send_json.call_args.args[0]
        self.assertEqual(task.data.func_args['case_id'], 57)
        self.assertEqual(task.user, 'web-user')

    def test_websocket_explicit_headless_choice_is_preserved(self):
        web = UiAutomationConsumer()
        web.send_json = AsyncMock()
        web.update_testcase_status = AsyncMock()
        async_to_sync(web.handle_execute_test_case)(
            {'case_id': 57, 'actuator_id': 'docker'}, 'ignored',
        )
        self.docker.send_json.assert_awaited_once()
        self.local.send_json.assert_not_awaited()
