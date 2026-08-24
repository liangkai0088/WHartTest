"""
通用自动化执行引擎 - 定位器解析器
支持多定位器备选、iframe、自愈机制
"""

import json
import logging
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Union

from playwright.async_api import Page, Locator, FrameLocator

logger = logging.getLogger('actuator')


# ============================================================================
# 定位器配置
# ============================================================================

@dataclass
class LocatorConfig:
    """定位器配置"""
    primary: Dict[str, Any]  # 主定位器
    fallbacks: List[Dict[str, Any]] = None  # 备选定位器列表
    iframe: Optional[str] = None  # iframe定位器
    healing: bool = True  # 是否启用自愈


# ============================================================================
# 定位器解析器
# ============================================================================

class LocatorResolver:
    """定位器解析器 - 支持多定位器备选、iframe、自愈"""

    def __init__(
        self,
        healing_enabled: bool = True,
        similarity_threshold: float = 0.78,
        max_candidates: int = 120
    ):
        """初始化定位器解析器

        Args:
            healing_enabled: 是否启用定位器自愈
            similarity_threshold: 自愈时的相似度阈值
            max_candidates: 自愈时最大候选元素数量
        """
        self.healing_enabled = healing_enabled
        self.similarity_threshold = similarity_threshold
        self.max_candidates = max_candidates
        self.last_diagnostics: Dict[str, Any] = {}

    async def resolve(
        self,
        page: Page,
        locator_config: Dict[str, Any],
        context: Any
    ) -> Optional[Locator]:
        """解析定位器配置，返回有效的Locator

        Args:
            page: Playwright页面对象
            locator_config: 定位器配置字典
            context: 执行上下文

        Returns:
            Locator对象或None
        """
        self.last_diagnostics = {
            'current_url': getattr(page, 'url', ''),
            'description': getattr(context, 'metadata', {}).get('description', '') if context else '',
            'attempted_locators': [],
            'candidates': [],
            'reason': '',
        }

        # 解析定位器配置
        config = self._parse_config(locator_config)

        # 确定容器（page或iframe）
        container = await self._resolve_container(page, config.iframe)

        # 尝试主定位器
        locator = await self._try_locator(
            container,
            config.primary,
            context,
            is_primary=True
        )

        if locator:
            return locator

        # 尝试备选定位器
        if config.fallbacks:
            for i, fallback in enumerate(config.fallbacks, start=2):
                logger.info(f"主定位器失效，尝试备选定位器 {i}")
                locator = await self._try_locator(
                    container,
                    fallback,
                    context,
                    is_primary=False
                )
                if locator:
                    return locator

        # 启用自愈机制
        if config.healing and self.healing_enabled:
            logger.info("所有定位器失效，尝试自愈机制")
            locator = await self._self_heal_locator(
                container,
                config,
                context
            )
            if locator:
                return locator

        # 所有尝试都失败
        logger.error("所有定位器都失效，无法定位元素")
        return None

    def _parse_config(self, raw_config: Dict) -> LocatorConfig:
        """解析定位器配置

        Args:
            raw_config: 原始配置字典

        Returns:
            LocatorConfig对象
        """
        primary = raw_config.get('primary', {})
        fallbacks = raw_config.get('fallbacks', [])
        iframe = raw_config.get('iframe')
        healing = raw_config.get('healing', True)

        return LocatorConfig(
            primary=primary,
            fallbacks=fallbacks or [],
            iframe=iframe,
            healing=healing
        )

    async def _resolve_container(
        self,
        page: Page,
        iframe_selector: Optional[str]
    ) -> Union[Page, FrameLocator]:
        """解析容器（page或iframe）

        Args:
            page: 页面对象
            iframe_selector: iframe选择器

        Returns:
            Page或FrameLocator
        """
        if not iframe_selector:
            return page

        # 支持多层iframe嵌套
        container = page

        # 支持两种分隔符：>>> 和 >>
        if ">>>" in iframe_selector:
            selectors = [s.strip() for s in iframe_selector.split(">>>") if s.strip()]
        elif ">>" in iframe_selector:
            selectors = [s.strip() for s in iframe_selector.split(">>") if s.strip()]
        else:
            selectors = [iframe_selector]

        for selector in selectors:
            container = container.frame_locator(selector)

        return container

    async def _try_locator(
        self,
        container: Union[Page, FrameLocator],
        locator_def: Dict,
        context: Any,
        is_primary: bool = False
    ) -> Optional[Locator]:
        """尝试使用定位器定位元素

        Args:
            container: 容器（page或frame）
            locator_def: 定位器定义
            context: 执行上下文
            is_primary: 是否是主定位器

        Returns:
            Locator对象或None
        """
        locator_type = locator_def.get('type', 'xpath')
        locator_value = locator_def.get('value', '')
        locator_index = locator_def.get('index')

        if self.last_diagnostics is not None:
            self.last_diagnostics.setdefault('attempted_locators', []).append({
                'type': locator_type,
                'value': locator_value,
                'index': locator_index,
                'primary': is_primary,
            })

        if not locator_value:
            if self.last_diagnostics is not None:
                self.last_diagnostics['reason'] = '定位器为空'
            return None

        try:
            # 获取定位器
            locator = self._get_locator(container, locator_type, locator_value)

            # 处理索引
            if locator_index is not None:
                locator = locator.nth(locator_index)

            # 等待元素可见（快速验证）
            timeout = 5000 if is_primary else 2000
            await locator.wait_for(state="visible", timeout=timeout)

            if self.last_diagnostics is not None:
                self.last_diagnostics['resolved_by'] = 'primary' if is_primary else 'fallback'
                self.last_diagnostics['resolved_locator'] = {'type': locator_type, 'value': locator_value}
            logger.info(f"定位器成功: [{locator_type}={locator_value}]")
            return locator

        except Exception as e:
            if self.last_diagnostics is not None:
                self.last_diagnostics['reason'] = f"定位器不可见或不可用: [{locator_type}={locator_value}] {e}"
            logger.debug(f"定位器失败 [{locator_type}={locator_value}]: {e}")
            return None

    def _get_locator(
        self,
        container: Union[Page, FrameLocator],
        locator_type: str,
        locator_value: str
    ) -> Locator:
        """根据定位类型获取Locator

        Args:
            container: 容器
            locator_type: 定位类型
            locator_value: 定位值

        Returns:
            Locator对象
        """
        normalized_type = (locator_type or '').lower().replace('-', '_')
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

        handler = locator_map.get(normalized_type)
        if not handler:
            # 默认使用CSS选择器
            return container.locator(locator_value)

        return handler()

    async def _self_heal_locator(
        self,
        container: Union[Page, FrameLocator],
        config: LocatorConfig,
        context: Any
    ) -> Optional[Locator]:
        """定位器自愈机制

        基于元素文本相似度自动修复失效的定位器

        Args:
            container: 容器
            config: 定位器配置
            context: 执行上下文

        Returns:
            Locator对象或None
        """
        # 提取目标文本
        target_text = self._extract_target_text(config, context)

        if len(self._normalize_text(target_text)) < 4:
            logger.debug("目标文本过短，跳过自愈")
            return None

        # 获取候选元素
        candidates = await self._get_interactive_candidates(container)

        if self.last_diagnostics is not None:
            self.last_diagnostics['candidates'] = candidates[:20]

        if not candidates:
            if self.last_diagnostics is not None:
                self.last_diagnostics['reason'] = '未找到可交互元素候选'
            logger.warning("未找到可交互元素候选")
            return None

        # 计算相似度并排序
        ranked = []
        for candidate in candidates:
            candidate_text = ' '.join(
                str(candidate.get(field) or '')
                for field in ('text', 'ariaLabel', 'title', 'placeholder', 'testId', 'id', 'name')
            ).strip()

            score = self._text_similarity(target_text, candidate_text)

            if score >= self.similarity_threshold:
                ranked.append((score, candidate, candidate_text))

        if self.last_diagnostics is not None:
            self.last_diagnostics['target_text'] = target_text
            self.last_diagnostics['ranked_candidates'] = [
                {'score': round(score, 3), 'text': candidate_text[:120], 'tag': candidate.get('tag', '')}
                for score, candidate, candidate_text in ranked[:10]
            ]

        if not ranked:
            if self.last_diagnostics is not None:
                self.last_diagnostics['reason'] = f'未找到相似度 >= {self.similarity_threshold} 的候选元素'
            logger.warning(f"未找到相似度 >= {self.similarity_threshold} 的候选元素")
            return None

        # 按相似度排序
        ranked.sort(key=lambda x: x[0], reverse=True)

        # 检查是否有明显的最佳候选
        if len(ranked) > 1 and ranked[0][0] - ranked[1][0] < 0.08:
            if self.last_diagnostics is not None:
                self.last_diagnostics['reason'] = '候选元素相似度过于接近，放弃自愈以避免误点'
            logger.warning(f"候选元素相似度过于接近，放弃自愈")
            return None

        # 使用最佳候选
        score, candidate, candidate_text = ranked[0]
        heal_id = candidate.get('healId')

        if not heal_id:
            return None

        locator = container.locator(f'[data-actuator-heal-id="{heal_id}"]')

        try:
            await locator.wait_for(state="visible", timeout=2000)
            if self.last_diagnostics is not None:
                self.last_diagnostics['resolved_by'] = 'self_heal'
                self.last_diagnostics['resolved_locator'] = {
                    'type': 'self_heal',
                    'value': candidate_text[:120],
                    'score': round(score, 3),
                    'tag': candidate.get('tag', ''),
                }
            logger.info(
                f"自愈成功: tag={candidate.get('tag')}, "
                f"text='{candidate_text[:80]}', score={score:.2f}"
            )
            return locator
        except Exception as e:
            logger.debug(f"自愈候选元素不可用: {e}")
            return None

    async def _get_interactive_candidates(
        self,
        container: Union[Page, FrameLocator]
    ) -> List[Dict[str, Any]]:
        """获取可交互元素候选列表

        Args:
            container: 容器

        Returns:
            候选元素列表
        """
        selector = (
            'button, a, input, textarea, select, [role="button"], [role="link"], '
            '[role="menuitem"], [contenteditable="true"], [tabindex]:not([tabindex="-1"])'
        )

        locator = container.locator(selector)

        try:
            candidates = await locator.evaluate_all(
                """
                (elements) => {
                    const isVisible = (element) => {
                        const style = window.getComputedStyle(element);
                        const rect = element.getBoundingClientRect();
                        return style.visibility !== 'hidden'
                            && style.display !== 'none'
                            && Number(style.opacity || 1) > 0
                            && rect.width > 0
                            && rect.height > 0;
                    };
                    const textOf = (element) => [
                        element.innerText,
                        element.textContent,
                        element.getAttribute('aria-label'),
                        element.getAttribute('title'),
                        element.getAttribute('placeholder'),
                        element.getAttribute('value'),
                        element.getAttribute('data-testid'),
                        element.id,
                        element.name,
                    ].filter(Boolean).join(' ').trim();
                    return elements
                        .filter(isVisible)
                        .slice(0, """ + str(self.max_candidates) + """)
                        .map((element, index) => {
                            const healId = `actuator-heal-${Date.now()}-${index}`;
                            element.setAttribute('data-actuator-heal-id', healId);
                            return {
                                healId,
                                tag: element.tagName.toLowerCase(),
                                role: element.getAttribute('role') || '',
                                text: textOf(element),
                                ariaLabel: element.getAttribute('aria-label') || '',
                                title: element.getAttribute('title') || '',
                                placeholder: element.getAttribute('placeholder') || '',
                                testId: element.getAttribute('data-testid') || '',
                                id: element.id || '',
                                name: element.getAttribute('name') || '',
                            };
                        })
                        .filter(item => item.text || item.ariaLabel || item.title || item.placeholder || item.testId || item.id || item.name);
                }
                """
            )
            return candidates
        except Exception as e:
            logger.warning(f"获取候选元素失败: {e}")
            return []

    @staticmethod
    def _extract_target_text(config: LocatorConfig, context: Any) -> str:
        """提取目标文本用于相似度匹配

        Args:
            config: 定位器配置
            context: 执行上下文

        Returns:
            目标文本
        """
        parts = []

        # 从主定位器提取
        if config.primary:
            parts.append(config.primary.get('value', ''))

        # 从备选定位器提取
        if config.fallbacks:
            for fallback in config.fallbacks:
                parts.append(fallback.get('value', ''))

        # 从上下文提取描述
        if hasattr(context, 'metadata') and context.metadata:
            parts.append(context.metadata.get('description', ''))

        return ' '.join(part for part in parts if part)

    @staticmethod
    def _normalize_text(value: str) -> str:
        """规范化文本用于相似度比较

        Args:
            value: 原始文本

        Returns:
            规范化后的文本
        """
        if not value:
            return ''

        # 移除xpath、css等语法字符
        value = re.sub(
            r'xpath=|css=|//|[@#.=\[\]"\'（）()_-]+',
            ' ',
            value,
            flags=re.IGNORECASE
        )

        # 移除多余空格并转小写
        value = re.sub(r'\s+', '', value).lower()

        return value

    @staticmethod
    def _text_similarity(source: str, target: str) -> float:
        """计算文本相似度

        Args:
            source: 源文本
            target: 目标文本

        Returns:
            相似度分数 (0-1)
        """
        source_normalized = LocatorResolver._normalize_text(source)
        target_normalized = LocatorResolver._normalize_text(target)

        if not source_normalized or not target_normalized:
            return 0.0

        # 子串匹配给予高分
        if len(source_normalized) >= 4 and len(target_normalized) >= 4:
            if source_normalized in target_normalized or target_normalized in source_normalized:
                return 0.95

        # 使用SequenceMatcher计算相似度
        return SequenceMatcher(None, source_normalized, target_normalized).ratio()
