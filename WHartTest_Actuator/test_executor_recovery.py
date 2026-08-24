#!/usr/bin/env python
"""Generic UI automation recovery strategy tests."""

import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).parent))

from executor import PlaywrightExecutor, StepConfig


class FakeLocator:
    def __init__(self, visible=True, candidates=None):
        self.visible = visible
        self.clicks = 0
        self.wait_calls = []
        self.candidates = candidates or []

    async def wait_for(self, state=None, timeout=None):
        self.wait_calls.append((state, timeout))
        if not self.visible:
            raise RuntimeError("not visible")

    async def click(self, **kwargs):
        self.clicks += 1

    async def evaluate_all(self, script):
        return self.candidates


class FakeLocatorList:
    def __init__(self, locators):
        self.locators = locators

    def nth(self, index):
        return self.locators[index]


class FakePage:
    def __init__(self, candidates=None):
        self.original_locator = FakeLocator(visible=False)
        self.healed_locator = FakeLocator()
        self.waits = []
        self.url = "http://localhost:5173/dashboard"
        self.candidates = candidates or [
            {
                "healId": "candidate-1",
                "tag": "button",
                "text": "执行用例",
                "ariaLabel": "",
                "title": "",
                "placeholder": "",
                "testId": "",
                "id": "",
                "name": "",
            }
        ]

    def locator(self, selector):
        if selector == ".missing-button":
            return self.original_locator
        if selector == '[data-actuator-heal-id="candidate-1"]':
            return self.healed_locator
        return FakeLocator(candidates=self.candidates)

    async def wait_for_load_state(self, state, timeout=None):
        self.waits.append((state, timeout))

    async def wait_for_url(self, predicate, timeout=None):
        return None


