"""web-qa-bot yaml → dataclasses 加载器（容忍解析）。

兼容 web-qa-bot 的 schema：
- 单键步骤（goto / click / type / select / waitFor / ...）
- 字符串简写 waitForLoad() / snapshot() / expectNoErrors()
- expectText 字符串简写 "selector, text"
- click ref 前缀 checkbox: / pagination: / row: / agent:
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, List, Optional

import yaml

STEP_KEYS = [
    'goto', 'waitForLoad', 'waitFor', 'waitMs', 'click', 'type', 'select',
    'hover', 'press', 'snapshot', 'screenshot', 'expectVisible',
    'expectNotVisible', 'expectText', 'expectTitle', 'expectValue',
    'expectUrl', 'expectCount', 'expectNoErrors', 'expectConsoleEvent',
    'expectModal', 'expectClickable', 'assert',
]
STEP_KEY_SET = set(STEP_KEYS)

STRING_STEPS = {
    'waitForLoad()': {'waitForLoad': True},
    'snapshot()': {'snapshot': True},
    'expectNoErrors()': {'expectNoErrors': True},
}


class YamlError(Exception):
    """yaml 解析 / 校验错误。"""


def step_label(step: dict) -> str:
    """根据步骤字典生成人类可读标签。"""
    for key in STEP_KEYS:
        if key in step:
            value = step[key]
            if key == 'type' and isinstance(value, dict):
                return f'Type "{value.get("text", "")}" into {value.get("ref", "")}'
            if key == 'select' and isinstance(value, dict):
                return f'Select "{value.get("value", "")}" in {value.get("ref", "")}'
            if key == 'expectText' and isinstance(value, dict):
                return f'Expect text: {value.get("text", "")}'
            if key == 'expectValue' and isinstance(value, dict):
                return f'Expect value: {value.get("ref", "")}'
            if key == 'goto':
                return f'Navigate to {value}'
            if key == 'click':
                return f'Click {value}'
            return f'{key}: {value if not isinstance(value, dict) else value}'
    return 'Unknown step'


@dataclass
class TestStep:
    """规范化后的单个测试步骤（恰好一个动作键）。"""

    raw: dict = field(default_factory=dict)
    name: str = ''
    optional: bool = False
    action: str = ''
    value: Any = None
    error: str = ''

    @property
    def action_label(self) -> str:
        return step_label(self.raw) if self.raw else (self.name or self.action)

    @classmethod
    def from_raw(cls, raw_step, label: str, tolerant: bool = True) -> 'TestStep':
        step = normalize_step(raw_step, label, tolerant)
        action = None
        for key in STEP_KEYS:
            if key in step:
                action = key
                break
        return cls(
            raw=step,
            name=str(step.get('name', '')),
            optional=bool(step.get('optional', False)),
            action=action or '',
            value=step.get(action) if action else None,
            error=step.get('_error', ''),
        )


@dataclass
class TestCase:
    """测试用例。"""

    name: str
    steps: List[TestStep] = field(default_factory=list)
    skip: bool = False
    only: bool = False
    known_issue: str = ''
    errors: List[str] = field(default_factory=list)


@dataclass
class TestSuite:
    """测试套件。"""

    name: str = ''
    base_url: str = ''
    before_all: List[TestStep] = field(default_factory=list)
    beforeEach: List[TestStep] = field(default_factory=list)
    after_each: List[TestStep] = field(default_factory=list)
    after_all: List[TestStep] = field(default_factory=list)
    tests: List[TestCase] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.errors and bool(self.name and self.tests)

    @property
    def step_count(self) -> int:
        return len(self.before_all) + len(self.before_each) + len(self.after_each) + len(self.after_all) + sum(
            len(t.steps) for t in self.tests
        )


def normalize_step(raw_step: Any, label: str = '', tolerant: bool = True) -> dict:
    """将原始步骤规范化为「恰好一个动作键」的字典。

    tolerant=True 时未知键/多动作键记录 _error 而非抛出。
    """
    if isinstance(raw_step, str):
        trimmed = raw_step.strip()
        normalized = STRING_STEPS.get(trimmed)
        if normalized:
            return dict(normalized)
        msg = f'{label}: 不支持的字符串步骤 "{raw_step}"'
        if tolerant:
            return {'_error': msg, 'name': raw_step}
        raise YamlError(msg)

    if not isinstance(raw_step, dict):
        msg = f'{label}: 步骤必须是对象或字符串'
        if tolerant:
            return {'_error': msg}
        raise YamlError(msg)

    step = dict(raw_step)
    keys = [k for k in step.keys() if k not in ('name', 'optional')]
    unknown = [k for k in keys if k not in STEP_KEY_SET]
    if unknown:
        msg = f'{label}: 不支持的步骤键: {", ".join(unknown)}'
        if tolerant:
            step['_error'] = msg
            return step
        raise YamlError(msg)

    action_keys = [k for k in keys if k in STEP_KEY_SET]
    if not action_keys:
        msg = f'{label}: 步骤缺少动作/断言键'
        if tolerant:
            step['_error'] = msg
            return step
        raise YamlError(msg)
    if len(action_keys) > 1:
        msg = f'{label}: 步骤必须恰好包含一个动作键，实际为: {", ".join(action_keys)}'
        if tolerant:
            step['_error'] = msg
            return step
        raise YamlError(msg)

    if isinstance(step.get('expectText'), str):
        step['expectText'] = _parse_expect_text_shorthand(step['expectText'], label)

    return step


def _parse_expect_text_shorthand(value: str, label: str) -> dict:
    """expectText 简写 "selector, 期望文本" -> {ref, text, contains: true}。"""
    parts = re.split(r'[,，]', value)
    if len(parts) < 2:
        raise YamlError(f'{label}: expectText 简写必须为 "选择器, 期望文本"')
    ref = parts.pop(0).strip()
    text = ','.join(parts).strip()
    if not ref or not text:
        raise YamlError(f'{label}: expectText 简写缺少选择器或期望文本')
    return {'ref': ref, 'text': text, 'contains': True}


def _parse_steps(raw_steps: Any, label: str, tolerant: bool) -> List[TestStep]:
    if raw_steps is None:
        return []
    if not isinstance(raw_steps, list):
        if tolerant:
            return []
        raise YamlError(f'{label}: steps 必须是数组')
    return [TestStep.from_raw(s, f'{label} 步骤 {i + 1}', tolerant) for i, s in enumerate(raw_steps)]


def parse_suite(content: str, tolerant: bool = True) -> TestSuite:
    """解析 web-qa-bot yaml 为 TestSuite。"""
    try:
        data = yaml.safe_load(content) or {}
    except yaml.YAMLError as e:
        suite = TestSuite(errors=[f'YAML 解析失败: {e}'])
        return suite

    if not isinstance(data, dict):
        return TestSuite(errors=['YAML 顶层必须是对象'])

    suite = TestSuite(
        name=str(data.get('name') or ''),
        base_url=str(data.get('baseUrl') or ''),
    )

    for hook in ('beforeAll', 'beforeEach', 'afterEach', 'afterAll'):
        attr = {
            'beforeAll': 'before_all',
            'beforeEach': 'before_each',
            'afterEach': 'after_each',
            'afterAll': 'after_all',
        }[hook]
        steps = _parse_steps(data.get(hook), hook, tolerant)
        setattr(suite, attr, steps)
        for s in steps:
            if s.error:
                suite.errors.append(s.error)

    if not suite.name:
        suite.errors.append('缺少必填字段 name')
    if 'baseUrl' not in data and not data.get('baseUrl'):
        # web-qa-bot 允许缺省 baseUrl（使用配置默认），不视为错误
        pass

    raw_tests = data.get('tests')
    if not isinstance(raw_tests, list):
        suite.errors.append('缺少必填字段 tests（必须为数组）')
        return suite

    for i, raw_test in enumerate(raw_tests):
        if not isinstance(raw_test, dict):
            suite.errors.append(f'tests[{i}]: 必须是对象')
            continue
        test_name = str(raw_test.get('name') or '')
        if not test_name:
            suite.errors.append(f'tests[{i}]: 缺少 name')
        test = TestCase(
            name=test_name,
            skip=bool(raw_test.get('skip', False)),
            only=bool(raw_test.get('only', False)),
            known_issue=str(raw_test.get('knownIssue') or ''),
        )
        steps = _parse_steps(raw_test.get('steps'), f'用例 "{test_name}"', tolerant)
        test.steps = steps
        for s in steps:
            if s.error:
                suite.errors.append(s.error)
        suite.tests.append(test)

    return suite


def count_tests(content: str) -> int:
    """容忍地统计用例数（供 test_count 落库，绝不抛错）。"""
    try:
        suite = parse_suite(content, tolerant=True)
        return len(suite.tests)
    except Exception:
        return 0


def parse_suite_tolerant(content: str) -> Optional[TestSuite]:
    """仅在无明显结构错误时返回 TestSuite，否则返回 None。"""
    suite = parse_suite(content, tolerant=True)
    if not suite.name:
        return None
    return suite
