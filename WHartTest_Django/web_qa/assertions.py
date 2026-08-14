"""测试断言库（web-qa-bot src/assertions.ts 的 Python 移植）。"""

from __future__ import annotations

import re
from typing import List, Optional, Union

from .snapshot import Snapshot, detect_modals, element_exists, find_by_text, resolve_ref


class AssertionError(Exception):
    """断言失败。"""

    def __init__(self, message: str, actual: Optional[str] = None, expected: Optional[str] = None):
        super().__init__(message)
        self.actual = actual
        self.expected = expected


def expect_visible(snapshot: Snapshot, selector: str) -> None:
    if not element_exists(snapshot, selector):
        raise AssertionError(f'Element not visible: {selector}', 'not found', 'visible')


def expect_not_visible(snapshot: Snapshot, selector: str) -> None:
    if element_exists(snapshot, selector):
        raise AssertionError(f'Element should not be visible: {selector}', 'visible', 'not visible')


def expect_text(snapshot: Snapshot, selector: str, text: str, contains: bool = False) -> None:
    found = None
    if selector.startswith('@'):
        found = snapshot.refs.get(selector)
    else:
        found = find_by_text(snapshot, selector)
    if not found:
        raise AssertionError(f'Element not found: {selector}', 'not found', text)
    actual = found.name
    matches = (
        text.lower() in actual.lower()
        if contains
        else actual.lower() == text.lower()
    )
    if not matches:
        raise AssertionError(f'Text mismatch for {selector}', actual, text)


def expect_url(snapshot: Snapshot, expected: Union[str, dict]) -> None:
    actual = snapshot.url
    if isinstance(expected, str):
        if actual != expected:
            raise AssertionError('URL mismatch', actual, expected)
    elif isinstance(expected, dict):
        contains = expected.get('contains')
        matches = expected.get('matches')
        if contains:
            if contains not in actual:
                raise AssertionError(
                    'URL does not contain expected string', actual, contains
                )
        elif matches:
            if not re.search(str(matches), actual):
                raise AssertionError(
                    'URL does not match pattern', actual, str(matches)
                )
    else:
        raise AssertionError(f'Invalid expectUrl value: {expected!r}')


def expect_count(snapshot: Snapshot, role: str, expected: Union[int, dict]) -> None:
    count = 0
    for key, ref in snapshot.refs.items():
        if key.startswith('@') and ref.role.lower() == role.lower():
            count += 1
    if isinstance(expected, int):
        if count != expected:
            raise AssertionError(
                f'Element count mismatch for role "{role}"', count, expected
            )
    else:
        if expected.get('min') is not None and count < expected['min']:
            raise AssertionError(
                f'Too few elements with role "{role}"', count, f'at least {expected["min"]}'
            )
        if expected.get('max') is not None and count > expected['max']:
            raise AssertionError(
                f'Too many elements with role "{role}"', count, f'at most {expected["max"]}'
            )


def expect_no_errors(events: List[dict]) -> None:
    errors = [e for e in events if e.get('type') == 'error']
    if errors:
        messages = '\n'.join(e.get('text', '') for e in errors)
        raise AssertionError(f'Console errors detected:\n{messages}', len(errors), 0)


def expect_console_event(events: List[dict], pattern) -> None:
    regex = re.compile(str(pattern), re.IGNORECASE)
    found = any(regex.search(e.get('text', '')) for e in events)
    if not found:
        raise AssertionError(f'Console event not found: {pattern}', 'not found', str(pattern))


def expect_state(snapshot: Snapshot, selector: str, state: str, expected: bool = True) -> None:
    ref = snapshot.refs.get(selector) if selector.startswith('@') else find_by_text(snapshot, selector)
    if not ref:
        raise AssertionError(f'Element not found: {selector}', 'not found', state)
    actual = bool((ref.state or {}).get(state, False))
    if actual != expected:
        raise AssertionError(f'Element {selector} state "{state}" mismatch', actual, expected)


def expect_modal(snapshot: Snapshot, present: bool = True) -> None:
    modals = detect_modals(snapshot)
    if present and not modals:
        raise AssertionError('Expected modal to be present', 'no modal', 'modal visible')
    if not present and modals:
        raise AssertionError('Expected no modal to be present', f'{len(modals)} modal(s)', 'no modal')


def expect_title(snapshot: Snapshot, title: str, contains: bool = False) -> None:
    actual = snapshot.title
    matches = (
        title.lower() in actual.lower()
        if contains
        else actual.lower() == title.lower()
    )
    if not matches:
        raise AssertionError('Page title mismatch', actual, title)


def get_snapshot_value(snapshot: Snapshot, selector: str, expected: Optional[str] = None) -> Optional[str]:
    ref_id = resolve_ref(snapshot, selector)
    ref = snapshot.refs.get(ref_id) if ref_id else None
    if not ref:
        raise AssertionError(f'Element not found: {selector}', 'not found', expected)
    return ref.value if ref.value is not None else ref.text


def assert_value_match(selector: str, actual: str, expected: str, contains: bool = False) -> None:
    matches = (
        expected.lower() in actual.lower()
        if contains
        else actual.lower() == expected.lower()
    )
    if not matches:
        raise AssertionError(f'Value mismatch for {selector}', actual, expected)


def expect_value(
    snapshot: Snapshot,
    selector: str,
    expected: str,
    contains: bool = False,
) -> None:
    actual = get_snapshot_value(snapshot, selector, expected)
    if actual is None:
        raise AssertionError(
            f'Cannot determine value for {selector}; agent-browser snapshot did not expose a value',
            'value unavailable',
            expected,
        )
    assert_value_match(selector, actual, expected, contains)


_CLICKABLE_ROLES = ('button', 'link', 'menuitem', 'tab', 'checkbox', 'radio', 'switch')


def expect_clickable(snapshot: Snapshot, selector: str) -> None:
    ref = snapshot.refs.get(selector) if selector.startswith('@') else find_by_text(snapshot, selector)
    if not ref:
        raise AssertionError(f'Element not found: {selector}', 'not found', 'clickable')
    if ref.role.lower() not in _CLICKABLE_ROLES:
        raise AssertionError(f'Element {selector} is not clickable', ref.role, 'clickable role')
    if (ref.state or {}).get('disabled'):
        raise AssertionError(f'Element {selector} is disabled', 'disabled', 'enabled')
