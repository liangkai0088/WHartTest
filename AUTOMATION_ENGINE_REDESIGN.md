# 通用自动化执行引擎 - 重构设计方案

## 一、当前问题分析

### 1.1 写死的逻辑
```python
# ❌ 问题1: URL验证逻辑写死
if not self._navigation_matches(page_step_url, page.url):
    if self._is_auth_redirect(...):  # 写死了登录重定向判断
        return
    if self._origin(...) == self._origin(...):  # 写死了同源判断
        return
    raise RuntimeError(...)

# ❌ 问题2: 操作类型写死
if operation == 'click':
    await locator.click()
elif operation == 'fill':
    await locator.fill(value)
# ... 每个操作都硬编码

# ❌ 问题3: 断言类型写死
if assert_type == 'visible':
    expect(locator).to_be_visible()
elif assert_type == 'text':
    expect(locator).to_have_text(value)
# ... 每个断言都硬编码

# ❌ 问题4: 定位器类型写死
locator_map = {
    'xpath': lambda: container.locator(f"xpath={value}"),
    'css': lambda: container.locator(value),
    # ... 固定的定位器类型
}
```

### 1.2 核心问题
| 问题 | 影响 |
|------|------|
| **策略硬编码** | 无法配置导航、等待、重试策略 |
| **操作固定** | 新增操作需要修改代码 |
| **断言固定** | 新增断言需要修改代码 |
| **无插件机制** | 无法扩展自定义逻辑 |
| **配置能力弱** | 用户无法自定义行为 |

## 二、通用引擎架构设计

### 2.1 核心理念
```
配置驱动 > 约定 > 代码
插件化 > 硬编码
策略模式 > if-else
声明式 > 命令式
```

### 2.2 架构分层

```
┌─────────────────────────────────────────┐
│          用户配置层（JSON/YAML）          │
│  - 执行策略配置                          │
│  - 自定义操作定义                        │
│  - 钩子函数配置                          │
└─────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────┐
│           策略引擎层                     │
│  - NavigationStrategy（导航策略）        │
│  - WaitStrategy（等待策略）              │
│  - RetryStrategy（重试策略）             │
│  - ValidationStrategy（验证策略）        │
└─────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────┐
│          操作注册层                      │
│  - OperationRegistry（操作注册表）       │
│  - AssertionRegistry（断言注册表）       │
│  - LocatorRegistry（定位器注册表）       │
└─────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────┐
│          插件系统层                      │
│  - BeforeStep / AfterStep Hooks         │
│  - CustomOperation Plugins              │
│  - CustomAssertion Plugins              │
└─────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────┐
│       Playwright执行层（底层驱动）        │
└─────────────────────────────────────────┘
```

## 三、详细设计

### 3.1 策略系统

#### NavigationStrategy（导航策略）
```python
class NavigationStrategy(ABC):
    """导航策略抽象基类"""
    
    @abstractmethod
    async def navigate(
        self, 
        page: Page, 
        target_url: str, 
        context: dict
    ) -> NavigationResult:
        """执行导航"""
        pass
    
    @abstractmethod
    def validate(
        self, 
        expected_url: str, 
        actual_url: str, 
        context: dict
    ) -> ValidationResult:
        """验证导航结果"""
        pass

# 内置策略实现
class StrictNavigationStrategy(NavigationStrategy):
    """严格策略：URL必须精确匹配"""
    pass

class RelaxedNavigationStrategy(NavigationStrategy):
    """宽松策略：允许同源重定向"""
    pass

class NoValidationStrategy(NavigationStrategy):
    """无验证策略：跳过所有验证"""
    pass

class CustomNavigationStrategy(NavigationStrategy):
    """自定义策略：基于配置的规则"""
    
    def __init__(self, config: dict):
        self.allow_same_origin = config.get('allow_same_origin', True)
        self.allow_auth_redirect = config.get('allow_auth_redirect', True)
        self.custom_rules = config.get('rules', [])
```

