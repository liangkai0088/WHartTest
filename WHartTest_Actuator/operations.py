"""
通用自动化执行引擎 - 操作注册系统
支持动态注册、扩展自定义操作
"""

import logging
from abc import ABC, abstractmethod
from urllib.parse import parse_qs, urljoin, urlsplit
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Callable

from playwright.async_api import Page, Locator, expect

from runtime_env import resolve_upload_file

logger = logging.getLogger('actuator')


def parse_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None or value == '':
        return default
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {'1', 'true', 'yes', 'y', 'on'}:
            return True
        if normalized in {'0', 'false', 'no', 'n', 'off'}:
            return False
    return default


def has_embedded_navigation_target(url: str) -> bool:
    """Detect URL query values that carry a route/URL target, without relying on parameter names."""
    for values in parse_qs(urlsplit(url).query).values():
        for value in values:
            target = str(value).strip()
            if target.startswith('/') and not target.startswith('//'):
                return True
            parsed = urlsplit(target)
            if parsed.scheme in {'http', 'https'} and parsed.netloc:
                return True
    return False


# ============================================================================
# 数据模型
# ============================================================================

@dataclass
class OperationResult:
    """操作执行结果"""
    success: bool
    message: str
    data: Any = None
    screenshot: Optional[str] = None


@dataclass
class ValidationResult:
    """参数验证结果"""
    valid: bool
    message: str = ''
    errors: List[str] = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []


# ============================================================================
# 操作处理器接口
# ============================================================================

class OperationHandler(ABC):
    """操作处理器抽象基类"""

    @property
    @abstractmethod
    def name(self) -> str:
        """操作名称"""
        pass

    @property
    def description(self) -> str:
        """操作描述"""
        return ''

    @property
    def requires_locator(self) -> bool:
        """是否需要元素定位器"""
        return True

    @abstractmethod
    async def execute(
        self,
        page: Page,
        locator: Optional[Locator],
        params: Dict[str, Any],
        context: Any
    ) -> OperationResult:
        """执行操作

        Args:
            page: Playwright页面对象
            locator: 元素定位器（如果需要）
            params: 操作参数
            context: 执行上下文

        Returns:
            OperationResult: 操作结果
        """
        pass

    def validate_params(self, params: Dict[str, Any]) -> ValidationResult:
        """验证参数（可选，子类可覆盖）

        Args:
            params: 操作参数

        Returns:
            ValidationResult: 验证结果
        """
        return ValidationResult(valid=True)


# ============================================================================
# 内置操作实现
# ============================================================================

class ClickOperation(OperationHandler):
    """点击操作"""

    @property
    def name(self) -> str:
        return 'click'

    @property
    def description(self) -> str:
        return '点击元素'

    async def execute(self, page: Page, locator: Locator, params: Dict, context: Any) -> OperationResult:
        button = params.get('button', 'left')
        click_count = int(params.get('click_count', params.get('count', 1)) or 1)
        delay = float(params.get('delay', 0) or 0)
        timeout = params.get('timeout')
        click_kwargs = {'button': button, 'click_count': click_count, 'delay': delay}
        if timeout not in (None, ''):
            click_kwargs['timeout'] = float(timeout)
        if 'force' in params:
            click_kwargs['force'] = parse_bool(params.get('force'))

        before_url = getattr(page, 'url', '')
        await locator.click(**click_kwargs)
        wait_message = await self._wait_after_click(page, before_url, params)

        return OperationResult(
            success=True,
            message=f'点击成功 (button={button}, count={click_count}){wait_message}'
        )

    @staticmethod
    async def _wait_after_click(page: Page, before_url: str, params: Dict) -> str:
        if not parse_bool(params.get('wait_after_click'), True):
            return ''

        wait_after = str(params.get('wait_after') or 'networkidle').lower()
        if wait_after in {'none', 'false', '0'}:
            return ''

        try:
            wait_timeout = int(float(params.get('wait_timeout', params.get('wait_after_timeout', 5000))))
        except (TypeError, ValueError):
            wait_timeout = 5000

        if wait_after in {'load', 'domcontentloaded', 'networkidle'}:
            try:
                await page.wait_for_load_state(wait_after, timeout=wait_timeout)
            except Exception as exc:
                logger.debug(f"click 后等待 {wait_after} 超时，继续执行: {exc}")

        auth_paths = set(params.get('auth_paths') or [])
        before_parts = urlsplit(before_url)
        before_path = before_parts.path.rstrip('/') or '/'
        has_navigation_target = has_embedded_navigation_target(before_url)
        should_wait_url_change = (
            parse_bool(params.get('expect_url_change'))
            or before_path in auth_paths
            or has_navigation_target
        )
        if should_wait_url_change:
            try:
                await page.wait_for_url(
                    lambda url: str(url) != before_url and (urlsplit(str(url)).path.rstrip('/') or '/') not in auth_paths,
                    timeout=max(wait_timeout, 10000 if before_path in auth_paths or has_navigation_target else wait_timeout),
                )
                return f'，点击后页面已跳转到 {getattr(page, "url", "-")}'
            except Exception as exc:
                if has_navigation_target or before_path in auth_paths:
                    raise TimeoutError(f'点击后页面未完成跳转，当前仍在 {getattr(page, "url", before_url)}') from exc
                logger.debug(f"click 后等待 URL 变化超时，继续执行: {exc}")

        return ''


