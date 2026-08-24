import os
import tempfile
from unittest.mock import patch

from asgiref.sync import async_to_sync
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase
from django.test import TestCase
from django.test.utils import override_settings

from . import agent_loop_view
from .agent_loop_view import (
    _build_container_reachable_url,
    _build_test_execution_system_prompt,
    _extract_linked_image_urls,
    _is_linked_image_url_allowed,
    _normalize_uploaded_image_base64_list,
    _prepare_agent_loop_human_message,
)
from .agent_review_prompts import render_review_prompt
from .agent_review_service import (
    _decide_route,
    _get_confirmed_issues,
    normalize_review_mode,
    normalize_review_thresholds,
)
from .builtin_tools.skill_tools import (
    _build_container_reachable_url as _build_skill_container_reachable_url,
    _rewrite_local_browser_url,
    _rewrite_ui_automation_persisted_url,
    _build_skill_artifacts_dir,
    _collect_skill_artifacts,
    _build_skill_screenshots_dir,
    _finalize_skill_result,
    _prepare_skill_screenshots_dir,
    _sanitize_runtime_path_segment,
)
from .builtin_tools.output_sanitizer import strip_terminal_control_sequences
from .middleware_config import get_user_friendly_llm_error, _model_retry_should_retry
from projects.models import Project, ProjectMember
from requirements.models import DocumentImage, RequirementDocument


class TestExecutionSystemPromptTests(SimpleTestCase):
    def test_test_execution_prompt_forces_injected_skill_tools(self):
        prompt = _build_test_execution_system_prompt(
            "使用 browser_navigate 工具执行测试。",
            generate_playwright_script=False,
        )

        self.assertIn("read_skill_content", prompt)
        self.assertIn("execute_skill_script", prompt)
        self.assertIn("playwright-skill", prompt)
        self.assertIn("禁止因为系统提示词", prompt)
        self.assertIn("browser_navigate", prompt)

    def test_generate_ui_case_prompt_requires_ui_automation_skill(self):
        prompt = _build_test_execution_system_prompt(
            "基础提示词",
            generate_playwright_script=True,
        )

        self.assertIn("ui-automation", prompt)
        self.assertIn("生成 UI 自动化用例规则", prompt)
        self.assertIn("最终 JSON", prompt)

    def test_project_url_injection(self):
        """测试项目 URL 动态注入到系统提示词"""
        prompt = _build_test_execution_system_prompt(
            "基础提示词",
            generate_playwright_script=False,
            project_url="https://test.example.com",
        )

        self.assertIn("https://test.example.com", prompt)
        self.assertIn("测试目标 URL", prompt)
        self.assertIn("忽略 Skill 文档中的示例 URL", prompt)

    def test_no_url_when_project_url_missing(self):
        """测试未配置项目 URL 时不注入 URL 指令"""
        prompt = _build_test_execution_system_prompt(
            "基础提示词",
            generate_playwright_script=False,
            project_url=None,
        )

        self.assertNotIn("测试目标 URL", prompt)
        self.assertIn("read_skill_content", prompt)

    def test_localhost_project_url_uses_container_reachable_url(self):
        """测试容器内浏览器访问宿主机 localhost 时自动转换地址"""
        prompt = _build_test_execution_system_prompt(
            "基础提示词",
            generate_playwright_script=False,
            project_url="http://localhost:8913/",
        )

        self.assertIn("项目配置地址**：http://localhost:8913/", prompt)
        self.assertIn("浏览器执行地址**：http://host.docker.internal:8913/", prompt)
        self.assertIn("容器内访问 `localhost` 指向容器自身", prompt)

    def test_remote_project_url_does_not_rewrite_host(self):
        """测试远端项目 URL 不被改写为本地地址"""
        runtime_url = _build_container_reachable_url("https://test.example.com/login")

        self.assertIsNone(runtime_url)

    def test_project_credentials_are_injected_for_login_generation(self):
        """测试项目登录凭据注入，避免使用 Skill 示例密码"""
        prompt = _build_test_execution_system_prompt(
            "基础提示词",
            generate_playwright_script=True,
            project_username="admin",
            project_password="admin123456",
        )

        self.assertIn("项目登录凭据", prompt)
        self.assertIn("**用户名**：admin", prompt)
        self.assertIn("**密码**：admin123456", prompt)
        self.assertIn("禁止使用 Skill 文档中的示例账号或密码", prompt)
        self.assertIn("前置交互", prompt)
        self.assertIn("password123", prompt)


