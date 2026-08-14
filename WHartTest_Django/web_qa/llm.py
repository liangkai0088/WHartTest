"""OpenAI 兼容 LLM 客户端（供 agent 定位 / PRD 生成使用）。

统一通过 LLMConfig 行构造 OpenAI-compatible chat.completions 请求
（web-qa-bot src/utils/llm.ts 的 Python 移植，去掉进程环境变量依赖）。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, List, Optional

import httpx

logger = logging.getLogger('web_qa')

LOCATOR_SYSTEM_PROMPT = (
    '你是网页自动化测试助手。你会收到一张网页截图和一段自然语言描述，任务是在截图中定位该元素。\n'
    '只返回一个 JSON 对象（不要输出任何其他文字，不要使用代码块，不要使用 Markdown），格式如下：\n'
    '{"selector": "...", "x": number|null, "y": number|null, "reason": "..."}\n\n'
    '规则：\n'
    '1. 优先返回稳定的选择器 selector：CSS 选择器（如 #login-btn、.nav .login），或形如 "button:提交" 的 role:name 文本选择器。\n'
    '2. 仅当元素没有稳定选择器时才返回像素坐标 x/y（相对截图左上角，整数）。有坐标时 selector 可为 null。\n'
    '3. 元素不存在时，也返回 selector: null、x: null、y: null，并在 reason 中说明。\n'
    '4. reason 用一句中文说明判断依据。'
)


class LlmError(Exception):
    """LLM 调用 / 解析错误。"""


def get_llm_timeout_ms(llm_config) -> int:
    try:
        return int(getattr(llm_config, 'request_timeout', None) or 30) * 1000
    except (TypeError, ValueError):
        return 30000


def chat_completions(
    llm_config,
    messages: List[dict],
    temperature: float = 0,
    timeout_ms: Optional[int] = None,
) -> str:
    """调用 OpenAI 兼容 chat/completions，返回 choices[0].message.content。"""
    base_url = str(getattr(llm_config, 'api_url', '') or '').strip().rstrip('/')
    api_key = str(getattr(llm_config, 'api_key', '') or '').strip()
    model = str(getattr(llm_config, 'name', '') or '').strip()

    if not base_url or not api_key or not model:
        raise LlmError('LLM 未配置（需要 api_url / api_key / model）')

    endpoint = f'{base_url}/chat/completions'
    timeout_ms = timeout_ms or get_llm_timeout_ms(llm_config)

    body = {
        'model': model,
        'temperature': temperature,
        'messages': messages,
    }

    try:
        resp = httpx.post(
            endpoint,
            json=body,
            headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {api_key}'},
            timeout=timeout_ms / 1000,
        )
    except httpx.HTTPError as e:
        raise LlmError(f'LLM 网络错误: {e}') from e

    if resp.status_code >= 400:
        raise LlmError(f'LLM 请求失败 HTTP {resp.status_code}: {resp.text[:300]}')

    try:
        data = resp.json()
    except ValueError as e:
        raise LlmError(f'LLM 响应非 JSON: {e}') from e

    content = (data.get('choices') or [{}])[0].get('message', {}).get('content')
    if not isinstance(content, str) or not content.strip():
        raise LlmError('LLM 响应内容为空')
    return content


def extract_json_block(text: str) -> Any:
    """宽松提取首个 JSON 对象 / 数组。"""
    cleaned = (text or '').strip()
    cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
    cleaned = re.sub(r'```\s*$', '', cleaned).strip()

    start = cleaned.find('{')
    end = cleaned.rfind('}')
    if start >= 0 and end > start:
        candidate = cleaned[start:end + 1]
        try:
            return json.loads(candidate)
        except ValueError:
            pass
    try:
        return json.loads(cleaned)
    except ValueError:
        raise LlmError('LLM 响应解析失败: 无法提取 JSON')


def parse_locator_response(input_text: Any) -> dict:
    """宽松解析 LLM 定位响应 -> {"selector","x","y","reason"}。"""
    data = extract_json_block(input_text)
    if not isinstance(data, dict):
        raise LlmError('LLM 响应不是合法 JSON 对象')

    selector = data.get('selector')
    selector = selector.strip() if isinstance(selector, str) and selector.strip() else None
    x = data.get('x')
    y = data.get('y')
    x = x if isinstance(x, (int, float)) and x == x else None
    y = y if isinstance(y, (int, float)) and y == y else None
    reason = data.get('reason') if isinstance(data.get('reason'), str) else None

    if not selector and (x is None or y is None):
        raise LlmError('LLM 返回结果缺少有效的 selector 或坐标')
    return {'selector': selector, 'x': x, 'y': y, 'reason': reason}
