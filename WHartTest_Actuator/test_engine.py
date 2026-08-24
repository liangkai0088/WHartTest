#!/usr/bin/env python3
"""
通用引擎验证脚本
测试新引擎是否正常工作
"""

import sys
import os

# 添加当前目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_imports():
    """测试模块导入"""
    print("=" * 60)
    print("测试1: 模块导入")
    print("=" * 60)

    try:
        from strategies import StrategyFactory, ExecutionContext
        print("✅ strategies.py")
    except Exception as e:
        print(f"❌ strategies.py: {e}")
        return False

    try:
        from operations import OperationRegistry
        print("✅ operations.py")
    except Exception as e:
        print(f"❌ operations.py: {e}")
        return False

    try:
        from engine import UniversalAutomationEngine, EngineConfig
        print("✅ engine.py")
    except Exception as e:
        print(f"❌ engine.py: {e}")
        return False

    try:
        from locator_resolver import LocatorResolver
        print("✅ locator_resolver.py")
    except Exception as e:
        print(f"❌ locator_resolver.py: {e}")
        return False

    try:
        from engine_integration import EnhancedExecutor
        print("✅ engine_integration.py")
    except Exception as e:
        print(f"❌ engine_integration.py: {e}")
        return False

    return True


def test_registry():
    """测试操作注册表"""
    print("\n" + "=" * 60)
    print("测试2: 操作注册表")
    print("=" * 60)

    try:
        from operations import OperationRegistry

        registry = OperationRegistry()
        ops = registry.list_operations()

        print(f"✅ 已注册 {len(ops)} 个操作")
        print("\n内置操作列表:")
        for op in ops[:10]:
            print(f"  - {op['name']}: {op['description']}")
        if len(ops) > 10:
            print(f"  ... 还有 {len(ops) - 10} 个操作")

        return True
    except Exception as e:
        print(f"❌ 错误: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_strategies():
    """测试策略创建"""
    print("\n" + "=" * 60)
    print("测试3: 策略系统")
    print("=" * 60)

    try:
        from strategies import StrategyFactory

        # 测试导航策略
        nav_strategy = StrategyFactory.create_navigation_strategy('relaxed')
        print(f"✅ 导航策略(relaxed): {nav_strategy.__class__.__name__}")

        # 测试等待策略
        wait_strategy = StrategyFactory.create_wait_strategy('auto')
        print(f"✅ 等待策略(auto): {wait_strategy.__class__.__name__}")

        # 测试重试策略
        retry_strategy = StrategyFactory.create_retry_strategy('exponential_backoff')
        print(f"✅ 重试策略(exponential_backoff): {retry_strategy.__class__.__name__}")

        return True
    except Exception as e:
        print(f"❌ 错误: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_engine():
    """测试引擎创建"""
    print("\n" + "=" * 60)
    print("测试4: 通用引擎")
    print("=" * 60)

    try:
        from engine import UniversalAutomationEngine, EngineConfig

        config = EngineConfig(
            navigation_strategy='relaxed',
            wait_strategy='auto',
            retry_strategy='exponential_backoff'
        )

        engine = UniversalAutomationEngine(config)
        print("✅ 引擎创建成功")
        print(f"  - 导航策略: {config.navigation_strategy}")
        print(f"  - 等待策略: {config.wait_strategy}")
        print(f"  - 重试策略: {config.retry_strategy}")

        return True
    except Exception as e:
        print(f"❌ 错误: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_integration():
    """测试集成适配器"""
    print("\n" + "=" * 60)
    print("测试5: 集成适配器")
    print("=" * 60)

    try:
        from engine_integration import EnhancedExecutor

        executor = EnhancedExecutor(screenshot_dir='./data/screenshots')
        print("✅ 增强执行器创建成功")

        # 列出可用操作
        ops = executor.list_available_operations()
        print(f"✅ 可用操作: {len(ops)} 个")

        return True
    except Exception as e:
        print(f"❌ 错误: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """主函数"""
    print("\n🚀 通用自动化引擎 - 验证测试")
    print()

    results = []

    # 运行测试
    results.append(("模块导入", test_imports()))
    results.append(("操作注册表", test_registry()))
    results.append(("策略系统", test_strategies()))
    results.append(("通用引擎", test_engine()))
    results.append(("集成适配器", test_integration()))

    # 输出结果
    print("\n" + "=" * 60)
    print("测试结果汇总")
    print("=" * 60)

    all_passed = True
    for name, passed in results:
        status = "✅ 通过" if passed else "❌ 失败"
        print(f"{name}: {status}")
        if not passed:
            all_passed = False

    print("\n" + "=" * 60)
    if all_passed:
        print("🎉 所有测试通过！通用引擎就绪。")
        print("\n下一步:")
        print("  1. 启动执行器: python main.py")
        print("  2. 查看日志确认: '通用自动化引擎已启用'")
        print("  3. 运行测试用例验证效果")
    else:
        print("❌ 部分测试失败，请检查错误信息")
        sys.exit(1)
    print("=" * 60)


if __name__ == '__main__':
    main()
