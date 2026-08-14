"""agent-browser 语义引擎执行器（web-qa-bot src/bot.ts 的 Python 移植）。

- executeStep 分发（含 checkbox: / pagination: / row: / agent: 前缀）
- beforeAll/beforeEach/afterEach/afterAll 钩子
- 渐进落库 QaStepResult（on_step 回调）
- 失败截图 + markdown 报告 + result_json；绝不抛出
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime
from typing import Callable, List, Optional

from django.conf import settings

from .agent_locator import AgentLocator, LocatorError, build_fallback_script
from .assertions import (
    AssertionError,
    expect_clickable,
    expect_console_event,
    expect_count,
    expect_modal,
    expect_no_errors,
    expect_not_visible,
    expect_text,
    expect_title,
    expect_url,
    expect_value,
    expect_visible,
    get_snapshot_value,
    assert_value_match,
)
from .browser import AgentBrowser, BrowserError
from .snapshot import Snapshot, parse_snapshot, resolve_ref, snapshot_has_selector
from .yaml_loader import TestSuite, parse_suite

logger = logging.getLogger('web_qa')

DEFAULT_TIMEOUT = 30000
DEFAULT_RETRIES = 3
CLICK_RETRY_TIMEOUT = 10000
SESSION_PREFIX = 'webqa-run'


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


class StepExecutionError(Exception):
    """步骤执行失败（包含可选跳过标记）。"""

    def __init__(self, message: str, optional: bool = False):
        super().__init__(message)
        self.optional = optional


class AgentBrowserRunner:
    """agent-browser 语义执行引擎。"""

    def __init__(
        self,
        suite: TestSuite,
        base_url: str,
        browser: AgentBrowser,
        project_id: int,
        llm_config=None,
        run_dir: str = '',
        on_step: Optional[Callable] = None,
        timeout: int = DEFAULT_TIMEOUT,
    ):
        self.suite = suite
        self.base_url = base_url or suite.base_url or 'http://localhost'
        self.browser = browser
        self.project_id = project_id
        self.llm_config = llm_config
        self.run_dir = run_dir
        self.screenshot_dir = os.path.join(run_dir, 'screenshots') if run_dir else 'screenshots'
        self.on_step = on_step
        self.timeout = timeout
        self.current_snapshot: Optional[Snapshot] = None
        self.console_events: List[dict] = []
        self.agent_locator: Optional[AgentLocator] = None
        self.active_test_index = 0
        self.active_test_name = ''
        self.suite_name = suite.name

    # ---------------- 基础设施 ----------------

    def _get_locator(self) -> AgentLocator:
        if self.agent_locator is None:
            js_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'js')
            self.agent_locator = AgentLocator(
                browser=self.browser,
                llm_config=self.llm_config,
                project_id=self.project_id,
                base_url=self.base_url,
                screenshot_dir=self.screenshot_dir,
                get_snapshot=lambda: self.current_snapshot,
                js_dir=js_dir,
            )
        return self.agent_locator

    def _notify_step(
        self,
        step_index: int,
        action: str,
        status: str,
        error: str = '',
        screenshot_path: str = '',
        locator_meta: Optional[dict] = None,
        duration_ms: int = 0,
    ) -> None:
        if self.on_step is None:
            return
        try:
            self.on_step(
                test_index=self.active_test_index,
                test_name=self.active_test_name,
                step_index=step_index,
                action=action,
                status=status,
                error=error,
                screenshot_path=screenshot_path,
                locator_meta=locator_meta or {},
                duration_ms=duration_ms,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning('[web_qa] on_step callback failed: %s', e)

    # ---------------- 快照 / 导航 ----------------

    def _snapshot(self) -> Snapshot:
        try:
            output = self.browser.snapshot(interactive=True)
            url = self.browser.get_url()
        except BrowserError:
            output = self.browser.snapshot_full()
            url = ''
        snap = parse_snapshot(output, url)
        self.current_snapshot = snap
        return snap

    def _full_snapshot(self) -> Snapshot:
        output = self.browser.snapshot_full()
        return parse_snapshot(output, self.browser.get_url())

    def _resolve_url(self, url: str) -> str:
        from urllib.parse import urlparse, urljoin
        if urlparse(url).scheme:
            return url
        return urljoin(self.base_url, url)

    def goto(self, url: str) -> Snapshot:
        full = self._resolve_url(url)
        self.browser.open(full)
        _sleep(0.5)
        return self._snapshot()

    def snapshot(self) -> Snapshot:
        return self._snapshot()

    def screenshot(self, name: Optional[str] = None) -> str:
        os.makedirs(self.screenshot_dir, exist_ok=True)
        filename = name or f'screenshot-{int(time.time() * 1000)}.png'
        path = os.path.join(self.screenshot_dir, filename)
        self.browser.screenshot(path)
        return path

    # ---------------- 元素操作 ----------------

    def _try_resolve_ref(self, selector: str, timeout_ms: int = CLICK_RETRY_TIMEOUT) -> Optional[str]:
        start = time.time()
        while (time.time() - start) * 1000 < timeout_ms:
            snap = self._snapshot()
            ref = resolve_ref(snap, selector)
            if ref:
                return ref
            _sleep(0.2)
        return None

    def click(self, selector: str) -> None:
        if selector.lower().startswith('checkbox:'):
            name = selector[len('checkbox:'):].strip()
            if not name:
                raise StepExecutionError(f'无效选择器: {selector}')
            clicked = self._eval_bool(build_fallback_script('click_checkbox_by_text', name))
            if not clicked:
                raise StepExecutionError(f'Element not found: {selector}')
            self._snapshot()
            return

        if selector.lower().startswith('pagination:'):
            target = selector[len('pagination:'):].strip()
            if not target:
                raise StepExecutionError(f'无效选择器: {selector}')
            clicked = self._eval_bool(build_fallback_script('click_pagination', target))
            if not clicked:
                raise StepExecutionError(f'Element not found: {selector}')
            self._snapshot()
            return

        if selector.lower().startswith('row:'):
            parts = [p.strip() for p in selector[len('row:'):].split(':') if p.strip()]
            if len(parts) < 2:
                raise StepExecutionError(f'row: 前缀需要 "row:行文本:操作文本"，实际: {selector}')
            row_text, action_text = parts[0], ':'.join(parts[1:])
            clicked = self._eval_bool(build_fallback_script('click_row_action', row_text, action_text))
            if not clicked:
                raise StepExecutionError(f'Element not found: {selector}')
            self._snapshot()
            return

        if selector.lower().startswith('agent:'):
            resolution = self._get_locator().locate(selector[len('agent:'):].strip(), 'click')
            if resolution.executed:
                _sleep(0.1)
                self._snapshot()
                return
            if resolution.x is not None and resolution.y is not None:
                self._click_coords(resolution.x, resolution.y)
                _sleep(0.1)
                self._snapshot()
                return
            selector = resolution.selector

        ref = self._try_resolve_ref(selector)
        if ref:
            self.browser.click(ref)
            _sleep(0.1)
            self._snapshot()
            return

        clicked = self._eval_bool(build_fallback_script('click_by_text', selector))
        if not clicked:
            raise StepExecutionError(f'Element not found: {selector}')
        _sleep(0.1)
        self._snapshot()

    def _click_coords(self, x, y) -> None:
        import json
        script = (
            "(() => { const el = document.elementFromPoint("
            f"{int(x)}, {int(y)}"
            "); if (!el) return false; const clickable = el.closest('button, a, [role=\"button\"], input, select, textarea, [onclick]') || el; clickable.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true, view: window })); clickable.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, cancelable: true, view: window })); clickable.click(); return true; })()"
        )
        ok = bool(self.browser.eval_js(script, use_stdin=True))
        if not ok:
            raise StepExecutionError('坐标点击失败: elementFromPoint 无元素')

    def type(self, selector: str, text: str) -> None:
        if selector.lower().startswith('agent:'):
            resolution = self._get_locator().locate(selector[len('agent:'):].strip(), 'type', text)
            if resolution.executed:
                self._snapshot()
                return
            if resolution.x is not None and resolution.y is not None:
                self._type_coords(resolution.x, resolution.y, text)
                self._snapshot()
                return
            selector = resolution.selector

        ref = self._try_resolve_ref(selector)
        if ref:
            self.browser.click(ref)
            self.browser.type(ref, text)
            self._snapshot()
            return
        typed = self._eval_bool(build_fallback_script('type_by_selector', selector, text))
        if not typed:
            raise StepExecutionError(f'Element not found: {selector}')
        self._snapshot()

    def _type_coords(self, x, y, text) -> None:
        import json
        value = json.dumps(text)
        script = (
            "(() => { const el = document.elementFromPoint("
            f"{int(x)}, {int(y)}"
            "); if (!el) return false; el.focus(); const input = el.matches('input, textarea') ? el : (el.querySelector('input, textarea') || el); if ('value' in input) { input.value = "
            + value
            + "; input.dispatchEvent(new Event('input', { bubbles: true })); input.dispatchEvent(new Event('change', { bubbles: true })); } else { input.textContent = "
            + value
            + "; input.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: "
            + value
            + " })); } return true; })()"
        )
        ok = bool(self.browser.eval_js(script, use_stdin=True))
        if not ok:
            raise StepExecutionError('坐标输入失败: elementFromPoint 无元素')

    def select(self, selector: str, value: str) -> None:
        if selector.lower().startswith('agent:'):
            resolution = self._get_locator().locate(selector[len('agent:'):].strip(), 'click')
            if resolution.x is not None and resolution.y is not None:
                self._click_coords(resolution.x, resolution.y)
            elif not resolution.executed:
                selector = resolution.selector
            else:
                selector = resolution.selector

        # 参考实现：点击 select，轮询下拉选项（快照 role=option/menuitem/listitem 或 DOM select-option）
        ref = self._try_resolve_ref(selector)
        if ref:
            self.browser.click(ref)
        timeout = 5000
        start = time.time()
        while (time.time() - start) * 1000 < timeout:
            try:
                snap = self._snapshot()
                for key, elem in snap.refs.items():
                    if not key.startswith('@'):
                        continue
                    if value.lower() in elem.name.lower():
                        if elem.role.lower() in ('option', 'menuitem', 'listitem'):
                            self.browser.click(elem.id)
                            return
            except BrowserError:
                pass
            clicked = self._eval_bool(build_fallback_script('select_option', value))
            if clicked:
                return
            _sleep(0.5)
        raise StepExecutionError(f'Option "{value}" not found in dropdown')

    def press(self, key: str) -> None:
        self.browser.press(key)
        self._snapshot()

    def hover(self, selector: str) -> None:
        if selector.lower().startswith('agent:'):
            resolution = self._get_locator().locate(selector[len('agent:'):].strip(), 'hover')
            if resolution.executed:
                return
            selector = resolution.selector
        ref = self._try_resolve_ref(selector)
        if not ref:
            raise StepExecutionError(f'Element not found: {selector}')
        self.browser.hover(ref)

    def wait_for(self, selector: str, timeout_ms: Optional[int] = None) -> Snapshot:
        timeout_ms = timeout_ms or self.timeout
        if selector.lower().startswith('agent:'):
            desc = selector[len('agent:'):].strip()
            start = time.time()
            while (time.time() - start) * 1000 < timeout_ms:
                try:
                    self._get_locator().locate_presence(desc)
                    return self._snapshot()
                except LocatorError:
                    _sleep(0.5)
            raise StepExecutionError(f'Timeout waiting for element: {selector}')
        start = time.time()
        while (time.time() - start) * 1000 < timeout_ms:
            try:
                snap = self._snapshot()
            except BrowserError:
                _sleep(0.5)
                continue
            if snapshot_has_selector(snap, selector):
                return snap
            if not selector.startswith('@') and ':' not in selector:
                if self._eval_bool(build_fallback_script('has_text', selector), quiet=True):
                    return snap
            _sleep(0.5)
        raise StepExecutionError(f'Timeout waiting for element: {selector}')

    def wait_for_load(self) -> None:
        _sleep(0.5)
        self._snapshot()

    def wait_for_url(self, pattern: str, timeout_ms: Optional[int] = None) -> None:
        timeout_ms = timeout_ms or self.timeout
        start = time.time()
        while (time.time() - start) * 1000 < timeout_ms:
            snap = self._snapshot()
            if pattern in snap.url:
                return
            _sleep(0.2)
        raise StepExecutionError(f'Timeout waiting for URL: {pattern}')

    def get_console(self) -> List[dict]:
        try:
            out = self.browser._run(['console'])
            return self._parse_console(out)
        except BrowserError:
            return []

    def _parse_console(self, output: str) -> List[dict]:
        events = []
        for line in output.splitlines():
            line = line.strip()
            if not line:
                continue
            evt_type = 'log'
            text = line
            lower = line.lower()
            if lower.startswith('error') or '[error]' in lower or '❌' in line:
                evt_type = 'error'
            elif lower.startswith('warn') or '[warn]' in lower or '⚠' in line:
                evt_type = 'warn'
            text = text.split(':', 1)[-1].strip() if (text.startswith(('Error', 'Warn', 'Info', 'Log', 'Debug'))) else text
            events.append({'type': evt_type, 'text': text, 'timestamp': time.time()})
        return events

    def _eval_bool(self, script: str, quiet: bool = False) -> bool:
        try:
            result = self.browser.eval_js(script, use_stdin=True)
            return bool(result)
        except BrowserError:
            if not quiet:
                logger.debug('[web_qa] eval failed (likely page error)')
            return False

    # ---------------- 断言 ----------------

    def expect_visible(self, selector: str) -> None:
        if selector.lower().startswith('agent:'):
            self._get_locator().locate_presence(selector[len('agent:'):].strip())
            return
        self.wait_for(selector, timeout_ms=min(self.timeout, 10000))

    def expect_value_action(self, selector: str, expected: str, contains: bool = False) -> None:
        if not self.current_snapshot:
            self._snapshot()
        try:
            snap_value = get_snapshot_value(self.current_snapshot, selector, expected)
        except AssertionError:
            snap_value = None
        if snap_value is not None:
            assert_value_match(selector, snap_value, expected, contains)
            return
        dom_value = self._get_dom_value(selector)
        if dom_value is not None:
            assert_value_match(selector, dom_value, expected, contains)
            return
        raise AssertionError(
            f'Cannot determine value for {selector}; snapshot did not expose a value and DOM fallback could not locate the control',
            'value unavailable',
            expected,
        )

    def _get_dom_value(self, selector: str):
        try:
            return self.browser.eval_js(build_fallback_script('get_value', selector), use_stdin=True)
        except BrowserError:
            return None

    # ---------------- 步骤分发 ----------------

    def execute_step(self, step, context: dict, step_index: int) -> dict:
        action = step.action
        value = step.value
        output = {'screenshot': ''}

        if action == 'goto':
            self.goto(value)
        elif action == 'waitForLoad':
            self.wait_for_load()
        elif action == 'waitFor':
            self.wait_for(value)
        elif action == 'waitMs':
            _sleep(int(value) / 1000.0)
        elif action == 'click':
            self.click(value)
        elif action == 'type':
            self.type(value['ref'], value['text'])
        elif action == 'select':
            self.select(value['ref'], value['value'])
        elif action == 'hover':
            self.hover(value)
        elif action == 'press':
            self.press(value)
        elif action == 'snapshot':
            self.snapshot()

        if action == 'screenshot':
            requested = value if isinstance(value, str) and value else None
            path = self.screenshot(self._format_screenshot_name(requested, context, step_index))
            output['screenshot'] = path
            return output

        if action == 'expectVisible':
            self.expect_visible(value)
        elif action == 'expectNotVisible':
            self._snapshot()
            expect_not_visible(self.current_snapshot, value)
        elif action == 'expectText':
            self._snapshot()
            expect_text(self.current_snapshot, value['ref'], value['text'], bool(value.get('contains', False)))
        elif action == 'expectTitle':
            self._snapshot()
            if isinstance(value, dict):
                expect_title(self.current_snapshot, value['text'], bool(value.get('contains', False)))
            else:
                expect_title(self.current_snapshot, value)
        elif action == 'expectValue':
            self._snapshot()
            self.expect_value_action(value['ref'], value.get('value') or value.get('text') or '', bool(value.get('contains', False)))
        elif action == 'expectUrl':
            self._snapshot()
            expect_url(self.current_snapshot, value.get('url') if isinstance(value, dict) and value.get('url') else value)
        elif action == 'expectCount':
            self._snapshot()
            role = value.get('role') or value.get('selector')
            if not role:
                raise StepExecutionError('expectCount requires role or selector')
            if value.get('count') is not None:
                expect_count(self.current_snapshot, role, value['count'])
            else:
                expect_count(self.current_snapshot, role, {'min': value.get('min'), 'max': value.get('max')})
        elif action == 'expectNoErrors':
            events = self.get_console()
            expect_no_errors(events)
        elif action == 'expectConsoleEvent':
            events = self.get_console()
            expect_console_event(events, value)
        elif action == 'expectModal':
            self._snapshot()
            expect_modal(self.current_snapshot, bool(value))
        elif action == 'expectClickable':
            self._snapshot()
            expect_clickable(self.current_snapshot, value)

        return output

    def _format_screenshot_name(self, template: Optional[str], context: dict, step_index: int) -> str:
        test_name = context.get('test_name') or context.get('case_name') or 'test'
        if template:
            name = template.replace('{{testName}}', test_name).replace('{{caseName}}', test_name)
            name = name.replace('{testName}', test_name).replace('{caseName}', test_name)
        else:
            name = f'{test_name}-{step_index + 1}'
        name = re_sanitize(name)
        if not name.lower().endswith('.png'):
            name += '.png'
        return name

    def step_to_name(self, step) -> str:
        return step.action_label

    def run(self, steps: list, context: dict) -> List[dict]:
        results = []
        for i, step in enumerate(steps):
            start = time.time()
            step_name = self.step_to_name(step)
            try:
                output = self.execute_step(step, context, i)
                duration_ms = int((time.time() - start) * 1000)
                self._notify_step(
                    step_index=i,
                    action=step_name,
                    status='pass',
                    duration_ms=duration_ms,
                    screenshot_path=output.get('screenshot', ''),
                )
                results.append({
                    'name': step_name,
                    'status': 'pass',
                    'duration': duration_ms,
                    'screenshot': output.get('screenshot', ''),
                })
            except (StepExecutionError, AssertionError, BrowserError, LocatorError, ValueError, KeyError, TypeError) as err:
                message = str(err)
                duration_ms = int((time.time() - start) * 1000)
                self._notify_step(
                    step_index=i,
                    action=step_name,
                    status='skip' if step.optional else 'fail',
                    error=f'Optional step skipped: {message}' if step.optional else message,
                    duration_ms=duration_ms,
                )
                results.append({
                    'name': step_name,
                    'status': 'skip' if step.optional else 'fail',
                    'duration': duration_ms,
                    'error': f'Optional step skipped: {message}' if step.optional else message,
                })
                if not step.optional:
                    raise
        return results

    def run_test(self, test, context: dict) -> dict:
        start = time.time()
        screenshots: List[str] = []
        steps: List[dict] = []

        if test.skip:
            return {'name': test.name, 'status': 'skip', 'duration': 0, 'screenshots': [], 'steps': []}

        try:
            self.console_events = []
            steps = self.run(test.steps, {**context, 'test_name': test.name, 'case_name': test.name})
            screenshots.extend(s['screenshot'] for s in steps if s.get('screenshot'))
            events = self.get_console()
            errors = [e for e in events if e.get('type') == 'error']
            if errors and not test.known_issue:
                return {
                    'name': test.name,
                    'status': 'warn',
                    'duration': int((time.time() - start) * 1000),
                    'error': f'{len(errors)} console error(s)',
                    'screenshots': screenshots,
                    'steps': steps,
                }
            return {
                'name': test.name,
                'status': 'warn' if test.known_issue else 'pass',
                'duration': int((time.time() - start) * 1000),
                'screenshots': screenshots,
                'steps': steps,
            }
        except Exception as err:  # noqa: BLE001
            error = str(err)
            shot = ''
            try:
                shot = self.screenshot(self._format_screenshot_name(f'failure-{test.name}', context, 0))
                screenshots.append(shot)
            except Exception:  # noqa: BLE001
                pass
            return {
                'name': test.name,
                'status': 'warn' if test.known_issue else 'fail',
                'duration': int((time.time() - start) * 1000),
                'error': error,
                'screenshots': screenshots,
                'steps': steps,
            }

    def run_suite(self) -> dict:
        start = time.time()
        suite = self.suite
        base_url = self.base_url
        results: List[dict] = []
        suite_context = {'suite_name': suite.name}

        # beforeAll
        if suite.before_all:
            try:
                self.run(suite.before_all, {**suite_context, 'hook_name': 'beforeAll'})
            except Exception as err:  # noqa: BLE001
                message = f'beforeAll failed: {err}'
                results.append({
                    'name': 'beforeAll hook', 'status': 'fail', 'duration': 0,
                    'error': message, 'screenshots': [], 'steps': [],
                })
                for test in suite.tests:
                    results.append({
                        'name': test.name, 'status': 'skip', 'duration': 0,
                        'error': message, 'screenshots': [], 'steps': [],
                    })
                return self._build_suite_result(suite.name, base_url, results, start)

        has_only = any(t.only for t in suite.tests)
        tests_to_run = [t for t in suite.tests if t.only] if has_only else suite.tests
        if has_only:
            for t in suite.tests:
                if not t.only:
                    results.append({
                        'name': t.name, 'status': 'skip', 'duration': 0,
                        'error': 'Skipped because another test has only: true',
                        'screenshots': [], 'steps': [],
                    })

        for test in tests_to_run:
            self.active_test_index = len(results)
            self.active_test_name = test.name
            test_ctx = {**suite_context, 'test_name': test.name, 'case_name': test.name}

            if suite.before_each:
                try:
                    self.run(suite.before_each, {**test_ctx, 'hook_name': 'beforeEach'})
                except Exception as err:  # noqa: BLE001
                    results.append({
                        'name': test.name, 'status': 'skip', 'duration': 0,
                        'error': f'beforeEach failed: {err}', 'screenshots': [], 'steps': [],
                    })
                    continue

            result = self.run_test(test, test_ctx)
            results.append(result)

            if suite.after_each:
                try:
                    after_steps = self.run(suite.after_each, {**test_ctx, 'hook_name': 'afterEach'})
                    result['steps'].extend(after_steps)
                    result['screenshots'].extend(s['screenshot'] for s in after_steps if s.get('screenshot'))
                except Exception as err:  # noqa: BLE001
                    message = f'afterEach failed: {err}'
                    result['status'] = 'fail'
                    result['error'] = f"{result.get('error') or ''}; {message}"

        if suite.after_all:
            try:
                self.run(suite.after_all, {**suite_context, 'hook_name': 'afterAll'})
            except Exception as err:  # noqa: BLE001
                results.append({
                    'name': 'afterAll hook', 'status': 'fail', 'duration': 0,
                    'error': str(err), 'screenshots': [], 'steps': [],
                })

        return self._build_suite_result(suite.name, base_url, results, start)

    def _build_suite_result(self, name: str, url: str, tests: List[dict], start_time: float) -> dict:
        summary = {
            'total': len(tests),
            'passed': len([t for t in tests if t.get('status') == 'pass']),
            'failed': len([t for t in tests if t.get('status') == 'fail']),
            'skipped': len([t for t in tests if t.get('status') == 'skip']),
            'warnings': len([t for t in tests if t.get('status') == 'warn']),
        }
        return {
            'name': name,
            'url': url,
            'tests': tests,
            'duration': int((time.time() - start_time) * 1000),
            'summary': summary,
            'timestamp': time.time(),
        }


def re_sanitize(name: str) -> str:
    import re
    name = re.sub(r'[\\/:*?"<>|]', '-', name)
    name = re.sub(r'\s+', '-', name)
    name = re.sub(r'-+', '-', name)
    return name.strip('-')


# ---------------- 顶层执行入口 ----------------

def run_agent_browser_suite(run_id: int) -> dict:
    """执行 agent_browser 引擎套件；绝不抛出。"""
    from .models import QaRun, QaStepResult

    try:
        run = QaRun.objects.select_related('suite', 'suite__project', 'suite__llm_config').get(id=run_id)
    except QaRun.DoesNotExist:
        return {'error': f'run {run_id} not found'}

    suite_model = run.suite
    try:
        suite = parse_suite(suite_model.yaml_content or '', tolerant=True)
    except Exception as e:  # noqa: BLE001
        run.status = 'failed'
        run.error = f'YAML 解析失败: {e}'
        run.finished_at = now()
        run.save(update_fields=['status', 'error', 'finished_at'])
        return {'run_id': run_id, 'status': 'failed', 'error': run.error}

    if suite.errors and not suite.tests:
        run.status = 'failed'
        run.error = '; '.join(suite.errors)
        run.finished_at = now()
        run.save(update_fields=['status', 'error', 'finished_at'])
        return {'run_id': run_id, 'status': 'failed', 'error': run.error}

    run_dir = os.path.join(settings.MEDIA_ROOT, 'web_qa', 'runs', str(run_id))
    os.makedirs(os.path.join(run_dir, 'screenshots'), exist_ok=True)

    session_id = f'{SESSION_PREFIX}-{run_id}'
    browser = AgentBrowser(session_id=session_id, timeout=30, cwd=run_dir)

    def on_step(**kwargs):
        QaStepResult.objects.create(run=run, **kwargs)

    runner = AgentBrowserRunner(
        suite=suite,
        base_url=suite_model.base_url,
        browser=browser,
        project_id=suite_model.project_id,
        llm_config=suite_model.llm_config,
        run_dir=run_dir,
        on_step=on_step,
    )

    result = {'status': 'running', 'error': '', 'summary': {}, 'tests': [], 'report_md': ''}
    try:
        runner.suite_name = suite.name
        suite_result = runner.run_suite()
        result = suite_result
        run.summary = suite_result['summary']
        run.result_json = suite_result
        run.report_md = build_report_md(suite_model, suite_result)
        if run.status != 'cancelled':
            run.status = 'passed' if suite_result['summary']['failed'] == 0 else 'failed'
    except Exception as e:  # noqa: BLE001
        logger.exception('[web_qa] run %s failed: %s', run_id, e)
        if run.status != 'cancelled':
            run.status = 'failed'
            run.error = str(e)
            run.summary = {'total': 0, 'passed': 0, 'failed': 1, 'skipped': 0, 'warnings': 0}
            run.report_md = build_report_md(suite_model, {
                'name': suite.name, 'url': suite_model.base_url,
                'tests': [{'name': 'runner', 'status': 'error', 'error': str(e), 'screenshots': [], 'steps': []}],
                'duration': 0, 'summary': run.summary,
            })
    finally:
        try:
            browser.close()
        except Exception:  # noqa: BLE001
            pass
        run.finished_at = now()
        run.save(update_fields=['status', 'summary', 'result_json', 'report_md', 'error', 'finished_at'])
    return {'run_id': run_id, 'status': run.status, 'error': run.error}


def now():
    from django.utils import timezone
    return timezone.now()


# ---------------- Markdown 报告 ----------------

def build_report_md(suite_model, suite_result: dict) -> str:
    title = suite_result.get('name') or suite_model.name
    summary = suite_result.get('summary') or {}
    total = summary.get('total', 0)
    passed = summary.get('passed', 0)
    failed = summary.get('failed', 0)
    skipped = summary.get('skipped', 0)
    warnings = summary.get('warnings', 0)
    duration_s = (suite_result.get('duration') or 0) / 1000.0
    pass_rate = (passed / total * 100) if total else 0

    lines = []
    lines.append(f'# {title}')
    lines.append('')
    lines.append(f'**生成时间:** {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    lines.append(f'**执行引擎:** agent_browser')
    lines.append(f'**URL:** {suite_result.get("url") or suite_model.base_url}')
    lines.append(f'**耗时:** {duration_s:.2f}s')
    lines.append('')
    lines.append('## 摘要')
    lines.append('')
    lines.append('| 指标 | 值 |')
    lines.append('| --- | --- |')
    lines.append(f'| 用例总数 | {total} |')
    lines.append(f'| 通过 | {passed} |')
    lines.append(f'| 失败 | {failed} |')
    lines.append(f'| 跳过 | {skipped} |')
    lines.append(f'| 警告 | {warnings} |')
    lines.append(f'| 通过率 | {pass_rate:.1f}% |')
    lines.append('')

    for test in suite_result.get('tests', []):
        status = test.get('status', '')
        icon = {'pass': '✅', 'fail': '❌', 'skip': '⏭️', 'warn': '⚠️', 'error': '❌'}.get(status, '➖')
        lines.append(f'## {icon} {test.get("name", "")}')
        lines.append('')
        if test.get('error'):
            lines.append(f'**错误:** {test["error"]}')
            lines.append('')
        if test.get('duration'):
            lines.append(f'**耗时:** {test["duration"]}ms')
            lines.append('')
        steps = test.get('steps', [])
        if steps:
            lines.append('| # | 步骤 | 状态 | 耗时 | 备注 |')
            lines.append('| --- | --- | --- | --- | --- |')
            for i, step in enumerate(steps):
                step_icon = {'pass': '✅', 'fail': '❌', 'skip': '⏭️', 'error': '❌'}.get(step.get('status'), '➖')
                note = step.get('error', '') or ''
                if step.get('screenshot'):
                    note = (note + '; ' if note else '') + f'screenshot: {step["screenshot"]}'
                lines.append(f'| {i + 1} | {step.get("name", "")} | {step_icon} | {step.get("duration", 0)}ms | {note} |')
            lines.append('')
        for shot in test.get('screenshots', []):
            lines.append(f'![{test.get("name", "")}]({shot})')
            lines.append('')

    return '\n'.join(lines)