class DoubleClickOperation(OperationHandler):
    """双击操作"""

    @property
    def name(self) -> str:
        return 'dblclick'

    @property
    def description(self) -> str:
        return '双击元素'

    async def execute(self, page: Page, locator: Locator, params: Dict, context: Any) -> OperationResult:
        await locator.dblclick()
        return OperationResult(success=True, message='双击成功')


class FillOperation(OperationHandler):
    """填充输入框操作"""

    @property
    def name(self) -> str:
        return 'fill'

    @property
    def description(self) -> str:
        return '填充输入框'

    async def execute(self, page: Page, locator: Locator, params: Dict, context: Any) -> OperationResult:
        value = params.get('value', '')

        # 文件上传框: 填充字符串语义自动升级为文件上传（通用规则，不针对具体页面）
        is_file_input = False
        try:
            is_file_input = bool(await locator.evaluate(
                "el => el.tagName === 'INPUT' && (el.type || '').toLowerCase() === 'file'"
            ))
        except Exception:
            is_file_input = False

        if is_file_input:
            if not value or not str(value).strip():
                return OperationResult(success=False, message='上传文件路径为空')
            file_path = resolve_upload_file(str(value))
            if not file_path:
                return OperationResult(success=False, message=f'未找到上传文件: {value}')
            try:
                await locator.set_input_files(file_path)
                return OperationResult(success=True, message='文件上传成功（file input 自动填充）')
            except Exception as e:
                if 'not an HTMLInputElement' in str(e):
                    try:
                        async with page.expect_file_chooser() as fc_info:
                            await locator.click()
                        chooser = await fc_info.value
                        await chooser.set_files(file_path)
                        return OperationResult(success=True, message='文件上传成功（file chooser）')
                    except Exception as chooser_error:
                        logger.warning("文件上传失败（file chooser）: %s", chooser_error)
                        return OperationResult(success=False, message='文件上传失败，请检查文件是否存在或权限')
                logger.warning("文件上传失败: %s", e)
                return OperationResult(success=False, message='文件上传失败，请检查文件是否存在或权限')

        await locator.fill(str(value))
        return OperationResult(success=True, message='填充成功')

    def validate_params(self, params: Dict) -> ValidationResult:
        if 'value' not in params:
            return ValidationResult(valid=False, message='缺少参数: value')
        return ValidationResult(valid=True)


class TypeOperation(OperationHandler):
    """逐字输入操作"""

    @property
    def name(self) -> str:
        return 'type'

    @property
    def description(self) -> str:
        return '逐字输入文本'

    async def execute(self, page: Page, locator: Locator, params: Dict, context: Any) -> OperationResult:
        value = params.get('value', '')
        delay = params.get('delay', 0)
        await locator.type(str(value), delay=delay)
        return OperationResult(success=True, message='输入成功')


class ClearOperation(OperationHandler):
    """清空输入框操作"""

    @property
    def name(self) -> str:
        return 'clear'

    @property
    def description(self) -> str:
        return '清空输入框'

    async def execute(self, page: Page, locator: Locator, params: Dict, context: Any) -> OperationResult:
        await locator.fill('')
        return OperationResult(success=True, message='清空成功')


