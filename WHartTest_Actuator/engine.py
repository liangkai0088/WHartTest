"""
通用自动化执行引擎 - 核心引擎
配置驱动、插件化、可扩展的自动化执行引擎
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from playwright.async_api import Page, Locator

from strategies import (
    NavigationStrategy, WaitStrategy, RetryStrategy,
    StrategyFactory, ExecutionContext
)
from operations import OperationRegistry, OperationResult
from models import StepResultModel

logger = logging.getLogger('actuator')


# ============================================================================
# 配置模型
# ============================================================================

@dataclass
class EngineConfig:
    """引擎配置"""
    # 策略配置
    navigation_strategy: str = 'relaxed'
    navigation_config: Dict = field(default_factory=dict)

    wait_strategy: str = 'auto'
    wait_config: Dict = field(default_factory=dict)

    retry_strategy: str = 'exponential_backoff'
    retry_config: Dict = field(default_factory=dict)

    # 定位器配置
    locator_healing_enabled: bool = True
    locator_similarity_threshold: float = 0.78
    locator_max_candidates: int = 500

    # 其他配置
    screenshot_on_failure: bool = True
    screenshot_dir: str = './data/screenshots'


@dataclass
class StepConfig:
    """步骤配置（通用格式）"""
    step_id: int
    operation: str  # 操作类型

    # 定位器配置
    locator: Optional[Dict] = None

    # 操作参数
    params: Dict = field(default_factory=dict)

    # 等待配置
    wait_before: Optional[Dict] = None
    wait_after: Optional[Dict] = None

    # 重试配置
    retry: Optional[Dict] = None

    # 其他
    description: str = ''
    env_config: Optional[Dict] = None


# ============================================================================
# 通用自动化引擎
# ============================================================================

class UniversalAutomationEngine:
    """通用自动化执行引擎"""

    def __init__(self, config: Optional[EngineConfig] = None):
        """初始化引擎

        Args:
            config: 引擎配置，如果为None则使用默认配置
        """
        self.config = config or EngineConfig()

        # 初始化策略
        self.navigation_strategy = StrategyFactory.create_navigation_strategy(
            self.config.navigation_strategy,
            self.config.navigation_config
        )

        self.wait_strategy = StrategyFactory.create_wait_strategy(
            self.config.wait_strategy,
            self.config.wait_config
        )

        self.retry_strategy = StrategyFactory.create_retry_strategy(
            self.config.retry_strategy,
            self.config.retry_config
        )

        # 初始化操作注册表
        self.operation_registry = OperationRegistry()

        logger.info(f"通用自动化引擎已初始化: "
                   f"导航策略={self.config.navigation_strategy}, "
                   f"等待策略={self.config.wait_strategy}, "
                   f"重试策略={self.config.retry_strategy}")

    async def execute_step(
        self,
        page: Page,
        step_config: StepConfig,
        context: Optional[ExecutionContext] = None,
        locator_resolver: Optional[Any] = None
    ) -> StepResultModel:
        """执行单个步骤

        Args:
            page: Playwright页面对象
            step_config: 步骤配置
            context: 执行上下文
            locator_resolver: 定位器解析器（用于定位元素）

        Returns:
            StepResultModel: 步骤执行结果
        """
        if context is None:
            context = ExecutionContext(step_id=step_config.step_id)

        start_time = time.time()

        try:
            # 获取操作处理器
            operation = self.operation_registry.get(step_config.operation)
            if not operation:
                return StepResultModel(
                    step_id=step_config.step_id,
                    status='failed',
                    message=f'未知操作类型: {step_config.operation}',
                    description=step_config.description,
                    duration=time.time() - start_time,
                    element_found=False
                )

            # 验证参数
            validation = operation.validate_params(step_config.params)
            if not validation.valid:
                return StepResultModel(
                    step_id=step_config.step_id,
                    status='failed',
                    message=f'参数验证失败: {validation.message}',
                    description=step_config.description,
                    duration=time.time() - start_time,
                    element_found=False
                )

            if operation.requires_locator and not locator_resolver:
                return StepResultModel(
                    step_id=step_config.step_id,
                    status='failed',
                    message='操作需要元素定位器，但未提供定位器解析器',
                    description=step_config.description,
                    duration=time.time() - start_time,
                    element_found=False
                )

            if operation.requires_locator and not step_config.locator:
                if step_config.operation.startswith('assert_'):
                    # 断言步骤未配置定位器：没有可校验的目标元素，跳过（通用规则，不作为失败）
                    logger.warning(
                        f"步骤 {step_config.step_id}: 断言 {step_config.operation} 未配置定位器，自动跳过"
                    )
                    return StepResultModel(
                        step_id=step_config.step_id,
                        status='success',
                        message=f'断言已跳过（未配置定位器，无校验目标）: {step_config.description or step_config.operation}',
                        description=step_config.description,
                        duration=time.time() - start_time,
                        element_found=False
                    )
                return StepResultModel(
                    step_id=step_config.step_id,
                    status='failed',
                    message='操作需要元素定位器，但步骤配置中未提供',
                    description=step_config.description,
                    duration=time.time() - start_time,
                    element_found=False
                )

            async def execute_op():
                context.metadata.update({
                    'operation': step_config.operation,
                    'description': step_config.description,
                    'current_url': getattr(page, 'url', ''),
                })
                locator = None
                if operation.requires_locator:
                    locator = await locator_resolver.resolve(page, step_config.locator, context)
                    if not locator:
                        diagnostics = getattr(locator_resolver, 'last_diagnostics', {}) or {}
                        raise TimeoutError(self._format_locator_failure(step_config, diagnostics))

                if step_config.wait_before:
                    await self._apply_wait_config(
                        page,
                        locator,
                        step_config.operation,
                        step_config.wait_before,
                        'before',
                        context
                    )

                result = await operation.execute(page, locator, step_config.params, context)

                if step_config.wait_after:
                    await self._apply_wait_config(
                        page,
                        locator,
                        step_config.operation,
                        step_config.wait_after,
                        'after',
                        context
                    )

                return result

            # 执行定位与操作（带重试，每次重试都会重新定位）
            result: OperationResult = await self.retry_strategy.execute_with_retry(
                execute_op,
                context
            )

            # 构建结果
            duration = time.time() - start_time

            message = result.message
            diagnostics = getattr(locator_resolver, 'last_diagnostics', {}) if locator_resolver else {}
            resolved = diagnostics.get('resolved_locator') if diagnostics.get('resolved_by') == 'self_heal' else None
            if resolved:
                message += f"（自愈定位器命中: {resolved.get('value')}, score={resolved.get('score')}）"

            return StepResultModel(
                step_id=step_config.step_id,
                status='success' if result.success else 'failed',
                message=message,
                description=step_config.description or step_config.operation,
                duration=duration,
                element_found=result.success,
                screenshot=result.screenshot
            )

        except Exception as e:
            duration = time.time() - start_time
            logger.error(f"步骤执行失败: {e}", exc_info=True)

            # 失败时截图
            screenshot_path = None
            if self.config.screenshot_on_failure:
                try:
                    candidate_path = f"{self.config.screenshot_dir}/error_{step_config.step_id}_{int(time.time())}.png"
                    await page.screenshot(path=candidate_path)
                    screenshot_path = candidate_path
                except Exception as screenshot_error:
                    logger.warning(f"截图失败: {screenshot_error}")

            return StepResultModel(
                step_id=step_config.step_id,
                status='failed',
                message=str(e),
                description=step_config.description or step_config.operation,
                duration=duration,
                element_found=False,
                screenshot=screenshot_path
            )

    @staticmethod
    def _format_locator_failure(step_config: StepConfig, diagnostics: Dict[str, Any]) -> str:
        attempted = diagnostics.get('attempted_locators') or []
        attempted_text = '; '.join(
            f"{item.get('type')}={item.get('value')}"
            for item in attempted[:5]
            if item.get('value')
        ) or '无有效定位器'
        candidates = diagnostics.get('ranked_candidates') or []
        if not candidates:
            candidates = [
                {'text': ' '.join(str(item.get(key) or '') for key in ('text', 'ariaLabel', 'title', 'placeholder', 'testId', 'id', 'name')).strip()[:120]}
                for item in (diagnostics.get('candidates') or [])[:10]
            ]
        candidate_text = '; '.join(
            filter(None, (str(item.get('text') or '') for item in candidates[:5]))
        ) or '未发现可交互候选元素'
        reason = diagnostics.get('reason') or '元素定位失败'
        return (
            f"元素定位失败（步骤: {step_config.description or step_config.step_id}，"
            f"URL: {diagnostics.get('current_url') or '-'}，"
            f"已尝试: {attempted_text}，"
            f"候选: {candidate_text}，"
            f"原因: {reason}）"
        )

    async def _apply_wait_config(
        self,
        page: Page,
        locator: Optional[Locator],
        action: str,
        wait_config: Dict,
        timing: str,  # 'before' or 'after'
        context: ExecutionContext
    ):
        """应用等待配置

        Args:
            page: 页面对象
            locator: 元素定位器
            action: 操作类型
            wait_config: 等待配置
            timing: 'before' 或 'after'
            context: 执行上下文
        """
        condition = wait_config.get('condition')
        timeout = wait_config.get('timeout', 30000)

        if not condition:
            return

        try:
            if condition == 'visible' and locator:
                await locator.wait_for(state="visible", timeout=timeout)
            elif condition == 'hidden' and locator:
                await locator.wait_for(state="hidden", timeout=timeout)
            elif condition == 'attached' and locator:
                await locator.wait_for(state="attached", timeout=timeout)
            elif condition == 'networkidle':
                await page.wait_for_load_state("networkidle", timeout=timeout)
            elif condition == 'load':
                await page.wait_for_load_state("load", timeout=timeout)
            elif condition == 'domcontentloaded':
                await page.wait_for_load_state("domcontentloaded", timeout=timeout)
            elif condition == 'timeout':
                await page.wait_for_timeout(timeout)
            elif condition == 'selector':
                selector = wait_config.get('selector')
                if selector:
                    await page.wait_for_selector(selector, timeout=timeout)
            else:
                logger.warning(f"未知的等待条件: {condition}")
        except Exception as e:
            logger.debug(f"等待超时 ({timing}): {e}")

    async def navigate(
        self,
        page: Page,
        target_url: str,
        context: Optional[ExecutionContext] = None,
        validate: bool = True,
        fail_on_validation_error: bool = False
    ) -> Dict[str, Any]:
        """导航到目标URL

        Args:
            page: 页面对象
            target_url: 目标URL
            context: 执行上下文
            validate: 是否验证导航结果
            fail_on_validation_error: 验证失败时是否抛出异常

        Returns:
            导航结果字典
        """
        if context is None:
            context = ExecutionContext()

        # 执行导航
        nav_result = await self.navigation_strategy.navigate(page, target_url, context)

        if not nav_result.success:
            return {
                'success': False,
                'message': nav_result.message,
                'final_url': nav_result.final_url
            }

        # 验证导航结果
        if validate:
            validation = self.navigation_strategy.validate(
                target_url,
                nav_result.final_url,
                context
            )

            if not validation.is_valid:
                if fail_on_validation_error:
                    raise RuntimeError(validation.message)
                else:
                    logger.log(
                        logging.WARNING if validation.severity == 'warning' else logging.ERROR,
                        validation.message
                    )

        return {
            'success': True,
            'message': nav_result.message,
            'final_url': nav_result.final_url,
            'redirected': nav_result.redirected
        }

    def update_strategy(
        self,
        strategy_type: str,
        strategy_name: str,
        config: Optional[Dict] = None
    ):
        """动态更新策略

        Args:
            strategy_type: 策略类型 ('navigation', 'wait', 'retry')
            strategy_name: 策略名称
            config: 策略配置
        """
        if strategy_type == 'navigation':
            self.navigation_strategy = StrategyFactory.create_navigation_strategy(
                strategy_name,
                config
            )
            self.config.navigation_strategy = strategy_name
            self.config.navigation_config = config or {}
            logger.info(f"已更新导航策略: {strategy_name}")

        elif strategy_type == 'wait':
            self.wait_strategy = StrategyFactory.create_wait_strategy(
                strategy_name,
                config
            )
            self.config.wait_strategy = strategy_name
            self.config.wait_config = config or {}
            logger.info(f"已更新等待策略: {strategy_name}")

        elif strategy_type == 'retry':
            self.retry_strategy = StrategyFactory.create_retry_strategy(
                strategy_name,
                config
            )
            self.config.retry_strategy = strategy_name
            self.config.retry_config = config or {}
            logger.info(f"已更新重试策略: {strategy_name}")

        else:
            logger.warning(f"未知的策略类型: {strategy_type}")

    def register_custom_operation(self, handler: Any):
        """注册自定义操作

        Args:
            handler: 操作处理器实例
        """
        self.operation_registry.register(handler)

    def list_operations(self) -> List[Dict[str, str]]:
        """列出所有可用操作

        Returns:
            操作列表
        """
        return self.operation_registry.list_operations()


# ============================================================================
# 向后兼容适配器
# ============================================================================

class LegacyAdapter:
    """向后兼容适配器 - 将旧格式配置转换为新格式"""

    @staticmethod
    def convert_step_config(old_step: Any) -> StepConfig:
        """转换步骤配置

        Args:
            old_step: 旧格式的StepConfig对象

        Returns:
            新格式的StepConfig对象
        """
        # 提取操作类型
        operation = getattr(old_step, 'operation_type', 'unknown')

        # 提取定位器配置
        locator = None
        if hasattr(old_step, 'locator_value') and old_step.locator_value:
            locator = {
                'primary': {
                    'type': getattr(old_step, 'locator_type', 'xpath'),
                    'value': old_step.locator_value,
                    'index': getattr(old_step, 'locator_index', None)
                }
            }

            # 添加备选定位器
            fallbacks = []
            if hasattr(old_step, 'locator_value_2') and old_step.locator_value_2:
                fallbacks.append({
                    'type': getattr(old_step, 'locator_type_2', 'css'),
                    'value': old_step.locator_value_2,
                    'index': getattr(old_step, 'locator_index_2', None)
                })

            if hasattr(old_step, 'locator_value_3') and old_step.locator_value_3:
                fallbacks.append({
                    'type': getattr(old_step, 'locator_type_3', 'text'),
                    'value': old_step.locator_value_3,
                    'index': getattr(old_step, 'locator_index_3', None)
                })

            if fallbacks:
                locator['fallbacks'] = fallbacks

            # iframe配置
            if getattr(old_step, 'is_iframe', False):
                locator['iframe'] = getattr(old_step, 'iframe_locator', '')

        # 提取操作参数。优先保留后端配置的完整 ope_value/case_data，
        # 再用 input_value 补齐旧格式步骤需要的标准字段。
        raw_params = getattr(old_step, 'params', {}) or {}
        params = dict(raw_params) if isinstance(raw_params, dict) else {}
        input_value = getattr(old_step, 'input_value', '')

        if operation in ['fill', 'type']:
            params.setdefault('value', input_value)
        elif operation == 'press':
            params.setdefault('key', input_value or 'Enter')
        elif operation == 'select':
            params.setdefault('value', input_value)
        elif operation == 'upload':
            params.setdefault('file_path', input_value)
            # 上传文件的元数据
            if hasattr(old_step, 'upload_file_id'):
                params.setdefault('file_id', old_step.upload_file_id)
            if hasattr(old_step, 'upload_file_name'):
                params.setdefault('file_name', old_step.upload_file_name)
            if hasattr(old_step, 'upload_download_url'):
                params.setdefault('download_url', old_step.upload_download_url)
            if hasattr(old_step, 'upload_project_id'):
                params.setdefault('project_id', old_step.upload_project_id)
        elif operation in ['goto', 'wait']:
            if operation == 'goto':
                params.setdefault('url', input_value)
            elif operation == 'wait':
                params.setdefault('timeout', int(float(input_value)) if input_value else 1000)
        elif operation.startswith('assert_'):
            params.setdefault('expected', input_value)
        elif operation == 'screenshot':
            params.setdefault('path', input_value)

        # 等待配置
        wait_before = None
        wait_after = None
        wait_time = getattr(old_step, 'wait_time', 0)
        if wait_time > 0:
            # wait_time 单位为秒；封顶 60 秒，防止配置异常（如误填毫秒值）导致长时间卡死
            wait_before = {
                'condition': 'timeout',
                'timeout': min(int(wait_time * 1000), 60000)
            }

        # 步骤描述
        description = getattr(old_step, 'description', '')

        return StepConfig(
            step_id=getattr(old_step, 'step_id', 0),
            operation=operation,
            locator=locator,
            params=params,
            wait_before=wait_before,
            wait_after=wait_after,
            retry=None,  # 使用全局重试策略
            description=description
        )

    @staticmethod
    def convert_engine_config(old_config: Any = None) -> EngineConfig:
        """转换引擎配置

        Args:
            old_config: 旧格式的配置对象（可选）

        Returns:
            新格式的EngineConfig对象
        """
        if old_config is None:
            # 使用默认配置
            return EngineConfig(
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
                }
            )

        # 从旧配置提取参数
        screenshot_dir = getattr(old_config, 'screenshot_dir', './data/screenshots')

        return EngineConfig(
            navigation_strategy='relaxed',
            navigation_config={
                'allow_same_origin': True,
                'allow_auth_redirect': True
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
