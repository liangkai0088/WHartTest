"""
通用自动化执行引擎 - 策略系统
Strategy Pattern 实现，支持配置驱动的执行策略
"""

import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Callable
from urllib.parse import urlsplit

from playwright.async_api import Page, Locator

logger = logging.getLogger('actuator')


# ============================================================================
# 数据模型
# ============================================================================

@dataclass
class NavigationResult:
    """导航结果"""
    success: bool
    final_url: str
    message: str
    redirected: bool = False
    redirect_count: int = 0


@dataclass
class ValidationResult:
    """验证结果"""
    is_valid: bool
    message: str
    severity: str = 'error'  # error, warning, info


@dataclass
class ExecutionContext:
    """执行上下文"""
    case_id: Optional[int] = None
    step_id: Optional[int] = None
    page_step_id: Optional[int] = None
    variables: Dict[str, Any] = None
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.variables is None:
            self.variables = {}
        if self.metadata is None:
            self.metadata = {}


# ============================================================================
# 导航策略
# ============================================================================

class NavigationStrategy(ABC):
    """导航策略抽象基类"""

    @abstractmethod
    async def navigate(
        self,
        page: Page,
        target_url: str,
        context: ExecutionContext
    ) -> NavigationResult:
        """执行导航

        Args:
            page: Playwright页面对象
            target_url: 目标URL
            context: 执行上下文

        Returns:
            NavigationResult: 导航结果
        """
        pass

    @abstractmethod
    def validate(
        self,
        expected_url: str,
        actual_url: str,
        context: ExecutionContext
    ) -> ValidationResult:
        """验证导航结果

        Args:
            expected_url: 期望URL
            actual_url: 实际URL
            context: 执行上下文

        Returns:
            ValidationResult: 验证结果
        """
        pass


class StrictNavigationStrategy(NavigationStrategy):
    """严格导航策略 - URL必须精确匹配"""

    async def navigate(self, page: Page, target_url: str, context: ExecutionContext) -> NavigationResult:
        """执行导航"""
        before_url = page.url

        response = await page.goto(target_url, wait_until="domcontentloaded")
        status = response.status if response else None

        if status and status >= 400:
            return NavigationResult(
                success=False,
                final_url=page.url,
                message=f"导航失败: HTTP {status}"
            )

        # 等待网络空闲
        try:
            await page.wait_for_load_state("networkidle", timeout=10000)
        except Exception as e:
            logger.debug(f"等待网络空闲超时: {e}")

        redirected = before_url != page.url

        return NavigationResult(
            success=True,
            final_url=page.url,
            message="导航成功",
            redirected=redirected,
            redirect_count=1 if redirected else 0
        )

    def validate(self, expected_url: str, actual_url: str, context: ExecutionContext) -> ValidationResult:
        """严格验证 - URL必须完全匹配"""
        expected_parts = urlsplit(expected_url)
        actual_parts = urlsplit(actual_url)

        # 比较scheme, netloc, path, query, fragment
        if (expected_parts.scheme, expected_parts.netloc,
            expected_parts.path.rstrip('/') or '/',
            expected_parts.query, expected_parts.fragment) == \
           (actual_parts.scheme, actual_parts.netloc,
            actual_parts.path.rstrip('/') or '/',
            actual_parts.query, actual_parts.fragment):
            return ValidationResult(
                is_valid=True,
                message="URL验证通过",
                severity='info'
            )

        return ValidationResult(
            is_valid=False,
            message=f"URL不匹配: 期望 {expected_url}，实际 {actual_url}",
            severity='error'
        )