class SelectOperation(OperationHandler):
    """下拉选择操作"""

    @property
    def name(self) -> str:
        return 'select'

    @property
    def description(self) -> str:
        return '选择下拉框选项'

    async def execute(self, page: Page, locator: Locator, params: Dict, context: Any) -> OperationResult:
        value = params.get('value', '')
        await locator.select_option(value)
        return OperationResult(success=True, message=f'选择成功: {value}')


class CheckOperation(OperationHandler):
    """勾选复选框操作"""

    @property
    def name(self) -> str:
        return 'check'

    @property
    def description(self) -> str:
        return '勾选复选框'

    async def execute(self, page: Page, locator: Locator, params: Dict, context: Any) -> OperationResult:
        await locator.check()
        return OperationResult(success=True, message='勾选成功')


class UncheckOperation(OperationHandler):
    """取消勾选操作"""

    @property
    def name(self) -> str:
        return 'uncheck'

    @property
    def description(self) -> str:
        return '取消勾选复选框'

    async def execute(self, page: Page, locator: Locator, params: Dict, context: Any) -> OperationResult:
        await locator.uncheck()
        return OperationResult(success=True, message='取消勾选成功')


class HoverOperation(OperationHandler):
    """悬停操作"""

    @property
    def name(self) -> str:
        return 'hover'

    @property
    def description(self) -> str:
        return '鼠标悬停'

    async def execute(self, page: Page, locator: Locator, params: Dict, context: Any) -> OperationResult:
        await locator.hover()
        return OperationResult(success=True, message='悬停成功')


class DragToOperation(OperationHandler):
    """拖拽元素到目标元素操作"""

    @property
    def name(self) -> str:
        return 'drag_to'

    @property
    def description(self) -> str:
        return '拖拽元素到目标元素'

    async def execute(self, page: Page, locator: Locator, params: Dict, context: Any) -> OperationResult:
        try:
            target = self._resolve_target_locator(page, params)
        except Exception as exc:
            logger.warning("drag_to 解析目标元素失败: %s", exc)
            target = None

        if target is None:
            return OperationResult(
                success=False,
                message='drag_to 缺少目标:ope_value 需提供 target_locator_type+target_locator_value 或 target_text',
            )

        # 源元素:支持 handle 约束拖拽(vuedraggable/Sortable 必须从手柄起拖才生效)
        source = locator
        handle_selector = params.get('source_handle')
        if handle_selector:
            source = locator.locator(str(handle_selector)).first

        # 优先使用 Playwright 原生 drag_to；HTML5 DnD 场景常不响应，降级手动鼠标序列
        try:
            await source.drag_to(target)
            return OperationResult(success=True, message='拖拽成功')
        except Exception as drag_error:
            logger.warning("drag_to 原生拖拽失败，降级鼠标序列: %s", drag_error)
            try:
                await source.hover()
                await page.mouse.down()
                box = await target.bounding_box()
                if not box:
                    return OperationResult(success=False, message='drag_to 目标不可见，无法计算坐标')
                await page.mouse.move(
                    box['x'] + box['width'] / 2,
                    box['y'] + box['height'] / 2,
                    steps=10,
                )
                await page.mouse.up()
                return OperationResult(success=True, message='拖拽成功')
            except Exception as fallback_error:
                return OperationResult(success=False, message=f'drag_to 执行失败: {fallback_error}')

    @staticmethod
    def _resolve_target_locator(page: Page, params: Dict) -> Optional[Locator]:
        """从操作参数解析目标元素定位器。

        优先 target_locator_type + target_locator_value（可带 target_locator_index），
        其次 target_text，再次 target（作为 CSS 选择器）。
        """
        locator_type = params.get('target_locator_type') or params.get('locator_type')
        locator_value = params.get('target_locator_value') or params.get('locator_value')
        target_text = params.get('target_text')
        selector = params.get('target')

        if locator_value:
            normalized_type = (str(locator_type or '').lower().replace('-', '_'))
            target = DragToOperation._get_target_locator(page, normalized_type, str(locator_value))
        elif target_text:
            target = page.get_by_text(str(target_text))
        elif selector:
            target = page.locator(str(selector))
        else:
            return None

        locator_index = params.get('target_locator_index')
        if locator_index is not None:
            try:
                target = target.nth(int(locator_index))
            except (TypeError, ValueError):
                pass
        return target

    @staticmethod
    def _get_target_locator(container: Any, locator_type: str, locator_value: str) -> Locator:
        """根据定位类型获取目标元素 Locator（与通用引擎定位器映射一致）"""
        locator_map = {
            'xpath': lambda: container.locator(f"xpath={locator_value}"),
            'css': lambda: container.locator(locator_value),
            'id': lambda: container.locator(f"#{locator_value}"),
            'name': lambda: container.locator(f"[name='{locator_value}']"),
            'text': lambda: container.get_by_text(locator_value),
            'role': lambda: container.get_by_role(locator_value),
            'placeholder': lambda: container.get_by_placeholder(locator_value),
            'label': lambda: container.get_by_label(locator_value),
            'testid': lambda: container.get_by_test_id(locator_value),
            'test_id': lambda: container.get_by_test_id(locator_value),
            'data_testid': lambda: container.get_by_test_id(locator_value),
        }
        return locator_map.get(locator_type, lambda: container.locator(locator_value))()


