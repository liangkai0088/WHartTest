"""
通用自动化执行引擎 - 集成模块
将新引擎集成到现有PlaywrightExecutor，提供完全向后兼容
"""

import logging
from typing import Any, Optional

from playwright.async_api import Page

from engine import UniversalAutomationEngine, EngineConfig, LegacyAdapter, StepConfig
from locator_resolver import LocatorResolver
from strategies import ExecutionContext
from models import StepResultModel

logger = logging.getLogger('actuator')


class EnhancedExecutor:
    """增强的执行器 - 集成通用引擎"""

    def __init__(
        self,
        screenshot_dir: str = './data/screenshots',
        engine_config: Optional[EngineConfig] = None
    ):
        """初始化增强执行器

        Args:
            screenshot_dir: 截图目录
            engine_config: 引擎配置，如果为None则使用默认配置
        """
        # 创建引擎配置
        if engine_config is None:
            engine_config = EngineConfig(
                navigation_strategy='relaxed',
                navigation_config={
                    'allow_same_origin': True,
                    'allow_auth_redirect': False,
                    'auth_paths': []
                },
                wait_strategy='auto',
                retry_strategy='exponential_backoff',
                retry_config={
                    'max_attempts': 3,
                    'initial_delay': 1000,
                    'multiplier': 2
                },
                screenshot_on_failure=True,
                screenshot_dir=screenshot_dir
            )

        # 初始化通用引擎
        self.engine = UniversalAutomationEngine(engine_config)

        self.locator_config = {
            'healing_enabled': True,
            'similarity_threshold': 0.78,
            'max_candidates': 120,
        }

        # 向后兼容适配器
        self.adapter = LegacyAdapter()

        logger.info("增强执行器已初始化（通用引擎模式）")

    async def execute_step_with_engine(
        self,
        page: Page,
        old_step: Any,
        env_config: Optional[dict] = None
    ) -> tuple[bool, str, Optional[str]]:
        """使用通用引擎执行步骤（兼容旧接口）

        Args:
            page: Playwright页面对象
            old_step: 旧格式的StepConfig
            env_config: 环境配置

        Returns:
            tuple: (成功与否, 消息, 截图路径)
        """
        # 转换为新格式
        new_step = self.adapter.convert_step_config(old_step)

        if env_config:
            new_step.env_config = env_config
            if new_step.operation == 'click':
                auth_paths = env_config.get('auth_paths') or env_config.get('login_paths')
                if auth_paths:
                    new_step.params.setdefault('auth_paths', auth_paths)
            if new_step.operation == 'goto':
                new_step.params.setdefault('base_url', env_config.get('base_url', ''))

        # 创建执行上下文
        context = ExecutionContext(
            step_id=new_step.step_id,
            metadata={
                'description': new_step.description,
                'env_config': env_config,
                'base_url': (env_config or {}).get('base_url', '')
            }
        )

        locator_resolver = LocatorResolver(**self.locator_config)

        # 执行步骤
        result: StepResultModel = await self.engine.execute_step(
            page,
            new_step,
            context,
            locator_resolver
        )

        # 返回旧格式结果
        return (
            result.status == 'success',
            result.message,
            result.screenshot
        )

    async def navigate_with_engine(
        self,
        page: Page,
        target_url: str,
        validate: bool = True,
        fail_on_error: bool = False
    ):
        """使用通用引擎导航（兼容旧接口）

        Args:
            page: 页面对象
            target_url: 目标URL
            validate: 是否验证
            fail_on_error: 验证失败时是否抛异常
        """
        await self.engine.navigate(
            page,
            target_url,
            validate=validate,
            fail_on_validation_error=fail_on_error
        )

    def update_navigation_strategy(
        self,
        strategy: str,
        config: Optional[dict] = None
    ):
        """动态更新导航策略

        Args:
            strategy: 策略名称 ('strict', 'relaxed', 'none', 'custom')
            config: 策略配置
        """
        self.engine.update_strategy('navigation', strategy, config)

    def update_retry_strategy(
        self,
        strategy: str,
        config: Optional[dict] = None
    ):
        """动态更新重试策略

        Args:
            strategy: 策略名称 ('none', 'exponential_backoff')
            config: 策略配置
        """
        self.engine.update_strategy('retry', strategy, config)

    def list_available_operations(self):
        """列出所有可用操作"""
        return self.engine.list_operations()