#### WaitStrategy（等待策略）
```python
class WaitStrategy(ABC):
    """等待策略抽象基类"""
    
    @abstractmethod
    async def wait_before_action(
        self, 
        page: Page, 
        element: Locator, 
        action: str,
        context: dict
    ):
        """操作前等待"""
        pass
    
    @abstractmethod
    async def wait_after_action(
        self, 
        page: Page, 
        action: str,
        context: dict
    ):
        """操作后等待"""
        pass

# 内置策略
class AutoWaitStrategy(WaitStrategy):
    """自动等待：依赖Playwright的auto-wait"""
    pass

class ExplicitWaitStrategy(WaitStrategy):
    """显式等待：明确的等待条件"""
    
    def __init__(self, config: dict):
        self.wait_for_visible = config.get('wait_for_visible', True)
        self.wait_for_stable = config.get('wait_for_stable', True)
        self.timeout = config.get('timeout', 30000)
```

#### RetryStrategy（重试策略）
```python
class RetryStrategy(ABC):
    """重试策略抽象基类"""
    
    @abstractmethod
    async def execute_with_retry(
        self, 
        func: Callable, 
        context: dict
    ) -> Any:
        """带重试的执行"""
        pass
    
    @abstractmethod
    def should_retry(
        self, 
        error: Exception, 
        attempt: int, 
        context: dict
    ) -> bool:
        """判断是否应该重试"""
        pass

# 内置策略
class NoRetryStrategy(RetryStrategy):
    """无重试"""
    pass

class ExponentialBackoffRetry(RetryStrategy):
    """指数退避重试"""
    
    def __init__(self, config: dict):
        self.max_attempts = config.get('max_attempts', 3)
        self.initial_delay = config.get('initial_delay', 1000)
        self.multiplier = config.get('multiplier', 2)
        self.retryable_errors = config.get('retryable_errors', [
            'TimeoutError',
            'ElementNotVisibleError',
            'StaleElementError'
        ])
```

### 3.2 操作注册系统

```python
class OperationRegistry:
    """操作注册表 - 支持动态注册自定义操作"""
    
    def __init__(self):
        self._operations: Dict[str, OperationHandler] = {}
        self._register_builtin_operations()
    
    def register(
        self, 
        name: str, 
        handler: OperationHandler,
        metadata: Optional[dict] = None
    ):
        """注册操作"""
        self._operations[name] = handler
        logger.info(f"已注册操作: {name}")
    
    def unregister(self, name: str):
        """注销操作"""
        if name in self._operations:
            del self._operations[name]
    
    def get(self, name: str) -> Optional[OperationHandler]:
        """获取操作处理器"""
        return self._operations.get(name)
    
    def list_operations(self) -> List[str]:
        """列出所有已注册操作"""
        return list(self._operations.keys())
    
    def _register_builtin_operations(self):
        """注册内置操作"""
        self.register('click', ClickOperation())
        self.register('fill', FillOperation())
        self.register('select', SelectOperation())
        # ... 内置操作

# 操作处理器接口
class OperationHandler(ABC):
    """操作处理器抽象基类"""
    
    @abstractmethod
    async def execute(
        self, 
        page: Page, 
        locator: Optional[Locator],
        params: dict,
        context: ExecutionContext
    ) -> OperationResult:
        """执行操作"""
        pass
    
    @abstractmethod
    def validate_params(self, params: dict) -> ValidationResult:
        """验证参数"""
        pass

# 示例：自定义操作
class ClickOperation(OperationHandler):
    """点击操作"""
    
    async def execute(self, page, locator, params, context):
        await locator.click(**params)
        return OperationResult(success=True)
    
    def validate_params(self, params):
        # 验证参数有效性
        return ValidationResult(valid=True)

# 用户可以注册自定义操作
class CustomDragDropOperation(OperationHandler):
    """自定义拖拽操作"""
    
    async def execute(self, page, locator, params, context):
        target_selector = params['target']
        target = page.locator(target_selector)
        await locator.drag_to(target)
        return OperationResult(success=True)

# 注册自定义操作
registry = OperationRegistry()
registry.register('drag_drop', CustomDragDropOperation())
```