class FocusOperation(OperationHandler):
    """聚焦操作"""

    @property
    def name(self) -> str:
        return 'focus'

    @property
    def description(self) -> str:
        return '聚焦元素'

    async def execute(self, page: Page, locator: Locator, params: Dict, context: Any) -> OperationResult:
        await locator.focus()
        return OperationResult(success=True, message='聚焦成功')


class PressOperation(OperationHandler):
    """按键操作"""

    @property
    def name(self) -> str:
        return 'press'

    @property
    def description(self) -> str:
        return '按下键盘按键'

    async def execute(self, page: Page, locator: Locator, params: Dict, context: Any) -> OperationResult:
        key = params.get('key', 'Enter')
        await locator.press(key)
        return OperationResult(success=True, message=f'按键成功: {key}')


class UploadOperation(OperationHandler):
    """文件上传操作"""

    @property
    def name(self) -> str:
        return 'upload'

    @property
    def description(self) -> str:
        return '上传文件'

    async def execute(self, page: Page, locator: Locator, params: Dict, context: Any) -> OperationResult:
        raw_path = params.get('file_path', '')

        if not raw_path or not str(raw_path).strip():
            return OperationResult(
                success=False,
                message='上传文件路径为空'
            )

        # 通用文件解析：绝对路径/相对路径/文件名搜索/缺失时自动生成占位夹具
        file_path = resolve_upload_file(str(raw_path))
        if not file_path:
            return OperationResult(success=False, message=f'未找到上传文件: {raw_path}')

        # 尝试直接设置文件（file input）
        try:
            await locator.set_input_files(file_path)
            return OperationResult(success=True, message='文件上传成功')
        except Exception as e:
            # 如果不是file input，尝试使用file chooser
            if 'not an HTMLInputElement' in str(e):
                try:
                    async with page.expect_file_chooser() as fc_info:
                        await locator.click()
                    file_chooser = await fc_info.value
                    await file_chooser.set_files(file_path)
                    return OperationResult(success=True, message='文件上传成功（file chooser）')
                except Exception as chooser_error:
                    logger.warning("文件上传失败（file chooser）: %s", chooser_error)
                    return OperationResult(success=False, message='文件上传失败，请检查文件是否存在或权限')

            logger.warning("文件上传失败: %s", e)
            return OperationResult(success=False, message='文件上传失败，请检查文件是否存在或权限')


# ============================================================================
# 页面操作（不需要定位器）
# ============================================================================