class PlaywrightExecutorRecoveryTest(unittest.TestCase):
    def setUp(self):
        self.executor = PlaywrightExecutor()

    def test_resolve_page_url_keeps_old_routes_unchanged(self):
        resolved = self.executor._resolve_page_url("/requirement", "http://localhost:5173/dashboard")

        self.assertEqual(resolved, "http://localhost:5173/requirement")

    def test_resolve_page_url_joins_relative_path_with_base_url(self):
        resolved = self.executor._resolve_page_url("ui-automation", "http://localhost:5173/dashboard")

        self.assertEqual(resolved, "http://localhost:5173/ui-automation")

    def test_self_heals_click_locator_from_visible_interactive_text(self):
        page = FakePage()
        step = StepConfig(
            step_id=1,
            operation_type="click",
            locator_type="css",
            locator_value=".missing-button",
            description="点击执行用例按钮",
        )

        success, message, screenshot = asyncio.run(self.executor._execute_step(page, step))

        self.assertTrue(success)
        self.assertIn("自愈定位器命中", message)
        self.assertIsNone(screenshot)
        self.assertEqual(page.healed_locator.clicks, 1)
        self.assertEqual(page.original_locator.clicks, 0)

    def test_self_heal_rejects_ambiguous_candidates(self):
        page = FakePage(candidates=[
            {
                "healId": "candidate-1",
                "tag": "button",
                "text": "执行用例",
                "ariaLabel": "",
                "title": "",
                "placeholder": "",
                "testId": "",
                "id": "",
                "name": "",
            },
            {
                "healId": "candidate-2",
                "tag": "button",
                "text": "执行任务",
                "ariaLabel": "",
                "title": "",
                "placeholder": "",
                "testId": "",
                "id": "",
                "name": "",
            },
        ])
        step = StepConfig(
            step_id=1,
            operation_type="click",
            locator_type="css",
            locator_value=".missing-button",
            description="点击执行按钮",
        )

        success, message, screenshot = asyncio.run(self.executor._execute_step(page, step))

        self.assertFalse(success)
        self.assertIn("元素定位失败", message)
        self.assertIn("候选", message)
        self.assertIsNone(screenshot)
        self.assertEqual(page.healed_locator.clicks, 0)

    def test_resolve_page_url_rejects_unsafe_scheme(self):
        with self.assertRaisesRegex(ValueError, "不支持的页面 URL 协议"):
            self.executor._resolve_page_url("file:///etc/passwd", "http://localhost:5173")

    def test_resolve_page_url_rejects_cross_origin_absolute_url(self):
        with self.assertRaisesRegex(ValueError, "超出执行环境允许域名"):
            self.executor._resolve_page_url("https://evil.example/ui-automation", "http://localhost:5173")

    def test_navigation_rejects_query_hash_drift(self):
        self.assertFalse(
            self.executor._navigation_matches(
                "http://localhost:5173/ui-automation",
                "http://localhost:5173/ui-automation?unexpected=1#wrong",
            )
        )

    def test_base_url_networkidle_timeout_does_not_block(self):
        page = AsyncMock()
        page.url = "about:blank"
        response = AsyncMock()
        response.status = 200
        page.goto = AsyncMock(return_value=response)
        page.wait_for_load_state = AsyncMock(side_effect=TimeoutError("busy"))

        asyncio.run(self.executor._navigate_to_base_url(page, "http://localhost:5173/dashboard"))

        page.goto.assert_awaited_once_with("http://localhost:5173/dashboard", wait_until="domcontentloaded")

    def test_wait_after_click_uses_configured_auth_paths(self):
        page = AsyncMock()
        page.url = "http://localhost:5173/login?redirect=/dashboard"
        page.wait_for_load_state = AsyncMock(side_effect=TimeoutError("busy"))

        async def wait_for_url(predicate, timeout=None):
            page.url = "http://localhost:5173/dashboard"
            return None

        page.wait_for_url = AsyncMock(side_effect=wait_for_url)
        step = StepConfig(
            step_id=3,
            operation_type="click",
            locator_type="css",
            locator_value="button[type='submit']",
            params={"auth_paths": ["/login"]},
        )

        asyncio.run(self.executor._wait_after_click(page, step))

        page.wait_for_url.assert_awaited_once()

    def test_navigation_reports_unreachable_status(self):
        page = AsyncMock()
        page.url = "http://localhost:5173/dashboard"
        response = AsyncMock()
        response.status = 404
        page.goto = AsyncMock(return_value=response)
        config = AsyncMock()
        config.page_url = "/missing"

        async def run_navigation():
            await self.executor._navigate_to_page_step_url(page, config, "http://localhost:5173")

        with self.assertRaisesRegex(RuntimeError, "页面步骤 URL 不可达"):
            asyncio.run(run_navigation())

    def test_navigation_allows_auth_redirect_with_embedded_target(self):
        page = AsyncMock()
        page.url = "http://localhost:5173/dashboard"
        response = AsyncMock()
        response.status = 200

        async def goto_login(*args, **kwargs):
            page.url = "http://localhost:5173/login?next=/dashboard"
            return response

        page.goto = AsyncMock(side_effect=goto_login)
        page.wait_for_load_state = AsyncMock()
        config = AsyncMock()
        config.page_url = "/"

        asyncio.run(self.executor._navigate_to_page_step_url(page, config, "http://localhost:5173"))

        page.goto.assert_awaited_once()

    def test_navigation_rejects_same_origin_unexpected_redirect(self):
        page = AsyncMock()
        page.url = "http://localhost:5173/dashboard"
        response = AsyncMock()
        response.status = 200

        async def goto_dashboard(*args, **kwargs):
            page.url = "http://localhost:5173/dashboard"
            return response

        page.goto = AsyncMock(side_effect=goto_dashboard)
        page.wait_for_load_state = AsyncMock()
        config = AsyncMock()
        config.page_url = "/requirement"

        async def run_navigation():
            await self.executor._navigate_to_page_step_url(page, config, "http://localhost:5173")

        with self.assertRaisesRegex(RuntimeError, "页面步骤 URL 未到达目标页面"):
            asyncio.run(run_navigation())

    def test_navigation_rejects_wrong_origin_redirect(self):
        page = AsyncMock()
        page.url = "http://localhost:5173/dashboard"
        response = AsyncMock()
        response.status = 200

        async def goto_redirect(*args, **kwargs):
            page.url = "https://evil.example/ui-automation"
            return response

        page.goto = AsyncMock(side_effect=goto_redirect)
        page.wait_for_load_state = AsyncMock()
        config = AsyncMock()
        config.page_url = "/ui-automation"

        async def run_navigation():
            await self.executor._navigate_to_page_step_url(page, config, "http://localhost:5173")

        with self.assertRaisesRegex(RuntimeError, "跨域跳转"):
            asyncio.run(run_navigation())


if __name__ == "__main__":
    unittest.main()