class RelaxedNavigationStrategy(NavigationStrategy):
    """宽松导航策略 - 允许同源重定向"""

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self.allow_same_origin = self.config.get('allow_same_origin', True)
        self.allow_auth_redirect = self.config.get('allow_auth_redirect', True)
        self.auth_paths = self.config.get('auth_paths', [])

    async def navigate(self, page: Page, target_url: str, context: ExecutionContext) -> NavigationResult:
        """执行导航"""
        before_url = page.url

        response = await page.goto(target_url, wait_until="domcontentloaded")
        status = response.status if response else None

        if status and status >= 400:
            return NavigationResult(
                success=False,
                final_url=page.url,
                message=f"导航失败: HTTP {status}"
            )

        # 等待网络空闲
        try:
            await page.wait_for_load_state("networkidle", timeout=10000)
        except Exception as e:
            logger.debug(f"等待网络空闲超时: {e}")

        redirected = before_url != page.url

        return NavigationResult(
            success=True,
            final_url=page.url,
            message="导航成功",
            redirected=redirected,
            redirect_count=1 if redirected else 0
        )

    def validate(self, expected_url: str, actual_url: str, context: ExecutionContext) -> ValidationResult:
        """宽松验证 - 允许同源重定向"""
        expected_parts = urlsplit(expected_url)
        actual_parts = urlsplit(actual_url)

        # 精确匹配
        if (expected_parts.scheme, expected_parts.netloc,
            expected_parts.path.rstrip('/') or '/',
            expected_parts.query, expected_parts.fragment) == \
           (actual_parts.scheme, actual_parts.netloc,
            actual_parts.path.rstrip('/') or '/',
            actual_parts.query, actual_parts.fragment):
            return ValidationResult(
                is_valid=True,
                message="URL精确匹配",
                severity='info'
            )

        # 检查是否是登录重定向
        if self.allow_auth_redirect:
            actual_path = actual_parts.path.rstrip('/') or '/'
            if actual_path in self.auth_paths and 'redirect=' in actual_parts.query:
                return ValidationResult(
                    is_valid=True,
                    message=f"检测到登录重定向: {expected_url} → {actual_url}",
                    severity='info'
                )

        # 检查是否是同源重定向
        if self.allow_same_origin:
            expected_origin = f"{expected_parts.scheme}://{expected_parts.netloc}"
            actual_origin = f"{actual_parts.scheme}://{actual_parts.netloc}"

            if expected_origin == actual_origin:
                return ValidationResult(
                    is_valid=True,
                    message=f"同源重定向（前端路由跳转）: {expected_url} → {actual_url}",
                    severity='warning'
                )

        # 跨域重定向 - 安全风险
        return ValidationResult(
            is_valid=False,
            message=f"跨域重定向（安全限制）: {expected_url} → {actual_url}",
            severity='error'
        )


class NoValidationStrategy(NavigationStrategy):
    """无验证策略 - 跳过所有URL验证"""

    async def navigate(self, page: Page, target_url: str, context: ExecutionContext) -> NavigationResult:
        """执行导航"""
        before_url = page.url

        response = await page.goto(target_url, wait_until="domcontentloaded")
        status = response.status if response else None

        if status and status >= 400:
            return NavigationResult(
                success=False,
                final_url=page.url,
                message=f"导航失败: HTTP {status}"
            )

        # 等待网络空闲
        try:
            await page.wait_for_load_state("networkidle", timeout=10000)
        except Exception as e:
            logger.debug(f"等待网络空闲超时: {e}")

        redirected = before_url != page.url

        return NavigationResult(
            success=True,
            final_url=page.url,
            message="导航成功（已跳过URL验证）",
            redirected=redirected,
            redirect_count=1 if redirected else 0
        )

    def validate(self, expected_url: str, actual_url: str, context: ExecutionContext) -> ValidationResult:
        """无验证 - 总是返回有效"""
        return ValidationResult(
            is_valid=True,
            message=f"已跳过URL验证: {expected_url} → {actual_url}",
            severity='info'
        )