class SkillRuntimeUrlRewriteTests(SimpleTestCase):
    def test_skill_command_rewrites_localhost_project_url(self):
        command = "node run.js \"await page.goto('http://localhost:8913/login')\""

        rewritten = _rewrite_local_browser_url(command, "http://localhost:8913")

        self.assertIn("http://host.docker.internal:8913/login", rewritten)
        self.assertNotIn("http://localhost:8913/login", rewritten)

    def test_skill_command_does_not_rewrite_remote_project_url(self):
        command = "node run.js \"await page.goto('https://test.example.com/login')\""

        rewritten = _rewrite_local_browser_url(command, "https://test.example.com")

        self.assertEqual(rewritten, command)
        self.assertIsNone(_build_skill_container_reachable_url("https://test.example.com"))

    def test_ui_automation_save_rewrites_runtime_url_to_project_url(self):
        command = (
            "python ui_automation_tools.py --action create_ui_page "
            "--url http://host.docker.internal:8913/login"
        )

        rewritten = _rewrite_ui_automation_persisted_url(command, "http://localhost:8913/")

        self.assertIn("--url http://localhost:8913/login", rewritten)
        self.assertNotIn("host.docker.internal", rewritten)


class LLMFriendlyErrorTests(SimpleTestCase):
    def test_model_cooldown_error_returns_friendly_payload(self):
        exc = Exception(
            "Error code: 429 - {'error': {'code': 'model_cooldown', 'message': 'All credentials for model coder-model are cooling down', 'model': 'coder-model', 'reset_seconds': 27211, 'reset_time': '7h33m31s'}}"
        )

        result = get_user_friendly_llm_error(exc)

        if result is None:
            raise AssertionError("expected friendly error payload")
        self.assertEqual(result["status_code"], 429)
        self.assertEqual(result["error_code"], "model_cooldown")
        self.assertEqual(result["model"], "coder-model")
        self.assertEqual(result["reset_seconds"], 27211)
        self.assertEqual(result["reset_time"], "7h33m31s")
        self.assertIn("coder-model", result["message"])
        self.assertIn("7h33m31s", result["message"])

    def test_generic_rate_limit_error_returns_friendly_payload(self):
        exc = Exception("HTTP 429 Too Many Requests")

        result = get_user_friendly_llm_error(exc)

        if result is None:
            raise AssertionError("expected friendly error payload")
        self.assertEqual(result["status_code"], 429)
        self.assertEqual(result["error_code"], "rate_limit")
        self.assertEqual(result["message"], "当前模型服务请求过于频繁，请稍后重试。")

    def test_model_cooldown_error_will_not_retry(self):
        exc = Exception(
            "Error code: 429 - {'error': {'code': 'model_cooldown', 'message': 'All credentials for model coder-model are cooling down', 'model': 'coder-model', 'reset_seconds': 27211, 'reset_time': '7h33m31s'}}"
        )

        self.assertFalse(_model_retry_should_retry(exc))

    def test_cooling_down_text_without_code_still_maps_to_model_cooldown(self):
        exc = Exception(
            "RateLimitError: provider says model service is cooling down, retry-after: 6m0s"
        )

        result = get_user_friendly_llm_error(exc)

        if result is None:
            raise AssertionError("expected friendly cooldown payload")
        self.assertEqual(result["status_code"], 429)
        self.assertEqual(result["error_code"], "model_cooldown")
        self.assertIn("冷却中", result["message"])