class GotoOperation(OperationHandler):
    """页面导航操作"""

    @property
    def name(self) -> str:
        return 'goto'

    @property
    def description(self) -> str:
        return '导航到URL'

    @property
    def requires_locator(self) -> bool:
        return False

    async def execute(self, page: Page, locator: None, params: Dict, context: Any) -> OperationResult:
        url = params.get('url', '')
        if not url:
            return OperationResult(success=False, message='缺少URL参数')

        target_url = self._resolve_safe_url(str(url), context, params)
        await page.goto(target_url)
        return OperationResult(success=True, message=f'导航成功: {target_url}')

    @staticmethod
    def _origin(url: str) -> str:
        parsed = urlsplit(url)
        return f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else ''

    @classmethod
    def _resolve_safe_url(cls, url: str, context: Any, params: Dict) -> str:
        env_config = getattr(context, 'metadata', {}).get('env_config') or {}
        base_url = params.get('base_url') or env_config.get('base_url') or getattr(context, 'metadata', {}).get('base_url') or ''
        base_origin = cls._origin(base_url)
        if not base_origin:
            raise ValueError('goto 操作必须配置执行环境 base_url')

        parsed = urlsplit(url)
        if parsed.scheme and parsed.scheme not in {'http', 'https'}:
            raise ValueError(f"不支持的页面 URL 协议: {parsed.scheme}")

        if parsed.scheme and parsed.netloc:
            target_url = url
        else:
            target_url = urljoin(base_origin.rstrip('/') + '/', url.lstrip('/'))

        target_origin = cls._origin(target_url)
        if target_origin != base_origin:
            raise ValueError(f"goto URL 超出执行环境允许域名: {target_url}")
        return target_url


class ReloadOperation(OperationHandler):
    """刷新页面操作"""

    @property
    def name(self) -> str:
        return 'reload'

    @property
    def description(self) -> str:
        return '刷新页面'

    @property
    def requires_locator(self) -> bool:
        return False

    async def execute(self, page: Page, locator: None, params: Dict, context: Any) -> OperationResult:
        await page.reload()
        return OperationResult(success=True, message='页面刷新成功')


class GoBackOperation(OperationHandler):
    """后退操作"""

    @property
    def name(self) -> str:
        return 'go_back'

    @property
    def description(self) -> str:
        return '后退'

    @property
    def requires_locator(self) -> bool:
        return False

    async def execute(self, page: Page, locator: None, params: Dict, context: Any) -> OperationResult:
        await page.go_back()
        return OperationResult(success=True, message='后退成功')


class GoForwardOperation(OperationHandler):
    """前进操作"""

    @property
    def name(self) -> str:
        return 'go_forward'

    @property
    def description(self) -> str:
        return '前进'

    @property
    def requires_locator(self) -> bool:
        return False

    async def execute(self, page: Page, locator: None, params: Dict, context: Any) -> OperationResult:
        await page.go_forward()
        return OperationResult(success=True, message='前进成功')


class WaitOperation(OperationHandler):
    """等待操作"""

    @property
    def name(self) -> str:
        return 'wait'

    @property
    def description(self) -> str:
        return '等待指定时间'

    @property
    def requires_locator(self) -> bool:
        return False

    async def execute(self, page: Page, locator: None, params: Dict, context: Any) -> OperationResult:
        timeout = params.get('timeout', 1000)
        try:
            timeout = int(float(timeout))
        except (TypeError, ValueError):
            timeout = 1000

        await page.wait_for_timeout(timeout)
        return OperationResult(success=True, message=f'等待 {timeout}ms 完成')


class WaitLoadOperation(OperationHandler):
    """等待页面加载操作"""

    @property
    def name(self) -> str:
        return 'wait_load'

    @property
    def description(self) -> str:
        return '等待页面加载完成'

    @property
    def requires_locator(self) -> bool:
        return False

    async def execute(self, page: Page, locator: None, params: Dict, context: Any) -> OperationResult:
        await page.wait_for_load_state("load")
        return OperationResult(success=True, message='页面加载完成')


class WaitNetworkOperation(OperationHandler):
    """等待网络空闲操作"""

    @property
    def name(self) -> str:
        return 'wait_network'

    @property
    def description(self) -> str:
        return '等待网络空闲'

    @property
    def requires_locator(self) -> bool:
        return False

    async def execute(self, page: Page, locator: None, params: Dict, context: Any) -> OperationResult:
        await page.wait_for_load_state("networkidle")
        return OperationResult(success=True, message='网络空闲')


class ScreenshotOperation(OperationHandler):
    """截图操作"""

    @property
    def name(self) -> str:
        return 'screenshot'

    @property
    def description(self) -> str:
        return '页面截图'

    @property
    def requires_locator(self) -> bool:
        return False

    async def execute(self, page: Page, locator: None, params: Dict, context: Any) -> OperationResult:
        path = params.get('path', '')
        if not path:
            return OperationResult(success=False, message='缺少截图路径参数')

        await page.screenshot(path=path)
        return OperationResult(
            success=True,
            message=f'截图成功',
            screenshot=path
        )