### 3.3 配置驱动执行

#### 执行策略配置（JSON/YAML）
```json
{
  "execution_config": {
    "navigation": {
      "strategy": "relaxed",
      "config": {
        "allow_same_origin": true,
        "allow_auth_redirect": true,
        "auth_paths": ["/login", "/signin"],
        "custom_rules": [
          {
            "pattern": "/api/*",
            "redirect_to": "/dashboard",
            "action": "allow"
          }
        ]
      }
    },
    "wait": {
      "strategy": "explicit",
      "config": {
        "wait_for_visible": true,
        "wait_for_stable": true,
        "timeout": 30000,
        "poll_interval": 100
      }
    },
    "retry": {
      "strategy": "exponential_backoff",
      "config": {
        "max_attempts": 3,
        "initial_delay": 1000,
        "multiplier": 2,
        "retryable_errors": [
          "TimeoutError",
          "ElementNotVisibleError"
        ]
      }
    },
    "locator": {
      "healing": {
        "enabled": true,
        "similarity_threshold": 0.78,
        "max_candidates": 120
      },
      "fallback_chain": ["xpath", "css", "text", "self_heal"]
    }
  },
  "hooks": {
    "before_step": "plugins.logging.log_step_start",
    "after_step": "plugins.logging.log_step_end",
    "on_error": "plugins.recovery.attempt_recovery"
  },
  "custom_operations": [
    {
      "name": "wait_for_ajax",
      "handler": "plugins.custom.WaitForAjaxOperation"
    },
    {
      "name": "verify_no_console_errors",
      "handler": "plugins.custom.VerifyNoConsoleErrors"
    }
  ]
}
```

#### 步骤配置（数据库模型）
```json
{
  "step_id": 123,
  "operation": "click",
  "locator": {
    "primary": {
      "type": "xpath",
      "value": "//button[@id='submit']"
    },
    "fallbacks": [
      {"type": "css", "value": "#submit"},
      {"type": "text", "value": "提交"}
    ]
  },
  "params": {
    "button": "left",
    "click_count": 1,
    "delay": 0
  },
  "wait": {
    "before": {
      "condition": "visible",
      "timeout": 5000
    },
    "after": {
      "condition": "networkidle",
      "timeout": 10000
    }
  },
  "retry": {
    "enabled": true,
    "max_attempts": 3
  },
  "hooks": {
    "before": "validate_page_state",
    "after": "verify_submission"
  }
}
```

### 3.4 插件系统

```python
class PluginManager:
    """插件管理器"""
    
    def __init__(self):
        self._plugins: Dict[str, Plugin] = {}
        self._hooks: Dict[str, List[Callable]] = defaultdict(list)
    
    def register_plugin(self, plugin: Plugin):
        """注册插件"""
        self._plugins[plugin.name] = plugin
        plugin.on_register(self)
    
    def register_hook(self, hook_name: str, handler: Callable):
        """注册钩子"""
        self._hooks[hook_name].append(handler)
    
    async def execute_hook(self, hook_name: str, context: dict):
        """执行钩子"""
        for handler in self._hooks.get(hook_name, []):
            await handler(context)

# 插件接口
class Plugin(ABC):
    """插件抽象基类"""
    
    @property
    @abstractmethod
    def name(self) -> str:
        pass
    
    @abstractmethod
    def on_register(self, manager: PluginManager):
        """插件注册时调用"""
        pass

# 示例：日志插件
class LoggingPlugin(Plugin):
    name = "logging"
    
    def on_register(self, manager):
        manager.register_hook('before_step', self.log_step_start)
        manager.register_hook('after_step', self.log_step_end)
    
    async def log_step_start(self, context):
        logger.info(f"开始执行步骤: {context['step_id']}")
    
    async def log_step_end(self, context):
        logger.info(f"步骤执行完成: {context['step_id']}")

# 示例：性能监控插件
class PerformancePlugin(Plugin):
    name = "performance"
    
    def on_register(self, manager):
        manager.register_hook('before_step', self.start_timer)
        manager.register_hook('after_step', self.record_metrics)
    
    async def start_timer(self, context):
        context['start_time'] = time.time()
    
    async def record_metrics(self, context):
        duration = time.time() - context['start_time']
        # 记录性能指标
```