class LinkedImageUrlExtractionTests(SimpleTestCase):
    def test_extract_plain_http_url_stops_before_chinese_description(self):
        text = "请访问 https://localhost:8080，准备注册信息：用户名testuser010、密码abcdef123"

        self.assertEqual(_extract_linked_image_urls(text), ["https://localhost:8080"])

    def test_extract_markdown_image_url_trims_wrapping_punctuation(self):
        text = "参考截图 ![image](https://example.com/demo.png)，然后继续分析"

        self.assertEqual(
            _extract_linked_image_urls(text),
            ["https://example.com/demo.png"],
        )

    def test_extract_invalid_unicode_netloc_does_not_raise(self):
        text = "异常链接 https://localhost:8080：准备注册信息：用户名testuser014"

        self.assertEqual(_extract_linked_image_urls(text), ["https://localhost:8080"])

    def test_extract_plain_http_url_stops_before_ascii_comma_description(self):
        text = "Open http://localhost:8080,then fill the registration form"

        self.assertEqual(_extract_linked_image_urls(text), ["http://localhost:8080"])

    def test_extract_plain_http_url_stops_before_closing_parenthesis_text(self):
        text = "查看截图 https://example.com/demo.png)后继续分析"

        self.assertEqual(
            _extract_linked_image_urls(text),
            ["https://example.com/demo.png"],
        )

    def test_allowlist_check_rejects_invalid_url_without_raising(self):
        with patch.object(
            agent_loop_view, "_LINKED_IMAGE_URL_ALLOWLIST", {"example.com"}
        ):
            self.assertFalse(
                _is_linked_image_url_allowed(
                    "https://localhost:8080：准备注册信息：用户名testuser014"
                )
            )


class UploadedImageNormalizationTests(SimpleTestCase):
    def test_normalize_uploaded_images_merges_legacy_and_array_fields(self):
        result = _normalize_uploaded_image_base64_list(
            ["img-a", " img-b ", "", "img-a"],
            "img-c",
        )

        self.assertEqual(result, ["img-a", "img-b", "img-c"])

    def test_normalize_uploaded_images_accepts_legacy_single_image_only(self):
        result = _normalize_uploaded_image_base64_list(None, " legacy-img ")

        self.assertEqual(result, ["legacy-img"])


class AgentReviewPipelineTests(SimpleTestCase):
    def test_normalize_review_mode_defaults_to_single(self):
        self.assertEqual(normalize_review_mode(None), "single")
        self.assertEqual(normalize_review_mode("unknown"), "single")
        self.assertEqual(normalize_review_mode("multi_review"), "multi_review")

    def test_normalize_review_thresholds_accepts_frontend_aliases(self):
        thresholds = normalize_review_thresholds(
            {
                "quality_threshold": 90,
                "confidence_threshold": 0.8,
                "issue_confidence_threshold": 0.6,
            }
        )

        self.assertEqual(thresholds["quality_score"], 90)
        self.assertEqual(thresholds["confidence"], 0.8)
        self.assertEqual(thresholds["issue_confidence"], 0.6)

    def test_high_confidence_high_issue_routes_to_repair(self):
        review_results = [
            {
                "issues": [
                    {
                        "severity": "high",
                        "confidence": 0.9,
                        "target": "step-1",
                    }
                ]
            }
        ]
        thresholds = normalize_review_thresholds({})

        confirmed = _get_confirmed_issues(
            review_results,
            issue_confidence_threshold=thresholds["issue_confidence"],
        )
        status, needs_repair, reason = _decide_route(
            aggregate_score=95,
            aggregate_confidence=0.9,
            confirmed_issues=confirmed,
            thresholds=thresholds,
        )

        self.assertEqual(status, "repairing")
        self.assertTrue(needs_repair)
        self.assertIn("自动路由", reason)

    def test_low_confidence_review_skips_auto_repair(self):
        thresholds = normalize_review_thresholds({})

        status, needs_repair, reason = _decide_route(
            aggregate_score=50,
            aggregate_confidence=0.3,
            confirmed_issues=[],
            thresholds=thresholds,
        )

        self.assertEqual(status, "skipped")
        self.assertFalse(needs_repair)
        self.assertIn("置信度", reason)

    def test_passing_review_does_not_route_to_repair(self):
        thresholds = normalize_review_thresholds({})

        status, needs_repair, reason = _decide_route(
            aggregate_score=90,
            aggregate_confidence=0.9,
            confirmed_issues=[],
            thresholds=thresholds,
        )

        self.assertEqual(status, "passed")
        self.assertFalse(needs_repair)
        self.assertIn("审查通过", reason)

    def test_review_prompt_contains_strict_json_schema(self):
        prompt = render_review_prompt("ui_locator", '{"generated_content":"demo"}')

        self.assertIn("严格输出 JSON", prompt)
        self.assertIn("ui_locator", prompt)
        self.assertIn("quality_score", prompt)
        self.assertIn("generated_content", prompt)