# ============================================================================
# 断言操作
# ============================================================================

class AssertVisibleOperation(OperationHandler):
    """断言元素可见"""

    @property
    def name(self) -> str:
        return 'assert_visible'

    @property
    def description(self) -> str:
        return '断言元素可见'

    async def execute(self, page: Page, locator: Locator, params: Dict, context: Any) -> OperationResult:
        await expect(locator).to_be_visible()
        return OperationResult(success=True, message='断言通过: 元素可见')


class AssertHiddenOperation(OperationHandler):
    """断言元素隐藏"""

    @property
    def name(self) -> str:
        return 'assert_hidden'

    @property
    def description(self) -> str:
        return '断言元素隐藏'

    async def execute(self, page: Page, locator: Locator, params: Dict, context: Any) -> OperationResult:
        await expect(locator).to_be_hidden()
        return OperationResult(success=True, message='断言通过: 元素隐藏')


class AssertEnabledOperation(OperationHandler):
    """断言元素可用"""

    @property
    def name(self) -> str:
        return 'assert_enabled'

    @property
    def description(self) -> str:
        return '断言元素可用'

    async def execute(self, page: Page, locator: Locator, params: Dict, context: Any) -> OperationResult:
        await expect(locator).to_be_enabled()
        return OperationResult(success=True, message='断言通过: 元素可用')


class AssertDisabledOperation(OperationHandler):
    """断言元素禁用"""

    @property
    def name(self) -> str:
        return 'assert_disabled'

    @property
    def description(self) -> str:
        return '断言元素禁用'

    async def execute(self, page: Page, locator: Locator, params: Dict, context: Any) -> OperationResult:
        await expect(locator).to_be_disabled()
        return OperationResult(success=True, message='断言通过: 元素禁用')


class AssertCheckedOperation(OperationHandler):
    """断言复选框已勾选"""

    @property
    def name(self) -> str:
        return 'assert_checked'

    @property
    def description(self) -> str:
        return '断言复选框已勾选'

    async def execute(self, page: Page, locator: Locator, params: Dict, context: Any) -> OperationResult:
        await expect(locator).to_be_checked()
        return OperationResult(success=True, message='断言通过: 复选框已勾选')


class AssertTextOperation(OperationHandler):
    """断言元素文本（未绑定元素时退化为页面级文本断言）"""

    @property
    def name(self) -> str:
        return 'assert_text'

    @property
    def description(self) -> str:
        return '断言元素文本'

    @property
    def requires_locator(self) -> bool:
        # 支持页面级文本断言: 未绑定元素时校验整页文本
        return False

    async def execute(self, page: Page, locator: Optional[Locator], params: Dict, context: Any) -> OperationResult:
        expected = params.get('expected', '')
        if not expected:
            return OperationResult(success=False, message='缺少断言参数: expected')
        if locator is not None:
            await expect(locator).to_have_text(expected)
            return OperationResult(success=True, message=f'断言通过: 元素文本为 "{expected}"')
        # 页面级文本断言
        await expect(page.get_by_text(expected).first).to_be_visible()
        return OperationResult(success=True, message=f'页面断言通过: 页面存在文本 "{expected}"')


class AssertValueOperation(OperationHandler):
    """断言输入框值"""

    @property
    def name(self) -> str:
        return 'assert_value'

    @property
    def description(self) -> str:
        return '断言输入框值'

    async def execute(self, page: Page, locator: Locator, params: Dict, context: Any) -> OperationResult:
        expected = params.get('expected', '')
        await expect(locator).to_have_value(expected)
        return OperationResult(success=True, message=f'断言通过: 值为 "{expected}"')


class AssertContainTextOperation(OperationHandler):
    """断言元素包含文本（未绑定元素时退化为页面级包含断言）"""

    @property
    def name(self) -> str:
        return 'assert_contain_text'

    @property
    def description(self) -> str:
        return '断言元素包含文本'

    @property
    def requires_locator(self) -> bool:
        # 支持页面级包含断言: 未绑定元素时校验整页文本
        return False

    async def execute(self, page: Page, locator: Optional[Locator], params: Dict, context: Any) -> OperationResult:
        expected = params.get('expected', '')
        if not expected:
            return OperationResult(success=False, message='缺少断言参数: expected')
        if locator is not None:
            await expect(locator).to_contain_text(expected)
            return OperationResult(success=True, message=f'断言通过: 元素包含文本 "{expected}"')
        # 页面级包含断言
        await expect(page.get_by_text(expected).first).to_be_visible()
        return OperationResult(success=True, message=f'页面断言通过: 页面包含文本 "{expected}"')


