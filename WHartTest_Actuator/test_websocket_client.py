import unittest
from unittest.mock import AsyncMock, patch

from websocket_client import WebSocketClient, build_websocket_connect_url, build_websocket_origin


class WebSocketClientUrlTests(unittest.IsolatedAsyncioTestCase):
    def test_build_origin_for_ws_url(self):
        self.assertEqual(
            build_websocket_origin('ws://127.0.0.1:8000/ws/ui/actuator/'),
            'http://127.0.0.1:8000',
        )

    def test_build_origin_for_wss_url(self):
        self.assertEqual(
            build_websocket_origin('wss://example.com/ws/ui/actuator/'),
            'https://example.com',
        )

    def test_build_connect_url_adds_id_query_param(self):
        self.assertEqual(
            build_websocket_connect_url(
                'ws://127.0.0.1:8000/ws/ui/actuator/',
                'actuator-1',
            ),
            'ws://127.0.0.1:8000/ws/ui/actuator/?id=actuator-1',
        )

    def test_build_connect_url_preserves_existing_query(self):
        self.assertEqual(
            build_websocket_connect_url(
                'ws://127.0.0.1:8000/ws/ui/actuator/?lang=en',
                'actuator-1',
            ),
            'ws://127.0.0.1:8000/ws/ui/actuator/?lang=en&id=actuator-1',
        )

    def test_build_connect_url_replaces_existing_identity_query(self):
        self.assertEqual(
            build_websocket_connect_url(
                'ws://127.0.0.1:8000/ws/ui/actuator/?user_id=old&id=older&lang=en',
                'actuator-1',
            ),
            'ws://127.0.0.1:8000/ws/ui/actuator/?lang=en&id=actuator-1',
        )

    @patch('websocket_client.websockets.connect', new_callable=AsyncMock)
    async def test_connect_uses_supported_websocket_options(self, connect):
        client = WebSocketClient('ws://127.0.0.1:8000/ws/ui/actuator/', 'actuator-1')
        client._send_actuator_info = AsyncMock()

        connected = await client.connect()

        self.assertTrue(connected)
        self.assertNotIn('proxy', connect.await_args.kwargs)
        self.assertEqual(connect.await_args.kwargs['origin'], 'http://127.0.0.1:8000')

    @patch('websocket_client.inspect.signature')
    @patch('websocket_client.websockets.connect', new_callable=AsyncMock)
    async def test_connect_disables_proxy_when_supported(self, connect, signature):
        signature.return_value.parameters = {'proxy': object()}
        client = WebSocketClient('ws://127.0.0.1:8000/ws/ui/actuator/', 'actuator-1')
        client._send_actuator_info = AsyncMock()

        connected = await client.connect()

        self.assertTrue(connected)
        self.assertIsNone(connect.await_args.kwargs['proxy'])

    @patch('websocket_client.websockets.connect', new_callable=AsyncMock)
    async def test_connect_stops_when_token_provider_returns_empty_token(self, connect):
        client = WebSocketClient(
            'ws://127.0.0.1:8000/ws/ui/actuator/',
            'actuator-1',
            token_provider=AsyncMock(return_value=None),
        )

        connected = await client.connect()

        self.assertFalse(connected)
        self.assertFalse(client.connected)
        self.assertTrue(client._stop_event.is_set())
        connect.assert_not_awaited()

    async def test_run_keeps_reconnect_loop_after_transient_initial_failure(self):
        client = WebSocketClient('ws://127.0.0.1:8000/ws/ui/actuator/', 'actuator-1')
        client.connect = AsyncMock(return_value=False)
        client.receive_loop = AsyncMock()

        await client.run()

        client.receive_loop.assert_awaited_once()


if __name__ == '__main__':
    unittest.main()