class CustomNavigationStrategy(NavigationStrategy):
    """自定义导航策略 - 基于规则配置"""

    def __init__(self, config: Dict):
        self.config = config
        self.allow_same_origin = config.get('allow_same_origin', True)
        self.allow_auth_redirect = config.get('allow_auth_redirect', True)
        self.auth_paths = config.get('auth_paths', [])
        self.custom_rules = config.get('rules', [])

    async def navigate(self, page: Page, target_url: str, context: ExecutionContext) -> NavigationResult:
        """执行导航"""
        before_url = page.url

        response = await page.goto(target_url, wait_until="domcontentloaded")
        status = response.status if response else None

        if status and status >= 400:
            return NavigationResult(
                success=False,
                final_url=page.url,
                message=f"导航失败: HTTP {status}"
            )

        # 等待网络空闲
        try:
            await page.wait_for_load_state("networkidle", timeout=10000)
        except Exception as e:
            logger.debug(f"等待网络空闲超时: {e}")

        redirected = before_url != page.url

        return NavigationResult(
            success=True,
            final_url=page.url,
            message="导航成功",
            redirected=redirected,
            redirect_count=1 if redirected else 0
        )

    def validate(self, expected_url: str, actual_url: str, context: ExecutionContext) -> ValidationResult:
        """自定义验证 - 基于规则"""
        expected_parts = urlsplit(expected_url)
        actual_parts = urlsplit(actual_url)

        # 精确匹配
        if (expected_parts.scheme, expected_parts.netloc,
            expected_parts.path.rstrip('/') or '/',
            expected_parts.query, expected_parts.fragment) == \
           (actual_parts.scheme, actual_parts.netloc,
            actual_parts.path.rstrip('/') or '/',
            actual_parts.query, actual_parts.fragment):
            return ValidationResult(
                is_valid=True,
                message="URL精确匹配",
                severity='info'
            )

        # 检查自定义规则
        for rule in self.custom_rules:
            pattern = rule.get('pattern')
            redirect_to = rule.get('redirect_to')
            action = rule.get('action', 'allow')

            if pattern and re.match(pattern, expected_parts.path):
                if redirect_to:
                    actual_path = actual_parts.path.rstrip('/') or '/'
                    if actual_path == redirect_to or re.match(redirect_to, actual_path):
                        if action == 'allow':
                            return ValidationResult(
                                is_valid=True,
                                message=f"匹配自定义规则: {pattern} → {redirect_to}",
                                severity='info'
                            )

        # 登录重定向
        if self.allow_auth_redirect:
            actual_path = actual_parts.path.rstrip('/') or '/'
            if actual_path in self.auth_paths and 'redirect=' in actual_parts.query:
                return ValidationResult(
                    is_valid=True,
                    message=f"检测到登录重定向: {expected_url} → {actual_url}",
                    severity='info'
                )

        # 同源重定向
        if self.allow_same_origin:
            expected_origin = f"{expected_parts.scheme}://{expected_parts.netloc}"
            actual_origin = f"{actual_parts.scheme}://{actual_parts.netloc}"

            if expected_origin == actual_origin:
                return ValidationResult(
                    is_valid=True,
                    message=f"同源重定向: {expected_url} → {actual_url}",
                    severity='warning'
                )

        # 不匹配
        return ValidationResult(
            is_valid=False,
            message=f"URL验证失败: {expected_url} → {actual_url}",
            severity='error'
        )


# ============================================================================
# 等待策略
# ============================================================================

class WaitStrategy(ABC):
    """等待策略抽象基类"""

    @abstractmethod
    async def wait_before_action(
        self,
        page: Page,
        locator: Optional[Locator],
        action: str,
        context: ExecutionContext
    ):
        """操作前等待"""
        pass

    @abstractmethod
    async def wait_after_action(
        self,
        page: Page,
        action: str,
        context: ExecutionContext
    ):
        """操作后等待"""
        pass


class AutoWaitStrategy(WaitStrategy):
    """自动等待策略 - 依赖Playwright的auto-wait"""

    async def wait_before_action(self, page: Page, locator: Optional[Locator], action: str, context: ExecutionContext):
        """Playwright自动等待，无需额外操作"""
        pass

    async def wait_after_action(self, page: Page, action: str, context: ExecutionContext):
        """Playwright自动等待，无需额外操作"""
        pass


class ExplicitWaitStrategy(WaitStrategy):
    """显式等待策略 - 明确的等待条件"""

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self.wait_for_visible = self.config.get('wait_for_visible', True)
        self.wait_for_stable = self.config.get('wait_for_stable', True)
        self.timeout = self.config.get('timeout', 30000)

    async def wait_before_action(self, page: Page, locator: Optional[Locator], action: str, context: ExecutionContext):
        """操作前等待元素可见和稳定"""
        if locator and self.wait_for_visible:
            try:
                await locator.wait_for(state="visible", timeout=self.timeout)
            except Exception as e:
                logger.debug(f"等待元素可见超时: {e}")

        if locator and self.wait_for_stable:
            try:
                # 等待元素稳定（位置不变）
                await page.wait_for_timeout(100)
            except Exception as e:
                logger.debug(f"等待元素稳定超时: {e}")

    async def wait_after_action(self, page: Page, action: str, context: ExecutionContext):
        """操作后等待页面稳定"""
        if action in ['click', 'submit']:
            try:
                await page.wait_for_load_state("networkidle", timeout=10000)
            except Exception as e:
                logger.debug(f"操作后等待网络空闲超时: {e}")


# ============================================================================
# 重试策略
# ============================================================================

class RetryStrategy(ABC):
    """重试策略抽象基类"""

    @abstractmethod
    async def execute_with_retry(
        self,
        func: Callable,
        context: ExecutionContext
    ) -> Any:
        """带重试的执行"""
        pass

    @abstractmethod
    def should_retry(
        self,
        error: Exception,
        attempt: int,
        context: ExecutionContext
    ) -> bool:
        """判断是否应该重试"""
        pass


