"""agent 语义定位（web-qa-bot src/utils/agent-locator-cache.ts + llm.ts 的 Python 移植）。

定位链：
1. AgentLocatorCache 命中 → 快照校验 → 使用；失效 → 删除
2. LLM 视觉定位（LLMConfig OpenAI-compatible + 截图 base64）
3. agent-browser find（role→text→label→placeholder→testid 关键词路由）
4. 快照 resolveRef
5. DOM 降级脚本
6. 全部失败 → 人工介入错误 + 截图路径
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Callable, List, Optional

from .browser import BrowserError
from .llm import LlmError, chat_completions, parse_locator_response, LOCATOR_SYSTEM_PROMPT
from .snapshot import Snapshot, element_exists, resolve_ref

logger = logging.getLogger('web_qa')

FIND_ACTION_MAP = {
    'click': 'click',
    'type': 'fill',
    'fill': 'fill',
    'hover': 'hover',
    'check': 'check',
}

_ROLE_KEYWORDS = [
    (r'^(button|btn|按钮)[\s:：]*(.+)', 'button'),
    (r'^(link|链接)[\s:：]*(.+)', 'link'),
    (r'^(textbox|input|输入框|文本框)[\s:：]*(.+)', 'textbox'),
    (r'^(checkbox|勾选|复选框)[\s:：]*(.+)', 'checkbox'),
    (r'^(select|下拉|选择框|下拉框)[\s:：]*(.+)', 'combobox'),
    (r'^(heading|标题)[\s:：]*(.+)', 'heading'),
    (r'^(radio|单选|单选框)[\s:：]*(.+)', 'radio'),
]

_COORDS_CLICK_JS = """
(() => {
  const el = document.elementFromPoint(__X__, __Y__);
  if (!el) return false;
  const clickable = el.closest('button, a, [role="button"], input, select, textarea, [onclick]') || el;
  clickable.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true, view: window }));
  clickable.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, cancelable: true, view: window }));
  clickable.click();
  return true;
})()
"""

_COORDS_TYPE_JS = """
(() => {
  const el = document.elementFromPoint(__X__, __Y__);
  if (!el) return false;
  el.focus();
  const input = el.matches('input, textarea') ? el : (el.querySelector('input, textarea') || el);
  if ('value' in input) {
    input.value = __VALUE__;
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
  } else {
    input.textContent = __VALUE__;
    input.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: __VALUE__ }));
  }
  return true;
})()
"""

_QUERY_SELECTOR_CHECK_JS = """
(() => {
  try { return !!document.querySelector(__SEL__); } catch (e) { return false; }
})()
"""


class LocatorError(Exception):
    """定位失败。"""

    def __init__(self, message: str, screenshot_path: str = ''):
        super().__init__(message)
        self.screenshot_path = screenshot_path


@dataclass
class LocatorResolution:
    selector: str = ''
    strategy: str = 'llm'
    x: Optional[float] = None
    y: Optional[float] = None
    screenshot_path: str = ''
    executed: bool = False


class AgentLocator:
    """agent 语义定位器。"""

    def __init__(
        self,
        browser,
        llm_config,
        project_id: int,
        base_url: str,
        screenshot_dir: str,
        get_snapshot: Callable[[], Optional[Snapshot]],
        js_dir: str,
    ):
        self.browser = browser
        self.llm_config = llm_config
        self.project_id = project_id
        self.base_url = base_url or ''
        self.screenshot_dir = screenshot_dir
        self.get_snapshot = get_snapshot
        self.js_dir = js_dir

    # ---------------- 公共入口 ----------------

    def locate(self, description: str, operation: str = 'click', text: str = '') -> LocatorResolution:
        desc = (description or '').strip()
        if not desc:
            raise LocatorError('空定位描述', '')
        desc_hash = self._hash(desc)

        # 1. 缓存
        cached = self._cache_get(desc, desc_hash)
        if cached is not None:
            if self._verify_selector(cached.selector):
                self._cache_hit(cached)
                return LocatorResolution(selector=cached.selector, strategy=cached.strategy)
            cached.delete()
            logger.info('[web_qa] locator cache stale, delete: %s', desc)

        # 2. LLM 视觉
        screenshot_path = ''
        llm_res = self._locate_by_llm(desc)
        if llm_res is not None:
            screenshot_path = llm_res.get('screenshot_path', '')
            if self._verify_llm_result(llm_res):
                selector = llm_res.get('selector') or ''
                if selector:
                    self._cache_set(desc, desc_hash, selector, 'llm')
                    return LocatorResolution(
                        selector=selector, strategy='llm',
                        screenshot_path=screenshot_path,
                    )
                # 仅坐标
                self._cache_set(desc, desc_hash, desc, 'llm')
                return LocatorResolution(
                    selector='', strategy='llm',
                    x=llm_res.get('x'), y=llm_res.get('y'),
                    screenshot_path=screenshot_path,
                )

        # 3. agent-browser find（执行操作）
        if self._find_fallback(desc, operation):
            self._cache_set(desc, desc_hash, desc, 'find')
            return LocatorResolution(selector=desc, strategy='find', executed=True)

        # 4. 快照 resolveRef
        snap = self.get_snapshot()
        if snap is not None:
            ref = resolve_ref(snap, desc)
            if ref:
                self._cache_set(desc, desc_hash, desc, 'dom')
                return LocatorResolution(selector=desc, strategy='dom')

        # 5. DOM 降级脚本（点击）
        if operation == 'click' and self._dom_click_fallback(desc):
            self._cache_set(desc, desc_hash, desc, 'dom')
            return LocatorResolution(selector=desc, strategy='dom', executed=True)

        raise LocatorError(f'人工介入: 无法定位元素 "{desc}"', screenshot_path)

    def locate_presence(self, description: str) -> LocatorResolution:
        """仅校验元素存在（不执行任何操作），供 waitFor / expectVisible 使用。"""
        desc = (description or '').strip()
        if not desc:
            raise LocatorError('空定位描述', '')
        desc_hash = self._hash(desc)

        cached = self._cache_get(desc, desc_hash)
        if cached is not None:
            if self._verify_selector(cached.selector):
                self._cache_hit(cached)
                return LocatorResolution(selector=cached.selector, strategy=cached.strategy)
            cached.delete()

        llm_res = self._locate_by_llm(desc)
        if llm_res is not None and self._verify_llm_result(llm_res):
            selector = llm_res.get('selector') or ''
            self._cache_set(desc, desc_hash, selector or desc, 'llm')
            return LocatorResolution(selector=selector, strategy='llm', x=llm_res.get('x'), y=llm_res.get('y'))

        snap = self.get_snapshot()
        if snap is not None:
            if element_exists(snap, desc) or resolve_ref(snap, desc):
                self._cache_set(desc, desc_hash, desc, 'dom')
                return LocatorResolution(selector=desc, strategy='dom')

        try:
            script = build_fallback_script('has_text', desc)
            if bool(self.browser.eval_js(script, use_stdin=True)):
                self._cache_set(desc, desc_hash, desc, 'dom')
                return LocatorResolution(selector=desc, strategy='dom')
        except BrowserError:
            pass

        raise LocatorError(f'人工介入: 无法定位元素 "{desc}"', '')

    # ---------------- 缓存 ----------------

    def _hash(self, description: str) -> str:
        norm = re.sub(r'\s+', ' ', description).strip().lower()
        return hashlib.sha256(norm.encode('utf-8')).hexdigest()

    def _cache_get(self, desc: str, desc_hash: str):
        from .models import AgentLocatorCache
        return (
            AgentLocatorCache.objects
            .filter(project_id=self.project_id, base_url=self.base_url, description_hash=desc_hash)
            .first()
        )

    def _cache_set(self, desc: str, desc_hash: str, selector: str, strategy: str) -> None:
        from .models import AgentLocatorCache
        try:
            AgentLocatorCache.objects.update_or_create(
                project_id=self.project_id,
                base_url=self.base_url,
                description_hash=desc_hash,
                defaults={'description': desc, 'selector': selector, 'strategy': strategy},
            )
        except Exception as e:  # noqa: BLE001
            logger.warning('[web_qa] locator cache save failed: %s', e)

    def _cache_hit(self, entry) -> None:
        try:
            entry.hits += 1
            entry.save(update_fields=['hits', 'updated_at'])
        except Exception as e:  # noqa: BLE001
            logger.debug('[web_qa] locator cache hit save failed: %s', e)

    # ---------------- 校验 ----------------

    def _verify_selector(self, selector: str) -> bool:
        """缓存/LLM 选择器校验：快照 elementExists 或 DOM querySelector。"""
        if not selector:
            return False
        snap = self.get_snapshot()
        if snap is not None and element_exists(snap, selector):
            return True
        if selector.startswith('@') or ':' in selector:
            return False
        try:
            script = _QUERY_SELECTOR_CHECK_JS.replace('__SEL__', repr(selector))
            return bool(self.browser.eval_js(script, use_stdin=True))
        except BrowserError:
            return False

    def _verify_llm_result(self, llm_res: dict) -> bool:
        selector = llm_res.get('selector')
        x, y = llm_res.get('x'), llm_res.get('y')
        if selector:
            return self._verify_selector(selector)
        if x is not None and y is not None:
            try:
                return bool(self.browser.eval_js(_COORDS_CLICK_JS.replace('__X__', repr(int(x))).replace('__Y__', repr(int(y))), use_stdin=True))
            except BrowserError:
                return False
        return False

    # ---------------- LLM ----------------

    def _locate_by_llm(self, description: str) -> Optional[dict]:
        llm_config = self.llm_config
        if llm_config is None or not getattr(llm_config, 'supports_vision', False):
            return None
        screenshot_path, b64 = self._take_screenshot()
        if b64 is None:
            return None
        try:
            user_text = f'页面标题: {self._page_title()}\n请定位元素: {description}'
            messages = [
                {'role': 'system', 'content': LOCATOR_SYSTEM_PROMPT},
                {
                    'role': 'user',
                    'content': [
                        {'type': 'text', 'text': user_text},
                        {
                            'type': 'image_url',
                            'image_url': {'url': f'data:image/png;base64,{b64}'},
                        },
                    ],
                },
            ]
            content = chat_completions(llm_config, messages, temperature=0)
            result = parse_locator_response(content)
            result['screenshot_path'] = screenshot_path
            return result
        except LlmError as e:
            logger.warning('[web_qa] LLM 定位失败，进入降级链: %s', e)
            return None
        except Exception as e:  # noqa: BLE001
            logger.warning('[web_qa] LLM 定位异常，进入降级链: %s', e)
            return None

    def _take_screenshot(self) -> tuple:
        """截图并返回 (path, base64)。"""
        try:
            os.makedirs(self.screenshot_dir, exist_ok=True)
            path = os.path.join(self.screenshot_dir, f'locate-{int(time.time() * 1000)}.png')
            self.browser.screenshot(path)
            with open(path, 'rb') as fh:
                b64 = base64.b64encode(fh.read()).decode('ascii')
            return path, b64
        except Exception as e:  # noqa: BLE001
            logger.warning('[web_qa] 定位截图失败: %s', e)
            return '', None

    def _page_title(self) -> str:
        try:
            return self.browser.get_title() or ''
        except BrowserError:
            return ''

    # ---------------- find 降级 ----------------

    def _find_candidates(self, desc: str):
        lower = desc.lower()
        if ':' in desc:
            role, name = desc.split(':', 1)
            if role.strip() and name.strip():
                yield ('role', role.strip(), name.strip())
        for pattern, role in _ROLE_KEYWORDS:
            m = re.match(pattern, lower)
            if m and m.group(2).strip():
                yield ('role', role, m.group(2).strip())
                break
        yield ('text', desc, None)
        yield ('label', desc, None)
        yield ('placeholder', desc, None)
        yield ('testid', desc, None)

    def _find_fallback(self, desc: str, operation: str) -> bool:
        action = FIND_ACTION_MAP.get(operation, 'click')
        for kind, value, name in self._find_candidates(desc):
            try:
                data = self.browser.find(kind, value, action, name=name)
                if data:
                    return True
            except BrowserError:
                continue
        return False

    # ---------------- DOM 降级 ----------------

    def _dom_click_fallback(self, desc: str) -> bool:
        try:
            script = self._load_fallback_script('click_by_text', desc)
            return bool(self.browser.eval_js(script, use_stdin=True))
        except BrowserError:
            return False

    def _load_fallback_script(self, kind: str, *args) -> str:
        path = os.path.join(self.js_dir, 'fallback_scripts.js')
        with open(path, 'r', encoding='utf-8') as fh:
            script = fh.read()
        import json as _json
        a, b, c = args + (None,) * (3 - len(args))
        script = script.replace('__KIND__', _json.dumps(kind))
        script = script.replace('__A__', 'null' if a is None else _json.dumps(a))
        script = script.replace('__B__', 'null' if b is None else _json.dumps(b))
        script = script.replace('__C__', 'null' if c is None else _json.dumps(c))
        return script


def build_fallback_script(kind: str, *args) -> str:
    """独立构建 fallback 脚本（供 runner 直接调用）。"""
    import json as _json
    import os
    js_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'js')
    path = os.path.join(js_dir, 'fallback_scripts.js')
    with open(path, 'r', encoding='utf-8') as fh:
        script = fh.read()
    a, b, c = args + (None,) * (3 - len(args))
    script = script.replace('__KIND__', _json.dumps(kind))
    script = script.replace('__A__', 'null' if a is None else _json.dumps(a))
    script = script.replace('__B__', 'null' if b is None else _json.dumps(b))
    script = script.replace('__C__', 'null' if c is None else _json.dumps(c))
    return script