### 3.5 通用执行引擎

```python
class UniversalAutomationEngine:
    """通用自动化执行引擎"""
    
    def __init__(self, config: EngineConfig):
        self.config = config
        
        # 策略
        self.navigation_strategy = self._load_strategy(
            'navigation', 
            config.navigation
        )
        self.wait_strategy = self._load_strategy(
            'wait', 
            config.wait
        )
        self.retry_strategy = self._load_strategy(
            'retry', 
            config.retry
        )
        
        # 注册表
        self.operation_registry = OperationRegistry()
        self.assertion_registry = AssertionRegistry()
        self.locator_registry = LocatorRegistry()
        
        # 插件系统
        self.plugin_manager = PluginManager()
        
        # 加载自定义操作和插件
        self._load_custom_operations(config.custom_operations)
        self._load_plugins(config.plugins)
    
    async def execute_step(
        self, 
        page: Page, 
        step_config: StepConfig,
        context: ExecutionContext
    ) -> StepResult:
        """执行单个步骤 - 完全配置驱动"""
        
        # 执行前置钩子
        await self.plugin_manager.execute_hook('before_step', {
            'step_config': step_config,
            'context': context
        })
        
        try:
            # 获取操作处理器
            operation = self.operation_registry.get(step_config.operation)
            if not operation:
                raise ValueError(f"未知操作: {step_config.operation}")
            
            # 定位元素（如果需要）
            locator = None
            if step_config.locator:
                locator = await self._resolve_locator(
                    page, 
                    step_config.locator,
                    context
                )
            
            # 前置等待
            if step_config.wait and step_config.wait.before:
                await self.wait_strategy.wait_before_action(
                    page, 
                    locator, 
                    step_config.operation,
                    step_config.wait.before
                )
            
            # 执行操作（带重试）
            result = await self.retry_strategy.execute_with_retry(
                lambda: operation.execute(page, locator, step_config.params, context),
                step_config.retry or {}
            )
            
            # 后置等待
            if step_config.wait and step_config.wait.after:
                await self.wait_strategy.wait_after_action(
                    page,
                    step_config.operation,
                    step_config.wait.after
                )
            
            # 执行后置钩子
            await self.plugin_manager.execute_hook('after_step', {
                'step_config': step_config,
                'result': result,
                'context': context
            })
            
            return StepResult(success=True, data=result)
            
        except Exception as e:
            # 执行错误钩子
            await self.plugin_manager.execute_hook('on_error', {
                'step_config': step_config,
                'error': e,
                'context': context
            })
            
            return StepResult(success=False, error=str(e))
    
    async def navigate(
        self, 
        page: Page, 
        target_url: str,
        config: NavigationConfig,
        context: ExecutionContext
    ) -> NavigationResult:
        """导航到目标URL - 策略驱动"""
        
        result = await self.navigation_strategy.navigate(
            page, 
            target_url, 
            config.to_dict()
        )
        
        if config.validate:
            validation = self.navigation_strategy.validate(
                target_url, 
                page.url,
                config.to_dict()
            )
            
            if not validation.is_valid:
                if config.fail_on_validation_error:
                    raise NavigationError(validation.message)
                else:
                    logger.warning(validation.message)
        
        return result
    
    def _load_strategy(self, strategy_type: str, config: dict):
        """动态加载策略"""
        strategy_name = config.get('strategy', 'default')
        strategy_class = self._get_strategy_class(strategy_type, strategy_name)
        return strategy_class(config.get('config', {}))
    
    def _load_custom_operations(self, operations: List[dict]):
        """加载自定义操作"""
        for op_config in operations:
            handler_class = self._import_class(op_config['handler'])
            handler = handler_class()
            self.operation_registry.register(op_config['name'], handler)
    
    def _load_plugins(self, plugins: List[str]):
        """加载插件"""
        for plugin_path in plugins:
            plugin_class = self._import_class(plugin_path)
            plugin = plugin_class()
            self.plugin_manager.register_plugin(plugin)
```