class NoRetryStrategy(RetryStrategy):
    """无重试策略"""

    async def execute_with_retry(self, func: Callable, context: ExecutionContext) -> Any:
        """直接执行，不重试"""
        return await func()

    def should_retry(self, error: Exception, attempt: int, context: ExecutionContext) -> bool:
        """永不重试"""
        return False


class ExponentialBackoffRetry(RetryStrategy):
    """指数退避重试策略"""

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self.max_attempts = self.config.get('max_attempts', 3)
        self.initial_delay = self.config.get('initial_delay', 1000)  # ms
        self.multiplier = self.config.get('multiplier', 2)
        self.max_delay = self.config.get('max_delay', 30000)  # ms
        self.retryable_errors = self.config.get('retryable_errors', [
            'TimeoutError',
            'TargetClosedError',
        ])

    async def execute_with_retry(self, func: Callable, context: ExecutionContext) -> Any:
        """带指数退避的重试执行"""
        import asyncio

        last_error = None

        for attempt in range(1, self.max_attempts + 1):
            try:
                return await func()
            except Exception as e:
                last_error = e

                if not self.should_retry(e, attempt, context):
                    raise

                if attempt < self.max_attempts:
                    delay = min(
                        self.initial_delay * (self.multiplier ** (attempt - 1)),
                        self.max_delay
                    )
                    logger.warning(
                        f"操作失败，{delay}ms后重试 (尝试 {attempt}/{self.max_attempts}): {e}"
                    )
                    await asyncio.sleep(delay / 1000)

        # 所有重试都失败
        raise last_error

    def should_retry(self, error: Exception, attempt: int, context: ExecutionContext) -> bool:
        """判断是否应该重试"""
        if attempt >= self.max_attempts:
            return False

        error_type = type(error).__name__

        # 检查是否是可重试的错误类型
        for retryable in self.retryable_errors:
            if retryable in error_type:
                return True

        # 检查错误消息中的关键字
        error_msg = str(error).lower()
        retryable_keywords = [
            'timeout', 'timed out',
            'element not found', 'not visible',
            'stale element', 'detached',
            'network', 'connection',
        ]

        return any(keyword in error_msg for keyword in retryable_keywords)


# ============================================================================
# 策略工厂
# ============================================================================

class StrategyFactory:
    """策略工厂 - 根据配置创建策略实例"""

    # 导航策略映射
    NAVIGATION_STRATEGIES = {
        'strict': StrictNavigationStrategy,
        'relaxed': RelaxedNavigationStrategy,
        'none': NoValidationStrategy,
        'custom': CustomNavigationStrategy,
    }

    # 等待策略映射
    WAIT_STRATEGIES = {
        'auto': AutoWaitStrategy,
        'explicit': ExplicitWaitStrategy,
    }

    # 重试策略映射
    RETRY_STRATEGIES = {
        'none': NoRetryStrategy,
        'exponential_backoff': ExponentialBackoffRetry,
    }

    @classmethod
    def create_navigation_strategy(
        cls,
        strategy_name: str = 'relaxed',
        config: Optional[Dict] = None
    ) -> NavigationStrategy:
        """创建导航策略

        Args:
            strategy_name: 策略名称 (strict, relaxed, none, custom)
            config: 策略配置

        Returns:
            NavigationStrategy实例
        """
        strategy_class = cls.NAVIGATION_STRATEGIES.get(strategy_name)

        if not strategy_class:
            logger.warning(f"未知的导航策略: {strategy_name}，使用默认策略 'relaxed'")
            strategy_class = RelaxedNavigationStrategy

        if config and strategy_name in ['relaxed', 'custom']:
            return strategy_class(config)

        return strategy_class()

    @classmethod
    def create_wait_strategy(
        cls,
        strategy_name: str = 'auto',
        config: Optional[Dict] = None
    ) -> WaitStrategy:
        """创建等待策略"""
        strategy_class = cls.WAIT_STRATEGIES.get(strategy_name)

        if not strategy_class:
            logger.warning(f"未知的等待策略: {strategy_name}，使用默认策略 'auto'")
            strategy_class = AutoWaitStrategy

        if config and strategy_name == 'explicit':
            return strategy_class(config)

        return strategy_class()

    @classmethod
    def create_retry_strategy(
        cls,
        strategy_name: str = 'exponential_backoff',
        config: Optional[Dict] = None
    ) -> RetryStrategy:
        """创建重试策略"""
        strategy_class = cls.RETRY_STRATEGIES.get(strategy_name)

        if not strategy_class:
            logger.warning(f"未知的重试策略: {strategy_name}，使用默认策略 'exponential_backoff'")
            strategy_class = ExponentialBackoffRetry

        if config:
            return strategy_class(config)

        return strategy_class()
