#!/usr/bin/env python
"""Universal automation engine reliability tests."""

import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).parent))

from consumer import TaskConsumer
from engine import LegacyAdapter, StepConfig as EngineStepConfig, UniversalAutomationEngine
from executor import PageStepConfig, PlaywrightExecutor, StepConfig, TestCaseConfig
from locator_resolver import LocatorResolver
from operations import ClickOperation, GotoOperation, UploadOperation
from strategies import CustomNavigationStrategy, ExecutionContext, RelaxedNavigationStrategy


class FakeLocator:
    def __init__(self):
        self.click_calls = []

    async def click(self, **kwargs):
        self.click_calls.append(kwargs)


class FakePage:
    def __init__(self):
        self.url = "http://localhost/login?redirect=/dashboard"
        self.wait_for_load_state = AsyncMock(side_effect=TimeoutError("busy"))
        self.wait_for_url = AsyncMock(side_effect=self._wait_for_url)

    async def _wait_for_url(self, predicate, timeout=None):
        self.url = "http://localhost/dashboard"
        return None


class FlakyResolver:
    def __init__(self):
        self.calls = 0
        self.last_diagnostics = {}

    async def resolve(self, page, locator_config, context):
        self.calls += 1
        if self.calls == 1:
            self.last_diagnostics = {
                "current_url": page.url,
                "attempted_locators": [{"type": "css", "value": ".late"}],
                "reason": "not visible yet",
            }
            return None
        return FakeLocator()