## 四、数据库模型调整

### 4.1 执行策略配置表
```python
class UiExecutionStrategy(models.Model):
    """执行策略配置"""
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    strategy_type = models.CharField(max_length=50)  # navigation, wait, retry
    config = models.JSONField()  # 策略配置
    is_default = models.BooleanField(default=False)
    
    class Meta:
        db_table = 'ui_execution_strategy'
```

### 4.2 自定义操作表
```python
class UiCustomOperation(models.Model):
    """自定义操作定义"""
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    handler_path = models.CharField(max_length=500)  # Python类路径
    params_schema = models.JSONField()  # 参数JSON Schema
    description = models.TextField()
    
    class Meta:
        db_table = 'ui_custom_operation'
```

### 4.3 步骤配置扩展
```python
class UiPageStepsDetailed(models.Model):
    # ... 现有字段
    
    # 新增字段
    operation_params = models.JSONField(null=True)  # 操作参数
    wait_config = models.JSONField(null=True)  # 等待配置
    retry_config = models.JSONField(null=True)  # 重试配置
    hooks = models.JSONField(null=True)  # 钩子配置
    
    class Meta:
        db_table = 'ui_page_steps_detailed'
```

## 五、实施路线图

### 阶段1：基础架构（2周）
- [ ] 策略系统基础类
- [ ] 操作注册表
- [ ] 配置加载器
- [ ] 向后兼容层

### 阶段2：策略实现（2周）
- [ ] NavigationStrategy 实现
- [ ] WaitStrategy 实现
- [ ] RetryStrategy 实现
- [ ] ValidationStrategy 实现

### 阶段3：插件系统（1周）
- [ ] PluginManager 实现
- [ ] Hook 机制
- [ ] 内置插件（日志、性能）

### 阶段4：数据层（1周）
- [ ] 数据库模型扩展
- [ ] API 接口调整
- [ ] 配置UI

### 阶段5：迁移与测试（1周）
- [ ] 现有功能迁移
- [ ] 兼容性测试
- [ ] 性能测试
- [ ] 文档编写

## 六、向后兼容

```python
class LegacyAdapter:
    """旧版本适配器 - 确保现有用例不受影响"""
    
    def convert_old_config(self, old_config: dict) -> EngineConfig:
        """转换旧配置到新格式"""
        return EngineConfig(
            navigation=self._convert_navigation(old_config),
            wait=self._convert_wait(old_config),
            retry=self._convert_retry(old_config),
            # ...
        )
    
    def _convert_navigation(self, old_config):
        # 旧版本没有 skip_url_check，使用默认 relaxed 策略
        return {
            'strategy': 'relaxed',
            'config': {
                'allow_same_origin': True,
                'allow_auth_redirect': True
            }
        }
```

## 七、优势总结

| 特性 | 旧版本 | 新版本（通用引擎） |
|------|-------|-----------------|
| **扩展性** | ❌ 硬编码，需改代码 | ✅ 配置驱动，插件化 |
| **灵活性** | ❌ 固定行为 | ✅ 策略可配置 |
| **可维护性** | ❌ if-else 堆积 | ✅ 策略模式，清晰分层 |
| **用户自定义** | ❌ 不支持 | ✅ 自定义操作/插件 |
| **适应性** | ❌ 特定场景 | ✅ 通用场景 |
| **测试性** | ⚠️ 依赖具体实现 | ✅ 可mock策略 |

---

**下一步**：需要我开始实施第一阶段（基础架构）吗？
