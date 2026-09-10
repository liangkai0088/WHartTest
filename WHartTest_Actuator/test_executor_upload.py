#!/usr/bin/env python
"""Upload step tests for PlaywrightExecutor."""

import asyncio
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))

from executor import PlaywrightExecutor, StepConfig
from runtime_env import (
    resolve_upload_file,
    auto_fixtures_snapshot,
    cleanup_generated_upload_files,
)


class FakeFileChooser:
    def __init__(self):
        self.files = None

    async def set_files(self, files):
        self.files = files


class FakeFileChooserContext:
    def __init__(self, chooser):
        self.value = None
        self._chooser = chooser

    async def __aenter__(self):
        loop = asyncio.get_running_loop()
        self.value = loop.create_future()
        self.value.set_result(self._chooser)
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakePage:
    def __init__(self):
        self.expect_file_chooser_calls = 0
        self.file_chooser = FakeFileChooser()

    def expect_file_chooser(self):
        self.expect_file_chooser_calls += 1
        return FakeFileChooserContext(self.file_chooser)


class FakeLocator:
    def __init__(self, upload_error=None):
        self.upload_error = upload_error
        self.files = None
        self.clicks = 0
        self.waits = []

    async def wait_for(self, state=None, timeout=None):
        self.waits.append((state, timeout))

    async def set_input_files(self, files):
        if self.upload_error:
            raise self.upload_error
        self.files = files

    async def click(self):
        self.clicks += 1


class PlaywrightExecutorUploadTest(unittest.TestCase):
    def setUp(self):
        self.executor = PlaywrightExecutor()
        # 本组测试针对 legacy _upload_file/_execute_step 路径
        # （enhanced engine 为运行时主路径，FakePage 无法驱动）
        self.executor._enhanced_executor = None

    def _upload_step(self, file_path='/app/data/upload.txt'):
        return StepConfig(
            step_id=1,
            operation_type='upload',
            locator_type='xpath',
            locator_value='//button[text()=" upload"]',
            input_value=file_path,
        )

    def test_upload_uses_file_input_directly_when_locator_is_input(self):
        locator = FakeLocator()
        page = FakePage()
        step = self._upload_step()

        async def run_step():
            with patch.object(self.executor, '_get_locator', return_value=locator):
                return await self.executor._execute_step(page, step)

        success, message, screenshot = asyncio.run(run_step())

        self.assertTrue(success)
        self.assertIn('upload', message)
        self.assertIsNone(screenshot)
        self.assertEqual(locator.files, '/app/data/upload.txt')
        self.assertEqual(locator.clicks, 0)
        self.assertEqual(page.expect_file_chooser_calls, 0)

    def test_upload_falls_back_to_file_chooser_when_locator_is_button(self):
        locator = FakeLocator(
            upload_error=Exception('Locator.set_input_files: Error: Node is not an HTMLInputElement')
        )
        page = FakePage()
        step = self._upload_step()

        async def run_step():
            with patch.object(self.executor, '_get_locator', return_value=locator):
                return await self.executor._execute_step(page, step)

        success, message, screenshot = asyncio.run(run_step())

        self.assertTrue(success)
        self.assertIn('upload', message)
        self.assertIsNone(screenshot)
        self.assertEqual(locator.files, None)
        self.assertEqual(locator.clicks, 1)
        self.assertEqual(page.expect_file_chooser_calls, 1)
        self.assertEqual(page.file_chooser.files, '/app/data/upload.txt')

    def test_upload_does_not_hide_other_set_input_files_errors(self):
        locator = FakeLocator(upload_error=Exception('No such file or directory'))
        page = FakePage()
        step = self._upload_step()

        async def run_upload():
            await self.executor._upload_file(page, locator, step.input_value, step)

        with self.assertRaisesRegex(Exception, 'No such file'):
            asyncio.run(run_upload())
        self.assertEqual(page.expect_file_chooser_calls, 0)


class AutoFixtureTests(unittest.TestCase):
    """缺失上传文件时自动生成占位夹具 + 执行后清理（通用能力）"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix='wharttest_fixture_')
        os.environ['WHARTTEST_ACTUATOR_GENERATED_DIR'] = self.tmpdir
        # 确保默认开启（用例不依赖环境）
        os.environ.pop('WHARTTEST_ACTUATOR_AUTO_FIXTURE', None)

    def tearDown(self):
        os.environ.pop('WHARTTEST_ACTUATOR_GENERATED_DIR', None)
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        cleanup_generated_upload_files()

    def test_missing_file_generates_placeholder_fixture(self):
        path = resolve_upload_file('test_upload.exe')
        self.assertIsNotNone(path)
        self.assertTrue(Path(path).is_file())
        self.assertEqual(Path(path).name, 'test_upload.exe')  # 扩展名保留

    def test_cleanup_removes_only_files_generated_after_snapshot(self):
        before = auto_fixtures_snapshot()
        path_a = resolve_upload_file('a.exe')
        snapshot_mid = auto_fixtures_snapshot()
        path_b = resolve_upload_file('b.exe')

        cleanup_generated_upload_files(snapshot_mid)  # 只清理 b
        self.assertTrue(Path(path_a).is_file())
        self.assertFalse(Path(path_b).exists())

        cleanup_generated_upload_files(before)  # 清理 a
        self.assertFalse(Path(path_a).exists())

    def test_existing_file_not_replaced_by_fixture(self):
        real = Path(self.tmpdir) / 'real.bin'
        real.write_bytes(b'real')
        path = resolve_upload_file(str(real))
        self.assertEqual(str(path), str(real))
        self.assertEqual(real.read_bytes(), b'real')


if __name__ == '__main__':
    unittest.main()