class EngineReliabilityTests(unittest.TestCase):
    def test_build_page_step_preserves_full_operation_params_after_case_override(self):
        consumer = TaskConsumer(None, "http://127.0.0.1:8912")
        page_step = consumer._build_page_step_config(
            {
                "id": 1,
                "name": "page",
                "page_url": "/",
                "step_details": [
                    {
                        "id": 10,
                        "step_type": 0,
                        "ope_key": "click",
                        "ope_value": {"button": "left", "click_count": 1, "wait_timeout": 3000},
                        "locator_type": "css",
                        "locator_value": "button",
                        "description": "submit",
                    }
                ],
            },
            case_data_override={"10": {"click_count": 2, "wait_after_click": False}},
        )

        step = page_step.steps[0]

        self.assertEqual(step.params["button"], "left")
        self.assertEqual(step.params["click_count"], 2)
        self.assertFalse(step.params["wait_after_click"])
        self.assertEqual(step.raw_ope_value["wait_timeout"], 3000)

    def test_legacy_adapter_keeps_click_params(self):
        step = StepConfig(
            step_id=1,
            operation_type="click",
            locator_type="css",
            locator_value="button",
            params={"button": "right", "click_count": 2, "delay": 20},
        )

        converted = LegacyAdapter.convert_step_config(step)

        self.assertEqual(converted.params["button"], "right")
        self.assertEqual(converted.params["click_count"], 2)
        self.assertEqual(converted.params["delay"], 20)

    def test_engine_retries_locator_resolution(self):
        async def run():
            engine = UniversalAutomationEngine()
            page = AsyncMock()
            page.url = "http://localhost/page"
            resolver = FlakyResolver()
            result = await engine.execute_step(
                page,
                EngineStepConfig(
                    step_id=1,
                    operation="click",
                    locator={"primary": {"type": "css", "value": ".late"}},
                    params={"wait_after_click": False},
                    description="late button",
                ),
                ExecutionContext(step_id=1),
                resolver,
            )
            return result, resolver

        result, resolver = asyncio.run(run())

        self.assertEqual(result.status, "success")
        self.assertEqual(resolver.calls, 2)

    def test_click_wait_after_does_not_hardcode_auth_paths(self):
        async def run():
            page = FakePage()
            page.url = "http://localhost/account"
            locator = FakeLocator()
            result = await ClickOperation().execute(
                page,
                locator,
                {"wait_after": "networkidle", "wait_timeout": 100},
                ExecutionContext(step_id=1),
            )
            return page, locator, result

        page, locator, result = asyncio.run(run())

        self.assertTrue(result.success)
        self.assertEqual(page.url, "http://localhost/account")
        self.assertEqual(locator.click_calls[0]["button"], "left")
        page.wait_for_url.assert_not_awaited()

    def test_click_waits_for_embedded_navigation_target_without_parameter_name_hardcoding(self):
        async def run():
            page = FakePage()
            page.url = "http://localhost/sign-in?next=/dashboard"
            locator = FakeLocator()
            result = await ClickOperation().execute(
                page,
                locator,
                {"wait_after": "networkidle", "wait_timeout": 100},
                ExecutionContext(step_id=1),
            )
            return page, result

        page, result = asyncio.run(run())

        self.assertTrue(result.success)
        self.assertEqual(page.url, "http://localhost/dashboard")
        page.wait_for_url.assert_awaited_once()

    def test_click_fails_when_embedded_navigation_target_does_not_complete(self):
        async def run():
            page = FakePage()
            page.url = "http://localhost/sign-in?next=/dashboard"
            page.wait_for_url = AsyncMock(side_effect=TimeoutError("no navigation"))
            locator = FakeLocator()
            return await ClickOperation().execute(
                page,
                locator,
                {"wait_after": "networkidle", "wait_timeout": 100},
                ExecutionContext(step_id=1),
            )

        with self.assertRaisesRegex(TimeoutError, "点击后页面未完成跳转"):
            asyncio.run(run())

    def test_click_waits_for_configured_auth_paths(self):
        async def run():
            page = FakePage()
            locator = FakeLocator()
            result = await ClickOperation().execute(
                page,
                locator,
                {"wait_after": "networkidle", "wait_timeout": 100, "auth_paths": ["/login"]},
                ExecutionContext(step_id=1),
            )
            return page, result

        page, result = asyncio.run(run())

        self.assertTrue(result.success)
        self.assertEqual(page.url, "http://localhost/dashboard")
        page.wait_for_url.assert_awaited_once()

    def test_locator_resolver_accepts_test_id_aliases(self):
        class Container:
            def __init__(self):
                self.calls = []
                self.expected = object()

            def get_by_test_id(self, value):
                self.calls.append(value)
                return self.expected

        container = Container()
        resolver = LocatorResolver()

        self.assertIs(resolver._get_locator(container, "test_id", "submit"), container.expected)
        self.assertIs(resolver._get_locator(container, "data-testid", "submit"), container.expected)
        self.assertEqual(container.calls, ["submit", "submit"])

    def test_legacy_assert_url_does_not_require_locator(self):
        async def run():
            executor = PlaywrightExecutor()
            executor._enhanced_executor = None
            page = AsyncMock()
            page.url = "http://localhost/dashboard"
            assertion = AsyncMock()
            assertion.to_have_url = AsyncMock()
            with patch("executor.expect", return_value=assertion):
                result = await executor._execute_step(
                    page,
                    StepConfig(
                        step_id=1,
                        operation_type="assert_url",
                        locator_type="",
                        locator_value="",
                        input_value="http://localhost/dashboard",
                    ),
                )
            return result, assertion

        (success, message, _), assertion = asyncio.run(run())

        self.assertTrue(success)
        self.assertIn("页面断言", message)
        assertion.to_have_url.assert_awaited_once_with("http://localhost/dashboard")

    def test_step_level_goto_rejects_cross_origin_url(self):
        async def run():
            engine = UniversalAutomationEngine()
            page = AsyncMock()
            page.url = "http://localhost/page"
            return await engine.execute_step(
                page,
                EngineStepConfig(
                    step_id=1,
                    operation="goto",
                    params={"url": "https://evil.example/path", "base_url": "http://localhost"},
                ),
                ExecutionContext(step_id=1, metadata={"base_url": "http://localhost"}),
                None,
            )

        result = asyncio.run(run())

        self.assertEqual(result.status, "failed")
        self.assertIn("超出执行环境允许域名", result.message)

    def test_step_level_goto_requires_base_url_for_absolute_url(self):
        async def run():
            engine = UniversalAutomationEngine()
            page = AsyncMock()
            page.url = "http://localhost/page"
            return await engine.execute_step(
                page,
                EngineStepConfig(
                    step_id=1,
                    operation="goto",
                    params={"url": "https://example.com/path"},
                ),
                ExecutionContext(step_id=1),
                None,
            )

        result = asyncio.run(run())

        self.assertEqual(result.status, "failed")
        self.assertIn("必须配置执行环境 base_url", result.message)
        page = AsyncMock()
        page.goto.assert_not_awaited()

    def test_step_level_goto_resolves_relative_url_against_base_url(self):
        self.assertEqual(
            GotoOperation._resolve_safe_url("/dashboard", ExecutionContext(metadata={"base_url": "http://localhost/app"}), {}),
            "http://localhost/dashboard",
        )

    def test_upload_failure_message_does_not_expose_file_path(self):
        async def run():
            locator = AsyncMock()
            locator.set_input_files = AsyncMock(side_effect=RuntimeError("/Users/private/secret.txt missing"))
            page = AsyncMock()
            return await UploadOperation().execute(
                page,
                locator,
                {"file_path": "/Users/private/secret.txt"},
                ExecutionContext(step_id=1),
            )

        result = asyncio.run(run())

        self.assertFalse(result.success)
        self.assertEqual(result.message, "文件上传失败，请检查文件是否存在或权限")
        self.assertNotIn("/Users/private/secret.txt", result.message)

    def test_navigation_strategy_auth_paths_default_empty(self):
        self.assertEqual(RelaxedNavigationStrategy().auth_paths, [])
        self.assertEqual(CustomNavigationStrategy({}).auth_paths, [])

    def test_sql_step_uses_legacy_path_before_universal_engine(self):
        async def run():
            executor = PlaywrightExecutor()
            executor._execute_sql_step = lambda step, env_config: (True, "sql ok")
            page = AsyncMock()
            return await executor._execute_step(
                page,
                StepConfig(
                    step_id=1,
                    step_type=2,
                    operation_type="sql",
                    locator_type="",
                    locator_value="",
                    sql_execute={"sql": "select 1"},
                ),
            )

        success, message, _ = asyncio.run(run())

        self.assertTrue(success)
        self.assertEqual(message, "sql ok")

    def test_testcase_fail_fast_stops_remaining_steps_in_same_page_step(self):
        async def run():
            executor = PlaywrightExecutor()
            executor._enhanced_executor = None
            executor.browser_session_with_trace = Mock()
            page = AsyncMock()
            page.url = "http://localhost/page"
            page.wait_for_load_state = AsyncMock()
            page.on = Mock()
            executor._page = page

            class Session:
                async def __aenter__(self_inner):
                    return page

                async def __aexit__(self_inner, exc_type, exc, tb):
                    return False

            executor.browser_session_with_trace.return_value = Session()
            calls = []

            async def fake_execute_step(page_arg, step, env_config=None):
                calls.append(step.step_id)
                return (False, "first failed", None) if step.step_id == 1 else (True, "second ran", None)

            executor._execute_step = fake_execute_step
            result = await executor.execute_test_case(
                TestCaseConfig(
                    case_id=1,
                    case_name="case",
                    page_steps=[
                        PageStepConfig(
                            page_step_id=1,
                            page_url="http://localhost/page",
                            page_name="page",
                            steps=[
                                StepConfig(step_id=1, operation_type="click", locator_type="css", locator_value=".one"),
                                StepConfig(step_id=2, operation_type="click", locator_type="css", locator_value=".two"),
                            ],
                        )
                    ],
                )
            )
            return calls, result

        calls, result = asyncio.run(run())

        self.assertEqual(calls, [1])
        self.assertEqual(result.status, "failed")
        self.assertIn("后续步骤已停止", result.message)

    def test_testcase_without_executable_steps_fails_before_browser_start(self):
        async def run():
            executor = PlaywrightExecutor()
            executor.browser_session_with_trace = Mock()
            result = await executor.execute_test_case(
                TestCaseConfig(
                    case_id=1,
                    case_name="empty case",
                    page_steps=[
                        PageStepConfig(
                            page_step_id=6,
                            page_url="http://localhost/login",
                            page_name="超级管理员登录",
                            steps=[],
                        ),
                        PageStepConfig(
                            page_step_id=7,
                            page_url="http://localhost/requirements",
                            page_name="访问多个项目的需求文档",
                            steps=[],
                        ),
                    ],
                )
            )
            return result, executor.browser_session_with_trace.called

        result, browser_started = asyncio.run(run())

        self.assertFalse(browser_started)
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.total_steps, 0)
        self.assertIn("未配置可执行步骤", result.message)
        self.assertIn("超级管理员登录", result.message)

    def test_page_step_navigation_fails_fast_on_auth_redirect(self):
        async def run():
            executor = PlaywrightExecutor()
            page = AsyncMock()
            page.url = "about:blank"
            page.wait_for_load_state = AsyncMock()

            async def goto(url, wait_until=None):
                page.url = "http://localhost/login?redirect=/requirements"
                response = Mock()
                response.status = 200
                return response

            page.goto = AsyncMock(side_effect=goto)
            await executor._navigate_to_page_step_url(
                page,
                PageStepConfig(
                    page_step_id=7,
                    page_url="http://localhost/requirements",
                    page_name="需求文档",
                    steps=[StepConfig(step_id=1, operation_type="click", locator_type="text", locator_value="上传需求文档")],
                ),
            )

        with self.assertRaisesRegex(RuntimeError, "页面步骤 URL 被鉴权重定向"):
            asyncio.run(run())

    def test_unsupported_step_type_returns_clear_message(self):
        async def run():
            executor = PlaywrightExecutor()
            page = AsyncMock()
            return await executor._execute_step(
                page,
                StepConfig(
                    step_id=1,
                    step_type=5,
                    operation_type="python",
                    locator_type="",
                    locator_value="",
                ),
            )

        success, message, _ = asyncio.run(run())

        self.assertFalse(success)
        self.assertIn("步骤类型暂未启用通用执行", message)


if __name__ == "__main__":
    unittest.main()
