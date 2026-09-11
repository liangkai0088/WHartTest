import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from executor import PlaywrightExecutor


class BrowserLaunchTests(unittest.IsolatedAsyncioTestCase):
    async def test_direct_proxy_and_visible_mode_reach_both_launch_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            for persistent in (False, True):
                with self.subTest(persistent=persistent):
                    executor = PlaywrightExecutor(
                        headless=False, persistent=persistent,
                        user_data_dir=directory, screenshot_dir=directory,
                    )
                    page = MagicMock()
                    context = AsyncMock()
                    context.pages = [page]
                    context.new_page.return_value = page
                    browser = AsyncMock()
                    browser.new_context.return_value = context
                    launcher = MagicMock()
                    launcher.launch = AsyncMock(return_value=browser)
                    launcher.launch_persistent_context = AsyncMock(return_value=context)
                    executor._playwright = MagicMock(chromium=launcher)
                    with patch.dict(os.environ, WHARTTEST_BROWSER_PROXY='direct://'):
                        await executor.init_browser()
                    launch = launcher.launch_persistent_context if persistent else launcher.launch
                    self.assertEqual(launch.call_args.kwargs, {
                        'headless': False, 'timeout': 30000,
                        'proxy': {'server': 'direct://'},
                    })
                    self.assertIs(executor._page, page)

    def test_existing_deployments_keep_default_proxy_behavior(self):
        with tempfile.TemporaryDirectory() as directory:
            executor = PlaywrightExecutor(user_data_dir=directory, screenshot_dir=directory)
            with patch.dict(os.environ, WHARTTEST_BROWSER_PROXY=''):
                self.assertNotIn('proxy', executor._browser_launch_options())

    def test_direct_mode_disables_chromium_proxy(self):
        executor = PlaywrightExecutor()
        with patch.dict(os.environ, WHARTTEST_BROWSER_PROXY='', WHARTTEST_BROWSER_DIRECT='true'):
            self.assertEqual(executor._browser_launch_options()['args'], ['--no-proxy-server'])


if __name__ == '__main__':
    unittest.main()