class AssertUrlOperation(OperationHandler):
    """断言URL"""

    @property
    def name(self) -> str:
        return 'assert_url'

    @property
    def description(self) -> str:
        return '断言当前URL'

    @property
    def requires_locator(self) -> bool:
        return False

    async def execute(self, page: Page, locator: None, params: Dict, context: Any) -> OperationResult:
        expected = params.get('expected', '')
        await expect(page).to_have_url(expected)
        return OperationResult(success=True, message=f'断言通过: URL为 "{expected}"')


class AssertTitleOperation(OperationHandler):
    """断言页面标题"""

    @property
    def name(self) -> str:
        return 'assert_title'

    @property
    def description(self) -> str:
        return '断言页面标题'

    @property
    def requires_locator(self) -> bool:
        return False

    async def execute(self, page: Page, locator: None, params: Dict, context: Any) -> OperationResult:
        expected = params.get('expected', '')
        await expect(page).to_have_title(expected)
        return OperationResult(success=True, message=f'断言通过: 标题为 "{expected}"')


# ============================================================================
# 操作注册表
# ============================================================================

class OperationRegistry:
    """操作注册表 - 支持动态注册自定义操作"""

    def __init__(self):
        self._operations: Dict[str, OperationHandler] = {}
        self._register_builtin_operations()

    def _register_builtin_operations(self):
        """注册内置操作"""
        builtin_ops = [
            # 基础操作
            ClickOperation(),
            DoubleClickOperation(),
            FillOperation(),
            TypeOperation(),
            ClearOperation(),
            SelectOperation(),
            CheckOperation(),
            UncheckOperation(),
            HoverOperation(),
            DragToOperation(),
            FocusOperation(),
            PressOperation(),
            UploadOperation(),

            # 页面操作
            GotoOperation(),
            ReloadOperation(),
            GoBackOperation(),
            GoForwardOperation(),
            WaitOperation(),
            WaitLoadOperation(),
            WaitNetworkOperation(),
            ScreenshotOperation(),

            # 断言操作
            AssertVisibleOperation(),
            AssertHiddenOperation(),
            AssertEnabledOperation(),
            AssertDisabledOperation(),
            AssertCheckedOperation(),
            AssertTextOperation(),
            AssertValueOperation(),
            AssertContainTextOperation(),
            AssertUrlOperation(),
            AssertTitleOperation(),
        ]

        for op in builtin_ops:
            self._operations[op.name] = op

        logger.info(f"已注册 {len(builtin_ops)} 个内置操作")

    def register(self, handler: OperationHandler, override: bool = False):
        """注册操作

        Args:
            handler: 操作处理器
            override: 是否覆盖已存在的操作
        """
        if handler.name in self._operations and not override:
            logger.warning(f"操作 {handler.name} 已存在，跳过注册（使用 override=True 强制覆盖）")
            return

        self._operations[handler.name] = handler
        logger.info(f"已注册操作: {handler.name} ({handler.description})")

    def unregister(self, name: str):
        """注销操作

        Args:
            name: 操作名称
        """
        if name in self._operations:
            del self._operations[name]
            logger.info(f"已注销操作: {name}")

    def get(self, name: str) -> Optional[OperationHandler]:
        """获取操作处理器

        Args:
            name: 操作名称

        Returns:
            OperationHandler或None
        """
        return self._operations.get(name)

    def list_operations(self) -> List[Dict[str, str]]:
        """列出所有已注册操作

        Returns:
            操作列表 [{"name": "click", "description": "点击元素"}, ...]
        """
        return [
            {
                'name': op.name,
                'description': op.description,
                'requires_locator': op.requires_locator
            }
            for op in self._operations.values()
        ]

    def has(self, name: str) -> bool:
        """检查操作是否存在

        Args:
            name: 操作名称

        Returns:
            bool
        """
        return name in self._operations