class AgentLoopRequirementImageMessageTests(TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.override_media = override_settings(MEDIA_ROOT=self.temp_dir.name)
        self.override_media.enable()
        self.addCleanup(self.override_media.disable)

        self.user = get_user_model().objects.create_user(
            username="agent-loop-user",
            password="password123",
        )
        self.project = Project.objects.create(
            name="Agent Loop Image Project",
            creator=self.user,
        )
        ProjectMember.objects.create(
            project=self.project,
            user=self.user,
            role="member",
        )
        self.document = RequirementDocument.objects.create(
            project=self.project,
            title="Requirement With Images",
            document_type="docx",
            uploader=self.user,
            has_images=True,
            image_count=1,
        )
        DocumentImage.objects.create(
            document=self.document,
            image_id="img_000",
            order=0,
            content_type="image/png",
            file_size=3,
            image_file=SimpleUploadedFile(
                "img-000.png",
                b"png",
                content_type="image/png",
            ),
        )

    def test_prepare_agent_loop_human_message_rewrites_requirement_placeholders(self):
        message = (
            "请分析以下需求\n\n"
            "![图片](docimg://img_000)\n\n"
            f"(这些需求模块来源于需求文档ID: {self.document.id})"
        )

        human_message_content, additional_kwargs, display_message = async_to_sync(
            _prepare_agent_loop_human_message
        )(
            message,
            project=self.project,
            supports_vision=False,
            uploaded_images_base64=[],
        )

        expected_url = (
            f"/api/requirements/documents/{self.document.id}/images/img_000/"
        )
        self.assertEqual(human_message_content, display_message)
        self.assertIn(expected_url, display_message)
        self.assertEqual(
            additional_kwargs["requirement_document_id"], str(self.document.id)
        )

    def test_prepare_agent_loop_human_message_attaches_requirement_images_for_vision(self):
        message = (
            "请分析以下需求\n\n"
            "![图片](docimg://img_000)\n\n"
            f"(这些需求模块来源于需求文档ID: {self.document.id})"
        )

        human_message_content, additional_kwargs, display_message = async_to_sync(
            _prepare_agent_loop_human_message
        )(
            message,
            project=self.project,
            supports_vision=True,
            uploaded_images_base64=[],
        )

        self.assertIsInstance(human_message_content, list)
        self.assertEqual(human_message_content[0]["type"], "text")
        self.assertIn(
            f"/api/requirements/documents/{self.document.id}/images/img_000/",
            human_message_content[0]["text"],
        )
        self.assertEqual(human_message_content[1]["type"], "image_url")
        self.assertTrue(
            human_message_content[1]["image_url"]["url"].startswith(
                "data:image/png;base64,"
            )
        )
        self.assertEqual(
            additional_kwargs["requirement_document_id"], str(self.document.id)
        )
        self.assertEqual(additional_kwargs["image_source"], "requirement_document")
        self.assertIn(
            f"/api/requirements/documents/{self.document.id}/images/img_000/",
            display_message,
        )


class SkillScreenshotDirectoryTests(SimpleTestCase):
    def test_sanitize_runtime_path_segment_blocks_path_traversal(self):
        self.assertEqual(
            _sanitize_runtime_path_segment("../case/89", "_default"),
            "__case_89",
        )

    def test_build_skill_screenshots_dir_uses_runtime_media_root(self):
        with tempfile.TemporaryDirectory() as temp_media_root:
            with override_settings(MEDIA_ROOT=temp_media_root):
                screenshots_dir = _build_skill_screenshots_dir(1, "89")

        self.assertTrue(screenshots_dir.endswith("skill_runtime/screenshots/1/89"))
        self.assertNotIn("/skills/1/11/", screenshots_dir)

    def test_build_skill_screenshots_dir_keeps_path_inside_media_root(self):
        with tempfile.TemporaryDirectory() as temp_media_root:
            with override_settings(MEDIA_ROOT=temp_media_root):
                screenshots_dir = _build_skill_screenshots_dir(1, "../case/89")

        self.assertTrue(screenshots_dir.startswith(temp_media_root))
        self.assertNotIn("..", screenshots_dir)

    def test_prepare_skill_screenshots_dir_clears_stale_chat_session(self):
        with tempfile.TemporaryDirectory() as temp_media_root:
            with override_settings(MEDIA_ROOT=temp_media_root):
                screenshots_dir = _prepare_skill_screenshots_dir(1, "89", "chat-a")
                stale_file = os.path.join(screenshots_dir, "old.png")
                with open(stale_file, "w", encoding="utf-8") as f:
                    f.write("old screenshot")

                refreshed_dir = _prepare_skill_screenshots_dir(1, "89", "chat-b")
                marker_path = os.path.join(refreshed_dir, ".chat_session")

                self.assertEqual(refreshed_dir, screenshots_dir)
                self.assertFalse(os.path.exists(stale_file))
                with open(marker_path, "r", encoding="utf-8") as f:
                    self.assertEqual(f.read().strip(), "chat-b")

    def test_build_skill_artifacts_dir_uses_runtime_media_root(self):
        with tempfile.TemporaryDirectory() as temp_media_root:
            with override_settings(MEDIA_ROOT=temp_media_root):
                artifacts_dir = _build_skill_artifacts_dir(1, "session-1")

        self.assertTrue(artifacts_dir.endswith("skill_runtime/artifacts/1/session-1"))
        self.assertNotIn("/skills/1/11/", artifacts_dir)

    def test_collect_skill_artifacts_detects_named_generated_file(self):
        with tempfile.TemporaryDirectory() as temp_media_root:
            with override_settings(MEDIA_ROOT=temp_media_root, MEDIA_URL="/media/"):
                skill_dir = os.path.join(temp_media_root, "skills", "1", "11")
                os.makedirs(skill_dir, exist_ok=True)
                generated_file = os.path.join(skill_dir, "order-payment-flow.drawio")
                with open(generated_file, "w", encoding="utf-8") as f:
                    f.write("<mxfile></mxfile>")

                artifacts = _collect_skill_artifacts(
                    "已帮你生成 draw.io 文件：order-payment-flow.drawio",
                    skill_dir=skill_dir,
                    artifacts_dir=os.path.join(temp_media_root, "skill_runtime", "artifacts", "1", "s1"),
                    artifacts_before={},
                )

        self.assertEqual(len(artifacts), 1)
        self.assertEqual(artifacts[0]["name"], "order-payment-flow.drawio")
        self.assertEqual(artifacts[0]["url"], "/media/skills/1/11/order-payment-flow.drawio")

    def test_finalize_skill_result_wraps_output_with_file_payload(self):
        with tempfile.TemporaryDirectory() as temp_media_root:
            with override_settings(MEDIA_ROOT=temp_media_root, MEDIA_URL="/media/"):
                skill_dir = os.path.join(temp_media_root, "skills", "1", "11")
                os.makedirs(skill_dir, exist_ok=True)
                generated_file = os.path.join(skill_dir, "demo.drawio")
                with open(generated_file, "w", encoding="utf-8") as f:
                    f.write("<mxfile></mxfile>")

                wrapped = _finalize_skill_result(
                    "已生成文件 demo.drawio",
                    skill_dir=skill_dir,
                    artifacts_dir=os.path.join(temp_media_root, "skill_runtime", "artifacts", "1", "s1"),
                    artifacts_before={},
                )

        self.assertIn('"type": "file"', wrapped)
        self.assertIn('/media/skills/1/11/demo.drawio', wrapped)


class TerminalOutputSanitizerTests(SimpleTestCase):
    def test_strip_terminal_control_sequences_removes_ansi_color_codes(self):
        raw = "\x1b[32m✓\x1b[0m Browser closed"

        self.assertEqual(strip_terminal_control_sequences(raw), "✓ Browser closed")
